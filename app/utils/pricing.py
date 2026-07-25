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


# --------------------------------------------------- cash price list -------
_CASH_PAYER_KEY = "cash_price_payer_id"


def cash_payer():
    """The clinic's own **cash price list** (التسعيرة النقدية), if it has one.

    A cash agreement is not a third party that pays: it is the clinic's list
    of prices for the walk-in patient. So it must not need a membership card —
    it applies to everyone who has no other payer. The entity is chosen in
    settings; when the clinic has exactly one active ``cash`` entity that one
    is used without any setting to fill in.
    """
    from app.models import PayerEntity

    chosen = Setting.get(_CASH_PAYER_KEY)
    if chosen:
        try:
            payer = PayerEntity.query.get(int(chosen))
        except (TypeError, ValueError):
            payer = None
        if payer is not None and payer.is_active:
            return payer
        return None
    cash = (PayerEntity.query
            .filter_by(entity_type="cash", is_active=True).all())
    return cash[0] if len(cash) == 1 else None


def set_cash_payer(payer_id):
    """Pick which entity holds the cash price list (empty clears it)."""
    Setting.set(_CASH_PAYER_KEY, str(payer_id) if payer_id else "")


def cash_tariff(service, on_date=None):
    """The cash price for ``service`` on ``on_date`` — or None to keep the
    catalogue price. Only a contract in force can move a price, so a list that
    starts next month changes nothing today."""
    payer = cash_payer()
    if payer is None or service is None:
        return None
    return payer.tariff(service, on_date)
