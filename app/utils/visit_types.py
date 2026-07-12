"""Resolving visit types from the admin-editable catalogue.

Booking, the board, visits and the cashier all ask here for a visit type's
duration / colour / label so the logic lives in one place. Everything falls
back to the built-in :data:`APPOINTMENT_TYPES` defaults when the DB table is
empty or unavailable (fresh install, pre-migration), so nothing breaks before
the catalogue is seeded.
"""
from app.models.appointment import APPOINTMENT_TYPES, DEFAULT_APPT_TYPE, VisitType


def ensure_seeded():
    """Populate the catalogue from the built-in defaults if it's empty.

    Idempotent — safe to call from init-db and upgrade-db.
    """
    from app.extensions import db

    if VisitType.query.first() is not None:
        return 0
    added = 0
    for order, (key, meta) in enumerate(APPOINTMENT_TYPES.items()):
        db.session.add(VisitType(
            key=key, minutes=meta["minutes"], color=meta["color"],
            sort_order=order, is_active=True, is_system=True,
        ))
        added += 1
    db.session.commit()
    return added


def active_types():
    """Active visit types ordered for display (falls back to built-ins)."""
    try:
        rows = (VisitType.query.filter_by(is_active=True)
                .order_by(VisitType.sort_order, VisitType.id).all())
        if rows:
            return rows
    except Exception:  # noqa: BLE001 - table not ready yet
        pass
    return _synthetic()


def all_types():
    try:
        rows = VisitType.query.order_by(VisitType.sort_order, VisitType.id).all()
        if rows:
            return rows
    except Exception:  # noqa: BLE001
        pass
    return _synthetic()


def get(key):
    try:
        return VisitType.query.filter_by(key=key).first()
    except Exception:  # noqa: BLE001
        return None


def valid_key(key):
    row = get(key)
    if row is not None:
        return row.is_active
    return key in APPOINTMENT_TYPES


def minutes(key, fallback=15):
    row = get(key)
    if row is not None:
        return row.minutes
    meta = APPOINTMENT_TYPES.get(key)
    return meta["minutes"] if meta else fallback


def color(key):
    row = get(key)
    if row is not None:
        return row.color
    meta = APPOINTMENT_TYPES.get(key)
    return meta["color"] if meta else "blue"


def label(key, lang="ar"):
    row = get(key)
    if row is not None:
        return row.display_name(lang)
    from app.i18n import t
    return t("appt_types." + key)


def default_key():
    return DEFAULT_APPT_TYPE


class _Synth:
    """A lightweight stand-in for a VisitType row, used only as a fallback
    before the catalogue is seeded so templates can iterate uniformly."""

    def __init__(self, key, meta, order):
        self.key = key
        self.minutes = meta["minutes"]
        self.color = meta["color"]
        self.sort_order = order
        self.is_active = True
        self.is_system = True
        self.name_ar = None
        self.name_en = None

    def display_name(self, lang="ar"):
        from app.i18n import t
        return t("appt_types." + self.key)


def _synthetic():
    return [_Synth(k, m, i) for i, (k, m) in enumerate(APPOINTMENT_TYPES.items())]
