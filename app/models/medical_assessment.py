"""The initial medical assessment on a stay — GAHAR ICD.06.

Ten elements, (a) to (j), *"performed within 24 hours of hospitalization"*
(ev. 3 — the standard's own number). Most of them are already somewhere in
the record: the reason for admission, the visit the child came up from, the
allergies and chronic illnesses on the file, the medicines at home, the
specialty's case history, the diagnosis on the visit. So this row holds only
what nothing else in the record could know — the same split as
``NursingAssessment``: the program assembles, a person writes the rest.

Allergies and past history are *not* columns here: they are facts about the
child, and writing them on the stay would make a second copy that drifts.
The form writes them to the child's file.
"""
from datetime import datetime

from app.extensions import db

#: The ten, in the standard's order.
ELEMENTS = ("complaint", "present_illness", "past_history", "allergies", "medications",
            "social", "family", "exam", "specialty", "provisional_dx")
#: Ev. 3 — the standard's own timeframe.
WITHIN_HOURS = 24


class MedicalAssessment(db.Model):
    __tablename__ = "medical_assessments"

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"), nullable=False, index=True)
    admission_id = db.Column(db.Integer, db.ForeignKey("admissions.id"), nullable=False, index=True)
    complaint = db.Column(db.Text)
    present_illness = db.Column(db.Text)
    medications = db.Column(db.Text)
    social = db.Column(db.Text)
    family = db.Column(db.Text)
    exam = db.Column(db.Text)
    specialty = db.Column(db.Text)
    provisional_dx = db.Column(db.Text)
    by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime)

    by = db.relationship("User", foreign_keys=[by_id])
