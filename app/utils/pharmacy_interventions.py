"""The clinical pharmacist's interventions — written, answered, and counted.

``HOSPITAL_PLAN.md`` مرحلة ج ٧، ص-١ (`models/pharmacy_intervention`). Three
things and no clinical rule:

* :func:`record` — the pharmacist fills the form's boxes for one child in a
  bed, on an order or a dose of theirs or on neither;
* :func:`respond` — the prescriber accepts it, accepts it changed, or rejects
  it. It never stops a drug; the order is the doctor's to change;
* :func:`summary` — the month in numbers: by problem, by urgency, by expected
  outcome, by department, and how many the doctors accepted.
"""
from datetime import datetime, time

from app.extensions import db
from app.models.pharmacy_intervention import (NO_ORDER, OUTCOMES, PROBLEMS,
                                              RESPONSES, SEVERITIES,
                                              PharmacyIntervention,
                                              next_number)


class InterventionError(ValueError):
    """Said to the person filling the form; nothing is saved."""


def _text(value, limit):
    return (value or "").strip()[:limit] or None


def record(admission, form, user=None):
    """Write one intervention from the form's fields. Raises
    :class:`InterventionError` with the reason, as a translation key."""
    from app.models.medication import MedicationDose, MedicationOrder
    from app.utils.sequences import claim

    if admission is None:
        raise InterventionError("cpi.err_no_stay")
    problem = (form.get("problem") or "").strip()
    if problem not in PROBLEMS:
        raise InterventionError("cpi.err_problem")
    detail = (form.get("detail") or "").strip() or None
    if detail is not None and detail not in PROBLEMS[problem]:
        detail = None
    if PROBLEMS[problem] and detail is None:
        raise InterventionError("cpi.err_detail")
    severity = (form.get("severity") or "").strip()
    if severity not in SEVERITIES:
        raise InterventionError("cpi.err_severity")
    outcome = (form.get("outcome") or "").strip()
    if outcome not in OUTCOMES:
        raise InterventionError("cpi.err_outcome")

    order = dose = None
    order_id = _int(form.get("order_id"))
    if order_id and problem not in NO_ORDER:
        order = db.session.get(MedicationOrder, order_id)
        # Only this child's order — a posted id is a number anybody types.
        if order is None or order.admission_id != admission.id:
            raise InterventionError("cpi.err_order")
    dose_id = _int(form.get("dose_id"))
    if dose_id and problem not in NO_ORDER:
        dose = db.session.get(MedicationDose, dose_id)
        if dose is None or dose.order is None \
                or dose.order.admission_id != admission.id:
            raise InterventionError("cpi.err_order")
        order = order or dose.order
    note = _text(form.get("problem_note"), 500)
    # A problem with nothing to point at must say what it is about.
    if order is None and not note:
        raise InterventionError("cpi.err_note")

    row = PharmacyIntervention(
        admission_id=admission.id, patient_id=admission.patient_id,
        order_id=getattr(order, "id", None), dose_id=getattr(dose, "id", None),
        problem=problem, detail=detail,
        with_consultant=bool(form.get("with_consultant"))
        and problem == "no_indication",
        problem_note=note, severity=severity,
        severity_note=_text(form.get("severity_note"), 255),
        outcome=outcome, outcome_note=_text(form.get("outcome_note"), 255),
        created_by=getattr(user, "id", None))
    claim(row, "number", next_number)
    return row


def respond(row, response, note=None, user=None, at=None):
    """The prescriber's answer. Answering again replaces it — the last word
    is the one that stands, and the activity log keeps the earlier one."""
    if row is None:
        raise InterventionError("cpi.err_missing")
    if response not in RESPONSES or response == "pending":
        raise InterventionError("cpi.err_response")
    if response in ("modified", "rejected") and not (note or "").strip():
        # «Accepted with a change» says nothing without the change, and a
        # rejection without a reason is the one the pharmacist cannot act on.
        raise InterventionError("cpi.err_response_note")
    row.response = response
    row.response_note = _text(note, 255)
    row.responded_by = getattr(user, "id", None)
    row.responded_at = at or datetime.utcnow()
    return row


def open_for(admission):
    """This stay's interventions still waiting for the doctor."""
    if admission is None:
        return []
    return (PharmacyIntervention.query
            .filter_by(admission_id=admission.id, response="pending")
            .order_by(PharmacyIntervention.created_at).all())


def unit_of(admission):
    """``(kind, name)`` of the unit the child lies in, or ``(None, None)``."""
    bed = getattr(admission, "bed", None)
    unit = getattr(bed, "unit", None) if bed is not None else None
    if unit is None:
        return None, None
    return unit.kind, getattr(unit, "name", None)


def _int(value):
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def summary(start, end, kind=None):
    """Interventions written between ``start`` and ``end`` (dates, both
    included), counted the ways the form can be read.

    Acceptance is out of the ones the doctor has answered — a month's
    pending interventions are not rejections, and counting them so would
    make the newest pharmacist look the least listened to.
    """
    rows = (PharmacyIntervention.query
            .filter(PharmacyIntervention.created_at
                    >= datetime.combine(start, time.min),
                    PharmacyIntervention.created_at
                    <= datetime.combine(end, time.max))
            .order_by(PharmacyIntervention.created_at.desc()).all())
    if kind:
        rows = [r for r in rows if unit_of(r.admission)[0] == kind]

    def count(attr, keys):
        return {k: sum(1 for r in rows if getattr(r, attr) == k)
                for k in keys}

    answered = [r for r in rows if r.response != "pending"]
    taken = [r for r in answered if r.response in ("accepted", "modified")]
    units = {}
    for r in rows:
        units.setdefault(unit_of(r.admission)[1] or "—", 0)
        units[unit_of(r.admission)[1] or "—"] += 1
    by_detail = {}
    for r in rows:
        if r.detail:
            key = f"{r.problem}.{r.detail}"
            by_detail[key] = by_detail.get(key, 0) + 1
    return {
        "rows": rows,
        "total": len(rows),
        "by_problem": count("problem", PROBLEMS),
        "by_detail": by_detail,
        "by_severity": count("severity", SEVERITIES),
        "by_outcome": count("outcome", OUTCOMES),
        "by_response": count("response", RESPONSES),
        "by_unit": units,
        "answered": len(answered),
        "accepted_share": (round(100.0 * len(taken) / len(answered), 1)
                           if answered else None),
    }
