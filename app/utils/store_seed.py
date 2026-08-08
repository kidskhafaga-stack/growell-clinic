"""Default general-store catalogue: consumables, categories and units.

The vaccine fridge has its own rich catalogue, but the *general* store (tongue
depressors, gloves, syringes, antiseptics…) used to start empty — so the items
screen looked "vaccine only" and every category/unit had to be typed by hand.

This module seeds a sensible pediatric-clinic consumables list (fill-only, by
name) and exposes the default category/unit lists that back the add/edit
form's pick-or-type fields. Everything stays editable and deletable afterwards.
"""
from app.extensions import db
from app.models import StoreItem

# (name_ar, name_en, category_ar, unit_ar, purchase_unit_ar, units_per_purchase)
DEFAULT_CONSUMABLES = [
    ("خافض لسان خشبي", "Wooden tongue depressor", "أدوات الفحص", "قطعة", "علبة", 100),
    ("قفازات فحص", "Examination gloves", "مستهلكات طبية", "قطعة", "علبة", 100),
    ("سرنجة 5 مل", "Syringe 5 ml", "مستهلكات طبية", "قطعة", "علبة", 100),
    ("سرنجة أنسولين", "Insulin syringe", "مستهلكات طبية", "قطعة", "علبة", 100),
    ("قطن طبي", "Medical cotton", "مستهلكات طبية", "لفة", "كرتونة", 12),
    ("شاش طبي", "Gauze", "مستهلكات طبية", "قطعة", "علبة", 100),
    ("بلاستر جروح", "Adhesive plaster", "مستهلكات طبية", "قطعة", "علبة", 100),
    ("كحول طبي 70%", "Medical alcohol 70%", "مطهرات وتعقيم", "زجاجة", "كرتونة", 12),
    ("بيتادين مطهر", "Povidone-iodine antiseptic", "مطهرات وتعقيم", "زجاجة", "كرتونة", 12),
    ("كمامات طبية", "Surgical masks", "مستهلكات طبية", "قطعة", "علبة", 50),
    ("قناع نبيولايزر أطفال", "Pediatric nebulizer mask", "مستهلكات طبية", "قطعة", "علبة", 25),
    ("مناديل معقّمة", "Antiseptic wipes", "مطهرات وتعقيم", "علبة", "كرتونة", 24),
    ("ورق كشف (رول سرير)", "Exam couch paper roll", "أدوات الفحص", "لفة", "كرتونة", 6),
    ("أكواب بلاستيك", "Plastic cups", "مكتبية وإدارية", "قطعة", "علبة", 100),
    # What the clinic's devices burn per test — a study is not free of stock.
    ("مبسم وظائف تنفس", "Spirometry mouthpiece", "مستلزمات الأجهزة", "قطعة", "علبة", 100),
    ("فلتر بكتيري لوظائف التنفس", "Spirometry bacterial filter", "مستلزمات الأجهزة",
     "قطعة", "علبة", 50),
    ("أقطاب رسم قلب", "ECG electrodes", "مستلزمات الأجهزة", "قطعة", "علبة", 50),
    ("ورق رسم قلب", "ECG paper roll", "مستلزمات الأجهزة", "لفة", "كرتونة", 10),
    ("جل الموجات الصوتية", "Ultrasound gel", "مستلزمات الأجهزة", "زجاجة", "كرتونة", 12),
    ("أقطاب رسم مخ", "EEG electrodes", "مستلزمات الأجهزة", "قطعة", "علبة", 25),
    ("فوهة قياس السمع", "Audiometry tip", "مستلزمات الأجهزة", "قطعة", "علبة", 100),
]

# Suggested categories/units offered in the add-item form (as pick-or-type
# lists). Distinct values already in use are merged in on top of these.
DEFAULT_CATEGORIES = [
    "مستهلكات طبية", "مستلزمات الأجهزة", "مطهرات وتعقيم", "أدوات الفحص",
    "أدوية", "مكتبية وإدارية", "نظافة", "أخرى",
]
DEFAULT_UNITS = ["قطعة", "علبة", "زجاجة", "لفة", "كيس", "عبوة", "أمبول", "متر"]
DEFAULT_PURCHASE_UNITS = ["علبة", "كرتونة", "عبوة", "زجاجة", "شكارة", "دستة"]


# Which item type each seeded category belongs to, so the 21 bundled
# consumables arrive already typed. An item with no type is not broken — it
# simply cannot be grouped — but leaving the program's own seed data untyped
# would teach every clinic that the field is optional decoration.
CATEGORY_TYPE = {
    "مستهلكات طبية": "consumable",
    "مطهرات وتعقيم": "consumable",
    "أدوات الفحص": "consumable",
    "نظافة": "consumable",
    "مستلزمات الأجهزة": "device",
    "مكتبية وإدارية": "office",
    "أدوية": "drug",
}


def backfill_item_types():
    """Give existing items a type from the category they already carry.

    Runs on upgrade as well as on install: a clinic that has been typing
    categories for a year should not have to open every item to say which of
    them are drugs.
    """
    made = 0
    for item in StoreItem.query.filter(StoreItem.item_type.is_(None)).all():
        guess = CATEGORY_TYPE.get((item.category or "").strip())
        if guess:
            item.item_type = guess
            made += 1
    return made


def seed_store_items():
    """Create the default consumables that don't exist yet (matched by name).
    Idempotent and non-destructive — does not commit; caller owns the txn."""
    existing = {i.name for i in StoreItem.query.with_entities(StoreItem.name).all()}
    created = 0
    for name, name_en, cat, unit, punit, per in DEFAULT_CONSUMABLES:
        if name in existing:
            continue
        db.session.add(StoreItem(
            name=name, name_en=name_en, category=cat, unit=unit,
            purchase_unit=punit, units_per_purchase=per, reorder_level=0,
            opening_stock=0, is_active=True))
        existing.add(name)
        created += 1
    if created:
        db.session.flush()
    return created


def seed_store_items_if_empty():
    """Seed the default consumables only on a fresh store (idempotent helper
    for install/upgrade). Returns the number created."""
    if StoreItem.query.first() is not None:
        return 0
    return seed_store_items()


def _distinct(column):
    return [v for (v,) in db.session.query(column).distinct().all()
            if v and v.strip()]


def _picker(domain, column, fallback):
    """The clinic's own list, plus anything already on an item.

    The catalogue is the source: it can be added to *and* deleted from, which
    the old "defaults + everything ever typed" could not — one "قطعه" typed
    for "قطعة" stayed in the picker for the life of the installation.

    Values already sitting on items are still appended, because a picker that
    hides a clinic's own data is worse than an untidy one; they are simply not
    offered to anybody new once the entry is removed from the catalogue.
    """
    from app.utils.lookups import options

    try:
        names = [row.display_name("ar") for row in options(domain)]
    except Exception:                     # noqa: BLE001 - table not created yet
        names = list(fallback)
    seen, out = set(), []
    for value in names + _distinct(column):
        if value and value not in seen:
            seen.add(value)
            out.append(value)
    return out


def store_categories(item_type=None):
    """Categories, narrowed to one item type when the form knows it."""
    from app.utils.lookups import options

    if item_type:
        try:
            rows = options("item_category", parent=item_type)
            return [r.display_name("ar") for r in rows]
        except Exception:                 # noqa: BLE001
            pass
    return _picker("item_category", StoreItem.category, DEFAULT_CATEGORIES)


def store_units():
    return _picker("unit", StoreItem.unit, DEFAULT_UNITS)


def store_purchase_units():
    return _picker("purchase_unit", StoreItem.purchase_unit,
                   DEFAULT_PURCHASE_UNITS)
