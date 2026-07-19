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
    "nicu": [("SVC-NICU", "حضّانة (يوم)", "NICU (day)", 1500, "other", "none", 0)],
    "icu": [("SVC-ICU", "رعاية مركزة (يوم)", "ICU (day)", 2000, "other", "none", 0)],
    "ward": [("SVC-WARD", "إقامة داخلية (يوم)", "Inpatient ward (day)", 800, "other", "none", 0)],
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


def _ensure_visit_type_map():
    """Point each appointment type at a real base-charge service, if unset.

    Prefers the canonical code; otherwise the first active service of a fitting
    category (so it works even with a clinic's own custom services).
    """
    from app.utils.pricing import save_visit_type_service_map, visit_type_service_map

    if visit_type_service_map():
        return  # respect a clinic-defined map

    by_code = {s.code: s for s in Service.query.all()}

    def pick(code, *categories):
        if code in by_code:
            return by_code[code].id
        svc = (Service.query.filter(Service.is_active.is_(True),
                                    Service.category.in_(categories))
               .order_by(Service.id).first())
        return svc.id if svc else None

    mapping = {
        "new":          pick("SVC-KASHF", "consultation"),
        "urgent":       pick("SVC-KASHF", "consultation"),
        "consultation": pick("SVC-ESHARA", "consultation"),
        "followup":     pick("SVC-MOTABAA", "consultation"),
        "vaccination":  pick("SVC-VACFEE", "vaccination_fee"),
        "procedure":    pick("SVC-NEB", "procedure", "radiology"),
    }
    mapping = {k: v for k, v in mapping.items() if v}
    if mapping:
        save_visit_type_service_map(mapping)


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
