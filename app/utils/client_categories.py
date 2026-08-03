"""Resolving client categories from the clinic-editable catalogue.

The list used to be four strings in :data:`app.models.parent.CLIENT_CATEGORIES`
— ``normal``, ``friend``, ``relative``, ``employee`` — so a clinic whose real
categories are نقدي, عاملين, **أطباء** and **أعضاء نادي سبورتنج** had nowhere to
put two of them.

That matters because the category is what a discount aims at: a
:class:`~app.models.discount.NamedDiscount` with ``dtype="category"`` already
does "this category pays less". The mechanism was right; the list was short.
Squeezing "أطباء" into ``friend`` would have hung a real discount on a category
with the wrong name, and every report that groups clients by category would
then be quietly wrong.

Everything here falls back to the built-in list when the table is empty or
missing (fresh install, database not yet upgraded), so no screen breaks before
it is seeded.
"""
from app.models.parent import CLIENT_CATEGORIES, ClientCategory

DEFAULT_CATEGORY = "normal"


def ensure_seeded():
    """Populate the catalogue from the built-in list if it's empty.

    Idempotent — safe to call from init-db, upgrade-db and the screen itself.
    """
    from app.extensions import db

    if ClientCategory.query.first() is not None:
        return 0
    added = 0
    for order, key in enumerate(CLIENT_CATEGORIES):
        db.session.add(ClientCategory(key=key, sort_order=order,
                                      is_active=True, is_system=True))
        added += 1
    db.session.commit()
    return added


def all_categories():
    """Every category, ordered for display (falls back to the built-ins)."""
    try:
        rows = (ClientCategory.query
                .order_by(ClientCategory.sort_order, ClientCategory.id).all())
        if rows:
            return rows
    except Exception:  # noqa: BLE001 - table not ready yet
        pass
    return _synthetic()


def active_categories():
    return [r for r in all_categories() if r.is_active]


def get(key):
    """One category by key, read once per request.

    The patients list asks every row for its category's label, so this was a
    query per row of a table with a handful of rows in it.
    """
    from app.utils.request_cache import remember

    def load():
        try:
            return ClientCategory.query.filter_by(key=key).first()
        except Exception:  # noqa: BLE001
            return None

    return remember(f"client_category:{key}", load)


def valid_key(key):
    """Is this a category a parent may be given?

    Deliberately accepts an *inactive* one: hiding a category from the "add"
    dropdown must not invalidate the families already on it, or saving an
    unrelated field on such a family would silently reset their category — and
    with it, their discount.
    """
    if not key:
        return False
    if get(key) is not None:
        return True
    return key in CLIENT_CATEGORIES


def label(key, lang="ar"):
    row = get(key)
    if row is not None:
        return row.display_name(lang)
    from app.i18n import t
    return t("categories." + (key or DEFAULT_CATEGORY))


def choices_for(current=None):
    """Categories to offer in a dropdown: the active ones, plus whatever this
    family is already on even if it has been deactivated — so opening their
    profile and pressing save doesn't quietly move them somewhere else."""
    rows = active_categories()
    if current and not any(r.key == current for r in rows):
        row = get(current)
        rows = rows + [row if row is not None else _Synth(current, len(rows))]
    return rows


def make_key(name, name_en=None):
    """A stable ASCII key for a clinic-added category.

    Derived, never typed: the key is what parent rows and discounts match on,
    so it must not depend on how somebody spelt a label today, and renaming the
    label later must not orphan the families already on it. An Arabic-only name
    yields no ASCII at all, so it falls back to a numbered key rather than an
    empty one.
    """
    import re

    base = re.sub(r"[^a-z0-9]+", "-", (name_en or name or "").lower()).strip("-")
    if not base:
        base = "category"
    base = base[:24]
    candidate, n = base, 2
    while _taken(candidate):
        candidate, n = f"{base}-{n}", n + 1
    return candidate


def _taken(key):
    try:
        return ClientCategory.query.filter_by(key=key).first() is not None
    except Exception:  # noqa: BLE001
        return key in CLIENT_CATEGORIES


def usage_counts():
    """How many families sit on each category — what makes deleting one a
    decision rather than a surprise."""
    from app.extensions import db
    from app.models import Parent

    counts = {}
    try:
        rows = (db.session.query(Parent.client_category, db.func.count(Parent.id))
                .group_by(Parent.client_category).all())
    except Exception:  # noqa: BLE001
        return counts
    for key, num in rows:
        key = key or DEFAULT_CATEGORY
        counts[key] = counts.get(key, 0) + num
    return counts


def discount_counts():
    """How many discounts aim at each category.

    Shown beside the category because that is the whole reason a clinic adds
    one: "أعضاء نادي سبورتنج" exists so a discount can be pointed at it, and a
    category with no discount behind it is usually somebody half way through
    setting it up.
    """
    from app.extensions import db
    from app.models import NamedDiscount

    counts = {}
    try:
        rows = (db.session.query(NamedDiscount.client_category,
                                 db.func.count(NamedDiscount.id))
                .filter(NamedDiscount.client_category.isnot(None))
                .group_by(NamedDiscount.client_category).all())
    except Exception:  # noqa: BLE001
        return counts
    for key, num in rows:
        counts[key] = num
    return counts


class _Synth:
    """A stand-in for a :class:`ClientCategory` row, used only before the
    catalogue is seeded so templates can iterate uniformly."""

    def __init__(self, key, order):
        self.id = None
        self.key = key
        self.name_ar = None
        self.name_en = None
        self.sort_order = order
        self.is_active = True
        self.is_system = True

    def display_name(self, lang="ar"):
        from app.i18n import t
        return t("categories." + self.key)


def _synthetic():
    return [_Synth(key, i) for i, key in enumerate(CLIENT_CATEGORIES)]
