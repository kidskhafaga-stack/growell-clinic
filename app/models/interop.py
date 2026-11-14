"""Who may read a child's record over the FHIR interface (``utils/fhir_api``).

A **receiver** is one outside system — a hospital the clinic refers to, an
insurer, a national registry — with its own key. A receiver reads **only the
children somebody at the clinic shared with it**, one by one from the child's
file, each share with an end date. Nothing is shared by default, and the
whole interface is off until an administrator turns it on.
"""
from datetime import datetime

from app.extensions import db

#: What a receiver may take: the International Patient Summary only, or the
#: whole record as well.
SCOPES = ("summary", "full")


class FhirReceiver(db.Model):
    __tablename__ = "fhir_receivers"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    purpose = db.Column(db.String(255))
    scope = db.Column(db.String(10), nullable=False, default="summary")
    # Only the key's SHA-256 is kept; the key itself is shown once, when made.
    key_hash = db.Column(db.String(64), nullable=False, unique=True, index=True)
    key_hint = db.Column(db.String(8))
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    revoked_at = db.Column(db.DateTime)
    revoked_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    last_used_at = db.Column(db.DateTime)

    creator = db.relationship("User", foreign_keys=[created_by])

    @property
    def is_active(self):
        return self.revoked_at is None

    def __repr__(self):
        return f"<FhirReceiver {self.name}>"


class FhirShare(db.Model):
    """One child shared with one receiver, until a date."""

    __tablename__ = "fhir_shares"

    id = db.Column(db.Integer, primary_key=True)
    receiver_id = db.Column(db.Integer, db.ForeignKey("fhir_receivers.id"),
                            nullable=False, index=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"),
                           nullable=False, index=True)
    shared_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    shared_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    until = db.Column(db.DateTime, nullable=False)
    reason = db.Column(db.String(255))
    revoked_at = db.Column(db.DateTime)
    revoked_by = db.Column(db.Integer, db.ForeignKey("users.id"))

    receiver = db.relationship("FhirReceiver")
    patient = db.relationship("Patient")
    sharer = db.relationship("User", foreign_keys=[shared_by])

    def open_at(self, moment):
        return self.revoked_at is None and self.until > moment

    def __repr__(self):
        return f"<FhirShare r{self.receiver_id} p{self.patient_id}>"
