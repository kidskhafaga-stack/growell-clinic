"""The lab's door: a tube received, or turned away — GAHAR DAS.15.

*"Evaluation of received specimens by authorized staff member to ensure that
they meet the acceptance criteria"* — and the record of both answers:

* **accepted** (ب-١): the date and time the specimen reached the lab and who
  received it; (ب-٣) a suboptimal one accepted anyway says why;
* **rejected** (ب-٢): the cause, the time, the person rejecting it, and the
  person told — and the order goes back to be drawn again, under a new tube
  number, so the refused tube and its replacement are never one code.

**The reasons are the laboratory's.** Its acceptance and rejection criteria
are its policy (DAS.15 أ), so the list (`Lookup` domain ``sample_reject``)
starts empty and the lab writes it; until it does, the reason is typed.

**Receiving is a record, not a gate.** A small lab where the person who draws
is the person who runs never had a door to press, and a result typed before
anyone pressed «received» is still saved — the register simply shows the
tube as never recorded at the door, which is the truth.
"""
from datetime import datetime

from app.extensions import db

REASONS_DOMAIN = "sample_reject"


class ReceptionError(ValueError):
    """A refusal with a key the screen can name (``lab_reception.err_<key>``)."""


# ----------------------------------------------------------- the reasons --
def reasons():
    """The laboratory's rejection reasons, active only, in order."""
    from app.models import Lookup

    return (Lookup.query.filter_by(domain=REASONS_DOMAIN, is_active=True)
            .order_by(Lookup.sort_order, Lookup.id).all())


def add_reason(name):
    """A line on the laboratory's list. The caller commits."""
    from app.models import Lookup
    from app.utils.lookups import make_key

    name = (name or "").strip()[:80]
    if not name:
        raise ReceptionError("need_reason")
    existing = (Lookup.query.filter_by(domain=REASONS_DOMAIN)
                .filter(Lookup.name_ar == name).first())
    if existing is not None:
        existing.is_active = True
        return existing
    row = Lookup(domain=REASONS_DOMAIN, key=make_key(name, REASONS_DOMAIN),
                 name_ar=name, is_active=True)
    db.session.add(row)
    return row


def retire_reason(row):
    """Off the list — retired, not deleted: a tube refused under it last
    month still names the line that refused it."""
    if row is None or row.domain != REASONS_DOMAIN:
        raise ReceptionError("not_a_reason")
    row.is_active = False
    return row


def _list_words(key):
    from app.models import Lookup

    row = Lookup.query.filter_by(domain=REASONS_DOMAIN, key=key).first()
    return row.name_ar if row is not None else key


def reason_label(rejection):
    """The words a rejection was made under — the list's line, and what was
    typed beside it."""
    if rejection.reason_key:
        label = _list_words(rejection.reason_key)
        return f"{label} — {rejection.reason_text}" if rejection.reason_text else label
    return rejection.reason_text or ""


# ------------------------------------------------------------- the door --
def _a_tube(order):
    if order is None or order.kind != "lab":
        raise ReceptionError("not_lab")
    if order.status == "resulted":
        raise ReceptionError("resulted")
    if order.collected_at is None:
        raise ReceptionError("not_collected")


def receive(order, user=None, note=None, at=None):
    """The tube reached the lab and was accepted. A second press keeps the
    first time — the tube arrived once — and only adds a note if one is
    written."""
    _a_tube(order)
    note = (note or "").strip()[:200] or None
    if order.received_at is None:
        order.received_at = at or datetime.utcnow()
        order.received_by = getattr(user, "id", None)
    if note:
        order.received_note = note
    db.session.flush()
    return order


def reject(order, reason_key=None, reason_text=None, told_to=None,
           user=None, at=None):
    """The tube is refused. Recorded, and the order goes back to be drawn.

    The order keeps everything that was asked; what it loses is the tube —
    its number, its drawing and its reception — because the tube is what
    was refused. The next label prints a new number (`labs.sample_code`).
    """
    from app.models import SampleRejection

    _a_tube(order)
    reason_text = (reason_text or "").strip()[:200] or None
    key = (reason_key or "").strip() or None
    if key is not None and key not in {r.key for r in reasons()}:
        key = None
    if key is None and reason_text is None:
        raise ReceptionError("need_reason")
    told_to = (told_to or "").strip()[:120]
    if not told_to:
        raise ReceptionError("need_told")
    row = SampleRejection(
        order_id=order.id, patient_id=order.patient_id,
        sample_code=order.sample_code, collected_at=order.collected_at,
        collected_by=order.collected_by, reason_key=key,
        reason_text=reason_text, told_to=told_to,
        rejected_at=at or datetime.utcnow(),
        rejected_by=getattr(user, "id", None))
    db.session.add(row)
    order.collected_at = order.collected_by = None
    order.received_at = order.received_by = order.received_note = None
    order.sample_code = None
    order.status = "requested"
    db.session.flush()
    return row


def last_rejections(orders):
    """``{order_id: SampleRejection}`` — the latest refusal of each order on
    a list still waiting for its tube, in one query."""
    from app.models import SampleRejection

    ids = [o.id for o in orders if o.status == "requested"]
    if not ids:
        return {}
    out = {}
    for row in (SampleRejection.query
                .filter(SampleRejection.order_id.in_(ids))
                .order_by(SampleRejection.id).all()):
        out[row.order_id] = row
    return out


def register(start, end):
    """Every refused tube between two clinic days, newest first, and how
    many under each reason — what the surveyor matches against the policy."""
    from datetime import time

    from app.models import SampleRejection
    from app.utils.clock import to_utc

    since = to_utc(datetime.combine(start, time.min))
    until = to_utc(datetime.combine(end, time.max))
    rows = (SampleRejection.query
            .filter(SampleRejection.rejected_at >= since,
                    SampleRejection.rejected_at <= until)
            .order_by(SampleRejection.rejected_at.desc()).all())
    tally = {}
    for row in rows:
        label = (_list_words(row.reason_key) if row.reason_key
                 else (row.reason_text or ""))
        tally[label] = tally.get(label, 0) + 1
    return rows, sorted(tally.items(), key=lambda kv: (-kv[1], kv[0]))
