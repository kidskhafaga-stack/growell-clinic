"""Reading, seeding and guarding the clinic's short lists.

The model says what a :class:`~app.models.lookup.Lookup` is; this says which
lists exist, what each starts with, and — the part that matters — when one may
be deleted.

**Usage is counted against the data, not against a foreign key.** Categories
and units are stored on items as text, and converting a working clinic's
columns to foreign keys to gain a delete guard would be a large migration for
a small feature. So "is this in use" asks the items directly. The cost is one
count per entry on a screen nobody opens twice a week; the benefit is that the
guard is right even for values typed before this catalogue existed.
"""
from app.extensions import db
from app.models import Lookup

# Every list, with the built-in entries a clinic starts from.
#
# The item types are the layer the clinic asked for above categories: a thing
# is fundamentally a drug, a vaccine or a consumable, and *then* it is an
# antibiotic or a dressing.
BUILT_IN = {
    "item_type": [
        ("drug", "دواء", "Drug"),
        ("vaccine", "تطعيم", "Vaccine"),
        ("consumable", "مستهلكات", "Consumable"),
        ("device", "مستلزمات أجهزة", "Device supplies"),
        ("office", "مكتبية وإدارية", "Office"),
    ],
    "warehouse_kind": [
        ("main", "مخزن رئيسي", "Main store"),
        ("sub", "مخزن فرعي", "Sub store"),
        # A fridge is an ordinary warehouse with a particular nature — said
        # explicitly by the clinic, and it is why nothing else in the program
        # special-cases one. Anything that must behave differently in cold
        # storage keys off this nature rather than off a warehouse's name, so
        # "ثلاجة ٢" and "Cold room" both behave correctly.
        ("fridge", "ثلاجة", "Cold storage"),
        ("pharmacy", "صيدلية", "Pharmacy"),
    ],
    "unit": [
        ("piece", "قطعة", "Piece"), ("box", "علبة", "Box"),
        ("bottle", "زجاجة", "Bottle"), ("roll", "لفة", "Roll"),
        ("bag", "كيس", "Bag"), ("pack", "عبوة", "Pack"),
        ("ampoule", "أمبول", "Ampoule"), ("dose", "جرعة", "Dose"),
        ("vial", "فيال", "Vial"), ("metre", "متر", "Metre"),
    ],
    "purchase_unit": [
        ("box", "علبة", "Box"), ("carton", "كرتونة", "Carton"),
        ("pack", "عبوة", "Pack"), ("bottle", "زجاجة", "Bottle"),
        ("sack", "شكارة", "Sack"), ("dozen", "دستة", "Dozen"),
        ("vial", "فيال", "Vial"),
    ],
}

# Categories start under the type they belong to, which is the whole point of
# having two layers: a screen offering every category at once is the pile this
# was meant to replace.
BUILT_IN_CATEGORIES = [
    ("antibiotic", "مضادات حيوية", "Antibiotics", "drug"),
    ("analgesic", "خافض ومسكّن", "Analgesics & antipyretics", "drug"),
    ("respiratory", "أدوية الصدر", "Respiratory", "drug"),
    ("gi", "أدوية الجهاز الهضمي", "Gastrointestinal", "drug"),
    ("vitamins", "فيتامينات ومكمّلات", "Vitamins & supplements", "drug"),
    ("routine_vaccine", "تطعيمات أساسية", "Routine vaccines", "vaccine"),
    ("optional_vaccine", "تطعيمات اختيارية", "Optional vaccines", "vaccine"),
    ("medical_supplies", "مستهلكات طبية", "Medical supplies", "consumable"),
    ("antiseptic", "مطهرات وتعقيم", "Antiseptics & sterilisation", "consumable"),
    ("exam_tools", "أدوات الفحص", "Examination tools", "consumable"),
    ("device_supplies", "مستلزمات الأجهزة", "Device supplies", "device"),
    ("cleaning", "نظافة", "Cleaning", "consumable"),
    ("office", "مكتبية وإدارية", "Office & admin", "office"),
    ("other", "أخرى", "Other", None),
]

DOMAINS = list(BUILT_IN) + ["item_category"]


def ensure_seeded():
    """Create the built-in entries once. Idempotent; never overwrites edits."""
    made = 0
    for domain, rows in BUILT_IN.items():
        for order, (key, name_ar, name_en) in enumerate(rows):
            if Lookup.query.filter_by(domain=domain, key=key).first():
                continue
            db.session.add(Lookup(domain=domain, key=key, name_ar=name_ar,
                                  name_en=name_en, sort_order=order,
                                  is_system=True))
            made += 1
    for order, (key, name_ar, name_en, parent) in enumerate(BUILT_IN_CATEGORIES):
        if Lookup.query.filter_by(domain="item_category", key=key).first():
            continue
        db.session.add(Lookup(domain="item_category", key=key, name_ar=name_ar,
                              name_en=name_en, parent_key=parent,
                              sort_order=order, is_system=True))
        made += 1
    if made:
        db.session.flush()
    return made


def options(domain, parent=None, include_inactive=False):
    """The entries of one list, in the clinic's own order."""
    query = Lookup.query.filter_by(domain=domain)
    if not include_inactive:
        query = query.filter(Lookup.is_active.is_(True))
    if parent:
        # An entry with no parent belongs everywhere — that is what an
        # imported or hand-typed category starts as, and hiding it would make
        # a clinic's own data vanish from its own picker.
        query = query.filter(db.or_(Lookup.parent_key == parent,
                                    Lookup.parent_key.is_(None),
                                    Lookup.parent_key == ""))
    return query.order_by(Lookup.sort_order, Lookup.id).all()


def label(domain, key, lang="ar"):
    """The wording for one key, falling back to the key itself."""
    if not key:
        return ""
    row = Lookup.query.filter_by(domain=domain, key=key).first()
    return row.display_name(lang) if row else key


def make_key(name, domain):
    """A stable key from a typed name, unique within its list.

    Arabic names give no usable latin key, so those fall back to a numbered
    one. The key is never shown; it exists so the label can be reworded later
    without orphaning every row that stored it.
    """
    import re

    base = re.sub(r"[^a-z0-9_]+", "_", (name or "").strip().lower()).strip("_")
    if not base:
        base = "item"
    key, n = base[:36], 1
    while Lookup.query.filter_by(domain=domain, key=key).first() is not None:
        n += 1
        key = f"{base[:32]}_{n}"
    return key


def usage_counts(domain):
    """``{key: rows using it}`` — what makes the delete guard honest.

    Counted against the items themselves because categories and units live on
    them as text. A value typed years before this catalogue existed still
    counts, which is the case a foreign key would have missed.
    """
    from app.models import StoreItem, Warehouse

    rows = Lookup.query.filter_by(domain=domain).all()
    out = {}
    for row in rows:
        name = row.display_name("ar")
        if domain == "item_type":
            out[row.key] = StoreItem.query.filter_by(item_type=row.key).count()
        elif domain == "item_category":
            out[row.key] = StoreItem.query.filter_by(category=name).count()
        elif domain == "unit":
            out[row.key] = StoreItem.query.filter_by(unit=name).count()
        elif domain == "purchase_unit":
            out[row.key] = StoreItem.query.filter_by(purchase_unit=name).count()
        elif domain == "warehouse_kind":
            out[row.key] = Warehouse.query.filter_by(kind=row.key).count()
        else:
            out[row.key] = 0
    return out


def can_delete(row, counts=None):
    """Whether this entry may be removed, and why not when it may not.

    Returns ``(allowed, reason)``. Switching off is always available and is
    what a screen should offer instead — it keeps every existing item readable
    while taking the entry off tomorrow's list.
    """
    if row.is_system:
        return False, "system"
    counts = counts if counts is not None else usage_counts(row.domain)
    if counts.get(row.key):
        return False, "in_use"
    return True, ""
