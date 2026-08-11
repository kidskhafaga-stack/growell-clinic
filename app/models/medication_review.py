"""The decision taken about a medicine at an encounter.

The last open piece of GAHAR's medication reconciliation. The clinic already
had the two halves either side of it: a list of what the child is on
(``PatientMedication``), and a "continue" button on the prescription writer
that copies a past line into today's. What was missing is the thing the
standard actually asks for — that at an encounter **every medicine on the list
was looked at, and the decision was written down**.

"Continue" alone cannot satisfy that, for a reason worth stating: it records
only the drugs somebody chose to carry forward. A medicine deliberately
stopped, and a medicine nobody looked at, leave exactly the same trace —
nothing. Reconciliation is the claim that the whole list was reviewed, and a
claim like that needs a row per decision, including the boring ones.

**Continue is a decision.** It is tempting to store only stops and changes,
since those alter something. But then a reviewed list and an ignored list are
again indistinguishable, and the document says nothing.

**The row is the record of a review, not the state of the drug.** Whether the
child is still on something lives on ``PatientMedication`` and nowhere else. A
review says what was decided on a day, by whom — history, which stays true
even after the drug is stopped by somebody else next month.
"""
from datetime import datetime

from app.extensions import db
from app.utils.clock import local_today

# Continue unchanged, stop, or change the dose/frequency. Deliberately three
# and not more: a longer list is a form somebody skips.
REVIEW_DECISIONS = ["continue", "stop", "modify"]


class MedicationReview(db.Model):
    __tablename__ = "medication_reviews"

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"),
                           nullable=False, index=True)
    medication_id = db.Column(db.Integer,
                              db.ForeignKey("patient_medications.id"),
                              nullable=False, index=True)
    # The encounter it happened at. Nullable because a medicine can be
    # reviewed from the patient's file outside a visit, and a review with no
    # visit is still a review that happened.
    visit_id = db.Column(db.Integer, db.ForeignKey("visits.id"),
                         nullable=True, index=True)

    decision = db.Column(db.String(12), nullable=False)
    note = db.Column(db.String(200))

    reviewed_on = db.Column(db.Date, default=local_today, nullable=False)
    reviewed_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    patient = db.relationship("Patient")
    medication = db.relationship("PatientMedication", backref="reviews")
    visit = db.relationship("Visit")
    reviewer = db.relationship("User", foreign_keys=[reviewed_by])

    def __repr__(self):
        return f"<MedicationReview m={self.medication_id} {self.decision}>"
