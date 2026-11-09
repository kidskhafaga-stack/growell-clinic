"""The dose for this child as the order is written — one answer for every
order form that is not the prescription screen (DOCTOR_EASE ط-٣ in
emergency, د-٣ on the ward).

The clinic's own dosing rules (``rx_safety.check`` → ``dosing.calculate``),
the weight they were worked from with its date, the allergy on the file. A
suggestion the doctor presses to use — never filled in by itself, and no
number that is not the clinic's own rule.
"""
from app.extensions import db


def for_patient(patient, drug=None, name="", lang="ar"):
    """A JSON-ready dict: ``weight``, ``weight_date``, and — once a drug is
    named — ``generic``, ``dose_mg``(``_max``), ``ml``(``_max``),
    ``doses_per_day``, ``warnings`` (said) and ``allergy`` (said, or None)."""
    from app.i18n import t
    from app.utils.dosing import latest_weight_record
    from app.utils.rx_safety import check

    weighed = latest_weight_record(patient)
    out = {"weight": weighed.weight_kg if weighed else None,
           "weight_date": weighed.record_date.isoformat() if weighed else None}
    name = (name or "").strip()[:200]
    if not drug and not name:
        return out
    result = check([{"name": name or drug.label(lang), "drug": drug}], patient=patient, lang=lang)
    line = result["lines"][0]
    res = line.get("result") or {}
    alg = line.get("allergy")
    out.update({
        "generic": line.get("generic_name") or "",
        "dose_mg": res.get("dose_mg"), "dose_mg_max": res.get("dose_mg_max"),
        "ml": res.get("ml"), "ml_max": res.get("ml_max"),
        "doses_per_day": res.get("doses_per_day"),
        "warnings": [t("drugbook.warn_" + w) for w in line.get("warnings") or []],
        "allergy": (t("allergy.flash_" + alg["level"]).replace("{drug}", line["name"])
                    .replace("{allergy}", alg["allergy"]) if alg else None),
    })
    return out


def weigh(patient, kg, visit_id=None, source="ward"):
    """Today's weight. Returns the record, or ``None`` for a number that is
    not a child's (0.3–200 kg). The caller commits."""
    from app.models import GrowthRecord
    from app.utils.clock import local_today

    if kg is None or not (0.3 <= kg <= 200):
        return None
    row = GrowthRecord(patient_id=patient.id, visit_id=visit_id,
                       record_date=local_today(), weight_kg=round(kg, 2), source=source)
    db.session.add(row)
    return row
