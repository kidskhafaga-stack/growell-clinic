"""Paid at the desk, so here — one step, not two.

Reception takes the money for today's visit and then had to find the same
booking on the day board and press "arrived" — a second step for a fact the
first one already told the program: a family paying at the desk for today's
visit is standing at the desk. When the second step was forgotten the child
was not in the queue, and the doctor's board said nobody was waiting.

So money **taken at the desk** for **today's** booking that is still only
**booked** marks it arrived: the same ``apply_status("waiting")`` the button
calls, the check-in time stamped, the reminder settled, written in the log.
Nothing else is touched:

* a booking for another day — paid in advance — is not arrived;
* a child already waiting, inside, done, missed or cancelled is left exactly
  where they are: this only ever moves a booking forward from "booked";
* money paid online, from home, through a gateway is not the family at the
  desk, and does not come through here;
* a clinic that wants the two steps kept apart turns it off
  (``arrive_on_payment``); it is on unless it says otherwise.
"""
from app.models import ActivityLog, Setting
from app.utils.clock import local_today

SETTING = "arrive_on_payment"


def enabled():
    return (Setting.get(SETTING, "1") or "1") != "0"


def on_payment(appointment, user=None, ip_address=None, lang="ar"):
    """Money was just taken at the desk for ``appointment``. Marks it arrived
    when it is today's and still only booked; returns it when it did, else
    ``None``. The caller commits."""
    if appointment is None or not enabled():
        return None
    if appointment.status != "scheduled" or appointment.appt_date != local_today():
        return None
    if not appointment.can_transition_to("waiting"):
        return None
    appointment.apply_status("waiting")
    from app.utils import appt_reminder as reminders

    reminders.resync(appointment, user_id=getattr(user, "id", None), lang=lang)
    ActivityLog.record("appointment.status", user_id=getattr(user, "id", None),
                       entity="appointment", entity_id=appointment.id,
                       detail="waiting (paid at the desk)",
                       ip_address=ip_address)
    return appointment
