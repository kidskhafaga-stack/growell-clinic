"""After the visit: the family hears from the clinic (DOCTOR_EASE_PLAN.md ب-٦).

Three messages, each one pressed or ticked by a person on the visit screen —
nothing here decides on its own that a family should be written to:

* **The instructions** the doctor wrote in the follow-up box, sent now, on the
  channel the family last wrote from when the platform still allows a reply
  (Messenger and Instagram within a day, Telegram any time, e-mail in the
  thread) — otherwise on WhatsApp.
* **A reminder of the follow-up date**, a set number of days before it, only
  while nothing is booked: at the moment it is due to go, the follow-up's own
  state is read again, and a family that has booked or come is not reminded.
  A booked appointment already has its own reminder.
* **«How is he doing?»** a set number of days after the visit. The family's
  answer lands in the customer-service inbox like any other message.

The words are the doctor's and the clinic's: the templates are wrappers, and
the only clinical sentence in any of them is ``{instructions}`` — what the
doctor wrote for this child. The program gives no advice of its own.

Scheduled messages go on WhatsApp only: the other platforms' reply windows
will have closed by then, and the queue that sends at a time is WhatsApp's.
"""
from datetime import datetime, time, timedelta

from app.extensions import db
from app.models import MessageLog, Setting

INSTRUCTIONS, DUE, CHECKIN = "visit_instructions", "followup_due", "visit_checkin"
TYPES = (INSTRUCTIONS, DUE, CHECKIN)

#: When a scheduled message goes out on its day, in the clinic's own hours —
#: mid-morning, inside any sending window a clinic is likely to set.
SEND_AT = time(10, 0)

DEFAULT_DUE_LEAD_DAYS = 1
DEFAULT_CHECKIN_DAYS = 2
MAX_DAYS = 30


class AftercareError(ValueError):
    """A refusal with a locale key (``aftercare.err_<key>``)."""


def _days(key, default):
    try:
        days = int(Setting.get(key, default))
    except (TypeError, ValueError):
        days = default
    return max(1, min(MAX_DAYS, days))


def due_lead_days():
    return _days("aftercare_due_lead_days", DEFAULT_DUE_LEAD_DAYS)


def checkin_days():
    return _days("aftercare_checkin_days", DEFAULT_CHECKIN_DAYS)


def _clinic():
    return Setting.get("clinic_name_ar") or Setting.get("clinic_name") or ""


def _say(key, lang):
    """A locale string in the message's language, not the screen's."""
    from app.i18n import _load_translations, _lookup

    return _lookup(_load_translations(), lang, key) or _lookup(_load_translations(), "en", key) or ""


def render(kind, visit, lang="ar"):
    from app.utils import whatsapp as wa
    from app.utils.whatsapp import first_name_of

    patient = visit.patient
    due = visit.followup_due.isoformat() if visit.followup_due else ""
    name = patient.display_name(lang) if patient else ""
    followup_line = _say("aftercare.followup_line", lang).format(date=due) if due else ""
    return wa.render(wa.template_body(kind, getattr(patient, "gender", None)), {
        "patient": name, "first_name": first_name_of(name),
        "doctor": visit.doctor.display_name(lang) if visit.doctor else "",
        "clinic": _clinic(), "instructions": (visit.followup_instructions or "").strip(),
        "date": due, "followup": followup_line,
    }).strip()


def pending(visit, kind):
    return (MessageLog.query.filter_by(visit_id=visit.id, template_type=kind,
                                       status="scheduled")
            .order_by(MessageLog.id).first())


def cancel(visit, kind):
    """Drop a queued message for this visit. Deleted, not marked failed: a
    message nobody needs any more is not a delivery problem."""
    rows = (MessageLog.query.filter_by(visit_id=visit.id, template_type=kind,
                                       status="scheduled").all())
    for row in rows:
        db.session.delete(row)
    return len(rows)


def sent(visit):
    """This visit's after-care messages, newest first, for the screen."""
    return (MessageLog.query.filter(MessageLog.visit_id == visit.id,
                                    MessageLog.template_type.in_(TYPES))
            .order_by(MessageLog.created_at.desc()).all())


def _phone(visit):
    patient = visit.patient
    return patient.contact_phone if patient else None


def send_instructions(visit, user, lang="ar"):
    """The doctor's instructions, now. On the family's own channel when a
    reply is still allowed there, else WhatsApp. Returns the log row."""
    from app.utils import inbox, social, social_outbound
    from app.utils import whatsapp as wa

    if not (visit.followup_instructions or "").strip():
        raise AftercareError("no_instructions")
    if wa.type_is_off(INSTRUCTIONS):
        raise AftercareError("off")
    body = render(INSTRUCTIONS, visit, lang)
    key = f"p{visit.patient_id}"
    channel = inbox.reply_channel(key)
    if channel in social.SOCIAL_CHANNELS:
        log, _refused = social_outbound.reply(key, channel, body, user_id=user.id,
                                              template_type=INSTRUCTIONS, automated=True)
        if log is not None:
            log.visit_id = visit.id
            return log
    if not _phone(visit):
        raise AftercareError("no_phone")
    log = wa.send(body, _phone(visit), patient_id=visit.patient_id, user_id=user.id,
                  template_type=INSTRUCTIONS, ignore_window=True)
    log.visit_id = visit.id
    return log


def _local_moment(day):
    from app.utils.clock import to_utc

    return to_utc(datetime.combine(day, SEND_AT))


def _schedule(visit, kind, when, user, lang):
    from app.utils import whatsapp as wa

    if wa.type_is_off(kind):
        raise AftercareError("off")
    if not wa.sends_itself(kind):
        # Manual sending makes a link for a person to press; one queued for
        # next week has nobody standing in front of it.
        raise AftercareError("manual")
    if not _phone(visit):
        raise AftercareError("no_phone")
    if when is None or when <= datetime.utcnow():
        raise AftercareError("too_late")
    cancel(visit, kind)
    log = wa.send(render(kind, visit, lang), _phone(visit), patient_id=visit.patient_id,
                  user_id=user.id, template_type=kind, scheduled_at=when)
    log.visit_id = visit.id
    return log


def schedule_due_reminder(visit, user, lang="ar"):
    """The follow-up date, a few days ahead — while nothing is booked."""
    if visit.followup_due is None:
        raise AftercareError("no_due")
    when = _local_moment(visit.followup_due - timedelta(days=due_lead_days()))
    return _schedule(visit, DUE, when, user, lang)


def schedule_checkin(visit, user, days=None, lang="ar"):
    """«How is he doing?» a few days after the visit."""
    from app.utils.clock import local_today

    days = checkin_days() if days is None else max(1, min(MAX_DAYS, int(days)))
    when = _local_moment(local_today() + timedelta(days=days))
    return _schedule(visit, CHECKIN, when, user, lang)


def still_wanted(log):
    """Read again at the moment a queued message is due. A follow-up
    reminder is dropped once the family has booked or come."""
    if log.template_type != DUE or not log.visit_id:
        return True
    from app.models import Visit
    from app.utils import followup

    visit = db.session.get(Visit, log.visit_id)
    if visit is None or visit.followup_due is None:
        return False
    return followup.state(visit) not in (followup.BOOKED, followup.CAME)


__all__ = ["AftercareError", "CHECKIN", "DUE", "INSTRUCTIONS", "TYPES", "cancel",
           "checkin_days", "due_lead_days", "pending", "render", "schedule_checkin",
           "schedule_due_reminder", "send_instructions", "sent", "still_wanted"]
