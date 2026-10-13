"""The family and the medicines — see ``models/med_family``."""
from app.extensions import db
from app.models.med_family import (COUNSEL_KINDS, SELF_BY, WATCH_OUTCOMES, FirstDoseObservation,
                                   FirstDoseWatch, MedCounselling, SelfAdministration)


class FamilyMedError(ValueError):
    """A refusal with a locale key (``fammed.err_<key>``)."""


def _text(raw, limit):
    return (raw or "").strip()[:limit] or None


def counsel(stay, form, user, kind):
    if kind not in COUNSEL_KINDS:
        raise FamilyMedError("kind")
    to = _text(form.get("to_whom"), 120)
    if not to:
        raise FamilyMedError("to_whom")
    row = MedCounselling(admission_id=stay.id, patient_id=stay.patient_id, kind=kind, to_whom=to,
                         order_id=_int(form.get("order_id")), questions=form.get("questions") == "1",
                         note=_text(form.get("note"), 255), by_id=getattr(user, "id", None))
    db.session.add(row)
    db.session.flush()
    return row


def _int(raw):
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def self_admin(order, form, user):
    by = form.get("by_whom")
    if by not in SELF_BY:
        raise FamilyMedError("by_whom")
    supervision = _text(form.get("supervision"), 255)
    if not supervision:
        raise FamilyMedError("supervision")
    able = form.get("able") == "1"
    if not able:
        raise FamilyMedError("not_able")
    row = SelfAdministration(order_id=order.id, by_whom=by, taught_by=getattr(user, "id", None),
                             able=True, supervision=supervision)
    db.session.add(row)
    db.session.flush()
    return row


def watch_map():
    return {w.generic_id: w for w in FirstDoseWatch.query.filter_by(is_active=True)}


def add_watch(form):
    gid, what = _int(form.get("generic_id")), _text(form.get("watch_for"), 255)
    if not gid or not what:
        raise FamilyMedError("watch")
    row = FirstDoseWatch(generic_id=gid, watch_for=what)
    db.session.add(row)
    db.session.flush()
    return row


def first_dose_due(stay):
    """``[(order, watch, first_dose)]`` — a first dose given of a watched
    medicine with nothing written about what was seen."""
    from app.models import MedicationDose
    from app.models.medication import GIVEN

    known = watch_map()
    if not known:
        return []
    out = []
    for order in stay.medication_orders:
        gid = getattr(getattr(order, "drug", None), "generic_id", None)
        if gid not in known:
            continue
        if FirstDoseObservation.query.filter_by(order_id=order.id).first() is not None:
            continue
        first = (MedicationDose.query.filter_by(order_id=order.id, outcome=GIVEN)
                 .order_by(MedicationDose.at).first())
        if first is not None:
            out.append((order, known[gid], first))
    return out


def observe(order, form, user):
    outcome = form.get("outcome")
    if outcome not in WATCH_OUTCOMES:
        raise FamilyMedError("outcome")
    note = _text(form.get("note"), 255)
    if outcome == "reaction" and not note:
        raise FamilyMedError("note")
    if FirstDoseObservation.query.filter_by(order_id=order.id).first() is not None:
        raise FamilyMedError("done")
    row = FirstDoseObservation(order_id=order.id, outcome=outcome, note=note,
                               by_id=getattr(user, "id", None))
    db.session.add(row)
    db.session.flush()
    return row


def for_stay(stay):
    orders = [o.id for o in stay.medication_orders]
    return {
        "counselling": (MedCounselling.query.filter_by(admission_id=stay.id)
                        .order_by(MedCounselling.at.desc()).all()),
        "self": {s.order_id: s for s in (SelfAdministration.query
                                         .filter(SelfAdministration.order_id.in_(orders),
                                                 SelfAdministration.ended_at.is_(None)).all()
                                         if orders else [])},
        "first_dose": first_dose_due(stay),
    }


__all__ = ["FamilyMedError", "add_watch", "counsel", "first_dose_due", "for_stay", "observe",
           "self_admin", "watch_map"]
