"""The clinic's reference data — everything a real clinic needs, and nothing
that pretends to be a patient.

Two different things used to be tangled together: the **catalogues** (vaccine
names, the core services, the drug reference, investigations, store
consumables, the chart of accounts…) and the **demo dataset** (made-up
patients, visits and invoices). A clinic that wanted the vaccine list ended up
loading fake cases, and a clinic that cleared the fake cases lost catalogue
rows with them.

``seed_reference()`` is the catalogue half: it creates only master data, it is
idempotent, and it never creates a patient, a visit, an invoice or a user. It
runs on install, on every upgrade, and on demand via ``flask seed-reference``.
"""
from app.extensions import db


def _try(step, key, out):
    """Run one seeding step; a failure is recorded, never fatal."""
    try:
        out[key] = step() or 0
    except Exception as exc:                                # noqa: BLE001
        out.setdefault("errors", []).append(f"{key}: {exc}")
    return out


def seed_reference():
    """Seed every catalogue. Returns ``{step: created}`` (+ ``errors``)."""
    out = {}

    def _vaccines():
        from app.utils.vaccines import seed_vaccine_schedules, seed_vaccines
        n = seed_vaccines() or 0
        seed_vaccine_schedules()
        return n

    def _services():
        from app.utils.services import backfill_service_codes, seed_services
        n = seed_services() or 0
        backfill_service_codes()
        return n

    def _drugs():
        from app.utils.drugs import seed_drugs
        return seed_drugs() or 0

    def _investigations():
        from app.utils.investigations import seed_investigations
        return seed_investigations() or 0

    def _drugbook():
        from app.utils.drugbook_seed import (link_existing_drugs, seed_drugbook,
                                             seed_interactions)
        made = seed_drugbook()
        link_existing_drugs()
        seed_interactions()
        return (made.get("generics", 0) or 0) + (made.get("brands", 0) or 0)

    def _store():
        from app.utils.store_seed import seed_store_items_if_empty
        return seed_store_items_if_empty() or 0

    def _templates():
        from app.utils.whatsapp import seed_system_templates
        return seed_system_templates() or 0

    _try(_vaccines, "vaccines", out)
    _try(_services, "services", out)
    _try(_drugs, "drugs", out)
    _try(_investigations, "investigations", out)
    _try(_drugbook, "drug_reference", out)
    _try(_store, "store_items", out)
    _try(_templates, "message_templates", out)
    db.session.commit()
    return out


def reference_counts():
    """What the catalogues currently hold — for the CLI and the setup screen."""
    from app.models import (Drug, GenericDrug, Investigation, Service,
                            StoreItem, Vaccine)

    return {
        "vaccines": Vaccine.query.count(),
        "services": Service.query.count(),
        "drugs": Drug.query.count(),
        "ingredients": GenericDrug.query.count(),
        "investigations": Investigation.query.count(),
        "store_items": StoreItem.query.count(),
    }
