"""A clinical pharmacist looked at this child's chart, on this day.

**A row, not a derivation.** "Has anybody reviewed the drugs this child is
on?" cannot be worked out from the chart itself: a stay with no query on it
looks exactly like a stay nobody has opened, and those are opposite facts. The
same argument that made a ward round a ``RoundNote`` rather than a flag, and
an observation a reading rather than a tick.

**And it is per day, like the round.** A chart reviewed on Monday says nothing
about the drug that was started on Wednesday, so the question the board asks is
always *today's*: who is on the ward whose chart nobody has been through since
this morning.

The review carries what was found, not what was changed. Changing a dose is
the doctor's, and the pharmacist's half is the sentence that reaches them —
which is the query on the order itself, where the doctor is looking.
"""
from datetime import datetime

from app.extensions import db


class ChartReview(db.Model):
    """One clinical pharmacy review of one stay's drug chart."""

    __tablename__ = "chart_reviews"

    id = db.Column(db.Integer, primary_key=True)
    admission_id = db.Column(db.Integer, db.ForeignKey("admissions.id"),
                             nullable=False, index=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"),
                           nullable=False, index=True)

    # When it happened, not when it was typed — the same distinction the ward
    # round makes, and for the same reason: a pharmacist writing this up at
    # eleven reviewed the chart at nine.
    at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False,
                   index=True)
    by_id = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)

    # How many medicines were on the chart at the moment it was reviewed.
    #
    # Stored rather than counted later, because the chart moves: a review that
    # covered four drugs on Tuesday is not evidence about the six the child is
    # on today, and a screen that recomputed it would quietly claim it was.
    drugs_seen = db.Column(db.Integer)
    note = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    admission = db.relationship("Admission", backref="chart_reviews")
    patient = db.relationship("Patient")
    by = db.relationship("User", foreign_keys=[by_id])

    def __repr__(self):
        return f"<ChartReview stay={self.admission_id}>"
