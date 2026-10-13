"""The hospital's ambulance — see ``models/ambulance``."""
from datetime import date, datetime, timedelta
from statistics import median

from app.extensions import db
from app.models.ambulance import (OUTCOMES, PROVIDERS, READINESS_KINDS, STEPS, AmbulanceCall,
                                  AmbulanceReadiness, AmbulanceVehicle)

#: (c) the hospital's targets in minutes, from the call: to sending a vehicle,
#: and to reaching the child. Empty until written.
TARGET_SETTINGS = {"dispatched_at": "amb_target_dispatch_min", "at_scene_at": "amb_target_scene_min"}


class AmbulanceError(ValueError):
    """A refusal with a locale key (``amb.err_<key>``)."""


def _text(raw, limit=None):
    s = (raw or "").strip()
    return (s[:limit] if limit else s) or None


def _when(raw):
    from app.utils.clock import to_utc

    try:
        return to_utc(datetime.fromisoformat(str(raw or "").strip()))
    except ValueError:
        return None


def _day(raw):
    try:
        return date.fromisoformat((raw or "").strip())
    except ValueError:
        return None


def targets():
    from app.models import Setting

    out = {}
    for step, key in TARGET_SETTINGS.items():
        try:
            value = float((Setting.get(key) or "").strip())
        except ValueError:
            value = None
        out[step] = value if value and value > 0 else None
    return out


def set_targets(form):
    from app.models import Setting

    for step, key in TARGET_SETTINGS.items():
        raw = (form.get(step) or "").strip()
        if raw:
            try:
                if float(raw) <= 0:
                    raise ValueError
            except ValueError:
                raise AmbulanceError("target") from None
        Setting.set(key, raw)


# =============================================================== vehicles ==
def add_vehicle(form):
    name = _text(form.get("name"), 80)
    if not name:
        raise AmbulanceError("name")
    provider = form.get("provider") if form.get("provider") in PROVIDERS else "own"
    contractor = _text(form.get("contractor"), 160)
    if provider == "contracted" and not contractor:
        raise AmbulanceError("contractor")
    row = AmbulanceVehicle(name=name, plate=_text(form.get("plate"), 40), provider=provider,
                           contractor=contractor)
    db.session.add(row)
    db.session.flush()
    return row


def readiness(form, user):
    kind = form.get("kind") if form.get("kind") in READINESS_KINDS else "check"
    vehicle = db.session.get(AmbulanceVehicle, form.get("vehicle_id", type=int) or 0)
    if kind == "check" and vehicle is None:
        raise AmbulanceError("vehicle")
    held = _day(form.get("held_on")) or date.today()
    ok = form.get("ok") != "no"
    missing, action = _text(form.get("missing")), _text(form.get("action"))
    if not ok and not missing:
        raise AmbulanceError("missing")
    if not ok and not action:
        raise AmbulanceError("action")
    note = _text(form.get("note"))
    if kind == "drill" and not note:
        raise AmbulanceError("drill_note")
    row = AmbulanceReadiness(vehicle_id=vehicle.id if vehicle else None, kind=kind, held_on=held, ok=ok,
                             missing=missing, action=action, note=note, by_id=getattr(user, "id", None))
    db.session.add(row)
    db.session.flush()
    return row


def fleet():
    vehicles = AmbulanceVehicle.query.filter_by(is_active=True).order_by(AmbulanceVehicle.name).all()
    last = {}
    for r in (AmbulanceReadiness.query.filter_by(kind="check")
              .order_by(AmbulanceReadiness.held_on.desc(), AmbulanceReadiness.id.desc()).limit(500)):
        last.setdefault(r.vehicle_id, r)
    drills = (AmbulanceReadiness.query.filter_by(kind="drill")
              .order_by(AmbulanceReadiness.held_on.desc()).limit(20).all())
    return {"vehicles": vehicles, "last": last, "drills": drills}


# ================================================================== calls ==
def receive(form, user):
    location, complaint = _text(form.get("location"), 255), _text(form.get("complaint"), 255)
    if not location:
        raise AmbulanceError("location")
    if not complaint:
        raise AmbulanceError("complaint")
    from app.models import Patient

    patient = db.session.get(Patient, form.get("patient_id", type=int) or 0)
    row = AmbulanceCall(received_at=_when(form.get("received_at")) or datetime.utcnow(),
                        caller=_text(form.get("caller"), 160), phone=_text(form.get("phone"), 40),
                        location=location, complaint=complaint,
                        patient_id=patient.id if patient else None,
                        patient_name=_text(form.get("patient_name"), 120), by_id=getattr(user, "id", None))
    db.session.add(row)
    db.session.flush()
    return row


def stamp(call, step, form):
    """One of the four moments, in order — a moment can't be stamped
    before the one it follows."""
    if step not in STEPS:
        raise AmbulanceError("step")
    if not call.is_open:
        raise AmbulanceError("closed")
    i = STEPS.index(step)
    if i and getattr(call, STEPS[i - 1]) is None:
        raise AmbulanceError("order")
    if getattr(call, step) is not None:
        raise AmbulanceError("stamped")
    if step == "dispatched_at":
        vehicle = db.session.get(AmbulanceVehicle, form.get("vehicle_id", type=int) or 0)
        if vehicle is None:
            raise AmbulanceError("vehicle")
        call.vehicle_id = vehicle.id
        call.crew = _text(form.get("crew"), 255)
    moment = _when(form.get("at")) or datetime.utcnow()
    if moment < (getattr(call, STEPS[i - 1]) if i else call.received_at):
        raise AmbulanceError("before")
    setattr(call, step, moment)
    db.session.flush()
    return call


def record(call, form):
    """What the crew found and did — written as it happens, any number of
    times, until the run is closed."""
    if not call.is_open:
        raise AmbulanceError("closed")
    from app.models import Patient

    patient = db.session.get(Patient, form.get("patient_id", type=int) or 0)
    if patient is not None:
        call.patient_id = patient.id
    for field in ("assessment", "reassessment", "care"):
        value = _text(form.get(field))
        if value is not None:
            setattr(call, field, value)
    for field, limit in (("condition_on_arrival", 255), ("handed_to", 160)):
        value = _text(form.get(field), limit)
        if value is not None:
            setattr(call, field, value)
    db.session.flush()
    return call


def close(call, form):
    """The run's end. A child brought here needs the assessment, the care,
    the arrival and who received them — ev. 3's complete record."""
    if not call.is_open:
        raise AmbulanceError("closed")
    outcome = form.get("outcome") if form.get("outcome") in OUTCOMES else None
    if outcome is None:
        raise AmbulanceError("outcome")
    if outcome == "brought":
        for need, key in ((call.arrived_at, "arrived"), (call.assessment, "assessment"),
                          (call.care, "care"), (call.handed_to, "handed_to")):
            if not need:
                raise AmbulanceError("incomplete_" + key)
    note = _text(form.get("outcome_note"), 255)
    if outcome in ("refused", "cancelled", "other") and not note:
        raise AmbulanceError("outcome_note")
    call.outcome, call.outcome_note, call.closed_at = outcome, note, datetime.utcnow()
    db.session.flush()
    return call


def board():
    open_calls = (AmbulanceCall.query.filter(AmbulanceCall.closed_at.is_(None))
                  .order_by(AmbulanceCall.received_at).all())
    recent = (AmbulanceCall.query.filter(AmbulanceCall.closed_at.isnot(None))
              .order_by(AmbulanceCall.received_at.desc()).limit(30).all())
    return {"open": open_calls, "recent": recent, "targets": targets()}


def over_target(call, goals=None):
    goals = targets() if goals is None else goals
    return [step for step, limit in goals.items()
            if limit and call.minutes(step) is not None and call.minutes(step) > limit]


def report(start, end):
    """Ev. 4 — response times over a period: how many runs, the median to
    send and to reach, and how many were over the hospital's targets."""
    from app.utils.clock import to_utc

    since = to_utc(datetime.combine(start, datetime.min.time()))
    until = to_utc(datetime.combine(end + timedelta(days=1), datetime.min.time()))
    rows = (AmbulanceCall.query.filter(AmbulanceCall.received_at >= since, AmbulanceCall.received_at < until)
            .order_by(AmbulanceCall.received_at).all())
    goals = targets()
    out = {"rows": rows, "count": len(rows), "targets": goals, "over": {}, "median": {}}
    for step in ("dispatched_at", "at_scene_at", "arrived_at"):
        values = [r.minutes(step) for r in rows if r.minutes(step) is not None]
        out["median"][step] = median(values) if values else None
    for step, limit in goals.items():
        out["over"][step] = (sum(1 for r in rows if r.minutes(step) is not None and r.minutes(step) > limit)
                             if limit else None)
    out["outcomes"] = {o: sum(1 for r in rows if r.outcome == o) for o in OUTCOMES}
    return out


def for_attendance(attendance):
    """The ambulance runs that brought this child to this attendance — the
    same child, arriving within a few hours of it."""
    if attendance is None or not attendance.patient_id or not attendance.arrived_at:
        return []
    window = timedelta(hours=6)
    return (AmbulanceCall.query.filter(AmbulanceCall.patient_id == attendance.patient_id,
                                       AmbulanceCall.arrived_at.isnot(None),
                                       AmbulanceCall.arrived_at >= attendance.arrived_at - window,
                                       AmbulanceCall.arrived_at <= attendance.arrived_at + window)
            .all())


__all__ = ["AmbulanceError", "TARGET_SETTINGS", "add_vehicle", "board", "close", "fleet",
           "for_attendance", "over_target", "readiness", "receive", "record", "report", "set_targets",
           "stamp", "targets"]
