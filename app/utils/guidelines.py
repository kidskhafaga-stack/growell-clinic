"""Clinical practice guidelines — see ``models/guideline``."""
from datetime import date, datetime

from app.extensions import db
from app.models.guideline import (EMERGENCY_TOPICS, EVENT_KINDS, PER_YEAR, SCOPES, ClinicalGuideline,
                                  GuidelineEvent)


class GuidelineError(ValueError):
    """A refusal with a locale key (``cpg.err_<key>``)."""


def _text(raw, limit=None):
    s = (raw or "").strip()
    return (s[:limit] if limit else s) or None


def _day(raw):
    try:
        return date.fromisoformat((raw or "").strip())
    except ValueError:
        return None


def save(form):
    title, approved = _text(form.get("title"), 200), _text(form.get("approved_by"), 160)
    adopted = _day(form.get("adopted_on"))
    scope = form.get("scope") if form.get("scope") in SCOPES else None
    if not title:
        raise GuidelineError("title")
    if scope is None:
        raise GuidelineError("scope")
    if not approved:
        raise GuidelineError("approved_by")
    if adopted is None:
        raise GuidelineError("adopted_on")
    topic = form.get("topic") if scope == "emergency" and form.get("topic") in EMERGENCY_TOPICS else None
    if scope == "emergency" and topic is None:
        raise GuidelineError("topic")
    row = ClinicalGuideline(title=title, scope=scope, topic=topic, source=_text(form.get("source"), 160),
                            is_national=bool(form.get("is_national")), selection=_text(form.get("selection")),
                            panel=_text(form.get("panel"), 255), approved_by=approved, adopted_on=adopted,
                            plan=_text(form.get("plan")), link=_text(form.get("link"), 255))
    db.session.add(row)
    db.session.flush()
    return row


def add_event(row, form, user):
    kind = form.get("kind") if form.get("kind") in EVENT_KINDS else None
    held, note = _day(form.get("held_on")), _text(form.get("note"))
    if kind is None:
        raise GuidelineError("kind")
    if held is None:
        raise GuidelineError("held_on")
    if not note:
        raise GuidelineError("note")
    event = GuidelineEvent(guideline_id=row.id, kind=kind, held_on=held, note=note,
                           by_id=getattr(user, "id", None), at=datetime.utcnow())
    db.session.add(event)
    if kind == "review" and (row.reviewed_on is None or held > row.reviewed_on):
        row.reviewed_on = held
    db.session.flush()
    return event


def retire(row):
    row.is_active = False
    db.session.flush()
    return row


def board(today=None):
    today = today or date.today()
    rows = (ClinicalGuideline.query.filter_by(is_active=True)
            .order_by(ClinicalGuideline.scope, ClinicalGuideline.title).all())
    this_year = [r for r in rows if r.adopted_on.year == today.year]
    covered = {r.topic for r in rows if r.scope == "emergency" and r.topic}
    return {"rows": rows, "overdue": {r.id for r in rows if r.review_due < today},
            "this_year": len(this_year), "per_year": PER_YEAR, "year": today.year,
            "uncovered": [t for t in EMERGENCY_TOPICS if t != "other" and t not in covered],
            "untrained": {r.id for r in rows if not any(e.kind == "training" for e in r.events)}}


def library():
    rows = (ClinicalGuideline.query.filter_by(is_active=True)
            .order_by(ClinicalGuideline.scope, ClinicalGuideline.title).all())
    return {s: [r for r in rows if r.scope == s] for s in SCOPES}


__all__ = ["GuidelineError", "add_event", "board", "library", "retire", "save"]
