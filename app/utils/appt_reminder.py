"""The message that stops a family forgetting: a reminder *before* the visit.

The program had a confirmation and called it a reminder. The confirmation goes
out when the booking is made — often two or three weeks earlier — and by then
it is a receipt. Measured before building this: ``SYSTEM_TEMPLATE_TYPES`` had
no ``appointment_reminder`` at all, and ``scheduled_at`` was never written from
the booking screen. Nothing in this program has ever reminded anybody about an
appointment.

Everything it needs already existed and none of it had been wired together:
``MessageTemplate`` carries the body, the image and the auto/manual switch;
``wa.send`` takes a ``scheduled_at`` and already honours the patient opt-out,
the sending window and the daily cap; ``dispatch_due`` drains the queue. This
module is the missing half-page between them.

**Three decisions worth stating.**

*The lead time is its own setting, not the template's ``delay_hours``.* That
column means "this long **after** the trigger" everywhere else — the survey
after the visit, the birthday on the day. Reusing it here would make one column
mean "before" for one row and "after" for the rest, which is a bug factory. It
sits with the sending window and the daily cap, which is where the clinic's
other timing numbers already are.

*Nothing is queued unless it would actually send itself.* In manual mode every
message becomes a click-to-send link for a human to press. A link scheduled for
tomorrow at nine is a link nobody is standing in front of — it would sit in the
log looking like a reminder that went out. So in manual mode no row is created
at all, and the settings screen says why in one line, rather than the log
filling with hundreds of rows nobody will action.

*Changing the appointment changes the reminder.* A reminder for a cancelled
visit is worse than no reminder — it is the clinic telling a family to come to
something that is not happening. Rescheduling re-times it, cancelling drops it,
and both go through the same two functions.
"""
from datetime import datetime, timedelta

from app.extensions import db
from app.models import Appointment, MessageLog, Setting
from app.utils.clock import to_utc

TYPE = "appointment_reminder"

# A day ahead: long enough that a family can rearrange their morning, short
# enough that they have not forgotten again by the time it comes round.
DEFAULT_LEAD_HOURS = 24

# Below this the reminder has no purpose (they are already on their way) and
# above it, it is not a reminder any more — it is a second confirmation.
MIN_LEAD_HOURS = 1
MAX_LEAD_HOURS = 168  # a week


def lead_hours():
    """How far ahead of the appointment the reminder goes out."""
    try:
        hours = int(Setting.get("wa_reminder_hours", DEFAULT_LEAD_HOURS))
    except (TypeError, ValueError):
        return DEFAULT_LEAD_HOURS
    return max(MIN_LEAD_HOURS, min(MAX_LEAD_HOURS, hours))


def send_at(appt, hours=None):
    """When this appointment's reminder should go out, as naive UTC.

    The appointment is a wall-clock time in the clinic; ``scheduled_at`` is
    compared against ``utcnow()``. Converting in one place is the difference
    between a 10 a.m. appointment being reminded at 9 a.m. the day before and
    at 6 a.m. — off by exactly the clinic's offset, every single time, in a way
    nobody would notice from inside the same timezone.
    """
    if not appt or not appt.appt_date or not appt.appt_time:
        return None
    local = datetime.combine(appt.appt_date, appt.appt_time)
    return to_utc(local) - timedelta(hours=lead_hours() if hours is None else hours)


def pending_for(appt_id):
    """The reminder already queued for this appointment, if any."""
    return (MessageLog.query
            .filter_by(appointment_id=appt_id, template_type=TYPE,
                       status="scheduled")
            .order_by(MessageLog.id).first())


def render(appt, lang="ar"):
    """The reminder text for this appointment, from the clinic's template."""
    from app.utils import whatsapp as wa

    # Same shape as the confirmation's renderer, deliberately: the two messages
    # are about the same appointment and a family reading one after the other
    # should not meet two different ways of writing the doctor's name or the
    # clinic's.
    return wa.render(wa.template_body(TYPE), {
        "patient": appt.patient.display_name(lang) if appt.patient else "",
        "clinic": Setting.get("clinic_name_ar") or Setting.get("clinic_name") or "",
        "date": appt.appt_date.strftime("%Y-%m-%d"),
        "time": appt.time_label,
        "doctor": appt.doctor.display_name(lang) if appt.doctor else "",
    })


def schedule(appt, user_id=None, lang="ar"):
    """Queue this appointment's reminder. Returns the log row, or None.

    Silent about every reason it declines, because each of them is normal:
    the clinic sends links by hand, the type is switched off, the family has
    no number on file, the appointment is sooner than the lead time, or one is
    queued already. A booking screen is not the place to explain any of that —
    the reminder's own settings card is.
    """
    if appt is None or appt.status in ("cancelled", "no_show"):
        return None
    from app.utils import whatsapp as wa

    if wa.type_is_off(TYPE) or not wa.sends_itself(TYPE):
        return None
    patient = appt.patient
    phone = patient.contact_phone if patient else None
    if not phone:
        return None
    if pending_for(appt.id) is not None:
        return None

    when = send_at(appt)
    if when is None or when <= datetime.utcnow():
        # Booked for this afternoon: the reminder's moment is already behind
        # us. Sending it now would be a duplicate of the confirmation the
        # family just received.
        return None

    return wa.send(render(appt, lang), phone, patient_id=appt.patient_id,
                   appointment_id=appt.id, user_id=user_id,
                   template_type=TYPE, scheduled_at=when,
                   image_url=wa.template_image(TYPE))


def cancel(appt_id):
    """Drop the queued reminder for an appointment. Returns how many went.

    Deletes rather than marks skipped: a reminder that was never sent because
    the visit was cancelled is not a delivery failure, and putting it in the
    failures list would bury the ones that are.
    """
    rows = (MessageLog.query
            .filter_by(appointment_id=appt_id, template_type=TYPE,
                       status="scheduled").all())
    for row in rows:
        db.session.delete(row)
    return len(rows)


def resync(appt, user_id=None, lang="ar"):
    """Make the queued reminder match the appointment as it now stands.

    Called after a reschedule, a cancellation, or a status change. Cancelling
    first and re-queueing is deliberate: the alternative is editing the queued
    row's time and body in place, and every field forgotten in that update is
    a family told the wrong hour.
    """
    if appt is None:
        return None
    cancel(appt.id)
    if appt.status in ("cancelled", "no_show", "completed"):
        return None
    return schedule(appt, user_id=user_id, lang=lang)


def due_soon(within_hours=48):
    """Reminders queued to go out shortly — for the sending board to show.

    A queue nobody can look into is a queue nobody trusts.
    """
    now = datetime.utcnow()
    return (MessageLog.query
            .filter(MessageLog.template_type == TYPE,
                    MessageLog.status == "scheduled",
                    MessageLog.scheduled_at <= now + timedelta(hours=within_hours))
            .order_by(MessageLog.scheduled_at)
            .all())


def backfill(user_id=None, lang="ar", limit=500):
    """Queue reminders for appointments already booked before this existed.

    Without this the feature starts working for bookings made from today and
    silently skips every appointment already in the diary — which, the week it
    is switched on, is all of them.
    """
    now = datetime.utcnow()
    horizon = (now + timedelta(hours=MAX_LEAD_HOURS)).date()
    upcoming = (Appointment.query
                .filter(Appointment.status.in_(("scheduled", "waiting")),
                        Appointment.appt_date >= now.date(),
                        Appointment.appt_date <= horizon)
                .order_by(Appointment.appt_date, Appointment.appt_time)
                .limit(limit).all())
    made = 0
    for appt in upcoming:
        if schedule(appt, user_id=user_id, lang=lang) is not None:
            made += 1
    if made:
        db.session.commit()
    return made
