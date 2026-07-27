"""Counting a till, and what happens when it does not agree.

A balance the program computed is a claim. A stocktake is somebody checking
it against the world: notes counted by hand, an app opened, a statement read.
The two disagreeing is the only way a clinic ever finds out that money went
missing — which is why the difference is recorded as a fact of its own rather
than quietly folded into the balance.

**Counting and writing off are two acts, and they are deliberately split.**
Recording "I counted 4,700 and the program said 5,000" is something the person
holding the drawer does. Deciding that the missing 300 is now nobody's problem
is not: an adjustment entry is exactly how a shortage disappears, so it needs
``treasury_adjust`` — admin — and a reason in writing.

A count with a difference therefore sits **open** until somebody with that
authority explains it. A till that is 300 short every week and always written
off by the person who counted it is the situation this design exists to make
visible.
"""
from datetime import date, datetime

from app.extensions import db

COUNT_STATUSES = ["open", "adjusted", "accepted"]


class CashCount(db.Model):
    """One stocktake of one till: what was counted, and what was expected."""

    __tablename__ = "cash_counts"

    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey("cash_accounts.id"),
                           nullable=False, index=True)
    counted_on = db.Column(db.Date, default=date.today, nullable=False, index=True)
    # What the world says.
    counted = db.Column(db.Float, default=0, nullable=False)
    # What the program said at the moment of counting — frozen here on
    # purpose. Recomputing it later would silently change what the count
    # found, and a stocktake that changes after the fact is not a stocktake.
    expected = db.Column(db.Float, default=0, nullable=False)

    status = db.Column(db.String(10), default="open", nullable=False, index=True)
    note = db.Column(db.String(255))

    counted_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    # Who explained the difference, and why. Separate from counted_by because
    # they must be allowed to be different people.
    resolved_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    resolved_at = db.Column(db.DateTime)
    reason = db.Column(db.String(255))

    account = db.relationship("CashAccount")
    counter = db.relationship("User", foreign_keys=[counted_by])
    resolver = db.relationship("User", foreign_keys=[resolved_by])

    @property
    def difference(self):
        """Counted − expected. Negative is short, positive is over."""
        return round((self.counted or 0) - (self.expected or 0), 2)

    @property
    def is_short(self):
        return self.difference < 0

    @property
    def needs_explaining(self):
        """A difference nobody has accounted for yet."""
        return self.status == "open" and self.difference != 0

    def __repr__(self):
        return f"<CashCount till={self.account_id} diff={self.difference}>"
