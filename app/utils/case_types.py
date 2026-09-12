"""The kinds of case, seeded once and edited from the screen.

Same shape as :mod:`app.utils.invoice_sections`, and deliberately so: a clinic
that has learned where to add a bill section should not learn a second pattern
to add a kind of case.

**Why this list opens.** Nothing reads a kind by name. A rate is found by
matching whatever key the case carries against whatever key the rate carries —
so a hospital that also prices «تعاقد» gets a working fourth kind the minute
somebody types it, and no code changes.
"""
from app.models.theatre import CASE_TYPE_ICONS, CASE_TYPES, CaseType


def ensure_seeded():
    """Fill the catalogue from the built-in list if it is empty.

    Idempotent — safe from init-db, upgrade-db and the screen itself.
    """
    from app.extensions import db

    if CaseType.query.first() is not None:
        return 0
    added = 0
    for order, key in enumerate(CASE_TYPES):
        db.session.add(CaseType(
            key=key, icon=CASE_TYPE_ICONS.get(key), sort_order=order,
            is_active=True, is_system=True))
        added += 1
    db.session.commit()
    return added


def all_types():
    """Every kind, ordered for display.

    Falls back to the built-in keys when the table is not there yet, so a
    screen still draws during an upgrade rather than raising.
    """
    try:
        rows = (CaseType.query
                .order_by(CaseType.sort_order, CaseType.id).all())
    except Exception:                                   # noqa: BLE001
        rows = []
    return rows or [CaseType(key=k, icon=CASE_TYPE_ICONS.get(k), sort_order=i,
                             is_system=True)
                    for i, k in enumerate(CASE_TYPES)]


def active_types():
    return [r for r in all_types() if r.is_active]


def label(key, lang="ar"):
    """What to call a kind on screen, including one nobody catalogued."""
    if not key:
        return ""
    for row in all_types():
        if row.key == key:
            return row.display_name(lang)
    return key


def make_key(name, name_en=None):
    """A stable ASCII key for a clinic-added kind.

    The key never changes afterwards: a clinic renaming «طوارئ» must not
    thereby detach every emergency rate already set under it.
    """
    import re

    base = (name_en or name or "").strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "_", base).strip("_")
    if not slug:
        slug = "case"
    existing = {row.key for row in all_types()}
    key = slug[:30]
    n = 2
    while key in existing:
        key = f"{slug[:26]}_{n}"
        n += 1
    return key
