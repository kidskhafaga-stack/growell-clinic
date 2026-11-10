"""Apnoea, bradycardia and desaturation in a baby (DOCTOR_EASE ٤-ج ح-٢).

One row per episode the nurse saw: which of the three (any of them together),
how long, the lowest heart rate and saturation if read, and what brought the
baby back. The count is worked out from the rows; the program sets no limit.
"""
from datetime import datetime

from app.extensions import db

RECOVERIES = ("self", "stimulation", "oxygen", "bagging")


class NeonatalEvent(db.Model):
    __tablename__ = "neonatal_events"

    id = db.Column(db.Integer, primary_key=True)
    admission_id = db.Column(db.Integer, db.ForeignKey("admissions.id"),
                             nullable=False, index=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"),
                           nullable=False, index=True)
    at = db.Column(db.DateTime, nullable=False, index=True, default=datetime.utcnow)
    apnoea = db.Column(db.Boolean, default=False, nullable=False)
    brady = db.Column(db.Boolean, default=False, nullable=False)
    desat = db.Column(db.Boolean, default=False, nullable=False)
    seconds = db.Column(db.Integer)
    lowest_hr = db.Column(db.Integer)
    lowest_spo2 = db.Column(db.Integer)
    recovery = db.Column(db.String(12))
    note = db.Column(db.String(160))
    by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    recorded_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    admission = db.relationship("Admission", backref="neonatal_events")
    by = db.relationship("User", foreign_keys=[by_id])

    @property
    def label(self):
        """«A / B / D» — the three letters a nursery writes."""
        return " / ".join(x for x, on in (("A", self.apnoea), ("B", self.brady),
                                          ("D", self.desat)) if on)
