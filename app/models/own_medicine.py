"""Medicines a child brought in from home — GAHAR MMS.09 ev. 5,
*"Medications brought by patients are received, identified, labeled,
stored, and administered safely."*

Not the home list: that is what the child is *on* (``PatientMedication``,
and the reconciliation that decides about each). This is the bag the family
handed over at the bedside — what is in it, who received it, whether
somebody identified it, what was decided (used on the ward under an order,
kept aside, sent home, destroyed), and to whom it went back. A bag still
held by the ward on a closed stay is shown, because somebody's medicine is
still in a cupboard.
"""
from datetime import datetime

from app.extensions import db

DECISIONS = ("use", "keep", "home", "destroy")


class OwnMedicine(db.Model):
    __tablename__ = "own_medicines"

    id = db.Column(db.Integer, primary_key=True)
    admission_id = db.Column(db.Integer, db.ForeignKey("admissions.id"), nullable=False, index=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"), nullable=False, index=True)
    name = db.Column(db.String(160), nullable=False)
    quantity = db.Column(db.String(60))
    expiry = db.Column(db.String(20))
    received_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    received_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    #: Somebody looked at it and it is what the box says.
    identified_at = db.Column(db.DateTime)
    identified_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    decision = db.Column(db.String(8))
    note = db.Column(db.String(255))
    #: Out of the ward: handed back (to whom) or destroyed.
    out_at = db.Column(db.DateTime)
    out_to = db.Column(db.String(120))
    out_by = db.Column(db.Integer, db.ForeignKey("users.id"))

    patient = db.relationship("Patient")
    receiver = db.relationship("User", foreign_keys=[received_by])
    identifier = db.relationship("User", foreign_keys=[identified_by])

    @property
    def held(self):
        return self.out_at is None
