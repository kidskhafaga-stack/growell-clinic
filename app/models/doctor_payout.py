"""Money actually handed to a doctor.

The one record the program did not have, and the reason a doctor's own screen
carried the sentence *"it cannot say what is still owed — that would be a
guess, not a figure"*.

**Earning and being paid are two different events, and only one of them was
written down.** Every invoice line already carries the doctor's share, so what
a doctor has *earned* has always been computable. What left the clinic and went
to them was not recorded anywhere: paying a doctor was, at best, a "salaries"
expense with no doctor on it and no period. So "what am I still owed" had no
subtrahend, and the screen said so rather than showing a number it could not
stand behind.

**It is a running account, not a settlement of a month.** A payout carries no
period on purpose. A clinic pays a round number on the fifteenth and the rest
later; another pays weekly; another clears an old balance in one go. Tying each
payment to a month would force all of them into a shape only one of them has,
and the moment a payment covered two months the arithmetic would need a rule
nobody agreed to. Earned minus paid is the balance, over any window a screen
asks about — the same shape a supplier account already uses here.

**And it is money leaving a drawer.** It carries the till it came out of and
the shift it happened during, for exactly the reason ``Expense`` does: pay a
doctor 2,000 from the reception drawer and, without those two, the drawer comes
up 2,000 short at close and the variance lands on the cashier for doing what
they were told.
"""
from datetime import datetime

from app.extensions import db
from app.utils.clock import local_today

# The same four a supplier payment offers. A doctor paid by transfer and a
# supplier paid by transfer are the same act with a different payee, and two
# lists that mean the same thing drift.
DOCTOR_PAYOUT_METHODS = ["cash", "bank", "transfer", "cheque"]


class DoctorPayout(db.Model):
    """One payment to one doctor, on one day, out of one till."""

    __tablename__ = "doctor_payouts"

    id = db.Column(db.Integer, primary_key=True)
    doctor_id = db.Column(db.Integer, db.ForeignKey("users.id"),
                          nullable=False, index=True)
    amount = db.Column(db.Float, default=0, nullable=False)
    paid_on = db.Column(db.Date, default=local_today, nullable=False, index=True)
    method = db.Column(db.String(12), default="cash", nullable=False)
    reference = db.Column(db.String(80))          # cheque / transfer reference
    notes = db.Column(db.String(255))

    # Which drawer it left. Paying a doctor out of the reception till has to
    # come out of that till, not out of "cash" in the abstract.
    account_id = db.Column(db.Integer, db.ForeignKey("cash_accounts.id"),
                           nullable=True, index=True)
    # And which session, so the count at the end of it expects the right
    # amount. See Expense.shift_id for the same reasoning.
    shift_id = db.Column(db.Integer, db.ForeignKey("cashier_shifts.id"),
                         nullable=True, index=True)

    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    doctor = db.relationship("User", foreign_keys=[doctor_id])
    account = db.relationship("CashAccount", foreign_keys=[account_id])

    @classmethod
    def paid_to(cls, doctor_id, date_from=None, date_to=None):
        """What this doctor has been handed, over a window or over all time.

        Defaults to all time, because that is what "still owed" is made of: a
        balance is what happened since the beginning, not since the first of
        the month.
        """
        query = cls.query.filter(cls.doctor_id == doctor_id)
        if date_from is not None:
            query = query.filter(cls.paid_on >= date_from)
        if date_to is not None:
            query = query.filter(cls.paid_on <= date_to)
        return round(sum(row.amount or 0 for row in query.all()), 2)

    def __repr__(self):
        return f"<DoctorPayout {self.doctor_id} {self.amount} {self.paid_on}>"
