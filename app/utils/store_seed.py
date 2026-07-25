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


def store_categories():
    """Default + already-used categories, de-duplicated, for the pick list."""
    seen, out = set(), []
    for c in DEFAULT_CATEGORIES + _distinct(StoreItem.category):
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


def store_units():
    seen, out = set(), []
    for u in DEFAULT_UNITS + _distinct(StoreItem.unit):
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def store_purchase_units():
    seen, out = set(), []
    for u in DEFAULT_PURCHASE_UNITS + _distinct(StoreItem.purchase_unit):
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out
