"""Mental health on the stay — GAHAR CSS.11 (b), (h), (j).

The risk of harm to self or others is a ``RiskAssessment`` of kind
``self_harm`` (the hospital's tool and words, an at-risk answer, and the plan
it needs); rapid tranquilization is ``models/tranquilization``.
"""
from app.extensions import db
from app.models.risk_assessment import SELF_HARM, RiskAssessment
from app.models.tranquilization import RapidTranquilization

#: The hospital's screening tool's name — empty until written.
TOOL_SETTING = "self_harm_tool"


class MentalHealthError(ValueError):
    """A refusal with a locale key (``mental.err_<key>``)."""


def _text(raw, limit=None):
    s = (raw or "").strip()
    return (s[:limit] if limit else s) or None


def tool_name():
    from app.models import Setting

    return (Setting.get(TOOL_SETTING) or "").strip() or None


def screen(stay, form, user):
    answer = form.get("at_risk")
    if answer not in ("yes", "no"):
        raise MentalHealthError("at_risk")
    at_risk = answer == "yes"
    plan = _text(form.get("plan"))
    if at_risk and not plan:
        raise MentalHealthError("plan")
    row = RiskAssessment(patient_id=stay.patient_id, admission_id=stay.id, kind=SELF_HARM,
                         tool=_text(form.get("tool"), 120) or tool_name(),
                         level=_text(form.get("level"), 60), at_risk=at_risk, plan=plan,
                         family_told=True if form.get("family_told") == "1" else None,
                         by_id=getattr(user, "id", None))
    db.session.add(row)
    db.session.flush()
    return row


def tranquilize(stay, form, user):
    reason, given, monitoring = (_text(form.get("reason"), 255), _text(form.get("given"), 160),
                                 _text(form.get("monitoring"), 255))
    if not reason or not given:
        raise MentalHealthError("what")
    if not monitoring:
        raise MentalHealthError("monitoring")
    row = RapidTranquilization(admission_id=stay.id, reason=reason, given=given, monitoring=monitoring,
                               outcome=_text(form.get("outcome"), 255), by_id=getattr(user, "id", None))
    db.session.add(row)
    db.session.flush()
    return row


def for_stay(stay):
    screens = (RiskAssessment.query.filter_by(admission_id=stay.id, kind=SELF_HARM)
               .order_by(RiskAssessment.at.desc()).all())
    rt = (RapidTranquilization.query.filter_by(admission_id=stay.id)
          .order_by(RapidTranquilization.at.desc()).all())
    return {"screens": screens, "latest": screens[0] if screens else None, "rt": rt, "tool": tool_name()}


__all__ = ["MentalHealthError", "TOOL_SETTING", "for_stay", "screen", "tool_name", "tranquilize"]
