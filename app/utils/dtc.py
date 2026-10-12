"""The drug and therapeutics committee — see ``models/dtc``."""
from datetime import date, datetime

from app.extensions import db
from app.models.dtc import (DECISION_KINDS, REVIEW_ELEMENTS, DrugShortage, DtcAnnualReview,
                            DtcDecision, DtcMeeting)


class DtcError(ValueError):
    """A refusal with a locale key (``dtc.err_<key>``)."""


def _text(raw, limit=None):
    s = (raw or "").strip()
    return (s[:limit] if limit else s) or None


def _day(raw):
    try:
        return date.fromisoformat((raw or "").strip())
    except ValueError:
        return None


def _int(raw):
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def save_meeting(form, user):
    held = _day(form.get("held_on"))
    attendees, minutes = _text(form.get("attendees")), _text(form.get("minutes"))
    if held is None or not attendees or not minutes:
        raise DtcError("meeting")
    row = DtcMeeting(held_on=held, attendees=attendees, minutes=minutes,
                     written_by=getattr(user, "id", None))
    texts, owners = form.getlist("decision"), form.getlist("owner")
    kinds, dues, generics = form.getlist("kind"), form.getlist("due_on"), form.getlist("generic_id")
    for i, text in enumerate(texts):
        text = _text(text)
        if not text:
            continue
        owner = _text(owners[i] if i < len(owners) else None, 120)
        if not owner:
            raise DtcError("owner")
        kind = kinds[i] if i < len(kinds) and kinds[i] in DECISION_KINDS else "general"
        generic = _int(generics[i]) if i < len(generics) else None
        if kind != "general" and not generic:
            raise DtcError("generic")
        row.decisions.append(DtcDecision(kind=kind, text=text, owner=owner,
                                         due_on=_day(dues[i] if i < len(dues) else None),
                                         generic_id=generic if kind != "general" else None))
    db.session.add(row)
    db.session.flush()
    return row


def close_decision(row, note):
    note = _text(note, 255)
    if not note:
        raise DtcError("note")
    row.done_at, row.done_note = datetime.utcnow(), note
    db.session.flush()
    return row


def save_review(year, form, user):
    if not year or year < 2000:
        raise DtcError("year")
    row = DtcAnnualReview.query.filter_by(year=year).first() or DtcAnnualReview(year=year)
    filled = 0
    for key in REVIEW_ELEMENTS:
        value = _text(form.get(key))
        setattr(row, key, value)
        filled += 1 if value else 0
    if not filled:
        raise DtcError("review")
    row.signed_by, row.signed_at = getattr(user, "id", None), datetime.utcnow()
    db.session.add(row)
    db.session.flush()
    return row


def announce(form, user):
    name = _text(form.get("name"), 160)
    if not name:
        raise DtcError("shortage")
    row = DrugShortage(name=name, started_on=_day(form.get("started_on")) or date.today(),
                       expected_back=_text(form.get("expected_back"), 60),
                       alternative=_text(form.get("alternative"), 255),
                       note=_text(form.get("note"), 255), announced_by=getattr(user, "id", None))
    db.session.add(row)
    db.session.flush()
    return row


def end_shortage(row):
    row.ended_at = datetime.utcnow()
    db.session.flush()
    return row


def active_shortages():
    return DrugShortage.query.filter(DrugShortage.ended_at.is_(None)).order_by(DrugShortage.started_on.desc()).all()


def board():
    meetings = DtcMeeting.query.order_by(DtcMeeting.held_on.desc()).all()
    open_decisions = (DtcDecision.query.filter(DtcDecision.done_at.is_(None))
                      .order_by(DtcDecision.due_on.is_(None), DtcDecision.due_on).all())
    reviews = {r.year: r for r in DtcAnnualReview.query.all()}
    return {"meetings": meetings, "open": open_decisions, "reviews": reviews}


__all__ = ["DtcError", "active_shortages", "announce", "board", "close_decision", "end_shortage",
           "save_meeting", "save_review"]
