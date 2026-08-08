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

# The devices a paediatric clinic runs studies on. Catalogue data, so it
# belongs with the rest of the reference rather than only in the CLI.
DEFAULT_DEVICES = [
    ("جهاز وظائف تنفس", "Spirometer", "MIR", "Spirobank II", "spirometry", "WinSpiroPRO"),
    ("جهاز رسم قلب", "ECG", None, None, "ecg", None),
    ("جهاز إيكو", "Echocardiography", None, None, "echo", None),
    ("جهاز رسم مخ", "EEG", None, None, "eeg", None),
    ("جهاز موجات صوتية", "Ultrasound", None, None, "ultrasound", None),
    ("جهاز سمعيات", "Audiometer", None, None, "audiometry", None),
    ("جهاز ضغط الأذن", "Tympanometer", None, None, "tympanometry", None),
]


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

    def _egypt_register():
        """Every drug registered in Egypt — 25,000 trade names with prices.

        Seeded with the rest of the catalogues rather than left behind a
        button, because that is what an install is *for*: the curated 292
        brands are the ones that carry paediatric dosing, but a doctor writes
        from the whole market, and one who types a brand and finds nothing
        does not conclude the catalogue is short — they type it as free text,
        and a free-text line is one nothing can check for interactions,
        allergies or a dose.

        Placed after the drug reference for readability rather than for
        correctness: the register links to an ingredient on an exact name
        match, and ``_drugbook`` finishes by running ``link_existing_drugs``,
        which back-fills anything still unlinked. So either order ends with
        the same 2,000 dosable brands — which is worth knowing before
        somebody "fixes" the order and expects a difference.
        """
        from app.utils.egypt_drugs import seed_register

        return seed_register()

    def _lookups():
        """The clinic's own short lists — types, categories, units, kinds.

        Seeded before the store items so the first item added has a type to
        pick rather than an empty dropdown and a reason to type free text.
        """
        from app.utils.lookups import ensure_seeded

        return ensure_seeded()

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

    def _devices():
        from app.models import MedicalDevice
        made = 0
        for name, name_en, manuf, model, dtype, sw in DEFAULT_DEVICES:
            if MedicalDevice.query.filter_by(name=name).first() is not None:
                continue
            db.session.add(MedicalDevice(
                name=name, name_en=name_en, manufacturer=manuf, model=model,
                device_type=dtype, software=sw, connection_type="usb",
                import_mode="manual", is_active=True, is_system=True))
            made += 1
        db.session.flush()
        return made

    def _device_measurements():
        """Give every seeded device the fields its report captures.

        Without this a device arrives configured, priced and unusable: opening
        a study says "this device has no measurement template".
        """
        from app.utils.device_templates import seed_device_measurements

        return seed_device_measurements()

    def _device_services():
        """Give every device the service that bills it.

        A study has to cost something: without a service behind the device,
        running an echo charges nothing. Existing services are matched by
        their device type first (the seeded «إيكو / سونار» covers both the echo
        and the ultrasound), and only the genuinely missing ones are created —
        priced 0 so the clinic sets its own price rather than inheriting a
        made-up one."""
        from app.models import MedicalDevice, Service
        from app.utils.services import next_service_code

        # device_type → (service name, category, and the words that identify an
        # existing service for it)
        wanted = {
            "spirometry": ("وظائف تنفس", "procedure", ("تنفس", "spiro")),
            "ecg": ("رسم قلب", "procedure", ("رسم قلب", "ecg")),
            "echo": ("إيكو", "radiology", ("إيكو", "echo", "سونار")),
            "ultrasound": ("موجات صوتية (سونار)", "radiology", ("سونار", "موجات", "ultrasound")),
            "eeg": ("رسم مخ", "procedure", ("رسم مخ", "eeg")),
            "audiometry": ("قياس سمع", "procedure", ("سمع", "audio")),
            "tympanometry": ("قياس ضغط الأذن", "procedure", ("أذن", "tympan")),
        }
        made = 0
        for dev in MedicalDevice.query.filter_by(is_active=True).all():
            if any(sv.is_active for sv in dev.services):
                continue
            name, category, words = wanted.get(
                dev.device_type, (dev.name, "procedure", ()))
            match = None
            for svc in Service.query.filter_by(is_active=True).all():
                if svc.device_id is not None:
                    continue
                haystack = f"{svc.name} {svc.name_en or ''}".lower()
                if any(w.lower() in haystack for w in words):
                    match = svc
                    break
            if match is not None:
                match.device_id = dev.id
                continue
            db.session.add(Service(code=next_service_code(), name=name,
                                   price=0, category=category,
                                   device_id=dev.id, needs_device=True,
                                   commission_type="none", commission_value=0,
                                   is_active=True))
            made += 1
        db.session.flush()
        return made

    def _store():
        from app.utils.store_seed import (backfill_item_types,
                                          seed_store_items_if_empty)
        made = seed_store_items_if_empty() or 0
        # After the items exist, not before. The first version of this ran
        # with the lists — which are seeded earlier — so it typed nothing at
        # all and every count on the screen still looked right.
        #
        # It runs on upgrade as well as install: a clinic that has been typing
        # categories for a year should not have to open every item to say
        # which of them are drugs.
        backfill_item_types()
        return made

    def _device_consumables():
        """Tie each device's service to what it burns per test.

        Running the spirometer costs a mouthpiece and a filter; the ECG costs
        electrodes and paper. Billing the service deducts them from the store,
        so the shelf and the bill tell the same story. Fill-only: a clinic that
        edited its own list is left alone."""
        from app.models import MedicalDevice, ServiceConsumable, StoreItem

        burns = {
            "spirometry": (("مبسم وظائف تنفس", 1), ("فلتر بكتيري لوظائف التنفس", 1)),
            "ecg": (("أقطاب رسم قلب", 4), ("ورق رسم قلب", 1)),
            "echo": (("جل الموجات الصوتية", 1),),
            "ultrasound": (("جل الموجات الصوتية", 1),),
            "eeg": (("أقطاب رسم مخ", 8),),
            "audiometry": (("فوهة قياس السمع", 2),),
        }
        items = {i.name: i for i in StoreItem.query.all()}
        made = 0
        for dev in MedicalDevice.query.filter_by(is_active=True).all():
            svc = next((s for s in dev.services if s.is_active), None)
            if svc is None or svc.consumables:
                continue                      # never overwrite the clinic's own
            for item_name, qty in burns.get(dev.device_type, ()):
                item = items.get(item_name)
                if item is None:
                    continue
                db.session.add(ServiceConsumable(
                    service_id=svc.id, store_item_id=item.id, quantity=qty))
                svc.needs_consumables = True
                made += 1
        db.session.flush()
        return made

    def _templates():
        from app.utils.whatsapp import seed_system_templates
        return seed_system_templates() or 0

    _try(_vaccines, "vaccines", out)
    _try(_services, "services", out)
    _try(_drugs, "drugs", out)
    _try(_investigations, "investigations", out)
    _try(_lookups, "store_lists", out)
    _try(_drugbook, "drug_reference", out)
    _try(_egypt_register, "egypt_drug_register", out)
    _try(_devices, "devices", out)
    _try(_device_measurements, "device_measurements", out)
    _try(_device_services, "device_services", out)
    _try(_store, "store_items", out)
    _try(_device_consumables, "device_consumables", out)
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
