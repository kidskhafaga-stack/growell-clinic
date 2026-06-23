"""Seed a starter catalogue of common (paediatric-oriented) drugs.

Idempotent: only inserts drugs whose trade name is not already present.
"""
from app.extensions import db
from app.models import Drug, DrugInteraction

# (trade, generic, form, strength, default_dose, default_frequency, max_daily_dose)
COMMON_DRUGS = [
    ("Paramol", "Paracetamol", "syrup", "120 mg/5 ml", "10–15 mg/kg", "كل 6 ساعات", "60 mg/kg/يوم"),
    ("Cetal", "Paracetamol", "syrup", "250 mg/5 ml", "10–15 mg/kg", "كل 6 ساعات", "60 mg/kg/يوم"),
    ("Brufen", "Ibuprofen", "suspension", "100 mg/5 ml", "5–10 mg/kg", "كل 8 ساعات", "40 mg/kg/يوم"),
    ("Profinal", "Ibuprofen", "suspension", "100 mg/5 ml", "5–10 mg/kg", "كل 8 ساعات", "40 mg/kg/يوم"),
    ("Hibiotic", "Amoxicillin", "suspension", "250 mg/5 ml", "25–50 mg/kg/يوم", "كل 8 ساعات", "—"),
    ("Augmentin", "Amoxicillin/Clavulanate", "suspension", "457 mg/5 ml", "25–45 mg/kg/يوم", "كل 12 ساعة", "—"),
    ("Zisrocin", "Azithromycin", "suspension", "200 mg/5 ml", "10 mg/kg", "مرة يومياً", "—"),
    ("Suprax", "Cefixime", "suspension", "100 mg/5 ml", "8 mg/kg/يوم", "كل 12–24 ساعة", "—"),
    ("Zyrtec", "Cetirizine", "drops", "10 mg/ml", "حسب العمر", "مرة يومياً", "—"),
    ("Allergyl", "Chlorpheniramine", "syrup", "2 mg/5 ml", "حسب العمر", "كل 8 ساعات", "—"),
    ("Ventolin", "Salbutamol", "syrup", "2 mg/5 ml", "0.1 mg/kg", "كل 8 ساعات", "—"),
    ("Motilium", "Domperidone", "suspension", "1 mg/ml", "0.25 mg/kg", "قبل الأكل ×3", "—"),
    ("Rehydran", "Oral Rehydration Salts", "other", "كيس", "بعد كل إسهال", "حسب الحاجة", "—"),
    ("Vidrop", "Vitamin D3", "drops", "2800 IU/ml", "نقطة يومياً", "مرة يومياً", "—"),
    ("Prednisolone", "Prednisolone", "syrup", "5 mg/5 ml", "1–2 mg/kg/يوم", "حسب الوصف", "—"),
    ("Nasal Saline", "Sodium Chloride 0.9%", "drops", "0.9%", "نقطتان لكل فتحة", "حسب الحاجة", "—"),
]

# Weight-based dosing by generic: (mg/kg per dose, max mg/kg per day).
_DOSING_BY_GENERIC = {
    "Paracetamol": (12.5, 60),
    "Ibuprofen": (7.5, 40),
    "Amoxicillin": (15, 45),
    "Amoxicillin/Clavulanate": (15, 45),
    "Azithromycin": (10, 10),
    "Cefixime": (4, 8),
    "Salbutamol": (0.1, 0.3),
    "Domperidone": (0.25, 0.75),
    "Prednisolone": (1, 2),
}


def _parse_conc(strength):
    """Parse '250 mg/5 ml' → 50.0 (mg per ml), or None."""
    import re
    m = re.search(r"(\d+(?:\.\d+)?)\s*mg\s*/\s*(\d+(?:\.\d+)?)\s*ml", strength or "", re.I)
    if not m:
        return None
    mg, ml = float(m.group(1)), float(m.group(2))
    return round(mg / ml, 3) if ml else None


# Pairs by generic name → warned when both appear together.
_INTERACTIONS = [
    ("Ibuprofen", "Prednisolone", "moderate", "زيادة خطر تهيّج/نزيف المعدة"),
    ("Azithromycin", "Domperidone", "severe", "خطر إطالة فترة QT"),
    ("Cetirizine", "Chlorpheniramine", "moderate", "ازدواج مضادات الهيستامين (نعاس زائد)"),
    ("Ibuprofen", "Paracetamol", "mild", "مسكّنان معاً — راقب الجرعات"),
]


def seed_drugs():
    created = 0
    by_generic = {}
    for trade, generic, form, strength, dose, freq, maxd in COMMON_DRUGS:
        if Drug.query.filter_by(trade_name=trade).first():
            continue
        d = Drug(trade_name=trade, generic_name=generic, form=form, strength=strength,
                 default_dose=dose, default_frequency=freq, max_daily_dose=maxd,
                 is_active=True)
        db.session.add(d)
        created += 1
    db.session.flush()

    # Backfill weight-based dosing + liquid concentration (idempotent).
    for d in Drug.query.all():
        by_generic.setdefault(d.generic_name, d)
        dosing = _DOSING_BY_GENERIC.get(d.generic_name)
        if dosing:
            if d.dose_per_kg is None:
                d.dose_per_kg = dosing[0]
            if d.max_per_kg is None:
                d.max_per_kg = dosing[1]
        if d.conc_mg_per_ml is None:
            conc = _parse_conc(d.strength)
            if conc:
                d.conc_mg_per_ml = conc

    for ga, gb, sev, note in _INTERACTIONS:
        a, b = by_generic.get(ga), by_generic.get(gb)
        if not a or not b:
            continue
        exists = DrugInteraction.query.filter(
            ((DrugInteraction.drug_a_id == a.id) & (DrugInteraction.drug_b_id == b.id))
            | ((DrugInteraction.drug_a_id == b.id) & (DrugInteraction.drug_b_id == a.id))
        ).first()
        if not exists:
            db.session.add(DrugInteraction(drug_a_id=a.id, drug_b_id=b.id,
                                           severity=sev, note=note))
    return created
