"""The stay's own records of who decided what with whom — GAHAR ACT.11
(the multidisciplinary meeting), ACT.12 (a trip off the ward and back),
ACT.14 (temporary discharge), PCC.05 (the family's questions) and PCC.14
(belongings, and lost and found).

Four small records with one shape: written beside the child, read back on the
stay, and each with the one thing that keeps it open — a leave until the
child is back, a question until it is answered, belongings until they are
returned. The times are the hospital's; none is set here.
"""
from datetime import datetime, timedelta

from app.extensions import db
from app.models.belonging import Belonging, LostItem
from app.models.family_question import FOR_WHOM, FamilyQuestion
from app.models.mdt import MdtMeeting
from app.models.stay_leave import StayLeave
from app.models.stay_transport import StayTransport

#: PCC.05 ev. 2 — hours to answer a family's question. Empty until set.
QUESTION_HOURS_SETTING = "family_question_hours"
#: PCC.14 (e) — days a found item is held before the hospital's policy for
#: unclaimed items applies. Empty until set.
LOST_DAYS_SETTING = "lost_item_days"


class StayCareError(ValueError):
    """A refusal with a locale key (``staycare.err_<key>``)."""


def _text(raw, limit=None):
    s = (raw or "").strip()
    return (s[:limit] if limit else s) or None


def _when(raw):
    from app.utils.clock import to_utc

    try:
        return to_utc(datetime.fromisoformat(str(raw or "").strip()))
    except ValueError:
        return None


def _number(key):
    from app.models import Setting

    try:
        value = float((Setting.get(key) or "").strip())
    except ValueError:
        return None
    return value if value > 0 else None


def set_number(key, raw):
    from app.models import Setting

    raw = (raw or "").strip()
    if raw:
        try:
            if float(raw) <= 0:
                raise ValueError
        except ValueError:
            raise StayCareError("number") from None
    Setting.set(key, raw)


# ================================================================ ACT.11 ==
def add_mdt(stay, form, user):
    held = _when(form.get("held_at")) or datetime.utcnow()
    fields = {k: _text(form.get(k)) for k in ("reason", "attendees", "findings", "decision")}
    for k, v in fields.items():
        if not v:
            raise StayCareError("mdt_" + k)
    present = form.get("family_present")
    row = MdtMeeting(patient_id=stay.patient_id, admission_id=stay.id, held_at=held,
                     reason=fields["reason"][:255], attendees=fields["attendees"][:255],
                     findings=fields["findings"], decision=fields["decision"],
                     responsibilities=_text(form.get("responsibilities")),
                     family_present=True if present == "yes" else False if present == "no" else None,
                     by_id=getattr(user, "id", None))
    db.session.add(row)
    db.session.flush()
    return row


def mdt_for(patient_id):
    return (MdtMeeting.query.filter_by(patient_id=patient_id)
            .order_by(MdtMeeting.held_at.desc()).limit(20).all())


# ================================================================ ACT.14 ==
def open_leave(stay):
    return (StayLeave.query.filter_by(admission_id=stay.id, returned_at=None)
            .order_by(StayLeave.id.desc()).first())


def start_leave(stay, form, user):
    from app.models import User

    if not stay.is_open:
        raise StayCareError("closed")
    if open_leave(stay) is not None:
        raise StayCareError("leave_open")
    doctor = db.session.get(User, form.get("ordered_by", type=int) or 0)
    if doctor is None:
        raise StayCareError("ordered_by")
    reason = _text(form.get("reason"), 255)
    if not reason:
        raise StayCareError("reason")
    out = _when(form.get("out_at")) or datetime.utcnow()
    back = _when(form.get("back_by"))
    if back is None or back <= out:
        raise StayCareError("back_by")
    row = StayLeave(admission_id=stay.id, out_at=out, back_by=back, ordered_by=doctor.id,
                    reason=reason, instructions=_text(form.get("instructions")),
                    by_id=getattr(user, "id", None))
    db.session.add(row)
    db.session.flush()
    return row


def end_leave(row, form):
    if not row.is_open:
        raise StayCareError("leave_closed")
    row.returned_at = _when(form.get("returned_at")) or datetime.utcnow()
    row.return_note = _text(form.get("return_note"), 255)
    db.session.flush()
    return row


def leaves_for(stay_id):
    return StayLeave.query.filter_by(admission_id=stay_id).order_by(StayLeave.out_at.desc()).all()


# ================================================================ ACT.12 ==
def transport_out(stay, form, user):
    if not stay.is_open:
        raise StayCareError("closed")
    fields = {k: _text(form.get(k), 255 if k == "requirements" else 160)
              for k in ("to_where", "escort", "requirements")}
    for k, v in fields.items():
        if not v:
            raise StayCareError("tr_" + k)
    row = StayTransport(admission_id=stay.id, left_at=_when(form.get("left_at")) or datetime.utcnow(),
                        by_id=getattr(user, "id", None), **fields)
    db.session.add(row)
    db.session.flush()
    return row


def transport_back(row, form):
    if not row.is_out:
        raise StayCareError("tr_back")
    row.back_at = _when(form.get("back_at")) or datetime.utcnow()
    row.events = _text(form.get("events"), 255)
    db.session.flush()
    return row


def transports_for(stay_id):
    return (StayTransport.query.filter_by(admission_id=stay_id)
            .order_by(StayTransport.left_at.desc()).limit(20).all())


# ================================================================ PCC.05 ==
def ask(stay, form, user):
    question = _text(form.get("question"))
    if not question:
        raise StayCareError("question")
    whom = form.get("for_whom") if form.get("for_whom") in FOR_WHOM else "doctor"
    row = FamilyQuestion(patient_id=stay.patient_id, admission_id=stay.id,
                         asked_by=_text(form.get("asked_by"), 120), question=question,
                         for_whom=whom, taken_by=getattr(user, "id", None))
    db.session.add(row)
    db.session.flush()
    return row


def answer(row, form, user):
    if not row.is_open:
        raise StayCareError("answered")
    text = _text(form.get("answer"))
    if not text:
        raise StayCareError("answer")
    row.answer, row.answered_at, row.answered_by = text, datetime.utcnow(), getattr(user, "id", None)
    db.session.flush()
    return row


def questions_for(stay_id, now=None):
    now = now or datetime.utcnow()
    rows = (FamilyQuestion.query.filter_by(admission_id=stay_id)
            .order_by(FamilyQuestion.answered_at.isnot(None), FamilyQuestion.asked_at.desc()).all())
    limit = _number(QUESTION_HOURS_SETTING)
    late = {r.id for r in rows if limit and r.is_open and now > r.asked_at + timedelta(hours=limit)}
    late |= {r.id for r in rows if limit and not r.is_open
             and r.answered_at > r.asked_at + timedelta(hours=limit)}
    return {"rows": rows, "open": [r for r in rows if r.is_open], "late": late, "hours": limit}


# ================================================================ PCC.14 ==
def keep(stay, form, user):
    items, where = _text(form.get("items")), _text(form.get("kept_where"), 160)
    if not items:
        raise StayCareError("items")
    if not where:
        raise StayCareError("kept_where")
    row = Belonging(patient_id=stay.patient_id, admission_id=stay.id, items=items, kept_where=where,
                    family_told=bool(form.get("family_told")), received_by=getattr(user, "id", None))
    db.session.add(row)
    db.session.flush()
    return row


def give_back(row, form, user):
    if row.returned_at is not None:
        raise StayCareError("returned")
    to = _text(form.get("returned_to"), 160)
    if not to:
        raise StayCareError("returned_to")
    row.returned_at, row.returned_to, row.returned_by = datetime.utcnow(), to, getattr(user, "id", None)
    db.session.flush()
    return row


def belongings_for(patient_id):
    return (Belonging.query.filter_by(patient_id=patient_id)
            .order_by(Belonging.returned_at.isnot(None), Belonging.at.desc()).limit(20).all())


def found(form, user):
    fields = {k: _text(form.get(k), 255 if k == "description" else 160)
              for k in ("found_where", "description", "kept_where")}
    for k, v in fields.items():
        if not v:
            raise StayCareError("lost_" + k)
    row = LostItem(found_at=_when(form.get("found_at")) or datetime.utcnow(),
                   found_by=getattr(user, "id", None), **fields)
    db.session.add(row)
    db.session.flush()
    return row


def lost_returned(row, form):
    if not row.is_open:
        raise StayCareError("lost_closed")
    to = _text(form.get("returned_to"), 160)
    if not to:
        raise StayCareError("returned_to")
    row.returned_at, row.returned_to = datetime.utcnow(), to
    db.session.flush()
    return row


def lost_closed(row, form, now=None):
    """Past the hospital's holding time only — before it, an item is still
    waiting for its owner."""
    if not row.is_open:
        raise StayCareError("lost_closed")
    days = _number(LOST_DAYS_SETTING)
    if not days:
        raise StayCareError("lost_days")
    if (now or datetime.utcnow()) < row.found_at + timedelta(days=days):
        raise StayCareError("lost_too_soon")
    note = _text(form.get("closed_note"), 255)
    if not note:
        raise StayCareError("closed_note")
    row.closed_at, row.closed_note = datetime.utcnow(), note
    db.session.flush()
    return row


def lost_board(now=None):
    now = now or datetime.utcnow()
    days = _number(LOST_DAYS_SETTING)
    rows = LostItem.query.order_by(LostItem.found_at.desc()).limit(300).all()
    past = {r.id for r in rows if days and r.is_open and now >= r.found_at + timedelta(days=days)}
    return {"open": [r for r in rows if r.is_open], "closed": [r for r in rows if not r.is_open][:50],
            "past": past, "days": days,
            "kept": (Belonging.query.filter(Belonging.returned_at.is_(None))
                     .order_by(Belonging.at.desc()).limit(200).all())}


__all__ = ["LOST_DAYS_SETTING", "QUESTION_HOURS_SETTING", "StayCareError", "add_mdt", "answer",
           "ask", "belongings_for", "end_leave", "found", "give_back", "keep", "leaves_for",
           "lost_board", "lost_closed", "lost_returned", "mdt_for", "open_leave", "questions_for",
           "set_number", "start_leave", "transport_back", "transport_out", "transports_for"]
