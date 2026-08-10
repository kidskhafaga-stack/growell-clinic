"""A note on a family's payment conduct — and the care that needs.

Reception, a doctor or the office can record that a family does not pay, or
pays only after being chased. It shows where the decisions are made — booking,
the visit, the till — and comes off when the behaviour changes.

Everything unusual about this model exists because **it is an accusation about
a named person, written by a colleague, and read by everyone on the staff.**

*It is cleared, never deleted.* Closing a flag stamps who closed it, when, and
why, and the row stays. A note like this that can vanish without a trace is one
that can be put back on a bad morning, and a family who was wronged would have
nothing to point at.

*Two levels, and they are not the same thing.* ``warn`` shows the note and gets
out of the way. ``block`` stops a booking until somebody with financial
authority allows it — and that override is recorded too. A clinic that only had
"block" would use it for irritation; one that only had "warn" would have no
answer for a family who owes for a year.

*Raised by the staff who see it, cleared by somebody else.* Anyone at the desk
can raise one. Clearing needs ``finance_manage`` or an admin, so the person who
wrote it while annoyed is not the person who takes it off — in either
direction.

*It never prints.* Not on an invoice, a receipt, a prescription or a report —
nothing the family is handed. It is a note between staff about money, and a
family reading "does not pay" on their own receipt is the one outcome that
cannot be undone.
"""
from datetime import datetime

from app.extensions import db

# warn  — show it and let the person decide.
# block — stop the booking until somebody with financial authority allows it.
FLAG_LEVELS = ["warn", "block"]


class PatientFlag(db.Model):
    """A payment-conduct note on a patient file, open or closed."""

    __tablename__ = "patient_flags"

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"),
                           nullable=False, index=True)
    level = db.Column(db.String(10), default="warn", nullable=False)
    # Why, in the words of whoever raised it. Required by the route: a flag
    # with no reason is one nobody can judge, argue with, or clear fairly.
    reason = db.Column(db.Text, nullable=False)

    raised_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    raised_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    # Set when the behaviour changed. The row stays either way.
    cleared_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    cleared_at = db.Column(db.DateTime, index=True)
    clear_reason = db.Column(db.Text)

    patient = db.relationship("Patient")
    raiser = db.relationship("User", foreign_keys=[raised_by])
    clearer = db.relationship("User", foreign_keys=[cleared_by])

    @property
    def is_open(self):
        return self.cleared_at is None

    @property
    def blocks(self):
        """Does this stop a booking on its own?"""
        return self.is_open and self.level == "block"

    def __repr__(self):
        state = "open" if self.is_open else "cleared"
        return f"<PatientFlag p={self.patient_id} {self.level} {state}>"
