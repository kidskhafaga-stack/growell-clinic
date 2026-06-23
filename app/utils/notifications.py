"""In-app notification feed (the topbar bell).

Alerts are computed live from existing data — vaccines due, low / near-expiry
stock, unpaid invoices, today's appointments, birthdays this week and insurance
contracts about to expire — and cached briefly so the bell stays cheap on every
page. Each alert carries the module it belongs to, so it is only shown to users
who can reach it.
"""
import time
from datetime import date, timedelta

# Short process-level cache so the (heavier) scans run at most every TTL seconds.
_CACHE = {"at": 0.0, "data": None}
_TTL = 90
CONTRACT_SOON_DAYS = 30
BIRTHDAY_AHEAD_DAYS = 7


def invalidate():
    _CACHE["at"] = 0.0
    _CACHE["data"] = None


def _compute():
    today = date.today()
    items = []

    # --- cheap, indexed counts -------------------------------------------
    try:
        from app.models import Appointment
        from app.models.appointment import ACTIVE_STATUSES
        n = (Appointment.query
             .filter(Appointment.appt_date == today,
                     Appointment.status.in_(ACTIVE_STATUSES)).count())
        if n:
            items.append({"key": "appointments_today", "module": "appointments",
                          "icon": "calendar-check", "severity": "info", "count": n,
                          "endpoint": "appointments.index", "kwargs": {}})
    except Exception:  # noqa: BLE001
        pass

    try:
        from app.models import Invoice
        n = Invoice.query.filter(Invoice.status.in_(["unpaid", "partial"])).count()
        if n:
            items.append({"key": "unpaid_invoices", "module": "finance",
                          "icon": "cash-coin", "severity": "warning", "count": n,
                          "endpoint": "finance.invoices", "kwargs": {"status": "unpaid"}})
    except Exception:  # noqa: BLE001
        pass

    try:
        from app.models import VaccineInventory
        nexp = sum(1 for b in VaccineInventory.query.all()
                   if b.status in ("expired", "near_expiry"))
        if nexp:
            items.append({"key": "stock_expiry", "module": "inventory",
                          "icon": "hourglass-bottom", "severity": "danger", "count": nexp,
                          "endpoint": "inventory.index", "kwargs": {}})
    except Exception:  # noqa: BLE001
        pass

    try:
        from app.models import StoreItem
        low = sum(1 for i in StoreItem.query.filter_by(is_active=True).all() if i.is_low)
        if low:
            items.append({"key": "low_stock", "module": "inventory",
                          "icon": "box-seam", "severity": "warning", "count": low,
                          "endpoint": "inventory.store", "kwargs": {}})
    except Exception:  # noqa: BLE001
        pass

    try:
        from app.models import PayerContract
        soon = today + timedelta(days=CONTRACT_SOON_DAYS)
        n = (PayerContract.query
             .filter(PayerContract.end_date.isnot(None),
                     PayerContract.end_date >= today,
                     PayerContract.end_date <= soon,
                     PayerContract.is_active.is_(True)).count())
        if n:
            items.append({"key": "contracts_expiring", "module": "finance",
                          "icon": "file-earmark-text", "severity": "warning", "count": n,
                          "endpoint": "finance.payers", "kwargs": {}})
    except Exception:  # noqa: BLE001
        pass

    # --- single patient scan: vaccines due + birthdays this week ---------
    try:
        from app.models import Patient
        from app.utils.vaccines import next_due_dose, patient_plan

        vac_due = 0
        birthdays = 0
        end = today + timedelta(days=BIRTHDAY_AHEAD_DAYS)
        for p in Patient.query.filter_by(is_active=True).all():
            if p.date_of_birth:
                try:
                    bd = p.date_of_birth.replace(year=today.year)
                    if bd < today:
                        bd = bd.replace(year=today.year + 1)
                    if today <= bd <= end:
                        birthdays += 1
                except ValueError:  # Feb 29
                    pass
            if next_due_dose(patient_plan(p)):
                vac_due += 1
        if vac_due:
            items.append({"key": "vaccines_due", "module": "vaccinations",
                          "icon": "shield-exclamation", "severity": "warning", "count": vac_due,
                          "endpoint": "vaccinations.reminders", "kwargs": {}})
        if birthdays:
            items.append({"key": "birthdays", "module": "messages",
                          "icon": "balloon", "severity": "info", "count": birthdays,
                          "endpoint": "messages.occasions", "kwargs": {}})
    except Exception:  # noqa: BLE001
        pass

    return items


def _all():
    now = time.time()
    if _CACHE["data"] is None or (now - _CACHE["at"]) > _TTL:
        _CACHE["data"] = _compute()
        _CACHE["at"] = now
    return _CACHE["data"]


def get_notifications(user):
    """Alerts visible to this user (filtered by module access)."""
    if user is None or not getattr(user, "is_authenticated", False):
        return []
    return [it for it in _all() if user.can_access(it["module"])]
