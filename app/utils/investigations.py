"""Seed a starter catalogue of common paediatric lab tests and imaging studies.

Idempotent: only inserts entries whose Arabic name is not already present.
Doctors pick from these (with free-text fallback) when ordering investigations
on a prescription.
"""
from app.extensions import db
from app.models import Investigation

# (name_ar, name_en, kind, category)
COMMON_INVESTIGATIONS = [
    # --- Lab tests (تحاليل) ---
    ("صورة دم كاملة", "CBC", "lab", "أمراض الدم"),
    ("بروتين سي التفاعلي", "CRP", "lab", "التهابات"),
    ("سرعة الترسيب", "ESR", "lab", "التهابات"),
    ("تحليل بول كامل", "Urine Analysis", "lab", "بول/كلى"),
    ("مزرعة بول", "Urine Culture", "lab", "بول/كلى"),
    ("تحليل براز", "Stool Analysis", "lab", "جهاز هضمي"),
    ("سكر صائم", "Fasting Blood Sugar", "lab", "سكر"),
    ("سكر عشوائي", "Random Blood Sugar", "lab", "سكر"),
    ("وظائف كبد", "Liver Function Tests", "lab", "كبد"),
    ("وظائف كلى", "Kidney Function Tests", "lab", "كلى"),
    ("أملاح (صوديوم/بوتاسيوم)", "Electrolytes (Na/K)", "lab", "أملاح"),
    ("كالسيوم", "Serum Calcium", "lab", "أملاح"),
    ("فيتامين د", "Vitamin D (25-OH)", "lab", "فيتامينات"),
    ("مخزون الحديد (فيريتين)", "Ferritin", "lab", "أمراض الدم"),
    ("وظائف الغدة الدرقية", "Thyroid Function (TSH/FT4)", "lab", "غدد"),
    ("نسبة الهيموجلوبين", "Hemoglobin", "lab", "أمراض الدم"),
    ("زرع دم", "Blood Culture", "lab", "التهابات"),
    ("تحليل حلق (مزرعة)", "Throat Swab Culture", "lab", "التهابات"),
    # --- Imaging (أشعة) ---
    ("أشعة صدر", "Chest X-ray", "imaging", "أشعة عادية"),
    ("أشعة بطن", "Abdominal X-ray", "imaging", "أشعة عادية"),
    ("موجات صوتية على البطن", "Abdominal Ultrasound", "imaging", "سونار"),
    ("موجات صوتية على المخ", "Cranial Ultrasound", "imaging", "سونار"),
    ("موجات صوتية على الكلى", "Renal Ultrasound", "imaging", "سونار"),
    ("إيكو على القلب", "Echocardiography", "imaging", "قلب"),
    ("أشعة مقطعية على المخ", "Brain CT", "imaging", "مقطعية"),
    ("رنين مغناطيسي على المخ", "Brain MRI", "imaging", "رنين"),
    ("أشعة على عظام", "Bone X-ray", "imaging", "أشعة عادية"),
]


def seed_investigations():
    """Idempotently load the common investigations catalogue."""
    created = 0
    for name_ar, name_en, kind, category in COMMON_INVESTIGATIONS:
        if Investigation.query.filter_by(name_ar=name_ar).first():
            continue
        db.session.add(Investigation(
            name_ar=name_ar, name_en=name_en, kind=kind, category=category,
            is_active=True,
        ))
        created += 1
    db.session.commit()
    return created
