"""Smart scheduling helpers: available slot generation and doctor lookup."""
from datetime import datetime, timedelta

from app.extensions import db
from app.models import (
    Appointment,
    DoctorSchedule,
    ScheduleException,
    Setting,
    User,
)
from app.models.appointment import ACTIVE_STATUSES
from app.utils.clock import local_today, to_local

# How far ahead the "next available" finders scan before giving up.
LOOKAHEAD_DAYS = 60

# Consultation = a follow-up to a paid exam (كشف) within a window. Defaults are
# editable in settings.
CONSULT_FREE_DAYS_DEFAULT = 7
CONSULT_MAX_DAYS_DEFAULT = 10


def _setting_int(key, default):
    try:
        return int(Setting.get(key, default))
    except (TypeError, ValueError):
        return default


def consult_window_days():
    """Return (free_days, max_days) for the consultation follow-up window."""
    free = _setting_int("consult_free_days", CONSULT_FREE_DAYS_DEFAULT)
    mx = _setting_int("consult_max_days", CONSULT_MAX_DAYS_DEFAULT)
    if mx < free:
        mx = free
    return free, mx


def last_exam_date(patient_id, doctor_id, on_or_before=None):
    """Date of the patient's most recent exam (كشف / appt_type 'new') with this
    doctor, or None. Cancelled bookings are ignored."""
    if not patient_id or not doctor_id:
        return None
    q = (Appointment.query
         .filter(Appointment.patient_id == patient_id,
                 Appointment.doctor_id == doctor_id,
                 Appointment.appt_type == "new",
                 Appointment.status != "cancelled"))
    if on_or_before is not None:
        q = q.filter(Appointment.appt_date <= on_or_before)
    appt = q.order_by(Appointment.appt_date.desc()).first()
    return appt.appt_date if appt else None


def consultation_window(patient_id, doctor_id, on_date=None):
    """Classify a consultation booking against the follow-up window.

    Returns a dict: ``status`` is one of
      * ``no_exam``  – no prior exam on record with this doctor
      * ``ok``       – within the free follow-up window
      * ``warn``     – past the free window but within the max
      * ``exceeded`` – past the max → should be an exam (or doctor approval)
    plus ``days`` since the last exam, ``last_date``, ``free_days``, ``max_days``.
    """
    on_date = on_date or local_today()
    free_days, max_days = consult_window_days()
    last = last_exam_date(patient_id, doctor_id, on_date)
    if last is None:
        return {"status": "no_exam", "days": None, "last_date": None,
                "free_days": free_days, "max_days": max_days}
    days = (on_date - last).days
    if days <= free_days:
        status = "ok"
    elif days <= max_days:
        status = "warn"
    else:
        status = "exceeded"
    return {"status": status, "days": days, "last_date": last.isoformat(),
            "free_days": free_days, "max_days": max_days}


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


def schedules_for(doctor_id, on_date):
    """The doctor's working windows that apply on ``on_date`` for its weekday.

    A seasonal window (one carrying a date range, e.g. Ramadan) overrides the
    always-on schedule while ``on_date`` falls inside it; outside any season the
    default windows apply again automatically.
    """
    rows = (DoctorSchedule.query.filter_by(
        doctor_id=doctor_id, weekday=on_date.weekday(), is_active=True)
        .order_by(DoctorSchedule.start_time).all())
    seasonal = [r for r in rows if r.is_seasonal
                and (r.start_date is None or r.start_date <= on_date)
                and (r.end_date is None or on_date <= r.end_date)]
    if seasonal:
        return seasonal
    return [r for r in rows if not r.is_seasonal]


def available_slots(doctor_id, on_date, exclude_id=None):
    """Return ordered available ``HH:MM`` slots for a doctor on a date.

    Slots come from the doctor's schedule windows for that weekday, minus:
    times already booked (active statuses), past times when the date is today,
    times blocked by schedule exceptions (time off / breaks), and everything
    once the daily capacity is reached. This is the core of conflict-free
    smart booking.
    """
    schedules = schedules_for(doctor_id, on_date)
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
    # Both halves of "is this slot already past?" have to come off the same
    # clock. These were ``datetime.now()`` and ``date.today()`` — the machine's
    # — which agree with each other but not with the clinic's zone when the
    # machine is not in it. Splitting only one of them would be worse than
    # leaving both: the day would be the clinic's and the hour the server's.
    now = to_local(datetime.utcnow()) or datetime.utcnow()
    is_today = on_date == now.date()

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
    start = from_date or local_today()
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
    start = from_date or local_today()
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
    """Best-guess slot length for a doctor/date (first applicable window)."""
    rows = schedules_for(doctor_id, on_date)
    return rows[0].slot_minutes if rows else 15


def parse_date_arg(value, default=None):
    """Parse an ISO date string, falling back to ``default`` or **today**.

    Today here is the *clinic's* today, not the machine's. Thirty-four callers
    default through this one line, and it used to answer with ``date.today()``
    — the date in the **operating system's** timezone — while the doctor's
    station screen was already asking :func:`local_today`, which is the date in
    the timezone the clinic *set*.

    On a Windows box sitting in the clinic those are the same date and nothing
    was wrong. They come apart whenever the machine's zone is not the clinic's:
    a server left on UTC, a hosted install, or an admin who picks a zone in
    settings that the OS does not share. Then, for the hours each night when
    the two dates differ, the two halves of one feature look at different days.

    Measured, with the clinic's zone set so the dates differ: a walk-in was
    stored with the machine's date, appeared on reception's board, and **did
    not appear on the doctor's station at all** — a child checked in, sitting
    in the waiting room, and the doctor's screen saying nobody was there.

    Asking one clock removes the condition rather than narrowing it.
    """
    if value:
        try:
            return datetime.strptime(value, "%Y-%m-%d").date()
        except ValueError:
            pass
    if default:
        return default
    from app.utils.clock import local_today
    return local_today()


def next_booked(patient_id, on_or_after=None, doctor_id=None):
    """The next appointment this patient already has, or ``None``.

    For the prescription. A parent leaves holding one piece of paper, and the
    follow-up date they were told out loud is the first thing to go — so if
    the doctor has already booked it, it belongs on the page.

    Only the ones that are still going to happen: a cancelled or no-show
    booking is not a date anybody should be told to come back on, and a
    ``completed`` one has already happened. ``scheduled`` is the whole of
    "booked and still ahead of us", so it is the whole of what this returns.

    Ordered by date **and time** together. Ordering on the date alone leaves
    two bookings on the same morning in whatever order the table hands them
    back, which is how you print 4pm for a patient who is expected at 9.
    """
    on_or_after = on_or_after or local_today()
    query = (Appointment.query
             .filter(Appointment.patient_id == patient_id,
                     Appointment.status == "scheduled",
                     Appointment.appt_date >= on_or_after))
    if doctor_id is not None:
        query = query.filter(Appointment.doctor_id == doctor_id)
    return query.order_by(Appointment.appt_date.asc(),
                          Appointment.appt_time.asc()).first()
