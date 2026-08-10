"""What a child is already on, when they walk in.

The clinic has carried ``chronic_diseases`` as free text for a long time — the
asthma, the epilepsy, the diabetes. It never carried the **medicines**, and
those are the half that interacts with what the doctor is about to write.

The concrete failure this closes: the interaction check reads the drugs in the
prescription being written and nothing else. A child on carbamazepine for
epilepsy who is handed a macrolide for a chest infection is a real interaction,
and the program had no way to see it, because the carbamazepine was never in
the list — it was written months ago by somebody else and lives in a paragraph
of free text if it lives anywhere.

**Started and stopped, never deleted.** A medicine the child was on last year
is not the same statement as a medicine they were never on: the first explains
a rash, a level, a previous decision. So stopping writes a date and a name, and
the row stays. Anybody can add one; the screen records who, because "the mother
says he takes something white" and "the neurologist's letter says 200mg twice a
day" are not the same evidence and the next doctor deserves to know which.

The ingredient link is the part that does the work. Free text is accepted
because a parent's memory is often all there is, but a row with a
``generic_id`` is one the safety check can actually reason about.
"""
from datetime import datetime

from app.extensions import db
from app.utils.clock import local_today


class PatientMedication(db.Model):
    __tablename__ = "patient_medications"

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"),
                           nullable=False, index=True)

    # What it is. ``name`` is always set — it is what a person reads — while
    # the two links are what the program can reason about, and are often null
    # because a parent named a colour and a shape.
    name = db.Column(db.String(160), nullable=False)
    drug_id = db.Column(db.Integer, db.ForeignKey("drugs.id"), nullable=True)
    generic_id = db.Column(db.Integer, db.ForeignKey("generic_drugs.id"),
                           nullable=True, index=True)

    dose = db.Column(db.String(80))
    frequency = db.Column(db.String(80))
    # Why they are on it — "صرع", "ربو". Not the same as the diagnosis of
    # today's visit, and the reason a later doctor leaves it alone.
    reason = db.Column(db.String(160))
    notes = db.Column(db.Text)

    started_on = db.Column(db.Date, default=local_today)
    stopped_on = db.Column(db.Date)
    stop_reason = db.Column(db.String(200))

    added_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    stopped_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    patient = db.relationship("Patient", backref="medications")
    drug = db.relationship("Drug", foreign_keys=[drug_id])
    generic = db.relationship("GenericDrug", foreign_keys=[generic_id])
    adder = db.relationship("User", foreign_keys=[added_by])
    stopper = db.relationship("User", foreign_keys=[stopped_by])

    @property
    def is_current(self):
        """Still being taken. A stop date is the only thing that ends it."""
        return self.stopped_on is None

    def label(self, lang="ar"):
        """Name with its dose, as a person would say it."""
        parts = [self.name]
        if self.dose:
            parts.append(self.dose)
        if self.frequency:
            parts.append(self.frequency)
        return " · ".join(p for p in parts if p)

    def __repr__(self):
        return f"<PatientMedication p={self.patient_id} {self.name}>"
