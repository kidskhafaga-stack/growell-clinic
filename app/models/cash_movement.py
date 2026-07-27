"""Money moved on purpose: banked, drawn, transferred, settled.

Everything else that touches a till is a side-effect of something the clinic
was doing anyway — a patient paid, a supplier was settled, the electricity
bill went out. This is the other kind: money moved *because somebody decided
to move it*, from one of the clinic's own tills to another or to the outside
world.

Four of them, and they are one table because they are one act with a sign and
a direction:

* **deposit** — money put into a till from outside (an owner's injection, an
  opening float that arrived late);
* **withdraw** — money taken out to the outside world;
* **transfer** — one till to another. The reception drawer is banked at the
  end of the week; the safe tops the drawer up with change;
* **settle** — a ``clearing`` till clearing into the account it settles into.
  Card takings reaching the bank two days later, minus the processor's cut.

**Settlement is a transfer that loses money on the way**, and that is the
whole reason it is not just a transfer: the card machine takes 2.5%, so 1,000
leaves the clearing account and 975 arrives in the bank. The 25 is a cost, and
it has to be posted as one or the books stop balancing. A transfer with a fee
field would have made every ordinary transfer carry a fee it never has.
"""
from datetime import date, datetime

from app.extensions import db

CASH_MOVEMENT_KINDS = ["deposit", "withdraw", "transfer", "settle"]

# Movements that must name a destination till, and those that must not.
NEEDS_TARGET = ("transfer", "settle")


class CashMovement(db.Model):
    """One deliberate movement of money between tills, or in and out."""

    __tablename__ = "cash_movements"

    id = db.Column(db.Integer, primary_key=True)
    kind = db.Column(db.String(12), nullable=False, index=True)
    # The till the money leaves (withdraw/transfer/settle) or arrives in
    # (deposit). One column, because a movement always has a subject.
    account_id = db.Column(db.Integer, db.ForeignKey("cash_accounts.id"),
                           nullable=False, index=True)
    to_account_id = db.Column(db.Integer, db.ForeignKey("cash_accounts.id"),
                              nullable=True, index=True)
    # What left the source. The destination receives amount − fee.
    amount = db.Column(db.Float, default=0, nullable=False)
    fee = db.Column(db.Float, default=0, nullable=False)

    moved_on = db.Column(db.Date, default=date.today, nullable=False, index=True)
    reference = db.Column(db.String(80))
    notes = db.Column(db.String(255))
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    account = db.relationship("CashAccount", foreign_keys=[account_id])
    to_account = db.relationship("CashAccount", foreign_keys=[to_account_id])
    creator = db.relationship("User")

    @property
    def received(self):
        """What actually arrived at the other end."""
        return round((self.amount or 0) - (self.fee or 0), 2)

    def effect_on(self, account_id):
        """This movement's signed effect on one till.

        Asked per-till rather than stored as two rows, so a transfer cannot
        exist half-recorded: one row, and both sides read it.
        """
        out = 0.0
        if self.account_id == account_id:
            out += (self.amount or 0) if self.kind == "deposit" \
                else -(self.amount or 0)
        if self.to_account_id == account_id:
            out += self.received
        return round(out, 2)

    def __repr__(self):
        return f"<CashMovement {self.kind} {self.amount} from={self.account_id}>"
