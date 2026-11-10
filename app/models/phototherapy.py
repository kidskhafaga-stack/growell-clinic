"""Phototherapy for a baby in a bed (DOCTOR_EASE ٤-ج ح-٣).

The program already says when a bilirubin crosses this baby's own threshold
(``utils/jaundice``). This is the other half: when the light went on, what
kind, when it came off — and so how many hours. One row per session.
"""
from datetime import datetime

from app.extensions import db

KINDS = ("single", "double", "intensive", "blanket")


class PhotoSession(db.Model):
    __tablename__ = "photo_sessions"

    id = db.Column(db.Integer, primary_key=True)
    admission_id = db.Column(db.Integer, db.ForeignKey("admissions.id"),
                             nullable=False, index=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"),
                           nullable=False, index=True)
    kind = db.Column(db.String(12))
    started_at = db.Column(db.DateTime, nullable=False, index=True)
    started_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    stopped_at = db.Column(db.DateTime, index=True)
    stopped_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    note = db.Column(db.String(160))

    admission = db.relationship("Admission", backref="photo_sessions")

    @property
    def is_on(self):
        return self.stopped_at is None

    def hours(self, now=None):
        end = self.stopped_at or now or datetime.utcnow()
        return max((end - self.started_at).total_seconds() / 3600, 0)
