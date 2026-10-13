"""Medicines a child brought in — see ``models/own_medicine``."""
from datetime import datetime

from app.extensions import db
from app.models.own_medicine import DECISIONS, OwnMedicine


class OwnMedicineError(ValueError):
    """A refusal with a locale key (``ownmed.err_<key>``)."""


def _text(raw, limit):
    return (raw or "").strip()[:limit] or None


def receive(stay, form, user):
    name = _text(form.get("name"), 160)
    if not name:
        raise OwnMedicineError("name")
    row = OwnMedicine(admission_id=stay.id, patient_id=stay.patient_id, name=name,
                      quantity=_text(form.get("quantity"), 60), expiry=_text(form.get("expiry"), 20),
                      note=_text(form.get("note"), 255), received_by=getattr(user, "id", None))
    db.session.add(row)
    db.session.flush()
    return row


def identify(row, form, user):
    """Looked at, and what is decided. Using it on the ward needs it
    identified first — an unidentified tablet is not given."""
    decision = form.get("decision")
    if decision not in DECISIONS:
        raise OwnMedicineError("decision")
    if not row.held:
        raise OwnMedicineError("gone")
    row.identified_at = datetime.utcnow()
    row.identified_by = getattr(user, "id", None)
    row.decision = decision
    note = _text(form.get("note"), 255)
    if note:
        row.note = note
    db.session.flush()
    return row


def hand_out(row, form, user):
    """Back to the family (to whom), or destroyed (why)."""
    if not row.held:
        raise OwnMedicineError("gone")
    to = _text(form.get("out_to"), 120)
    if not to:
        raise OwnMedicineError("out_to")
    row.out_at, row.out_to, row.out_by = datetime.utcnow(), to, getattr(user, "id", None)
    db.session.flush()
    return row


def for_stay(stay_id):
    return OwnMedicine.query.filter_by(admission_id=stay_id).order_by(OwnMedicine.id).all()


__all__ = ["OwnMedicineError", "for_stay", "hand_out", "identify", "receive"]
