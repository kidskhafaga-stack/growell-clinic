"""Seed a starter catalogue of common paediatric lab tests and imaging studies.

Idempotent: only inserts entries whose code (or, for the older codeless rows,
whose Arabic name) is not already present. Doctors pick from these — with a
free-text fallback — when ordering investigations.

**Why the list grew, and why a code arrived with it.**

Every specialty in the specialties survey answers *"تحاليل تريد رؤيتها كمنحنى"*
with its own list, and between them they name sixty-three things. Eight of them
were in this catalogue. The rest — HbA1c, ferritin, albumin, creatinine and
eGFR, IgE, drug levels, NT-proBNP, INR, calprotectin, coeliac antibodies,
microalbumin, T2\u002a, platelets — a doctor had to type by hand.

That is not only inconvenient, it breaks the curve. `lab_series` groups results
by catalogue id where there is one and **by name where there is not**, so
"HbA1c" typed on Sunday and "hba1c" typed on Thursday are two curves for one
test. Seeding them is what makes the chart question answerable at all.

The code exists because a panel has to name a test from a data file, and a name
is not a name for long — a clinic renames an entry and every reference by text
stops matching. The survey review made the same point about the answer sheet.

**Three of the survey's chart answers are not tests, and are not here.** A chest
X-ray, a panoramic film, before-and-after photographs, retinopathy screening
dates: those are attachments and appointments. They are listed under "charts" in
the questionnaire because that is where a doctor thinks of them, but nothing
draws a curve through a photograph, and a catalogue entry promising one would be
a promise the program cannot keep. What *is* chartable and already works is the
third group — plaque index, decayed-tooth count, intraocular pressure, squint
angle, visual acuity — because those are specialty-panel measurements, and
`series.curves_for` has drawn panel readings since the panels existed.
"""
from app.extensions import db
from app.models import Investigation

# (code, name_ar, name_en, kind, category, unit)
#
# `code` is `None` for the entries that predate it having a meaning: nothing in
# the program refers to a urine culture by key, and inventing keys for the sake
# of symmetry would suggest a promise of stability nobody needs.
COMMON_INVESTIGATIONS = [
    # --- Lab tests (تحاليل) ---
    (None, "صورة دم كاملة", "CBC", "lab", "أمراض الدم", None),
    (None, "بروتين سي التفاعلي", "CRP", "lab", "التهابات", "mg/L"),
    (None, "سرعة الترسيب", "ESR", "lab", "التهابات", "mm/hr"),
    (None, "تحليل بول كامل", "Urine Analysis", "lab", "بول/كلى", None),
    (None, "مزرعة بول", "Urine Culture", "lab", "بول/كلى", None),
    (None, "تحليل براز", "Stool Analysis", "lab", "جهاز هضمي", None),
    ("fbs", "سكر صائم", "Fasting Blood Sugar", "lab", "سكر", "mg/dL"),
    (None, "سكر عشوائي", "Random Blood Sugar", "lab", "سكر", "mg/dL"),
    ("lft", "وظائف كبد", "Liver Function Tests", "lab", "كبد", None),
    ("kft", "وظائف كلى", "Kidney Function Tests", "lab", "كلى", None),
    (None, "أملاح (صوديوم/بوتاسيوم)", "Electrolytes (Na/K)", "lab", "أملاح", "mmol/L"),
    (None, "كالسيوم", "Serum Calcium", "lab", "أملاح", "mg/dL"),
    ("vit_d", "فيتامين د", "Vitamin D (25-OH)", "lab", "فيتامينات", "ng/mL"),
    ("ferritin", "مخزون الحديد (فيريتين)", "Ferritin", "lab", "أمراض الدم", "ng/mL"),
    ("tft", "وظائف الغدة الدرقية", "Thyroid Function (TSH/FT4)", "lab", "غدد", None),
    ("hb", "نسبة الهيموجلوبين", "Hemoglobin", "lab", "أمراض الدم", "g/dL"),
    (None, "زرع دم", "Blood Culture", "lab", "التهابات", None),
    (None, "تحليل حلق (مزرعة)", "Throat Swab Culture", "lab", "التهابات", None),

    # --- What the specialties asked to see as a curve -------------------
    # Added because every one of these was being typed by hand, and a
    # hand-typed test is a test whose curve splits on spelling.
    ("hba1c", "السكر التراكمي HbA1c", "HbA1c", "lab", "سكر", "%"),
    ("igf1", "عامل النمو IGF-1", "IGF-1", "lab", "غدد", "ng/mL"),
    ("microalbumin", "ميكروألبيومين البول", "Urine Microalbumin", "lab", "بول/كلى", "mg/g"),
    ("lipid", "الدهون الكاملة", "Lipid Profile", "lab", "قلب", "mg/dL"),
    ("celiac_abs", "أجسام السيلياك TTG", "Coeliac Antibodies (tTG)", "lab", "جهاز هضمي", "U/mL"),
    ("ntprobnp", "NT-proBNP", "NT-proBNP", "lab", "قلب", "pg/mL"),
    ("inr", "زمن البروثرومبين INR", "INR", "lab", "تجلط", None),
    ("asot", "ASOT", "ASOT", "lab", "التهابات", "IU/mL"),
    ("ige", "IgE الكلي", "Total IgE", "lab", "حساسية", "IU/mL"),
    ("eosinophils", "الحمضات في صورة الدم", "Eosinophil Count", "lab", "حساسية", "cells/µL"),
    ("sweat_test", "اختبار العرق", "Sweat Chloride Test", "lab", "صدر", "mmol/L"),
    ("drug_level", "مستوى الدواء في الدم", "Serum Drug Level", "lab", "أعصاب", "µg/mL"),
    ("sodium", "الصوديوم", "Serum Sodium", "lab", "أملاح", "mmol/L"),
    ("creatinine", "الكرياتينين", "Serum Creatinine", "lab", "كلى", "mg/dL"),
    ("egfr", "معدل الترشيح الكبيبي eGFR", "eGFR", "lab", "كلى", "mL/min/1.73m²"),
    ("albumin", "الألبيومين", "Serum Albumin", "lab", "كبد", "g/dL"),
    ("urine_pcr", "بروتين/كرياتينين البول", "Urine Protein/Creatinine Ratio", "lab", "بول/كلى", "mg/mg"),
    ("calprotectin", "الكالبروتكتين في البراز", "Faecal Calprotectin", "lab", "جهاز هضمي", "µg/g"),
    ("platelets", "الصفائح", "Platelet Count", "lab", "أمراض الدم", "×10³/µL"),
    ("t2_star", "T2* للقلب والكبد", "Cardiac & Hepatic T2*", "lab", "أمراض الدم", "ms"),
    ("bilirubin", "الصفراء (البيليروبين)", "Serum Bilirubin", "lab", "حديثي الولادة", "mg/dL"),
    ("phosphorus", "الفوسفور", "Serum Phosphorus", "lab", "أملاح", "mg/dL"),

    # --- What the proposed specialties follow ---------------------------
    # Added with the nine panels that are not in the survey; see the
    # `_source` note on each of those in specialty_panels.json.
    ("crp", "بروتين سي التفاعلي (CRP)", "C-Reactive Protein", "lab", "التهابات", "mg/L"),
    ("esr", "سرعة الترسيب (ESR)", "ESR", "lab", "التهابات", "mm/hr"),
    ("cbc", "صورة دم كاملة (CBC)", "Complete Blood Count", "lab", "أمراض الدم", None),
    ("anc", "العدلات المطلقة ANC", "Absolute Neutrophil Count", "lab", "أمراض الدم", "cells/µL"),
    ("ana", "الأجسام المضادة للنواة ANA", "Antinuclear Antibodies", "lab", "روماتيزم", None),
    ("immunoglobulins", "الغلوبولينات المناعية IgG/IgA/IgM", "Immunoglobulins", "lab", "مناعة", "mg/dL"),
    ("lymphocyte_subsets", "تحت مجموعات اللمفاويات", "Lymphocyte Subsets", "lab", "مناعة", "cells/µL"),
    ("ammonia", "الأمونيا", "Serum Ammonia", "lab", "أيض", "µmol/L"),
    ("lactate", "اللاكتات", "Serum Lactate", "lab", "أيض", "mmol/L"),
    ("blood_culture", "زرع دم (مزرعة)", "Blood Culture", "lab", "التهابات", None),
    ("urine_culture", "مزرعة بول (زرع)", "Urine Culture", "lab", "بول/كلى", None),
    ("vit_b12", "فيتامين ب١٢", "Vitamin B12", "lab", "فيتامينات", "pg/mL"),

    # --- Radiology (الأشعة) — taken and reported by the radiology room ---
    (None, "أشعة صدر", "Chest X-ray", "imaging", "أشعة عادية", None),
    (None, "أشعة بطن", "Abdominal X-ray", "imaging", "أشعة عادية", None),
    (None, "أشعة مقطعية على المخ", "Brain CT", "imaging", "مقطعية", None),
    (None, "رنين مغناطيسي على المخ", "Brain MRI", "imaging", "رنين", None),
    (None, "أشعة على عظام", "Bone X-ray", "imaging", "أشعة عادية", None),
    (None, "أشعة بانوراما للأسنان", "Panoramic Dental X-ray", "imaging", "أسنان", None),

    # --- Diagnostic studies (الفحوصات التشخيصية) ------------------------
    #
    # **A different room, not a lesser kind.** A sonar, an echo, an ECG and an
    # EEG are done by the treating team — the clinic room, cardiology,
    # neurophysiology — not by radiology, and the person who works the X-ray
    # list is not the person who works these. Asked for in those words:
    # «الاشعة العادية غير الايكو واللترا سونت وال eeg و ال ECG».
    (None, "موجات صوتية على البطن", "Abdominal Ultrasound", "diagnostic", "سونار", None),
    (None, "موجات صوتية على المخ", "Cranial Ultrasound", "diagnostic", "سونار", None),
    (None, "موجات صوتية على الكلى", "Renal Ultrasound", "diagnostic", "سونار", None),
    (None, "إيكو على القلب", "Echocardiography", "diagnostic", "قلب", None),
    # **These two were in no catalogue at all**, so a doctor who wanted one
    # had to free-type it and it reached no worklist under a name anything
    # could group by.
    (None, "رسم قلب (ECG)", "ECG", "diagnostic", "قلب", None),
    (None, "رسم مخ (EEG)", "EEG", "diagnostic", "مخ وأعصاب", None),
]

#: The seeded categories that belong to each room, for the one-time move of a
#: clinic's existing rows. **Only the program's own words are moved**: a
#: category somebody typed themselves is theirs, and guessing at it would
#: refile their catalogue on an assumption they never made.
SEEDED_DIAGNOSTIC_CATEGORIES = ("سونار", "قلب", "مخ وأعصاب")


def move_diagnostics_out_of_radiology():
    """One-time: refile the studies that are not radiology. Returns the count.

    ``diagnostic`` arrived after these rows existed, so every sonar, echo and
    ECG a clinic already had is sitting under ``imaging`` and would land on
    the radiology list — which is the same category error that put an echo on
    the lab bench, one room along.

    **It moves only the program's own words.** A row is refiled when its
    category is one this seed wrote (:data:`SEEDED_DIAGNOSTIC_CATEGORIES`) and
    its kind is still the old one. A clinic that typed its own category keeps
    it, because guessing at somebody else's vocabulary is how a catalogue gets
    refiled on an assumption nobody made — and a wrong guess here hides a
    child's outstanding order on a screen its department never opens.

    **The orders move with the catalogue, and only with it.** A
    ``VisitInvestigation`` carries its own ``kind`` as a snapshot, so an
    existing echo order would keep pointing at radiology even after the
    catalogue row moved. They are moved by following ``investigation_id`` —
    never by matching on the name, which would catch a free-typed order whose
    words merely look similar.

    Idempotent: a second run finds nothing left with the old kind.
    """
    from app.extensions import db
    from app.models.visit import VisitInvestigation

    rows = (Investigation.query
            .filter(Investigation.kind == "imaging",
                    Investigation.category.in_(SEEDED_DIAGNOSTIC_CATEGORIES))
            .all())
    if not rows:
        return 0
    ids = [r.id for r in rows]
    for row in rows:
        row.kind = "diagnostic"
    (VisitInvestigation.query
     .filter(VisitInvestigation.investigation_id.in_(ids),
             VisitInvestigation.kind == "imaging")
     .update({"kind": "diagnostic"}, synchronize_session=False))
    db.session.commit()
    return len(rows)


def seed_investigations():
    """Idempotently load the common investigations catalogue.

    Matched on the code where there is one and on the Arabic name where there
    is not. Both, because this runs on clinics that already have the older
    codeless rows: matching on code alone would insert a second ferritin
    beside the one they have been ordering for months, and every result taken
    under the old row would fall out of the new row's curve.

    A row that exists but has no code **is given one** rather than duplicated,
    which is what lets an upgraded clinic's history join the panels.
    """
    created = adopted = 0
    for code, name_ar, name_en, kind, category, unit in COMMON_INVESTIGATIONS:
        row = None
        if code:
            row = Investigation.query.filter_by(code=code).first()
        if row is None:
            row = Investigation.query.filter_by(name_ar=name_ar).first()

        if row is not None:
            # Only ever fill a blank. A clinic that renamed a test, or set its
            # own unit, keeps what it chose — the seed is a starting point, not
            # an owner.
            if code and not row.code:
                row.code = code
                adopted += 1
            if unit and not row.unit:
                row.unit = unit
            continue

        db.session.add(Investigation(
            code=code, name_ar=name_ar, name_en=name_en, kind=kind,
            category=category, unit=unit, is_active=True,
        ))
        created += 1
    db.session.commit()
    return created
