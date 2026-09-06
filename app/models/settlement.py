"""The month closed with a doctor, written down and not recomputed.

**A running balance is not a settlement.** The program can already say what a
doctor has earned since the clinic opened and what has been handed to them,
and that is the right answer to *"where do we stand"*. It is the wrong answer
to the thing a clinic actually does at the end of a month: sit with somebody,
agree a figure, and pay it. Asked for in one line: *"وفى استشاري بيتحاسب اخر
الشهر"*.

The difference is that a settlement has to **stop moving**. A screen that
recomputes is honest and useless here: an invoice edited in October changes
what September's figure would have been, and a doctor who agreed 12,400 and
finds 12,150 next week stops trusting every number the program shows them. So
a closed statement carries its own figures, copied at the moment it closed,
and nothing afterwards touches them.

**Two bases, because two agreements exist.** Cash work is collected at the
desk the same hour, so billed and collected are the same number and the
distinction costs a single-doctor clinic nothing. Contract work is paid when
the insurer sends the money — *"التعاقد غالباً لما يتم التحصيل من الجهة"* —
and settling that at billing pays a doctor out of money the clinic has not
got. Which one applies is the agreement with that doctor, so it is a column
on them and not a rule in this file.

**And a period is settled once.** The database refuses a second statement
overlapping a closed one for the same doctor, for the reason the bed nights
have the same rule: two documents covering the same fortnight pay it twice,
and both of them look right on their own.
"""
from datetime import datetime

from app.extensions import db
from app.utils.clock import local_today

# Draft while it is being agreed, closed once the figure is fixed, paid when
# the money has gone. Three and not two: "we agreed 12,400" and "we handed
# over 12,400" are different facts, and a month can sit between them.
SETTLEMENT_STATUSES = ("draft", "closed", "paid")

# What the figure is made of. ``billed`` is everything earned in the period;
# ``collected`` is the part of it the clinic has actually been paid for.
SETTLEMENT_BASES = ("billed", "collected")
DEFAULT_BASIS = "billed"


class Settlement(db.Model):
    """One doctor's account for one period, agreed and frozen."""

    __tablename__ = "doctor_settlements"

    id = db.Column(db.Integer, primary_key=True)
    # Its identity on the paper both sides keep.
    number = db.Column(db.String(40), unique=True, index=True)
    doctor_id = db.Column(db.Integer, db.ForeignKey("users.id"),
                          nullable=False, index=True)
    date_from = db.Column(db.Date, nullable=False, index=True)
    date_to = db.Column(db.Date, nullable=False, index=True)
    basis = db.Column(db.String(10), default=DEFAULT_BASIS, nullable=False)
    status = db.Column(db.String(10), default="draft", nullable=False,
                       index=True)

    # --- the snapshot -------------------------------------------------------
    #
    # Copied when the statement is drawn and rewritten only while it is still a
    # draft. A closed statement is the figure two people agreed, and a figure
    # that moves after it was agreed is worse than no figure at all.
    lines_amount = db.Column(db.Float, default=0, nullable=False)
    vaccine_amount = db.Column(db.Float, default=0, nullable=False)
    duty_amount = db.Column(db.Float, default=0, nullable=False)
    gross_amount = db.Column(db.Float, default=0, nullable=False)
    # What was already handed over inside the period — advances, a mid-month
    # payment. Subtracted rather than ignored, or the month is paid twice.
    advances = db.Column(db.Float, default=0, nullable=False)
    net_due = db.Column(db.Float, default=0, nullable=False)
    # On a collected statement, what is still out. Carried on the paper
    # because it is the sentence the doctor asks about: "and the rest?"
    awaiting = db.Column(db.Float, default=0, nullable=False)

    note = db.Column(db.String(255))
    closed_at = db.Column(db.DateTime)
    closed_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    paid_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"))

    doctor = db.relationship("User", foreign_keys=[doctor_id])

    @property
    def is_open(self):
        return self.status == "draft"

    @property
    def covers(self):
        """``(from, to)`` — the days this statement answers for."""
        return (self.date_from, self.date_to)

    def overlaps(self, date_from, date_to):
        """Whether this statement shares a day with that period."""
        if not date_from or not date_to:
            return False
        return self.date_from <= date_to and date_from <= self.date_to

    def __repr__(self):
        return f"<Settlement {self.number} {self.doctor_id} {self.status}>"


def next_number(on_date=None):
    """Serial statement number: STL-2026-000001, per year.

    The same shape the invoices and the claims use, and generated rather than
    typed for the same reason: two statements carrying one number is a mess
    with no clean fix once somebody has printed them both.
    """
    on_date = on_date or local_today()
    prefix = f"STL-{on_date.year}-"
    top = 0
    rows = (Settlement.query
            .filter(Settlement.number.like(prefix + "%"))
            .with_entities(Settlement.number).all())
    for (number,) in rows:
        tail = (number or "")[len(prefix):]
        if tail.isdigit():
            top = max(top, int(tail))
    return f"{prefix}{top + 1:06d}"
