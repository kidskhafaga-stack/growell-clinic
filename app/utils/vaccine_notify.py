"""The message a parent gets after a dose — wherever the dose was given.

A clinic reported that the post-vaccination message "is not generated". It
was, from the vaccinations screen. It was not from inside the visit, which is
where a doctor gives most of the doses: that route recorded the dose, deducted
the stock, posted the cost — and said nothing to the family. Two routes doing
one job is how the second one comes to do only half of it, so the message
lives here now and both call it.

The other half of the report is what happens when it *doesn't* go. A file with
no phone number on it, or the notification type switched off in settings, both
ended in a bare ``return``: nothing on the screen, nothing in the log, which
from the outside is indistinguishable from a program that forgot. Both are
recorded now, with the reason and with the message that would have gone, so
the clinic can read it — and, if it matters, send it by hand.
"""
from app.models import MessageLog, Setting
from app.utils import whatsapp as wa

TYPE = "vaccine_given"

# The clinic switched this notification off. Not an error and not a delivery
# failure — but the doctor who gave the dose is entitled to know that the
# message they expect is not coming.
TYPE_OFF = "type_off"


def dose_message(patient, vaccine, brand, dose_number, given_date, lang="ar"):
    """The filled-in body for this dose, ready to send or to record unsent."""
    from app.utils.dose_labels import dose_label, next_dose_text

    return wa.render(wa.template_body(TYPE), {
        "patient": patient.display_name(lang),
        "vaccine": vaccine.display_name(lang),
        "dose": dose_label(dose_number, lang, brand=brand, vaccine=vaccine,
                           on_date=given_date),
        # "—" told a parent nothing. This says the date, or that the course is
        # finished, or that it comes back next season.
        "next_date": next_dose_text(patient, vaccine, brand, dose_number, lang,
                                    given_date),
        "clinic": Setting.get("clinic_name_ar") or Setting.get("clinic_name") or "",
    })


def notify_dose(patient, vaccine, brand, dose_number, given_date,
                user_id=None, lang="ar"):
    """Send the post-vaccination message. Returns ``(log, reason)``.

    ``reason`` is None when the message went (or was queued to go), and
    otherwise names why it did not — ``type_off``, or whatever the sender
    itself recorded, which is ``missing_phone`` for a file with no number on
    it and ``opted_out`` for a family that asked not to be messaged. Either
    way there is a row, so the answer to "why didn't they get it" is on a
    screen instead of in somebody's head.
    """
    from app.extensions import db

    body = dose_message(patient, vaccine, brand, dose_number, given_date, lang)

    if wa.type_is_off(TYPE):
        return _unsent(body, TYPE_OFF, patient, user_id), TYPE_OFF

    log = wa.send(body, patient.contact_phone, patient_id=patient.id,
                  user_id=user_id, template_type=TYPE,
                  image_url=wa.template_image(TYPE))
    db.session.flush()
    reason = log.error if log.status in ("failed", "skipped") else None
    return log, reason


def _unsent(body, reason, patient, user_id):
    """Record a message that was not sent, and why.

    With the body, because the reasons are recoverable: somebody who turns the
    notification back on, or finds the phone number later, should be able to
    read what the parent was supposed to get instead of reconstructing it.
    """
    from app.extensions import db

    log = MessageLog(patient_id=patient.id, to_phone=patient.contact_phone,
                     body=body, template_type=TYPE, created_by=user_id,
                     status="skipped", error=reason)
    db.session.add(log)
    db.session.flush()
    return log
