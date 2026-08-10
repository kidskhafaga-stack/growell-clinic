"""Send the failed ones again — the ones that are still worth sending.

The board has told the clinic "12 failed" since the failures panel was built,
and offered no way to do anything about it: there is no ``resend`` or
``requeue`` anywhere in the routes or the templates. The only remedy was to
find each one and send it by hand, which nobody does twelve times.

**This became worth building only after delivery receipts.** Before them,
``failed`` mostly meant "the provider did not answer" — a shrug. Now a failure
carries the provider's own reason, so pressing this re-sends messages the
clinic knows why it lost.

**A retry is a new message, not a rewritten one.** Flipping the old row back to
``scheduled`` would erase the fact that it failed, and the failure is the
record of what happened. So the original keeps its status and the retry points
back at it — which also makes "already retried" a fact in the data rather than
something a button has to remember.

**And the important half is what it refuses.**

* *Skips are not failures.* ``opted_out``, ``missing_phone`` and ``type_off``
  are the clinic's own states. Re-sending an opt-out would message a family
  that asked not to be messaged, which is the one mistake in this whole module
  that is not recoverable.
* *A message whose moment has gone is not resent.* A reminder for yesterday's
  appointment, or a "we missed you" for a visit the family has since attended,
  is worse arriving late than never arriving. Time-bound types are checked
  against the appointment they belong to.
* *Once.* A number that is wrong is wrong; retrying it on every press turns
  one dead number into a daily habit.
"""
from datetime import datetime, timedelta

from app.extensions import db
from app.models import Appointment, MessageLog, SKIP_REASONS

# Types whose message stops making sense once its appointment has passed.
TIME_BOUND = ("appointment_reminder", "appointment_confirm")

# How far back a retry is offered. Older than this, a failed message is
# history: nobody wants yesterday's month of reminders going out at once.
DEFAULT_DAYS = 7

# One press must not become a send-storm; the window and the daily cap still
# apply on top of this, but a bounded batch is easier to reason about.
MAX_PER_PRESS = 200


def _already_retried_ids(rows):
    """Ids among ``rows`` that a retry already points at."""
    ids = [r.id for r in rows]
    if not ids:
        return set()
    done = (db.session.query(MessageLog.retry_of)
            .filter(MessageLog.retry_of.in_(ids)).all())
    return {r[0] for r in done}


def _still_worth_sending(log, now):
    """False for a message whose moment has gone.

    A reminder that arrives the morning after the appointment tells a family
    to come to something they have already missed — and it is the clinic that
    looks like it has lost track.
    """
    if log.template_type not in TIME_BOUND or not log.appointment_id:
        return True
    appt = db.session.get(Appointment, log.appointment_id)
    if appt is None or appt.appt_date is None:
        return False
    return appt.appt_date >= now.date()


def retryable(days=DEFAULT_DAYS, limit=MAX_PER_PRESS):
    """The failed messages a resend would actually help.

    Deliberately not "everything red on the board": that list includes skips,
    which are the clinic's own decisions, and stale time-bound messages, which
    should not arrive at all.
    """
    now = datetime.utcnow()
    since = now - timedelta(days=days)
    rows = (MessageLog.query
            .filter(MessageLog.status == "failed",
                    MessageLog.direction == "out",
                    MessageLog.created_at >= since)
            .filter(db.or_(MessageLog.error.is_(None),
                           MessageLog.error.notin_(SKIP_REASONS)))
            .order_by(MessageLog.created_at.desc())
            .limit(limit).all())
    retried = _already_retried_ids(rows)
    return [r for r in rows
            if r.id not in retried and _still_worth_sending(r, now)]


def resend(log, user_id=None):
    """Send one failed message again as a new message. Returns the new row.

    Goes through ``wa.send`` rather than writing a row directly, so the opt-out,
    the sending window and the daily cap all apply exactly as they would to any
    other message. A family that opted out between the failure and the retry is
    not messaged, and the retry lands as a skip — which is correct and is the
    reason not to shortcut it.
    """
    from app.utils import whatsapp as wa

    if log is None or not log.to_phone:
        return None
    fresh = wa.send(log.body, log.to_phone, patient_id=log.patient_id,
                    appointment_id=log.appointment_id, user_id=user_id,
                    template_type=log.template_type, image_url=log.image_url)
    if fresh is not None:
        fresh.retry_of = log.id
    return fresh


def resend_all(days=DEFAULT_DAYS, limit=MAX_PER_PRESS, user_id=None):
    """Retry every failure worth retrying. Returns a small summary."""
    rows = retryable(days=days, limit=limit)
    sent = 0
    for row in rows:
        if resend(row, user_id=user_id) is not None:
            sent += 1
    if sent:
        db.session.commit()
    return {"considered": len(rows), "resent": sent}
