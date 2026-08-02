"""Resolving service types from the admin-editable catalogue.

Reported: *"there is nowhere to add service types"*. There wasn't — the list
was eight strings in :data:`app.models.service.SERVICE_TYPES`, so adding one
meant editing Python. This module is the read side of the catalogue that
replaced it, and everything falls back to the built-in list when the table is
empty or missing (fresh install, database not yet upgraded) so no screen
breaks before it is seeded.

**Keys are not labels.** A clinic renaming "كشف" to "كشف عام" must not change
the key, because ``vaccination`` is read by
:func:`app.utils.accounting._vaccine_split` to decide which half of an invoice
is vaccination revenue. Built-ins are seeded ``is_system`` and their key is
fixed; only their label, icon, order and visibility are editable.
"""
from app.models.service import SERVICE_TYPE_ICONS, SERVICE_TYPES, ServiceType

DEFAULT_TYPE = "other"


def ensure_seeded():
    """Populate the catalogue from the built-in list if it's empty.

    Idempotent — safe to call from init-db, upgrade-db and the screen itself.
    """
    from app.extensions import db

    if ServiceType.query.first() is not None:
        return 0
    added = 0
    for order, key in enumerate(SERVICE_TYPES):
        db.session.add(ServiceType(
            key=key, icon=SERVICE_TYPE_ICONS.get(key), sort_order=order,
            is_active=True, is_system=True,
        ))
        added += 1
    db.session.commit()
    return added


def all_types():
    """Every type, ordered for display (falls back to the built-ins)."""
    try:
        rows = (ServiceType.query
                .order_by(ServiceType.sort_order, ServiceType.id).all())
        if rows:
            return rows
    except Exception:  # noqa: BLE001 - table not ready yet
        pass
    return _synthetic()


def active_types():
    return [r for r in all_types() if r.is_active]


def get(key):
    """One type by key, read once per request.

    The services table asks every row for its type's label and icon, so this
    was a query per row of a table with a handful of rows in it.
    """
    from app.utils.request_cache import remember

    def load():
        try:
            return ServiceType.query.filter_by(key=key).first()
        except Exception:  # noqa: BLE001
            return None

    return remember(f"service_type:{key}", load)


def valid_key(key):
    """Is this a key a service may be given?

    Deliberately accepts an *inactive* type: deactivating one hides it from
    the "add" dropdown, it does not invalidate the services already on it —
    otherwise saving an unrelated field on such a service would silently
    reset its type.
    """
    if not key:
        return False
    if get(key) is not None:
        return True
    return key in SERVICE_TYPES


def label(key, lang="ar"):
    row = get(key)
    if row is not None:
        return row.display_name(lang)
    from app.i18n import t
    return t("service_types." + key)


def icon(key):
    row = get(key)
    if row is not None and row.icon:
        return row.icon
    return SERVICE_TYPE_ICONS.get(key, "bi-tag")


def choices_for(service=None):
    """Types to offer in a dropdown: the active ones, plus the service's own
    current type even when it has been deactivated — so opening the editor on
    an old service and pressing save doesn't quietly move it somewhere else."""
    rows = active_types()
    current = getattr(service, "kind", None)
    if current and not any(r.key == current for r in rows):
        row = get(current)
        if row is not None:
            rows = rows + [row]
        else:
            rows = rows + [_Synth(current, len(rows))]
    return rows


def make_key(name, name_en=None):
    """A stable ASCII key for a clinic-added type.

    The key is derived, never typed, because it is what old rows and code
    match on — it must not depend on how somebody spelt a label today, and
    renaming the label later must not orphan the services already on it. An
    Arabic-only name yields no ASCII at all, so it falls back to a numbered
    key rather than an empty one.
    """
    import re

    base = re.sub(r"[^a-z0-9]+", "-", (name_en or name or "").lower()).strip("-")
    if not base:
        base = "type"
    base = base[:24]
    candidate, n = base, 2
    while _taken(candidate):
        candidate, n = f"{base}-{n}", n + 1
    return candidate


def _taken(key):
    try:
        return ServiceType.query.filter_by(key=key).first() is not None
    except Exception:  # noqa: BLE001
        return key in SERVICE_TYPES


def usage_counts():
    """How many services sit on each type key — what makes deleting a type a
    decision rather than a surprise."""
    from app.extensions import db
    from app.models import Service

    counts = {}
    try:
        rows = (db.session.query(Service.service_type, db.func.count(Service.id))
                .group_by(Service.service_type).all())
    except Exception:  # noqa: BLE001
        return counts
    for key, num in rows:
        counts[key or DEFAULT_TYPE] = counts.get(key or DEFAULT_TYPE, 0) + num
    return counts


class _Synth:
    """A stand-in for a :class:`ServiceType` row, used only before the
    catalogue is seeded so templates can iterate uniformly."""

    def __init__(self, key, order):
        self.id = None
        self.key = key
        self.name_ar = None
        self.name_en = None
        self.icon = SERVICE_TYPE_ICONS.get(key)
        self.sort_order = order
        self.is_active = True
        self.is_system = True

    def display_name(self, lang="ar"):
        from app.i18n import t
        return t("service_types." + self.key)


def _synthetic():
    return [_Synth(key, i) for i, key in enumerate(SERVICE_TYPES)]
