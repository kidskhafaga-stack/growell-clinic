"""Medication reconciliation helper (GAHAR).

Surfaces the patient's recent medications (from prior prescriptions) so the
doctor can review and reconcile — continue, stop or modify — when examining or
writing a new prescription, avoiding duplication and interactions.
"""
from datetime import date, timedelta
from app.utils.clock import local_today


def recent_medications(patient_id, days=180, limit=25):
    """Most-recent distinct medications the patient was prescribed within
    ``days``. Returns dicts: {drug_id, drug_name, dose, frequency, duration,
    instructions, rx_date}, newest first, deduped by drug name.
    """
    from app.models import Prescription, PrescriptionItem

    since = local_today() - timedelta(days=days)
    rows = (PrescriptionItem.query
            .join(Prescription, PrescriptionItem.prescription_id == Prescription.id)
            .filter(Prescription.patient_id == patient_id,
                    Prescription.rx_date >= since)
            .order_by(Prescription.rx_date.desc(), PrescriptionItem.id.desc())
            .all())
    seen, out = set(), []
    for it in rows:
        key = (it.drug_name or "").strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append({
            "drug_id": it.drug_id or "", "drug_name": it.drug_name,
            "dose": it.dose or "", "frequency": it.frequency or "",
            "duration": it.duration or "", "instructions": it.instructions or "",
            "rx_date": it.prescription.rx_date.isoformat(),
        })
        if len(out) >= limit:
            break
    return out
