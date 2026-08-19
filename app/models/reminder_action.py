"""What somebody already did about a reminder, so it stops asking again.

The work list is rebuilt from scratch every time it is opened: who is late,
computed from birthdays and doses. That is right, and it means a row somebody
worked yesterday comes back this morning looking exactly like a row nobody has
touched. Reception calls a family, the family says "next month", and tomorrow
the list says call them.

A list that cannot remember is one people stop believing, and the failure is
quiet: they do not complain, they just work the top of it and ignore the rest.

Three actions, and the difference between them is how long they last:

  * ``called`` — spoke to them. Logged, and clears itself the same day, because
    a call is a fact about today and not a decision about next week.
  * ``snoozed`` — they asked for later, and said when. Hidden until that day.
  * ``dismissed`` — not going to happen. Hidden with no date on it.

**Nothing is deleted and nothing is hidden without a way back.** The screens
count what they are holding back and will show it, because a row that vanishes
for good is how a child quietly stops being followed — the same reason the
opt-out is asked in one place and never assumed.
"""
from datetime import timedelta

from app.extensions import db
from app.utils.clock import local_today

# How long a plain "I called them" keeps a row quiet. One day: the point is to
# stop the same person being rung twice this afternoon, not to decide anything
# about next week.
CALL_QUIET_DAYS = 1

ACTIONS = ["called", "snoozed", "dismissed"]


class ReminderAction(db.Model):
    __tablename__ = "reminder_actions"

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"),
                           nullable=False, index=True)
    vaccine_id = db.Column(db.Integer, db.ForeignKey("vaccines.id"),
                           nullable=False, index=True)
    # Which dose it was about. A course moves on, and an action taken about
    # the second dose must not silence the third.
    dose_number = db.Column(db.Integer)
    action = db.Column(db.String(20), nullable=False)
    # The day it stops applying. NULL means "no date on it" — a dismissal,
    # which lasts until somebody undoes it.
    until = db.Column(db.Date)
    note = db.Column(db.String(200))
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id"),
                              nullable=True)
    created_at = db.Column(db.DateTime, server_default=db.func.now())

    patient = db.relationship("Patient")
    vaccine = db.relationship("Vaccine")
    created_by = db.relationship("User")

    def is_active(self, today=None):
        today = today or local_today()
        return self.until is None or self.until > today

    def __repr__(self):
        return f"<ReminderAction {self.action} p={self.patient_id}>"


def default_until(action, until=None, today=None):
    """When an action stops applying, if the caller did not say."""
    today = today or local_today()
    if action == "called":
        return today + timedelta(days=CALL_QUIET_DAYS)
    if action == "dismissed":
        return None
    return until


def silenced(patient_ids, today=None):
    """``{(patient_id, vaccine_id, dose_number)}`` currently being held back.

    One query for the whole sweep. The dose number is part of the key on
    purpose: silencing a reminder about the second dose says nothing about the
    third, and treating it as if it did is how a child stops being followed
    after one phone call.
    """
    if not patient_ids:
        return set()
    today = today or local_today()
    rows = (ReminderAction.query
            .filter(ReminderAction.patient_id.in_(list(patient_ids)))
            .filter(db.or_(ReminderAction.until.is_(None),
                           ReminderAction.until > today)).all())
    return {(r.patient_id, r.vaccine_id, r.dose_number) for r in rows}
