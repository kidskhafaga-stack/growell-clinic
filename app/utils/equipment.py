"""The medical equipment register — GAHAR EFS.10 / GSR.27 and CSS.02 /
GSR.08. Models in ``app/models/equipment.py``.

**The rules the records keep:**

* a malfunction takes the equipment out of service on the spot, and only a
  repair (or a passed check) puts it back — a broken pump is never shown as
  available because nobody wrote the next line;
* a malfunction, an adverse incident, an alarm event and a failed check all
  need what was done written beside them, and an incident also whom it was
  reported to (EFS.10 دليل ٦, CSS.02 دليل ٥);
* a preventive maintenance, a calibration or an alarm test is due again on
  the date written, or else the manufacturer's interval the hospital wrote
  — **and without either, nothing is overdue**: the program invents no
  maintenance schedule;
* alarm tests and alarm events belong only to equipment marked as carrying
  a critical alarm, with its agreed settings on record.

Nothing here stops a clinician using equipment; it says what is due, what
is broken and who was trained.
"""
from datetime import date, datetime, timedelta

from app.extensions import db
from app.models.equipment import (ALARM_EVENT, ALARM_TEST, CALIBRATION,
                                  EVENT_KINDS, IN_SERVICE, INCIDENT,
                                  MALFUNCTION, OUT_OF_SERVICE, PPM, REPAIR,
                                  RESULTS, RETIRED, SCHEDULED, Equipment,
                                  EquipmentEvent, EquipmentTraining)


class EquipmentError(ValueError):
    """A refusal with a key the screen can name (``equip.err_<key>``)."""


def _today():
    from app.utils.clock import local_today

    return local_today()


def _day(value):
    if isinstance(value, date):
        return value
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise EquipmentError("bad_date") from None


def _days(value):
    raw = str(value or "").strip()
    if not raw:
        return None
    if not raw.isdigit() or not 0 < int(raw) <= 3650:
        raise EquipmentError("bad_interval")
    return int(raw)


def _text(value, limit):
    return (value or "").strip()[:limit] or None


def may_manage(user):
    """Whoever looks after the equipment: the administrators and the
    store — where a hospital's biomedical engineer usually sits in the
    program."""
    return bool(user is not None and (user.is_admin or user.can_access("inventory")))


def may_report(user):
    """A broken pump, an alarm that went off, an incident — reported by
    whoever was standing there."""
    return bool(user is not None and (
        user.is_admin or any(user.can_access(m) for m in
                             ("beds", "labs", "imaging", "visits", "inventory",
                              "pharmacy", "theatres", "emergency"))))


#: What a person without the managing role may report.
REPORTABLE = (MALFUNCTION, INCIDENT, ALARM_EVENT)


# ================================================================ register ==
def save(form, row=None):
    name = _text(form.get("name"), 160)
    if not name:
        raise EquipmentError("need_name")
    row = row or Equipment()
    row.name = name
    for field, limit in (("category", 80), ("manufacturer", 120), ("model", 120),
                         ("serial_number", 80), ("asset_tag", 60), ("location", 160),
                         ("backup", 200), ("company", 160), ("company_contact", 160),
                         ("installation_test", 400)):
        setattr(row, field, _text(form.get(field), limit))
    row.alarm_settings = _text(form.get("alarm_settings"), 4000)
    row.is_critical = bool(form.get("is_critical"))
    row.has_critical_alarm = bool(form.get("has_critical_alarm"))
    row.installed_on = _day(form.get("installed_on"))
    row.ppm_every_days = _days(form.get("ppm_every_days"))
    row.calibration_every_days = _days(form.get("calibration_every_days"))
    row.alarm_test_every_days = _days(form.get("alarm_test_every_days"))
    device = str(form.get("medical_device_id") or "").strip()
    row.medical_device_id = int(device) if device.isdigit() else None
    if row.has_critical_alarm and not row.alarm_settings:
        raise EquipmentError("need_settings")
    if row.id is None:
        db.session.add(row)
    db.session.flush()
    return row


def retire(row, reason, on=None):
    if row is None or row.status == RETIRED:
        raise EquipmentError("retired")
    reason = _text(reason, 200)
    if not reason:
        raise EquipmentError("need_reason")
    row.status = RETIRED
    row.retired_on = on or _today()
    row.retired_reason = reason
    return row


# ================================================================== events ==
def record(row, user, form, at=None):
    """One event on one piece of equipment. The caller commits."""
    if row is None:
        raise EquipmentError("no_equipment")
    if row.status == RETIRED:
        raise EquipmentError("retired")
    kind = form.get("kind")
    if kind not in EVENT_KINDS:
        raise EquipmentError("need_kind")
    if kind not in REPORTABLE and not may_manage(user):
        raise EquipmentError("not_allowed")
    if kind in (ALARM_TEST, ALARM_EVENT) and not row.has_critical_alarm:
        raise EquipmentError("no_alarm")
    details = _text(form.get("details"), 4000)
    if not details:
        raise EquipmentError("need_details")
    result = form.get("result") if kind in SCHEDULED else None
    if kind in SCHEDULED and result not in RESULTS:
        raise EquipmentError("need_result")
    action = _text(form.get("action"), 4000)
    if (kind in (MALFUNCTION, INCIDENT, ALARM_EVENT) or result == "fail") and not action:
        raise EquipmentError("need_action")
    reported_to = _text(form.get("reported_to"), 160)
    if kind == INCIDENT and not reported_to:
        raise EquipmentError("need_reported")
    if kind == REPAIR and row.status != OUT_OF_SERVICE:
        raise EquipmentError("not_broken")
    moment = at or datetime.utcnow()
    next_due = None
    if kind in SCHEDULED:
        next_due = _day(form.get("next_due"))
        if next_due is None and row.interval(kind):
            from app.utils.clock import local_date

            next_due = (local_date(moment) or moment.date()) + timedelta(days=row.interval(kind))
    event = EquipmentEvent(
        equipment_id=row.id, kind=kind, at=moment,
        done_by=_text(form.get("done_by"), 160), result=result, details=details,
        action=action, reported_to=reported_to, next_due=next_due,
        recorded_by=getattr(user, "id", None))
    db.session.add(event)
    if kind == MALFUNCTION or result == "fail":
        row.status = OUT_OF_SERVICE
    elif kind == REPAIR or (kind in SCHEDULED and result == "pass"
                            and row.status == OUT_OF_SERVICE and kind != ALARM_TEST):
        row.status = IN_SERVICE
    db.session.flush()
    return event


def last(row, kind):
    for event in row.events:
        if event.kind == kind:
            return event
    return None


def due(row, kind, today=None):
    """``{"state", "on", "last"}`` — ``state`` is ``ok`` · ``overdue`` ·
    ``never`` (an interval and no check yet) · ``quiet`` (no interval and
    no date written: nothing to judge)."""
    today = today or _today()
    previous = last(row, kind)
    on = None
    if previous is not None:
        on = previous.next_due
        if on is None and row.interval(kind):
            from app.utils.clock import local_date

            on = (local_date(previous.at) or previous.at.date()) + timedelta(days=row.interval(kind))
    elif row.interval(kind):
        if row.installed_on is None:
            return {"state": "never", "on": None, "last": None}
        on = row.installed_on + timedelta(days=row.interval(kind))
    if on is None:
        return {"state": "quiet", "on": None, "last": previous}
    return {"state": "overdue" if on < today else "ok", "on": on, "last": previous}


def open_malfunction(row):
    """The malfunction that took it out of service, while it still is."""
    if row.status != OUT_OF_SERVICE:
        return None
    for event in row.events:
        if event.kind in (MALFUNCTION,) or event.result == "fail":
            return event
        if event.kind == REPAIR:
            return None
    return None


# ================================================================ training ==
def train(row, user_id, trained_on, trainer=None, valid_until=None, by=None):
    from app.models import User

    if row is None:
        raise EquipmentError("no_equipment")
    person = db.session.get(User, int(user_id)) if str(user_id or "").isdigit() else None
    if person is None:
        raise EquipmentError("no_person")
    on = _day(trained_on)
    if on is None:
        raise EquipmentError("need_date")
    if on > _today():
        raise EquipmentError("future")
    until = _day(valid_until)
    if until is not None and until <= on:
        raise EquipmentError("until_before")
    entry = EquipmentTraining(equipment_id=row.id, user_id=person.id, trained_on=on,
                              trainer=_text(trainer, 160), valid_until=until,
                              recorded_by=getattr(by, "id", None))
    db.session.add(entry)
    db.session.flush()
    return entry


def trained_now(row, today=None):
    """``{user_id: newest training}`` that is still in date."""
    today = today or _today()
    out = {}
    for entry in row.trainings:
        if entry.user_id in out:
            continue
        out[entry.user_id] = entry
    return {uid: e for uid, e in out.items()
            if e.valid_until is None or e.valid_until >= today}


# ================================================================== board ==
def board(today=None, include_retired=False):
    today = today or _today()
    query = Equipment.query
    if not include_retired:
        query = query.filter(Equipment.status != RETIRED)
    rows = []
    for row in query.order_by(Equipment.name).all():
        checks = {kind: due(row, kind, today) for kind in SCHEDULED
                  if kind != ALARM_TEST or row.has_critical_alarm}
        rows.append({"equipment": row, "checks": checks,
                     "broken": open_malfunction(row),
                     "attention": row.status == OUT_OF_SERVICE or any(
                         c["state"] in ("overdue", "never") for c in checks.values())})
    rows.sort(key=lambda r: (not r["attention"], not r["equipment"].is_critical,
                             r["equipment"].name))
    return rows


def attention(today=None):
    return sum(1 for r in board(today) if r["attention"])


def incidents(start, end):
    """Adverse incidents and alarm events in a period — EFS.10 دليل ٦,
    CSS.02 دليل ٥."""
    from app.utils.clock import to_utc

    since = to_utc(datetime.combine(start, datetime.min.time()))
    until = to_utc(datetime.combine(end, datetime.max.time()))
    return (EquipmentEvent.query
            .filter(EquipmentEvent.kind.in_((INCIDENT, ALARM_EVENT, MALFUNCTION)),
                    EquipmentEvent.at >= since, EquipmentEvent.at <= until)
            .order_by(EquipmentEvent.at.desc()).all())
