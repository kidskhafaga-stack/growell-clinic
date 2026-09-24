"""Marking the site — GAHAR SAS.05 · GSR.14, and whether it was done right.

*"The precise site where surgery or invasive procedure shall be performed is
clearly marked by the physician, along with the patient and/or family
involvement."* The hospital's policy names seven things; the program carries
the ones a record can answer and leaves the rest to the policy:

* (a) **a unified mark** — the hospital writes what its mark is
  (:data:`STYLE_SETTING`), and whoever marks says that was the mark used;
* (b) **when marking is needed** — a side the record names, on a procedure
  the hospital has not exempted;
* (c) **by the physician who will operate** — the marker is compared with
  the surgeon on the booking;
* (d) **with the patient and family** — who stood with the child;
* (e) **exempted procedures** — the hospital's list, kept on the procedure;
* (f) **in time** — *"before sending the patient to the operating room"*,
  compared with the moment the program already stamps when the child is
  called (``Operation.called_at``). No interval is invented;
* (g) **monitoring** — :func:`report`, the same checks over a period.

**Nothing here refuses a marking.** A registrar marking at the surgeon's word,
or a child brought by a school with no family, is recorded as it happened and
shows as the finding it is. A screen that refused would be worked around, and
the record would stop saying what actually happened.
"""
from datetime import timedelta

from app.models.theatre import IDENTITY_PRESENT

#: The hospital's description of its unified mark (a).
STYLE_SETTING = "site_mark_style"

#: The checks, in the policy's order.
CHECKS = ("marked", "unified", "by_surgeon", "with_family", "in_time")


def mark_style():
    from app.models import Setting

    try:
        text = (Setting.get(STYLE_SETTING) or "").strip()
    except Exception:                   # noqa: BLE001 — settings not ready
        return None
    return text or None


def exempt(operation):
    """(e) — the procedure is on the hospital's exempt list."""
    service = getattr(operation, "service", None)
    return bool(getattr(service, "site_mark_exempt", None))


def required(operation):
    """(b) — does this case need a mark?

    Not when the hospital exempted the procedure, and not when whoever looked
    recorded that there is no side (``not_applicable``). Otherwise yes —
    including a case nobody has looked at yet, which is exactly the one that
    must not pass as not needing it.
    """
    if operation is None or operation.status == "cancelled":
        return False
    if exempt(operation):
        return False
    return operation.site_side != "not_applicable"


def checks(operation):
    """``{check: True | False | None}`` for a case that needs a mark.

    ``None`` is "cannot say yet" — the child has not been called, so whether
    the mark came first is not yet a question.
    """
    from app.utils import theatres as theatre

    marked = theatre.site_state(operation) == "marked"
    called = getattr(operation, "called_at", None)
    at = operation.site_marked_at
    return {
        "marked": marked,
        "unified": bool(operation.site_unified) if marked else False,
        "by_surgeon": (marked and operation.surgeon_id is not None
                       and operation.site_marked_by == operation.surgeon_id),
        "with_family": marked and operation.site_with in IDENTITY_PRESENT,
        # Not a question until the child is called. After that, a mark that
        # is missing or came later both fail it.
        "in_time": (None if called is None
                    else bool(marked and at is not None and at <= called)),
    }


def problems(operation):
    """The checks this case fails, named — empty when it needs no mark."""
    if not required(operation):
        return []
    return [name for name, ok in checks(operation).items() if ok is False]


def report(start, end):
    """(g) — every case in the period that needed a mark, and how each check
    went. ``start`` and ``end`` are the clinic's dates, inclusive; cases are
    taken by their operation day."""
    from app.models import Operation

    rows = (Operation.query
            .filter(Operation.on_date >= start, Operation.on_date <= end,
                    Operation.status != "cancelled")
            .order_by(Operation.on_date, Operation.id).all())
    needed = [op for op in rows if required(op)]
    totals = {name: {"ok": 0, "no": 0, "open": 0} for name in CHECKS}
    failing = []
    for op in needed:
        result = checks(op)
        for name, ok in result.items():
            totals[name]["ok" if ok else ("open" if ok is None else "no")] += 1
        wrong = [name for name, ok in result.items() if ok is False]
        if wrong:
            failing.append({"operation": op, "problems": wrong})
    return {"cases": len(rows), "needed": len(needed),
            "exempt": sum(1 for op in rows if exempt(op)),
            "totals": totals, "failing": failing}


def default_period(today):
    """The last thirty days, ending today."""
    return today - timedelta(days=29), today
