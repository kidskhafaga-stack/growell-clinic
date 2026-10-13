"""The family's questions — GAHAR PCC.05.

*"Systems are in place to capture questions that arise when healthcare
professionals are not present to answer them"*, and they are answered *"in a
timely manner, according to the hospital process"* (ev. 2).

A mother asks the night nurse when the doctor will say whether the scan was
clear. The nurse is not the one to answer, and by morning nobody remembers it
was asked. So the question is written on the stay — who asked, what, and for
whom — and stays open until somebody answers it. How long is too long is the
hospital's number; the standard's 24 hours is an example it gives, not a
rule, so the program sets none.
"""
from datetime import datetime

from app.extensions import db

FOR_WHOM = ("doctor", "nurse", "other")


class FamilyQuestion(db.Model):
    __tablename__ = "family_questions"

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"), nullable=False, index=True)
    admission_id = db.Column(db.Integer, db.ForeignKey("admissions.id"), nullable=False, index=True)
    asked_by = db.Column(db.String(120))
    question = db.Column(db.Text, nullable=False)
    for_whom = db.Column(db.String(8), nullable=False, default="doctor")
    asked_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    taken_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    answer = db.Column(db.Text)
    answered_at = db.Column(db.DateTime, index=True)
    answered_by = db.Column(db.Integer, db.ForeignKey("users.id"))

    taker = db.relationship("User", foreign_keys=[taken_by])
    answerer = db.relationship("User", foreign_keys=[answered_by])

    @property
    def is_open(self):
        return self.answered_at is None
