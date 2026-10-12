"""Expressed breast milk — GAHAR IPC.20 (h), *"Safe handling and storage of
expressed breast milk and formula"*.

A bag is one baby's: labelled with the baby, when it was expressed and where
it is kept, and given only to that baby before it expires. The commonest
harm is the wrong baby's milk, so giving checks the bag against the baby on
whose page it is being given and refuses another baby's bag outright.

How long milk keeps — in the fridge, the freezer, once thawed — is the
hospital's policy (`utils/breast_milk.HOURS_SETTINGS`); until it is written
the nurse writes the expiry on each bag, and the program invents none.
"""
from datetime import datetime

from app.extensions import db

STORAGES = ("fridge", "freezer", "thawed")
STATUSES = ("stored", "given", "discarded")


class MilkBag(db.Model):
    __tablename__ = "milk_bags"

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"), nullable=False, index=True)
    admission_id = db.Column(db.Integer, db.ForeignKey("admissions.id"), index=True)
    expressed_at = db.Column(db.DateTime, nullable=False)
    received_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    received_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    storage = db.Column(db.String(8), nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False, index=True)
    volume_ml = db.Column(db.Float)
    note = db.Column(db.String(255))
    status = db.Column(db.String(10), default="stored", nullable=False, index=True)
    given_at = db.Column(db.DateTime)
    given_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    #: The second person who checked the bag against the baby, if the
    #: hospital asks for one — as they signed.
    second_check = db.Column(db.String(120))
    discarded_at = db.Column(db.DateTime)
    discard_reason = db.Column(db.String(160))

    patient = db.relationship("Patient")
    receiver = db.relationship("User", foreign_keys=[received_by])
    giver = db.relationship("User", foreign_keys=[given_by])

    @property
    def code(self):
        return f"EBM{self.id:06d}"
