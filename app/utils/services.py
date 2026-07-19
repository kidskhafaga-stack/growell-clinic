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


def seed_services():
    """Idempotently ensure the clinic has base services and a visit-type map.

    On a fresh database (no services at all) the canonical set is created. On
    any database, the visit-type→service map is filled in if it's empty, so the
    reception collect flow always has a base charge to bill. Never overrides an
    existing map or existing services. Does not commit — caller owns the txn.
    """
    created = 0
    if Service.query.first() is None:
        for code, ar, en, price, cat, ctype, cval in CORE_SERVICES:
            db.session.add(Service(
                code=code, name=ar, name_en=en, price=price, category=cat,
                commission_type=ctype, commission_value=cval, is_active=True))
            created += 1
        db.session.flush()
    _ensure_visit_type_map()
    return created


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
