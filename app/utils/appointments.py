"""Smart scheduling helpers: available slot generation and doctor lookup."""
from datetime import date, datetime

from app.models import Appointment, DoctorSchedule, User
from app.models.appointment import ACTIVE_STATUSES


def list_doctors():
    """Active users who can hold appointments (doctors, plus admins)."""
    return (
        User.query.filter(User.is_active.is_(True))
        .filter(User.role.in_(["doctor", "admin"]))
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


def available_slots(doctor_id, on_date, exclude_id=None):
    """Return ordered available ``HH:MM`` slots for a doctor on a date.

    Slots come from the doctor's schedule windows for that weekday, minus
    times already booked (active statuses), minus past times when the date is
    today. This is the core of conflict-free smart booking.
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
            seen.add(label)
            slots.append(label)
    return sorted(slots)


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
