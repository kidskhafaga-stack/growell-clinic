"""End-of-life care — see ``models/palliative``."""
from app.extensions import db
from app.models.palliative import SYMPTOMS, PalliativePlan, PalliativeReview


class PalliativeError(ValueError):
    """A refusal with a locale key (``pall.err_<key>``)."""


def _text(raw, limit=None):
    s = (raw or "").strip()
    return (s[:limit] if limit else s) or None


def save_plan(stay, form, user):
    goals, decided = _text(form.get("goals")), _text(form.get("decided_with"), 160)
    if not goals:
        raise PalliativeError("goals")
    if not decided:
        raise PalliativeError("decided_with")
    row = PalliativePlan(admission_id=stay.id, goals=goals, decided_with=decided,
                         support=_text(form.get("support"), 255), team=_text(form.get("team"), 255),
                         by_id=getattr(user, "id", None))
    db.session.add(row)
    db.session.flush()
    return row


def review(stay, form, user):
    present = [s for s in SYMPTOMS if s in form.getlist("present")]
    action = _text(form.get("action"), 255)
    if present and not action:
        raise PalliativeError("action")
    row = PalliativeReview(admission_id=stay.id, present=",".join(present) or None, action=action,
                           note=_text(form.get("note"), 255), by_id=getattr(user, "id", None))
    db.session.add(row)
    db.session.flush()
    return row


def for_stay(stay_id):
    plan = (PalliativePlan.query.filter_by(admission_id=stay_id)
            .order_by(PalliativePlan.at.desc()).first())
    reviews = (PalliativeReview.query.filter_by(admission_id=stay_id)
               .order_by(PalliativeReview.at.desc()).limit(10).all())
    return {"plan": plan, "reviews": reviews}


__all__ = ["PalliativeError", "for_stay", "review", "save_plan"]
