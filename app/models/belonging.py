"""Patients' belongings, and lost and found — GAHAR PCC.14.

*"The patient's belongings are protected and recorded according to the
policy"* (ev. 4), the family *"is given information about the hospital's
responsibility for belongings"* (ev. 3), and *"lost and found items are
recorded, protected, and returned when possible"* (ev. 5).

Whether the hospital takes custody at all, and of what, is its policy (a). A
row here is what it did take: what, where it is kept, who received it, that
the family was told what the hospital is and is not responsible for, and who
it went back to. A found item waits for its owner for as long as the
hospital's policy says (e) — the program counts the days only once that
number is written.
"""
from datetime import datetime

from app.extensions import db


class Belonging(db.Model):
    __tablename__ = "belongings"

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"), nullable=False, index=True)
    admission_id = db.Column(db.Integer, db.ForeignKey("admissions.id"), index=True)
    items = db.Column(db.Text, nullable=False)
    kept_where = db.Column(db.String(160), nullable=False)
    family_told = db.Column(db.Boolean, default=False, nullable=False)
    received_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    returned_at = db.Column(db.DateTime)
    returned_to = db.Column(db.String(160))
    returned_by = db.Column(db.Integer, db.ForeignKey("users.id"))

    receiver = db.relationship("User", foreign_keys=[received_by])


class LostItem(db.Model):
    __tablename__ = "lost_items"

    id = db.Column(db.Integer, primary_key=True)
    found_at = db.Column(db.DateTime, nullable=False, index=True)
    found_where = db.Column(db.String(160), nullable=False)
    description = db.Column(db.String(255), nullable=False)
    kept_where = db.Column(db.String(160), nullable=False)
    found_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    returned_at = db.Column(db.DateTime)
    returned_to = db.Column(db.String(160))
    #: Past the hospital's holding time, what happened to it — and only then.
    closed_at = db.Column(db.DateTime)
    closed_note = db.Column(db.String(255))

    @property
    def is_open(self):
        return self.returned_at is None and self.closed_at is None
