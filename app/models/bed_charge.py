"""One night in a bed, charged once.

**Why this is a table at all**, in a codebase whose rule is *المحسوب أحسن من
المتخزّن*: it does not store something derivable. How many nights a child has
been in is derivable, and is derived. **That the clinic has charged for a
given night is an event** — it happened, on a date, at a price, onto an
invoice — and an event that is recomputed rather than recorded is an event
that happens twice.

That is the whole design. The posting runs whenever anybody asks — on the
stay screen, at discharge, and in principle nightly — and it must be safe to
run four times on the same Tuesday. A unique index on (stay, date) is what
makes it safe, rather than a flag somebody has to remember to set.

**The price is a snapshot.** The service is linked *and* its price is copied
onto the row, for the reason every printed name in this program is
snapshotted: a price list edited in March must not silently rewrite what a
family was billed in February.

**The bed is recorded too**, because it answers the question a family asks
when they read the bill: *why is Tuesday more than Monday?* A child moved
into intensive care on Tuesday afternoon, and Tuesday night cost what
intensive care costs.

**A night is not the only unit.** Emergency is charged by the hour — a child
on a trolley for three hours who goes home has not spent a night anywhere,
and billing one is not a rounding difference, it is a bill for something that
did not happen. So the row carries how many of what: ``quantity`` and
``basis``. A ward night is ``1`` of ``night``; a four-hour emergency stay is
``4`` of ``hour``, on one row, written when the stay ends — because how many
hours it was is not known until then.
"""
from datetime import datetime

from app.extensions import db


class BedCharge(db.Model):
    """This stay, this night or these hours, billed on this invoice."""

    __tablename__ = "bed_charges"
    __table_args__ = (
        # The whole of the idempotence. Not a convention and not a check in
        # Python: two people pressing "post the nights" in the same second on
        # two screens is exactly how a family gets billed twice for a Tuesday,
        # and only the database can refuse that.
        db.UniqueConstraint("admission_id", "on_date",
                            name="uq_bed_charge_period"),
    )

    id = db.Column(db.Integer, primary_key=True)
    admission_id = db.Column(db.Integer, db.ForeignKey("admissions.id"),
                             nullable=False, index=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"),
                           nullable=False, index=True)

    # The **clinic's** calendar date, not a UTC one. A night is a thing a
    # family counts on a calendar, and for a Cairo clinic on a UTC server the
    # two disagree for the first three hours of every day — which would put a
    # child admitted at 1am on the previous night's bill.
    on_date = db.Column(db.Date, nullable=False, index=True)

    # How many of what. One night is (1, "night"); a four-hour stay in
    # emergency is (4, "hour"). Both on one row so the invoice line and the
    # audit trail say the same thing, and so that "was this date charged"
    # stays one question with one answer.
    quantity = db.Column(db.Integer, default=1, nullable=False)
    basis = db.Column(db.String(8), default="night", nullable=False)

    bed_id = db.Column(db.Integer, db.ForeignKey("care_beds.id"), nullable=True)
    service_id = db.Column(db.Integer, db.ForeignKey("services.id"),
                           nullable=True)
    unit_price = db.Column(db.Float, default=0, nullable=False)

    invoice_item_id = db.Column(db.Integer, db.ForeignKey("invoice_items.id"),
                                nullable=True, index=True)
    posted_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow,
                           nullable=False)

    admission = db.relationship("Admission", backref="bed_charges")
    bed = db.relationship("Bed")
    service = db.relationship("Service")
    invoice_item = db.relationship("InvoiceItem")

    @property
    def amount(self):
        return round((self.unit_price or 0) * (self.quantity or 1), 2)

    def __repr__(self):
        return (f"<BedCharge {self.on_date} x{self.quantity} "
                f"{self.basis} stay={self.admission_id}>")
