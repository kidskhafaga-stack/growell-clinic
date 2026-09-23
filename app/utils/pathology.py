"""The pathway of a removed tissue — GAHAR SAS.10.

**Two ways a specimen can end, and only two.** Exempt under a line of the
hospital's own list (:func:`exempt`), or labelled → sent → result back
(:func:`send`, :func:`record_result`). A specimen that is neither is on the
board until it is one or the other, which is EOC 1's *"clear pathway"* in
practice: nothing removed from a child is allowed to simply stop being
talked about.

**The two numbers are the hospital's.** The exempt list starts empty and the
result time frame starts unset. Until the list has an entry, nothing can be
exempted — every specimen goes to the lab — and until the time frame is
written, nothing is called late. The program chooses neither.

**And the operative report is a witness.** SAS.08 (g) already asks the
surgeon *"any removed specimen, or not"*. A report that says yes over a case
with no specimen recorded is a tissue with no pathway, and :func:`untracked`
is the list of them.
"""
from datetime import datetime, timedelta

from app.extensions import db
from app.models import Lookup
from app.models.specimen import EXEMPT_DOMAIN, Specimen

#: The time frame for results, in days — the hospital's (EOC 4).
DAYS_SETTING = "pathology_result_days"


def result_days():
    """The hospital's time frame for a result, or ``None`` until written."""
    from app.models import Setting

    try:
        raw = (Setting.get(DAYS_SETTING) or "").strip()
    except Exception:                   # noqa: BLE001 — settings not ready
        return None
    try:
        days = int(raw)
    except (TypeError, ValueError):
        return None
    return days if days > 0 else None


# ------------------------------------------------------ the exempt list ----
def exempt_list():
    """The hospital's exempt tissues, active only, in order."""
    return (Lookup.query.filter_by(domain=EXEMPT_DOMAIN, is_active=True)
            .order_by(Lookup.sort_order, Lookup.id).all())


def add_exempt(name):
    """A line on the hospital's list. The caller commits."""
    from app.utils.lookups import make_key

    name = (name or "").strip()[:80]
    if not name:
        raise ValueError("no name")
    existing = Lookup.query.filter_by(domain=EXEMPT_DOMAIN).filter(
        Lookup.name_ar == name).first()
    if existing is not None:
        existing.is_active = True
        return existing
    row = Lookup(domain=EXEMPT_DOMAIN, key=make_key(name, EXEMPT_DOMAIN),
                 name_ar=name, is_active=True)
    db.session.add(row)
    return row


def retire_exempt(row):
    """Off the list — **retired, not deleted**: a specimen exempted under it
    last year still names the line that allowed it."""
    if row is None or row.domain != EXEMPT_DOMAIN:
        raise ValueError("not an exempt line")
    row.is_active = False
    return row


def exempt_label(key):
    """The words of the list line a specimen was exempted under."""
    if not key:
        return None
    row = Lookup.query.filter_by(domain=EXEMPT_DOMAIN, key=key).first()
    return row.name_ar if row else key


# ----------------------------------------------------------- the pathway ----
def record(operation, tissue, user=None, at=None):
    """A specimen came out. The caller commits."""
    if operation is None or operation.status == "cancelled":
        raise ValueError("no case")
    tissue = (tissue or "").strip()[:160]
    if not tissue:
        raise ValueError("no tissue")
    row = Specimen(operation_id=operation.id, patient_id=operation.patient_id,
                   tissue=tissue, recorded_by=getattr(user, "id", None),
                   taken_at=at or datetime.utcnow())
    db.session.add(row)
    return row


def exempt(specimen, key, note=None, user=None, at=None):
    """Not sent, under a line of the hospital's list — EOC 2.

    **Only a line that is on the list, and active.** An exemption the
    hospital never wrote is a specimen somebody decided not to send.
    """
    if specimen is None or specimen.is_sent:
        raise ValueError("already sent")
    if not any(row.key == key for row in exempt_list()):
        raise ValueError("not on the list")
    specimen.exempt_key = key
    specimen.exempt_note = (note or "").strip()[:200] or None
    specimen.exempt_by = getattr(user, "id", None)
    specimen.exempt_at = at or datetime.utcnow()
    return specimen


def send(specimen, lab, labelled, user=None, at=None):
    """Labelled and sent — EOC 3, one moment.

    ``labelled`` is the sender saying the label with the date and time, the
    child's identity and the tissue was on the container. Refused without it:
    a specimen the lab cannot match to a child is the failure the label
    exists to prevent.
    """
    if specimen is None or specimen.is_exempt:
        raise ValueError("exempt")
    if specimen.is_sent:
        return specimen
    if not labelled:
        raise ValueError("not labelled")
    specimen.lab = (lab or "").strip()[:120] or None
    specimen.sent_at = at or datetime.utcnow()
    specimen.sent_by = getattr(user, "id", None)
    return specimen


def record_result(specimen, text, on=None, user=None, now=None):
    """The result is back — EOC 4. ``on`` is the date on the report.

    A result for a specimen nobody sent, or dated before it was sent, or in
    the future, is refused: each is a typing slip that would otherwise
    shorten or lengthen the time the time frame is measured on.
    """
    now = now or datetime.utcnow()
    if specimen is None or not specimen.is_sent:
        raise ValueError("not sent")
    text = (text or "").strip()
    if not text:
        raise ValueError("no result")
    when = on or now
    if when > now + timedelta(minutes=5) or when < specimen.sent_at:
        raise ValueError("bad date")
    specimen.result_on = when
    specimen.result_text = text
    specimen.result_by = getattr(user, "id", None)
    return specimen


# ---------------------------------------------------------- where it is ----
def due_by(specimen, days=None):
    """When the result is due, or ``None`` with no time frame or not sent."""
    days = result_days() if days is None else days
    if specimen is None or not specimen.is_sent or not days:
        return None
    return specimen.sent_at + timedelta(days=days)


def state(specimen, now=None, days=None):
    """``exempt`` · ``resulted`` · ``late`` · ``sent`` · ``to_send``."""
    if specimen.is_exempt:
        return "exempt"
    if specimen.has_result:
        return "resulted"
    if specimen.is_sent:
        due = due_by(specimen, days)
        if due is not None and (now or datetime.utcnow()) > due:
            return "late"
        return "sent"
    return "to_send"


def for_operation(operation):
    if operation is None:
        return []
    return (Specimen.query.filter_by(operation_id=operation.id)
            .order_by(Specimen.id).all())


def untracked(limit=200):
    """Cases whose operative report says a specimen was removed and which
    have none recorded — a tissue with no pathway."""
    from app.models import Operation
    from app.models.operative_report import OperativeReport

    has = db.session.query(Specimen.operation_id).distinct()
    return (Operation.query
            .join(OperativeReport, OperativeReport.operation_id == Operation.id)
            .filter(OperativeReport.specimen.is_(True),
                    Operation.id.notin_(has))
            .order_by(Operation.on_date.desc(), Operation.id.desc())
            .limit(limit).all())


def board(now=None, limit=300):
    """What the pathology board shows: to send, awaiting (late first), and
    the untracked cases."""
    days = result_days()
    now = now or datetime.utcnow()
    open_rows = (Specimen.query
                 .filter(Specimen.exempt_key.is_(None),
                         Specimen.result_on.is_(None))
                 .order_by(Specimen.taken_at).limit(limit).all())
    to_send = [r for r in open_rows if not r.is_sent]
    waiting = [{"specimen": r, "state": state(r, now, days),
                "due": due_by(r, days)}
               for r in open_rows if r.is_sent]
    waiting.sort(key=lambda item: (item["state"] != "late",
                                   item["specimen"].sent_at))
    return {"to_send": to_send, "waiting": waiting,
            "untracked": untracked(), "days": days}
