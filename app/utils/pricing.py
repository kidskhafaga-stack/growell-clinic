"""Resolving which priced :class:`Service` a visit type charges.

The appointment/visit type (new / followup / consultation / …) is clinical
and carries no price itself. Reception maps each type to a catalogue
``Service`` once; the amount then comes from that service's per-doctor price
(:meth:`Service.price_for`). Kept here so booking, visits and the cashier all
resolve the base charge the same way — no duplicated logic.
"""
import json

from app.models import Service, Setting

_SETTING_KEY = "visit_type_services"


def visit_type_service_map():
    """Return ``{appt_type: service_id}`` from settings (ignoring blanks)."""
    raw = Setting.get(_SETTING_KEY)
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return {}
    out = {}
    for key, value in data.items():
        try:
            out[key] = int(value)
        except (TypeError, ValueError):
            continue
    return out


def save_visit_type_service_map(mapping):
    """Persist ``{appt_type: service_id}`` (caller commits)."""
    clean = {k: int(v) for k, v in mapping.items() if v}
    Setting.set(_SETTING_KEY, json.dumps(clean))


def service_for_visit_type(appt_type):
    """The base-charge :class:`Service` for a visit type, or ``None``."""
    from app.extensions import db

    service_id = visit_type_service_map().get(appt_type)
    if not service_id:
        return None
    return db.session.get(Service, service_id)
