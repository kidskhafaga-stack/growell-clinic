"""Smart scheduling helpers: available slot generation and doctor lookup."""
from datetime import date, datetime, timedelta

from app.extensions import db
from app.models import (
    Appointment,
    DoctorSchedule,
    ScheduleException,
    User,
)
from app.models.appointment import ACTIVE_STATUSES

# How far ahead the "next available" finders scan before giving up.
LOOKAHEAD_DAYS = 60


def list_doctors():
    """Active users who actually hold appointments.

    This is the role == "doctor" set, plus any user explicitly flagged as a
    practitioner (e.g. an admin who also sees patients). Admins are *not*
    included by default, so the super-admin no longer shows up as a doctor.
    """
    return (
        User.query.filter(User.is_active.is_(True))
        .filter(db.or_(User.role == "doctor", User.is_practitioner.is_(True)))
        .order_by(User.full_name)
        .all()
    )


def taken_times(doctor_id, on_date, exclude_id=None):
    """Set of ``HH:MM`` strings already booked for a doctor on a date."""
    query = Appointment.query.filter(
        Appointment.doctor_id == doctor_id,
        Appointment.appt_date == on_date,
        Appointment.status.in_(ACTIVE_STATUSES),
    )
    if exclude_id:
        query = query.filter(Appointment.id != exclude_id)
    return {a.appt_time.strftime("%H:%M") for a in query.all()}


def day_exceptions(doctor_id, on_date):
    """Schedule exceptions (time off / breaks) for a doctor on a date."""
    return ScheduleException.query.filter_by(
        doctor_id=doctor_id, exc_date=on_date
    ).all()


def active_count(doctor_id, on_date, exclude_id=None):
    """Number of slot-occupying appointments for a doctor on a date."""
    query = Appointment.query.filter(
        Appointment.doctor_id == doctor_id,
        Appointment.appt_date == on_date,
        Appointment.status.in_(ACTIVE_STATUSES),
    )
    if exclude_id:
        query = query.filter(Appointment.id != exclude_id)
    return query.count()


def day_capacity(schedules):
    """Daily booking cap for a set of windows, or ``None`` for unlimited.

    Only capped when *every* window sets ``max_patients`` (their sum); if any
    window is uncapped the day is treated as unlimited.
    """
    caps = [s.max_patients for s in schedules]
    if caps and all(c is not None for c in caps):
        return sum(caps)
    return None


def available_slots(doctor_id, on_date, exclude_id=None):
    """Return ordered available ``HH:MM`` slots for a doctor on a date.

    Slots come from the doctor's schedule windows for that weekday, minus:
    times already booked (active statuses), past times when the date is today,
    times blocked by schedule exceptions (time off / breaks), and everything
    once the daily capacity is reached. This is the core of conflict-free
    smart booking.
    """
    weekday = on_date.weekday()
    schedules = (
        DoctorSchedule.query.filter_by(
            doctor_id=doctor_id, weekday=weekday, is_active=True
        )
        .order_by(DoctorSchedule.start_time)
        .all()
    )
    if not schedules:
        return []

    exceptions = day_exceptions(doctor_id, on_date)
    if any(e.is_full_day for e in exceptions):
        return []  # doctor off the whole day (vacation / holiday)

    # Daily capacity check (whole-day cap across windows).
    cap = day_capacity(schedules)
    if cap is not None and active_count(doctor_id, on_date, exclude_id) >= cap:
        return []

    taken = taken_times(doctor_id, on_date, exclude_id=exclude_id)
    now = datetime.now()
    is_today = on_date == date.today()

    slots = []
    seen = set()
    for sched in schedules:
        for slot in sched.iter_slots():
            label = slot.strftime("%H:%M")
            if label in seen or label in taken:
                continue
            if is_today and slot <= now.time():
                continue
            if any(e.blocks(slot) for e in exceptions):
                continue
            seen.add(label)
            slots.append(label)
    return sorted(slots)


def next_available(doctor_id, from_date=None, days=LOOKAHEAD_DAYS):
    """First free slot for a doctor scanning forward from ``from_date``.

    Returns ``{"date": iso, "time": "HH:MM"}`` or ``None`` if nothing is free
    within the lookahead window.
    """
    start = from_date or date.today()
    for offset in range(days):
        on_date = start + timedelta(days=offset)
        slots = available_slots(doctor_id, on_date)
        if slots:
            return {"date": on_date.isoformat(), "time": slots[0]}
    return None


def first_available_doctor(from_date=None, days=LOOKAHEAD_DAYS, doctors=None):
    """Earliest free slot across all (or given) doctors.

    Scans date-by-date so the *soonest* slot wins regardless of doctor.
    Returns a dict with doctor/date/time, or ``None``.
    """
    start = from_date or date.today()
    docs = doctors if doctors is not None else list_doctors()
    if not docs:
        return None
    for offset in range(days):
        on_date = start + timedelta(days=offset)
        best = None
        for doc in docs:
            slots = available_slots(doc.id, on_date)
            if slots and (best is None or slots[0] < best[1]):
                best = (doc, slots[0])
        if best:
            doc, slot = best
            return {
                "doctor_id": doc.id,
                "doctor_name": doc.display_name(),
                "date": on_date.isoformat(),
                "time": slot,
            }
    return None


def slot_duration(doctor_id, on_date):
    """Best-guess slot length for a doctor/date (first matching window)."""
    sched = DoctorSchedule.query.filter_by(
        doctor_id=doctor_id, weekday=on_date.weekday(), is_active=True
    ).first()
    return sched.slot_minutes if sched else 15


def parse_date_arg(value, default=None):
    """Parse an ISO date string, falling back to ``default`` or today."""
    if value:
        try:
            return datetime.strptime(value, "%Y-%m-%d").date()
        except ValueError:
            pass
    return default or date.today()
