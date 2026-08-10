"""The child who did not come, and the one message that brings them back.

Measured before building: ``no_show`` is a terminal status in
``appointment.py``, and every use of it in the program is a report filter or a
percentage. Nothing was ever sent. A child who misses a follow-up is the most
important patient of that day — the clinic has their number, knows which doctor
they were booked with, and does nothing with either.

**Separate from the reminder on purpose.** They look alike and are opposites:
the reminder goes out *before* a specific hour and must be re-timed or dropped
every time the appointment moves, while this goes out *after* an event that has
already happened and can never need re-timing. Keeping them in one module would
mean one set of functions with two meanings of "when".

**And the delay here is the template's own.** ``delay_days`` / ``delay_hours``
on ``MessageTemplate`` mean "this long after the trigger", which is exactly
what this is — unlike the reminder, whose lead time had to become its own
setting because "before" is not a delay. So the clinic sets the wait on the
template like it does for the satisfaction survey.

**The rule that matters is not sending.** If the family rebooks before the
message goes out — often the same afternoon, because they phoned — the follow-up
becomes the clinic asking somebody to book an appointment they have already
booked. Every booking clears any pending follow-up for that patient.
"""
from app.extensions import db
from app.models import MessageLog

TYPE = "no_show_followup"

# When the template carries no delay of its own. Not immediate: a message that
# lands while a family is still stuck in the traffic that made them miss the
# appointment reads as a rebuke rather than an offer.
DEFAULT_DELAY_HOURS = 3


def pending_for_patient(patient_id):
    """Follow-ups queued for this patient and not yet sent."""
    if not patient_id:
        return []
    return (MessageLog.query
            .filter_by(patient_id=patient_id, template_type=TYPE,
                       status="scheduled").all())


def cancel_for_patient(patient_id):
    """Drop queued follow-ups for a patient. Returns how many went.

    Called when they book again — which is the ordinary outcome, and often
    happens within the hour because they rang to explain.
    """
    rows = pending_for_patient(patient_id)
    for row in rows:
        db.session.delete(row)
    return len(rows)


def render(appt, lang="ar"):
    from app.models import Setting
    from app.utils import whatsapp as wa

    return wa.render(wa.template_body(TYPE), {
        "patient": appt.patient.display_name(lang) if appt.patient else "",
        "clinic": Setting.get("clinic_name_ar") or Setting.get("clinic_name") or "",
        "date": appt.appt_date.strftime("%Y-%m-%d") if appt.appt_date else "",
        "doctor": appt.doctor.display_name(lang) if appt.doctor else "",
    })


def _send_at(tpl):
    """When the follow-up should go out, from the template's own delay."""
    from datetime import datetime, timedelta

    from app.models.message import _template_schedule

    if tpl is None:
        return datetime.utcnow() + timedelta(hours=DEFAULT_DELAY_HOURS)
    if not (tpl.delay_days or tpl.delay_hours or tpl.send_hour is not None):
        return datetime.utcnow() + timedelta(hours=DEFAULT_DELAY_HOURS)
    return _template_schedule(tpl)


def schedule(appt, user_id=None, lang="ar"):
    """Queue the follow-up for a missed appointment. Returns the log row, or None.

    Declines quietly for the ordinary reasons — manual mode, type switched off,
    no number on file, one already queued — for the same reason the reminder
    does: a status dropdown is not the place to explain the messaging
    configuration.
    """
    if appt is None or appt.status != "no_show":
        return None
    from app.utils import whatsapp as wa

    if wa.type_is_off(TYPE) or not wa.sends_itself(TYPE):
        return None
    phone = appt.patient.contact_phone if appt.patient else None
    if not phone:
        return None
    # One per missed appointment, and none at all if the family already has a
    # follow-up waiting for another child's missed visit today — that second
    # one is the same conversation.
    if pending_for_patient(appt.patient_id):
        return None

    when = _send_at(wa.template_for(TYPE))
    if when is None:
        return None
    return wa.send(render(appt, lang), phone, patient_id=appt.patient_id,
                   appointment_id=appt.id, user_id=user_id,
                   template_type=TYPE, scheduled_at=when,
                   image_url=wa.template_image(TYPE))
