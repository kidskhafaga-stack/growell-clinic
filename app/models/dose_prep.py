"""A day's doses, made up by the pharmacy for one child and one order.

**The half of clinical pharmacy that is work rather than opinion.** Reviewing
a chart is reading; this is a person standing at a bench making up what ward
four needs before the eight o'clock round — labelled per child, per drug, per
day. In most hospitals it is the larger half of the job, and the program had
nothing for it at all: a dose existed only at the moment a nurse recorded
giving it, so "is this child's amoxicillin ready?" had no answer anywhere.

**A day, not a dose.** Unit-dose supply is made up in daily batches: today's
six doses of one drug go up in one labelled bag. A row per individual dose
would be six rows nobody makes, six rows nobody ticks, and a screen that no
pharmacy would use twice.

**And the count comes from the doctor's own order**, never from anything this
program decides: six-hourly for a day is four, and that is arithmetic on what
was written rather than a judgement about what a child needs. A PRN order has
no count — there is no hour it is owed at — so it is supplied by agreement and
this program does not pretend to know how many.

**What is deliberately not here:** what to dilute an infusion in, to what
volume, over how long, and how long it is stable after mixing. Those are
clinical numbers and the rule that stopped this program inventing an alert
threshold stops it inventing these. A clinic that wants its own recipe on the
label writes it in ``instructions`` on the order, where a person wrote it.
"""
from datetime import datetime

from app.extensions import db


class DosePrep(db.Model):
    """One drug, one child, one day — made up and sent to the ward."""

    __tablename__ = "dose_preps"
    __table_args__ = (
        # One batch per order per day. Two would mean two answers to "is it
        # ready", and the ward would be told yes by whichever row was read
        # first while half the doses were still on the bench.
        db.UniqueConstraint("order_id", "for_date", name="uq_prep_day"),
    )

    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("medication_orders.id"),
                         nullable=False, index=True)
    admission_id = db.Column(db.Integer, db.ForeignKey("admissions.id"),
                             nullable=False, index=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"),
                           nullable=False, index=True)

    # **The clinic's date, not a UTC one.** A supply round is a day somebody
    # works through; for a Cairo clinic on a UTC server the first three hours
    # of every day belong to yesterday in UTC, and the eight o'clock batch
    # would be filed against the wrong day.
    for_date = db.Column(db.Date, nullable=False, index=True)

    # How many doses went into the bag, and how many units of stock that took.
    # Both stored: "four doses" is what the ward is owed and "eight ampoules"
    # is what left the shelf, and one cannot be worked back from the other
    # once somebody changes the order.
    doses = db.Column(db.Integer)
    units = db.Column(db.Integer)

    prepared_at = db.Column(db.DateTime, default=datetime.utcnow,
                            nullable=False, index=True)
    prepared_by = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)
    # What is written on the bag. Free text, and the only place a clinic's own
    # mixing instruction ever appears — this program never composes one.
    label = db.Column(db.String(255))
    note = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    order = db.relationship("MedicationOrder", backref="preps")
    admission = db.relationship("Admission")
    patient = db.relationship("Patient")
    by = db.relationship("User", foreign_keys=[prepared_by])

    def __repr__(self):
        return f"<DosePrep order={self.order_id} {self.for_date}>"
