"""Adverse drug reactions — see ``models/adverse_reaction``."""
from datetime import datetime, timedelta

from app.extensions import db
from app.models.adverse_reaction import SEVERITIES, AdverseReaction


class ReactionError(ValueError):
    """A refusal with a locale key (``adr.err_<key>``)."""


def _text(raw, limit=None):
    s = (raw or "").strip()
    return (s[:limit] if limit else s) or None


def _when(raw):
    from app.utils.clock import to_utc

    try:
        return to_utc(datetime.fromisoformat(str(raw or "").strip()))
    except ValueError:
        return None


def record(stay, form, user):
    drug = _text(form.get("drug_name"), 160)
    if not drug:
        raise ReactionError("drug")
    what = _text(form.get("what_happened"))
    if not what:
        raise ReactionError("what")
    severity = form.get("severity")
    if severity not in SEVERITIES:
        raise ReactionError("severity")
    action = _text(form.get("action_taken"), 255)
    if not action:
        raise ReactionError("action")
    onset = _when(form.get("onset_at")) or datetime.utcnow()
    if onset > datetime.utcnow() + timedelta(minutes=5):
        raise ReactionError("future")
    row = AdverseReaction(patient_id=stay.patient_id, admission_id=stay.id, drug_name=drug,
                          onset_at=onset, what_happened=what, severity=severity,
                          action_taken=action, recorded_by=getattr(user, "id", None),
                          order_id=_int(form.get("order_id")))
    told = _text(form.get("prescriber_told"), 120)
    if told:
        row.prescriber_told, row.prescriber_told_at = told, datetime.utcnow()
    if form.get("add_allergy") == "1":
        _add_allergy(stay.patient, drug)
        row.added_to_allergies = True
    db.session.add(row)
    db.session.flush()
    return row


def _int(raw):
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _add_allergy(patient, drug):
    """Appended to the child's allergy line as written — so the prescription
    and drug-round checks, which read that line, see it from now on."""
    have = (patient.allergies or "").strip()
    if drug.lower() in have.lower():
        return
    patient.allergies = f"{have}، {drug}" if have else drug


def tell_prescriber(row, form):
    told = _text(form.get("prescriber_told"), 120)
    if not told:
        raise ReactionError("told")
    row.prescriber_told, row.prescriber_told_at = told, datetime.utcnow()
    db.session.flush()
    return row


def mark_reported(row, form, user):
    ref = _text(form.get("report_ref"), 80)
    if not ref:
        raise ReactionError("ref")
    row.reported_at, row.report_ref, row.reported_by = datetime.utcnow(), ref, getattr(user, "id", None)
    db.session.flush()
    return row


def for_patient(patient_id):
    return (AdverseReaction.query.filter_by(patient_id=patient_id)
            .order_by(AdverseReaction.onset_at.desc()).all())


def board():
    return AdverseReaction.query.order_by(AdverseReaction.reported_at.isnot(None),
                                          AdverseReaction.onset_at.desc()).all()


def unreported_count():
    return AdverseReaction.query.filter(AdverseReaction.reported_at.is_(None)).count()


__all__ = ["ReactionError", "board", "for_patient", "mark_reported", "record",
           "tell_prescriber", "unreported_count"]
