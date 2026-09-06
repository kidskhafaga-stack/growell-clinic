"""Core services + visit-type→service mapping seeded on every install.

These used to be created only by the demo seeder, so a fresh (or reset)
database had no services and no visit-type pricing — the reception "collect"
flow then had nothing to bill. This module ensures a permanent, editable set of
services and a non-empty visit-type map, independent of the demo data.
"""
from app.extensions import db
from app.models import Service

# Canonical services created on a fresh install (clinic edits prices/commission
# afterwards). Stable codes so the visit-type map and reports stay anchored.
# The consultant's round on an inpatient, as a line the family can be billed
# for. **Shipped at zero, and that is the switch**, exactly as the bed rate is:
# a clinic that never prices it is never charged for it and never sees a card
# about it, and a resident walking the ward every morning stays what it has
# always been — a clinical note with no money attached.
#
# The price is set **per consultant**, on the doctor–service row that already
# exists for every other service: `price_override` is what the family pays for
# that consultant's round, and a `fixed` commission on the same row is what the
# hospital pays the consultant. The difference is the hospital's margin, and it
# is computed by the same `doctor_share` every other line uses.
#
# Which is the arrangement as it was described: *«غالباً الاستشاري بيتحاسب من
# المستشفى في ساعتها، والمستشفى بتحط على فاتورة الأهل بعد كده وغالباً بيبقى
# ليها نسبة من المبلغ ده»*.
ROUND_SERVICE = ("SVC-ROUND", "مرور استشاري", "Consultant round",
                 0, "consultation", "none", 0)

# (code, name_ar, name_en, price, category, commission_type, commission_value)
CORE_SERVICES = [
    ("SVC-KASHF", "كشف", "Consultation", 250, "consultation", "percent", 40),
    ("SVC-ESHARA", "استشارة", "Follow-up consultation", 150, "consultation", "percent", 50),
    ("SVC-MOTABAA", "متابعة", "Follow-up", 150, "consultation", "percent", 50),
    ("SVC-VACFEE", "رسم تطعيم", "Vaccination fee", 100, "vaccination_fee", "fixed", 20),
    ("SVC-NEB", "جلسة نيبولايزر", "Nebulizer session", 100, "procedure", "percent", 30),
    ("SVC-ECHO", "إيكو / سونار", "Echo / ultrasound", 400, "radiology", "percent", 30),
    ("SVC-LAB", "تحاليل", "Lab tests", 0, "lab", "none", 0),
]


# Wizard capability → the base coded services it brings. Ticking a capability
# in the facility setup creates these (idempotent by code); the user then edits
# prices/commissions or adds extra services with the same screen.
CAPABILITY_SERVICES = {
    "general_consultation": [
        ("SVC-KASHF", "كشف", "Consultation", 250, "consultation", "percent", 40),
        ("SVC-ESHARA", "استشارة", "Follow-up consultation", 150, "consultation", "percent", 50),
        ("SVC-NEB", "جلسة نيبولايزر", "Nebulizer session", 100, "procedure", "percent", 30),
    ],
    "followup": [
        ("SVC-MOTABAA", "متابعة", "Follow-up", 150, "consultation", "percent", 50),
    ],
    "vaccination": [
        ("SVC-VACFEE", "رسم تطعيم", "Vaccination fee", 100, "vaccination_fee", "fixed", 20),
    ],
    "growth_monitoring": [
        ("SVC-GROWTH", "تقييم نمو", "Growth assessment", 100, "consultation", "percent", 40),
    ],
    "emergency_care": [
        ("SVC-URGENT", "كشف طوارئ", "Urgent consultation", 350, "consultation", "percent", 40),
    ],
    "home_care": [
        ("SVC-HOME", "زيارة منزلية", "Home visit", 500, "consultation", "percent", 50),
    ],
    "ecg": [("SVC-ECG", "رسم قلب", "ECG", 150, "procedure", "percent", 30)],
    "echo": [("SVC-ECHO", "إيكو على القلب", "Echocardiography", 400, "radiology", "percent", 30)],
    "eeg": [("SVC-EEG", "رسم مخ", "EEG", 300, "procedure", "percent", 30)],
    "spirometry": [("SVC-SPIRO", "قياس وظائف تنفس", "Spirometry", 200, "procedure", "percent", 30)],
    "audiology": [("SVC-AUDIO", "قياس سمع", "Audiometry", 200, "procedure", "percent", 30)],
    "vision_screening": [("SVC-VISION", "فحص نظر", "Vision screening", 100, "procedure", "percent", 30)],
    "ultrasound": [("SVC-US", "سونار", "Ultrasound", 300, "radiology", "percent", 30)],
    "xray": [("SVC-XRAY", "أشعة عادية", "X-ray", 200, "radiology", "percent", 30)],
    "laboratory": [("SVC-LAB", "تحاليل", "Lab tests", 0, "lab", "none", 0)],
    "sample_collection": [("SVC-SAMPLE", "سحب عينة", "Sample collection", 50, "lab", "none", 0)],
    "observation": [("SVC-OBS", "ملاحظة (يوم)", "Observation (day)", 500, "other", "none", 0)],
    "day_care": [("SVC-DAYCARE", "رعاية نهارية (يوم)", "Day care (day)", 700, "other", "none", 0)],
    "nicu": [("SVC-NICU", "حضّانة (يوم)", "NICU (day)", 1500, "other", "none", 0), ROUND_SERVICE],
    "icu": [("SVC-ICU", "رعاية مركزة (يوم)", "ICU (day)", 2000, "other", "none", 0), ROUND_SERVICE],
    "ward": [("SVC-WARD", "إقامة داخلية (يوم)", "Inpatient ward (day)", 800, "other", "none", 0),
             ROUND_SERVICE],

    # Paediatric dentistry, and the word paediatric is doing work here. A
    # general dental list carries implants, bridges and dentures; a
    # five-year-old has none of them, and every row like that is a row
    # somebody scrolls past to reach the one they want. What a child's mouth
    # actually needs is on this list and nothing else is: the pulpotomy, the
    # stainless steel crown and the space maintainer are here precisely
    # because the patient is a child.
    #
    # Filling, pulp treatment and crown are priced **per tooth**, because that
    # is how they are agreed and how a treatment plan is built — one line per
    # tooth, which is what lets a parent hold the statement against their
    # child's mouth.
    #
    # The commission is 40% rather than the 30% every other procedure here
    # carries. A nebulizer session is set up by a nurse; a filling is the
    # dentist's own hands for its whole length, and a default that paid it
    # like a nebulizer would be visibly wrong to the first dentist who read
    # it. Every figure below is a starting point the clinic edits on the
    # services screen, the same as the rest of this file.
    "dentistry": [
        ("SVC-DENT-EXAM", "كشف أسنان", "Dental examination",
         300, "consultation", "percent", 40),
        ("SVC-DENT-EMERG", "علاج ألم طارئ", "Emergency pain relief",
         400, "procedure", "percent", 40),
        ("SVC-DENT-CLEAN", "تنظيف وتلميع", "Scale and polish",
         500, "procedure", "percent", 40),
        ("SVC-DENT-FLUOR", "تفلور", "Fluoride application",
         350, "procedure", "percent", 40),
        ("SVC-DENT-SEAL", "حشو وقائي (سيلانت) — للسن", "Fissure sealant (per tooth)",
         350, "procedure", "percent", 40),
        ("SVC-DENT-FILLP", "حشو سن لبني — للسن", "Filling, primary tooth (per tooth)",
         600, "procedure", "percent", 40),
        ("SVC-DENT-FILL", "حشو سن دائم — للسن", "Filling, permanent tooth (per tooth)",
         750, "procedure", "percent", 40),
        ("SVC-DENT-PULPO", "بتر عصب — للسن", "Pulpotomy (per tooth)",
         1100, "procedure", "percent", 40),
        ("SVC-DENT-PULPE", "علاج عصب لبني — للسن", "Pulpectomy, primary tooth (per tooth)",
         1400, "procedure", "percent", 40),
        ("SVC-DENT-SSC", "تلبيسة ستانلس — للسن", "Stainless steel crown (per tooth)",
         1300, "procedure", "percent", 40),
        ("SVC-DENT-ZR", "تلبيسة تجميلية أمامية — للسن", "Aesthetic anterior crown (per tooth)",
         1800, "procedure", "percent", 40),
        ("SVC-DENT-EXTP", "خلع سن لبني", "Extraction, primary tooth",
         400, "procedure", "percent", 40),
        ("SVC-DENT-EXT", "خلع سن دائم", "Extraction, permanent tooth",
         700, "procedure", "percent", 40),
        ("SVC-DENT-SPACE", "حافظ مسافة", "Space maintainer",
         1800, "procedure", "percent", 40),
        ("SVC-DENT-XRAY", "أشعة أسنان", "Dental radiograph",
         200, "radiology", "percent", 30),
    ],
}


def _add_rows(rows, existing):
    created = 0
    for code, ar, en, price, cat, ctype, cval in rows:
        if code in existing:
            continue
        db.session.add(Service(
            code=code, name=ar, name_en=en, price=price, category=cat,
            commission_type=ctype, commission_value=cval, is_active=True))
        existing.add(code)
        created += 1
    return created


def seed_services_for_caps(caps):
    """Create the base coded services matching the facility's ticked
    capabilities (idempotent by code — re-running the wizard only adds what's
    new). Falls back to the canonical core set when no capability maps.
    Does not commit — caller owns the txn."""
    existing = {c for (c,) in Service.query.with_entities(Service.code).all() if c}
    created = 0
    matched = False
    for cap in caps or []:
        rows = CAPABILITY_SERVICES.get(cap)
        if rows:
            matched = True
            created += _add_rows(rows, existing)
    if not matched and Service.query.first() is None:
        created += _add_rows(CORE_SERVICES, existing)
    if created:
        db.session.flush()
    _ensure_visit_type_map()
    return created


def seed_services():
    """Idempotently ensure the clinic has base services and a visit-type map.

    Uses the facility's configured capabilities (from the setup wizard) when
    available so the seeded set matches what the clinic actually offers; falls
    back to the canonical core set otherwise. On any database, the visit-type→
    service map is filled in if it's empty, so the reception collect flow
    always has a base charge to bill. Never overrides existing services or a
    clinic-defined map. Does not commit — caller owns the txn.
    """
    if Service.query.first() is not None:
        _ensure_visit_type_map()
        return 0
    try:
        from app.utils.facility import capabilities
        caps = capabilities()
    except Exception:  # noqa: BLE001 - settings table not ready
        caps = []
    return seed_services_for_caps(caps)


# Set once the visit-type base charges have been filled in, so the self-heal
# never runs again and cannot argue with a clinic that cleared one on purpose.
VT_SEEDED_KEY = "visit_type_charges_seeded"


def _ensure_visit_type_map():
    """Point each appointment type at a real base-charge service, if unset.

    Prefers the canonical code; otherwise the first active service of a fitting
    category (so it works even with a clinic's own custom services).

    The charge lives on the service now rather than in a settings blob, so this
    fills ``Service.visit_type`` — and never over a slot a clinic has already
    claimed, on the new screen or the old map.
    """
    from app.models import Setting
    from app.utils.pricing import visit_type_service_map

    # Once, and recorded. This runs on every visit to the services screen, and
    # without the stamp it re-claimed a slot the moment a clinic *deliberately*
    # cleared the last one — so "this visit type has no base charge" was a
    # state the program would not let anybody be in. Refilling an empty choice
    # is the self-heal arguing with the person it is meant to help.
    if Setting.get(VT_SEEDED_KEY) == "1":
        return
    if visit_type_service_map():
        Setting.set(VT_SEEDED_KEY, "1")
        return  # respect a clinic-defined map (migrated on upgrade)
    if Service.query.filter(Service.visit_type.isnot(None)).first() is not None:
        Setting.set(VT_SEEDED_KEY, "1")
        return  # already assigned on the services screen

    by_code = {s.code: s for s in Service.query.all()}

    def pick(code, *categories):
        if code in by_code:
            return by_code[code]
        return (Service.query.filter(Service.is_active.is_(True),
                                     Service.category.in_(categories))
                .order_by(Service.id).first())

    wanted = [
        ("new",          pick("SVC-KASHF", "consultation")),
        ("consultation", pick("SVC-ESHARA", "consultation")),
        ("followup",     pick("SVC-MOTABAA", "consultation")),
        ("vaccination",  pick("SVC-VACFEE", "vaccination_fee")),
        ("procedure",    pick("SVC-NEB", "procedure", "radiology")),
    ]
    # One base charge per service: "urgent" and "new" both wanting the same
    # consultation would have the second quietly steal it from the first.
    taken = set()
    for key, svc in wanted:
        if svc is None or svc.id in taken or svc.visit_type:
            continue
        svc.visit_type = key
        taken.add(svc.id)
    from app.models import Setting
    Setting.set(VT_SEEDED_KEY, "1")


def next_service_code():
    """Sequential auto-code (SVC-001, SVC-002…) for services created without
    one, skipping past both auto and canonical codes."""
    top = 0
    for (code,) in Service.query.with_entities(Service.code).all():
        if code and code.upper().startswith("SVC-"):
            tail = code[4:]
            if tail.isdigit():
                top = max(top, int(tail))
    return f"SVC-{top + 1:03d}"


def backfill_service_codes():
    """Give every code-less service an auto code (idempotent; no commit)."""
    fixed = 0
    for svc in Service.query.filter((Service.code.is_(None)) | (Service.code == "")).all():
        svc.code = next_service_code()
        db.session.flush()
        fixed += 1
    return fixed
