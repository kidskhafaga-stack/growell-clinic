"""The patient's own account: money the clinic holds for a family.

Asked as *«حساب دفعات مقدّمة منفصل»* and *«ويبقى في حساب دائن للمرضى لان ده
المفروض موجود فى الاسنان»*. It was not there — the dental deposit's own code
said so: *"money taken beyond what is owed is a credit this program has
nowhere to keep"*. A hospital asks for a deposit before a stay has a bill
big enough to hold it, and a dental family pays ahead of a plan that is not
written yet. Both are this.

**A ledger, not a running figure.** Each row is one thing that happened —
money in, money used on a bill, money handed back — and the balance is what
they add up to. A stored balance is a second place for the number to be
wrong; rows are what an accountant asks to see when it is.

* ``in`` — money received on account (cash, card, InstaPay…). Into a till,
  inside a shift when it is cash, like any money at the desk.
* ``applied`` — part of the balance used to pay a bill. No money moves; the
  bill gets an ordinary payment of method ``credit`` and this row points at
  it, so the bill, the statement and the receipt all read as they always do.
* ``refund`` — what is left, handed back. Out of a till.

In the ledger the balance is a liability (2030): the clinic owes it to the
family until it is spent on their care or given back.
"""
from datetime import datetime

from app.extensions import db

CREDIT_KINDS = ["in", "applied", "refund"]
# The method a bill's payment carries when it was paid from this account.
CREDIT_METHOD = "credit"


class PatientCredit(db.Model):
    __tablename__ = "patient_credits"

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"),
                           nullable=False, index=True)
    kind = db.Column(db.String(10), nullable=False, index=True)
    # Always positive; the kind gives the sign.
    amount = db.Column(db.Float, nullable=False)
    # How the money came or went. Empty for ``applied`` — nothing moved.
    method = db.Column(db.String(12))
    # The till and the shift, for money that moved — the drawer counts it.
    account_id = db.Column(db.Integer, db.ForeignKey("cash_accounts.id"),
                           nullable=True, index=True)
    shift_id = db.Column(db.Integer, db.ForeignKey("cashier_shifts.id"),
                         nullable=True, index=True)
    # A deposit taken for a stay says which one, so the stay's screen can
    # show what the family put down against what the stay has come to.
    admission_id = db.Column(db.Integer, db.ForeignKey("admissions.id"),
                             nullable=True, index=True)
    # For ``applied``: the bill and the payment on it.
    invoice_id = db.Column(db.Integer, db.ForeignKey("invoices.id"),
                           nullable=True, index=True)
    payment_id = db.Column(db.Integer, db.ForeignKey("payments.id"),
                           nullable=True)
    note = db.Column(db.String(200))
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False,
                           index=True)

    patient = db.relationship("Patient")
    account = db.relationship("CashAccount")
    invoice = db.relationship("Invoice")
    admission = db.relationship("Admission")
    creator = db.relationship("User")

    @property
    def signed(self):
        """+ for money in, − for money used or handed back."""
        return round((self.amount or 0) * (1 if self.kind == "in" else -1), 2)

    def __repr__(self):
        return f"<PatientCredit {self.kind} {self.amount} p={self.patient_id}>"
