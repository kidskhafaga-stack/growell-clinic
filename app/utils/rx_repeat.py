"""Repeat the last prescription for a long-term problem (DOCTOR_EASE_PLAN.md ب-٢).

A child with asthma, epilepsy or hypothyroidism — or an adult with diabetes
or high blood pressure in another specialty — comes back for the same
medicines. Writing them again line by line is the slow part; copying them
blindly is the dangerous part, because a child who has grown needs a new
dose.

So the old prescription is offered beside each active problem, and repeating
it opens a **new** prescription that the doctor reviews and saves:

* a medicine dosed by weight is worked out again on today's weight, by the
  same code as any other line on the prescription screen, and the line says
  what it was and on which weight, when the dose changed;
* a medicine that is not dosed by weight (most adult chronic medicines) keeps
  its dose, and the line says it is last time's;
* the allergy and interaction checks run on the repeated lines like on any
  other;
* the weight used is the latest one on file with its date. When it is older
  than the clinic's limit it is **not** used on its own: the screen asks for
  today's weight and offers the old one only as a deliberate press.
"""
from datetime import timedelta

from app.extensions import db
from app.utils.clock import local_today

# How old a weight may be before the prescription screen stops using it on
# its own. A clinic setting (``rx_weight_stale_days``); this is only the value
# it starts with, and it decides when to ask for a new weight — never a dose.
STALE_DAYS_DEFAULT = 30


def stale_days():
    from app.models import Setting

    try:
        days = int(Setting.get("rx_weight_stale_days", STALE_DAYS_DEFAULT))
    except (TypeError, ValueError):
        days = STALE_DAYS_DEFAULT
    return max(days, 1)


def weight_info(patient):
    """``{kg, date, days, stale}`` for the latest weight on file, or ``None``."""
    from app.utils.dosing import latest_weight_record

    if patient is None:
        return None
    row = latest_weight_record(patient)
    if row is None or not row.weight_kg:
        return None
    days = (local_today() - row.record_date).days
    return {"kg": row.weight_kg, "date": row.record_date.isoformat(), "days": days,
            "stale": days > stale_days()}


def weight_on(patient_id, on_date):
    """The weight on file on or before ``on_date`` — what the old dose was
    worked out on, as far as the file knows."""
    from app.models import GrowthRecord

    row = (GrowthRecord.query
           .filter(GrowthRecord.patient_id == patient_id,
                   GrowthRecord.weight_kg.isnot(None),
                   GrowthRecord.record_date <= on_date)
           .order_by(GrowthRecord.record_date.desc()).first())
    return row.weight_kg if row is not None else None


def _norm(text):
    return " ".join((text or "").split()).lower()


def _matches(problem, rx):
    code, rx_code = _norm(problem.icd_code), _norm(rx.diagnosis_code)
    if code and rx_code and (rx_code.startswith(code) or code.startswith(rx_code)):
        return True
    said = _norm(rx.diagnosis)
    if not said:
        return False
    return any(t and t in said for t in (_norm(problem.title), _norm(problem.title_en)))


def last_for(problem, rows=None):
    """The newest prescription with medicines written for this problem."""
    from app.models import Prescription

    if rows is None:
        rows = (Prescription.query.filter_by(patient_id=problem.patient_id)
                .order_by(Prescription.rx_date.desc(), Prescription.id.desc()).all())
    for rx in rows:
        if rx.items and _matches(problem, rx):
            return rx
    return None


def offers(patient, lang="ar"):
    """One offer per active problem that has a prescription to repeat:
    ``[{problem, title, rx, date, count}]``."""
    from app.models import PatientProblem, Prescription

    if patient is None:
        return []
    problems = (PatientProblem.query
                .filter_by(patient_id=patient.id, status="active")
                .order_by(PatientProblem.id).all())
    if not problems:
        return []
    since = local_today() - timedelta(days=3 * 365)
    rows = (Prescription.query
            .filter(Prescription.patient_id == patient.id, Prescription.rx_date >= since)
            .order_by(Prescription.rx_date.desc(), Prescription.id.desc()).all())
    out = []
    for pr in problems:
        rx = last_for(pr, rows)
        if rx is not None:
            out.append({"problem": pr.id, "title": pr.display_title(lang), "rx": rx.id,
                        "date": rx.rx_date.isoformat(), "count": len(rx.items)})
    return out


def lines(rx):
    """The old prescription's lines, ready for the prescription screen, each
    carrying what it was and the drug's weight rule for the new dose."""
    prev_weight = weight_on(rx.patient_id, rx.rx_date)
    out = []
    for it in rx.items:
        drug = it.drug
        out.append({
            "drug_id": it.drug_id or "", "name": it.drug_name,
            "dose": it.dose or "", "frequency": it.frequency or "",
            "duration": it.duration or "", "instructions": it.instructions or "",
            "dose_per_kg": drug.dose_per_kg if drug is not None else None,
            "max_per_kg": drug.max_per_kg if drug is not None else None,
            "conc": drug.conc_mg_per_ml if drug is not None else None,
            "prev_dose": it.dose or "", "prev_weight": prev_weight,
            "prev_date": rx.rx_date.isoformat(),
        })
    return out


def repeatable(rx_id, patient):
    """The prescription asked for, when it belongs to this patient."""
    from app.models import Prescription

    if not rx_id or patient is None:
        return None
    rx = db.session.get(Prescription, rx_id)
    return rx if rx is not None and rx.patient_id == patient.id and rx.items else None


__all__ = ["STALE_DAYS_DEFAULT", "last_for", "lines", "offers", "repeatable",
           "stale_days", "weight_info", "weight_on"]
