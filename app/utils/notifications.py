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

    # --- vaccines due + birthdays this week ------------------------------
    # Computed with a handful of bulk queries instead of a per-patient plan
    # build, so it stays cheap even with thousands of patients on the books.
    try:
        from sqlalchemy import or_

        from app.models import Patient, PatientVaccine, Vaccine
        from app.utils.vaccines import DUE_WINDOW_DAYS, add_months

        # Dose schedule per vaccine (default brand) — small, loaded once.
        schedule = {}
        for v in Vaccine.query.order_by(Vaccine.sort_order).all():
            brand = v.default_brand
            if brand is None:
                continue
            schedule[v.id] = [(d.dose_number, d.age_months) for d in brand.doses]

        # Every given dose, grouped by patient: {patient_id: {(vaccine_id, dose_number)}}.
        given = {}
        gq = (PatientVaccine.query
              .filter(or_(PatientVaccine.event_type == "given",
                          PatientVaccine.event_type.is_(None)))
              .with_entities(PatientVaccine.patient_id,
                             PatientVaccine.vaccine_id,
                             PatientVaccine.dose_number))
        for pid, vid, dnum in gq.all():
            given.setdefault(pid, set()).add((vid, dnum))

        vac_due = 0
        birthdays = 0
        cutoff = today + timedelta(days=DUE_WINDOW_DAYS)
        bday_end = today + timedelta(days=BIRTHDAY_AHEAD_DAYS)
        rows = (Patient.query.filter_by(is_active=True)
                .with_entities(Patient.id, Patient.date_of_birth).all())
        for pid, dob in rows:
            if dob:
                try:
                    bd = dob.replace(year=today.year)
                    if bd < today:
                        bd = bd.replace(year=today.year + 1)
                    if today <= bd <= bday_end:
                        birthdays += 1
                except ValueError:  # Feb 29
                    pass
                gset = given.get(pid, ())
                for vid, doses in schedule.items():
                    found = False
                    for dnum, age_m in doses:
                        if (vid, dnum) in gset:
                            continue
                        if add_months(dob, age_m) <= cutoff:  # overdue or due-soon
                            found = True
                            break
                    if found:
                        vac_due += 1
                        break
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


def _dismissed_map(user):
    """Per-user record of dismissed alerts: {key: {'c': count, 'd': 'YYYY-MM-DD'}}."""
    import json

    from app.models import Setting

    raw = Setting.get(f"notif_dismiss:{user.id}")
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return {}


def dismiss(user, key):
    """Mark an alert as seen for this user, snapshotting its current count so it
    reappears only if new items show up later (and it auto-clears next day)."""
    import json

    from app.extensions import db
    from app.models import Setting

    if user is None or not getattr(user, "is_authenticated", False):
        return
    current = next((it["count"] for it in _all() if it["key"] == key), 0)
    data = _dismissed_map(user)
    data[key] = {"c": int(current or 0), "d": date.today().isoformat()}
    Setting.set(f"notif_dismiss:{user.id}", json.dumps(data))
    db.session.commit()


def dismiss_all(user):
    """Mark every currently-visible alert as seen for this user at once."""
    import json

    from app.extensions import db
    from app.models import Setting

    if user is None or not getattr(user, "is_authenticated", False):
        return
    today_s = date.today().isoformat()
    data = _dismissed_map(user)
    for it in _all():
        if not user.can_access(it["module"]):
            continue
        data[it["key"]] = {"c": int(it["count"] or 0), "d": today_s}
    Setting.set(f"notif_dismiss:{user.id}", json.dumps(data))
    db.session.commit()


def get_notifications(user):
    """Alerts visible to this user (filtered by module access + dismissals)."""
    if user is None or not getattr(user, "is_authenticated", False):
        return []
    dismissed = _dismissed_map(user)
    today_s = date.today().isoformat()
    out = []
    for it in _all():
        if not user.can_access(it["module"]):
            continue
        seen = dismissed.get(it["key"])
        # Hide if dismissed today and nothing new has arrived since.
        if seen and seen.get("d") == today_s and (it["count"] or 0) <= seen.get("c", 0):
            continue
        out.append(it)
    return out
