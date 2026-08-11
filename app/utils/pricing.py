"""Resolving which priced :class:`Service` a visit type charges.

The appointment/visit type (new / followup / consultation / …) is clinical
and carries no price itself. Reception maps each type to a catalogue
``Service`` once; the amount then comes from that service's per-doctor price
(:meth:`Service.price_for`). Kept here so booking, visits and the cashier all
resolve the base charge the same way — no duplicated logic.
"""
import json

from app.models import Service, Setting
from app.utils.clock import local_today

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
    """The base-charge :class:`Service` for a visit type, or ``None``.

    Read off the service itself. The mapping used to be a ``{type: id}`` blob
    in settings edited on its own panel, so the price of a visit and the thing
    being priced lived on two screens — and deleting a service left an id in
    the blob pointing at nothing, which reads on the till as a visit type with
    no charge rather than as a broken reference.

    The blob is still consulted as a fallback, because a clinic that has not
    run the upgrade yet still has its pricing there and must keep billing.
    """
    from app.extensions import db

    if not appt_type:
        return None
    svc = (Service.query.filter_by(visit_type=appt_type, is_active=True)
           .order_by(Service.id).first())
    if svc is not None:
        return svc
    service_id = visit_type_service_map().get(appt_type)
    if not service_id:
        return None
    return db.session.get(Service, service_id)


def set_visit_type_service(appt_type, service):
    """Make ``service`` the base charge for ``appt_type``, and only it.

    One base charge per type: two services both claiming "كشف" is a question
    the till would have to answer by picking, so assigning it **moves** it.
    """
    from app.extensions import db

    if not appt_type:
        return
    from app.models import Setting
    from app.utils.services import VT_SEEDED_KEY

    for other in Service.query.filter_by(visit_type=appt_type).all():
        if service is None or other.id != service.id:
            other.visit_type = None
    if service is not None:
        service.visit_type = appt_type
    # A human has now expressed an opinion, so the first-run self-heal stops.
    # Without this, clearing the last base charge and reopening the services
    # screen put one straight back — "no base charge for this visit type" was
    # a state the program refused to let anybody be in.
    Setting.set(VT_SEEDED_KEY, "1")
    db.session.flush()


def migrate_visit_type_map():
    """Move an existing settings blob onto the services (idempotent).

    Runs on upgrade. Only ever fills a service whose ``visit_type`` is empty,
    so a clinic that has already set one on the new screen keeps it.
    """
    from app.extensions import db

    mapping = visit_type_service_map()
    if not mapping:
        return 0
    moved = 0
    for key, service_id in mapping.items():
        svc = db.session.get(Service, service_id)
        if svc is None or svc.visit_type:
            continue
        if Service.query.filter_by(visit_type=key).first() is not None:
            continue
        svc.visit_type = key
        moved += 1
    return moved


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
        from app.extensions import db

        try:
            payer = db.session.get(PayerEntity, int(chosen))
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
    # Checked here and not only on the payers screen, because nobody opens the
    # payers screen on 1 January: reception opens the cashier. The stamp makes
    # this one extra question a day, not one per priced line.
    ensure_cash_contract()
    return payer.tariff(service, on_date)


# ------------------------------------------- keeping the cash list alive ----
# A cash contract's renewal is checked at most once a day; the stamp is what
# stops every price lookup in a busy morning from asking the same question.
_CASH_RENEW_KEY = "cash_contract_renewed_on"

# How early the next year is prepared. Two weeks is enough for somebody to
# notice and adjust the prices before they take effect, and short enough that
# the new list is not sitting there for months collecting edits meant for the
# current one.
RENEW_AHEAD_DAYS = 14


def year_window(start):
    """``(start, the day before the same date next year)`` — a calendar year.

    Not ``start + 365``: a clinic thinks in "until the end of next July", and a
    leap year would quietly shift every subsequent renewal by a day.
    """
    from datetime import date as _date, timedelta

    try:
        next_year = _date(start.year + 1, start.month, start.day)
    except ValueError:                      # 29 February
        next_year = _date(start.year + 1, start.month, start.day - 1)
    return start, next_year - timedelta(days=1)


def next_contract_number(payer):
    """The next contract number for one payer, as a string.

    Generated, never typed. Two contracts sharing a number is a data problem
    with no clean fix afterwards, and the person filling the form has no way of
    knowing what is already taken.
    """
    highest = 0
    for contract in (payer.contracts if payer is not None else []):
        raw = (contract.number or "").strip()
        if raw.isdigit():
            highest = max(highest, int(raw))
    return str(highest + 1)


def ensure_cash_contract(today=None, ahead_days=RENEW_AHEAD_DAYS):
    """Keep the clinic's own price list in force, year after year.

    The cash "contract" is not an agreement with anybody — it is the clinic's
    own prices for the walk-in patient. But coverage only applies while a
    contract is current, so a list that ended on 31 December leaves the clinic
    with **no prices at all on 1 January**: every service silently falls back to
    its catalogue figure, and nobody finds out from a screen, they find out from
    a wrong bill.

    So the next year is prepared before the current one runs out, by **copying**
    the prices into a new contract rather than pushing the old one's end date
    out. Two reasons: what a service cost in 2026 stays answerable in 2027, and
    a clinic that wants to raise prices in the new year has somewhere to do it
    that does not rewrite history.

    Idempotent, and cheap: it asks at most once a day. Returns the contract it
    created, or None.
    """
    from datetime import date as _date, timedelta

    from app.extensions import db

    today = today or local_today()
    if Setting.get(_CASH_RENEW_KEY) == today.isoformat():
        return None
    Setting.set(_CASH_RENEW_KEY, today.isoformat())

    payer = cash_payer()
    if payer is None:
        return None
    live = [c for c in payer.contracts if c.is_active]
    if not live:
        return None                        # nothing to renew from
    # An open-ended list never lapses, so there is nothing to prepare.
    dated = [c for c in live if c.end_date]
    if len(dated) < len(live):
        return None

    latest = max(dated, key=lambda c: c.end_date)
    if latest.end_date - today > timedelta(days=ahead_days):
        return None                        # not due yet

    starts = latest.end_date + timedelta(days=1)
    # Somebody may have prepared it by hand already.
    if any(c.start_date and c.start_date >= starts for c in live):
        return None

    start, end = year_window(starts)
    renewed = latest.copy_to(number=next_contract_number(payer),
                             start_date=start, end_date=end)
    db.session.add(renewed)
    db.session.commit()
    return renewed
