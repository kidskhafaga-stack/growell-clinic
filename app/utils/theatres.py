"""The theatre day, and whether it is safe to cut.

Two questions, and the second is the one this module exists for.

**What is on today** is a list, and an easy one: the bookings for a date,
theatre by theatre, in time order. Nothing clever, and nothing clever wanted —
a theatre list is printed and pinned to a wall.

**Whether the checklist has been done** is the other question, and it is the
same shape as every other absence this program has learned to answer: a stop
that nobody ran leaves no row behind. So the state of an operation's checklist
is worked out from which of the three rows exist, and the screen can say *the
team has not stopped before the first cut* — which is the sentence the WHO
Surgical Safety Checklist exists to force somebody to say out loud.

**And the program refuses to start a case whose sign-in is missing**, which is
the one hard refusal here. Everything else it will let a hospital do and
record: a stop signed with items unticked is stored with the unticked ones
named, because a checklist that silently rounds "four of seven" up to "done"
is worse than no checklist — it manufactures a signature.
"""
from datetime import datetime

from app.extensions import db
from app.models.theatre import (CHECK_ITEMS, CHECK_STOPS, SIGN_IN, SIGN_OUT,
                                TIME_OUT, Operation, SafetyCheck, Theatre)
from app.utils.clock import local_today


class NotSafeYet(Exception):
    """The team has not signed in, and somebody asked to start.

    Raised rather than returned, for the reason ``BedTaken`` is: every caller
    has to deal with it, and this is the one place in the program where the
    right answer to a request is *no*.
    """


def day(on_date=None):
    """Every booking on a date, theatre by theatre, in time order.

    Cancelled cases stay on the list, marked. A theatre morning where two of
    six were called off is a fact about that morning — dropping them would
    make the list agree with itself and disagree with the day.
    """
    from sqlalchemy.orm import selectinload

    on_date = on_date or local_today()
    theatres = (Theatre.query.filter(Theatre.is_active.is_(True))
                .order_by(Theatre.sort_order, Theatre.id).all())
    bookings = (Operation.query
                .options(selectinload(Operation.patient),
                         selectinload(Operation.checks),
                         selectinload(Operation.surgeon))
                .filter(Operation.on_date == on_date)
                .order_by(Operation.start_time, Operation.id).all())

    by_theatre = {}
    for booking in bookings:
        by_theatre.setdefault(booking.theatre_id, []).append(booking)

    return [{"theatre": room,
             "operations": [{"operation": op, "safety": safety(op)}
                            for op in by_theatre.get(room.id, [])]}
            for room in theatres]


def safety(operation):
    """Where this operation's checklist stands.

    ``{"done": [...], "next": stop or None, "missed": {...}, "ready": bool}``
    — ``ready`` meaning the team has signed in and the knife may be picked up
    at all. The missing stop is the finding, so it is named rather than left
    to be noticed.
    """
    signed = {c.stop: c for c in (operation.checks if operation else [])}
    pending = [stop for stop in CHECK_STOPS if stop not in signed]
    return {
        "signed": signed,
        "done": [stop for stop in CHECK_STOPS if stop in signed],
        "next": pending[0] if pending else None,
        # What was ticked short at each stop that *was* signed. A checklist
        # completed with gaps is not a completed checklist, and the screen
        # says which ones rather than showing a green tick.
        "missed": {stop: row.missed for stop, row in signed.items()
                   if row.missed},
        "ready": SIGN_IN in signed,
        "closed": SIGN_OUT in signed,
    }


def sign(operation, stop, items=None, user=None, note=None, at=None):
    """Record one stop of the checklist.

    Stores the items that were actually confirmed, so a stop signed with two
    of seven ticked is kept as exactly that. Re-signing the same stop updates
    it rather than adding a second row — the unique constraint is what makes
    that safe when two screens run the checklist in the same minute.
    """
    if operation is None:
        raise ValueError("no operation")
    if stop not in CHECK_STOPS:
        raise ValueError("unknown stop")

    known = set(CHECK_ITEMS.get(stop, ()))
    confirmed = [i for i in (items or []) if i in known]

    row = operation.check_for(stop)
    if row is None:
        row = SafetyCheck(operation_id=operation.id, stop=stop)
        db.session.add(row)
    row.at = at or datetime.utcnow()
    row.by_id = getattr(user, "id", None)
    row.confirmed = ",".join(confirmed)
    row.note = (note or "").strip()[:255] or None
    return row


def start(operation, user=None, when=None):
    """Take the child into theatre — refused until the team has signed in.

    **The one hard refusal in this module.** Everything else a hospital may do
    and the program records; this is the stop the checklist exists for, and a
    program that lets a case start without it has a checklist that is a poster.
    """
    if operation is None or operation.status not in ("scheduled",):
        raise ValueError("not scheduled")
    if operation.check_for(SIGN_IN) is None:
        raise NotSafeYet(SIGN_IN)
    operation.status = "in_theatre"
    operation.started_at = when or datetime.utcnow()
    return operation


def finish(operation, user=None, findings=None, when=None):
    """The case is over. The sign-out is asked for but never forced.

    Refusing to record that an operation finished because the last stop is
    unsigned would leave the child in theatre for ever in the program's own
    telling. What the screen does instead is say the sign-out is missing and
    keep saying it — a gap that is visible is worth more than a refusal that
    gets worked around.
    """
    if operation is None or operation.status != "in_theatre":
        raise ValueError("not in theatre")
    operation.status = "done"
    operation.finished_at = when or datetime.utcnow()
    if findings is not None:
        operation.findings = (findings or "").strip() or None
    return operation


def cancel(operation, reason=None, user=None):
    """Called off. Kept on the list, marked, because a cancelled morning is
    a fact about the theatre's day."""
    if operation is None or not operation.is_open:
        return operation
    operation.status = "cancelled"
    operation.cancel_reason = (reason or "").strip()[:200] or None
    return operation


def book(patient, theatre, procedure, on_date=None, user=None, **extra):
    """Put a case on the list.

    Refuses a booking with no procedure named: "an operation" is not something
    a theatre list can be read from, and a name is the one thing nobody can
    supply later from the record.
    """
    name = (procedure or "").strip()[:200]
    # Each refusal names itself. "No child" and "no room" send whoever is
    # booking to two different next steps, and one message for both wastes
    # the trip — the same lesson the admission screen already learned.
    if patient is None:
        raise ValueError("no patient")
    if theatre is None:
        raise ValueError("no theatre")
    if not name:
        raise ValueError("no procedure")
    row = Operation(
        patient_id=patient.id, theatre_id=theatre.id, procedure=name,
        on_date=on_date or local_today(),
        booked_by=getattr(user, "id", None),
        **{k: v for k, v in extra.items() if v not in ("", None)})
    db.session.add(row)
    return row


def charge(admission, invoice, user=None, lang="ar"):
    """Put this stay's finished operations on its bill. Returns how many.

    Folded into the stay's one posting rather than billed on its own, for the
    reason the drugs are: a family gets one account for the admission, not a
    bed bill and a theatre bill and a pharmacy bill for the same three days.
    The procedure is a ``Service``, so the doctor's share, the insurance and
    the consumables it burns all follow with nothing added here.
    """
    from app.models.invoice import InvoiceItem

    if admission is None or invoice is None:
        return 0
    due = unbilled(admission_id=admission.id)
    for operation in due:
        service = operation.service
        price = float(service.price or 0)
        item = InvoiceItem(
            invoice_id=invoice.id, service_id=service.id,
            description=_line(operation, service, lang),
            unit_price=price, quantity=1)
        # The surgeon's share, snapshotted like any other chargeable line —
        # and read against **the surgeon**, not the admitting doctor, because
        # the person who did the operation is the person it is owed to.
        item.commission_amount = service.doctor_share(
            item.net, operation.surgeon or invoice.doctor)
        # And recorded on the line, so repricing the bill from the cash list
        # later works it out at the surgeon's rate rather than handing it back
        # to the doctor the invoice belongs to.
        item.doctor_id = operation.surgeon_id or None
        db.session.add(item)
        db.session.flush()
        operation.invoice_item_id = item.id
    return len(due)


def _line(operation, service, lang):
    name = (service.display_name(lang) if hasattr(service, "display_name")
            else service.name)
    parts = [name]
    if operation.procedure and operation.procedure != name:
        parts.append(operation.procedure)
    return f"{' · '.join(parts)} ({operation.on_date.isoformat()})"[:200]


def unbilled(admission_id=None, patient_id=None):
    """Operations that were done and never charged.

    Same shape as an uncharged night or an unbilled dose: the operation
    carries the invoice line it went onto, so asking twice charges once.
    Only a **finished** case is chargeable — a cancelled morning owes nothing,
    and a case still on the table has not happened yet.
    """
    query = Operation.query.filter(Operation.status == "done",
                                   Operation.invoice_item_id.is_(None),
                                   Operation.service_id.isnot(None))
    if admission_id is not None:
        query = query.filter(Operation.admission_id == admission_id)
    if patient_id is not None:
        query = query.filter(Operation.patient_id == patient_id)
    return query.order_by(Operation.on_date, Operation.id).all()
