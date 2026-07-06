"""Patient satisfaction feedback — post-visit surveys and doctor ratings.

A ``Feedback`` row is created when a survey is sent (usually on visit
completion) and carries a public ``token``. The guardian opens a tokenised,
login-free page and submits star ratings + an optional comment; the row then
flips to ``submitted``. Doctor star roll-ups and CRM analytics read from here.
"""
import secrets
from datetime import datetime

from app.extensions import db

FEEDBACK_STATUSES = ["sent", "submitted"]


class Feedback(db.Model):
    __tablename__ = "feedback"

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"), nullable=True, index=True)
    visit_id = db.Column(db.Integer, db.ForeignKey("visits.id"), nullable=True, index=True)
    doctor_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    token = db.Column(db.String(32), unique=True, index=True, nullable=False)

    doctor_rating = db.Column(db.Integer)   # 1..5 stars for the doctor
    service_rating = db.Column(db.Integer)  # 1..5 stars for the service
    nps = db.Column(db.Integer)             # 0..10 "would you recommend us?"
    comment = db.Column(db.Text)

    status = db.Column(db.String(12), default="sent", nullable=False, index=True)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    submitted_at = db.Column(db.DateTime)

    patient = db.relationship("Patient")
    visit = db.relationship("Visit")
    doctor = db.relationship("User", foreign_keys=[doctor_id])
    creator = db.relationship("User", foreign_keys=[created_by])

    @staticmethod
    def new_token():
        return secrets.token_urlsafe(18)[:24]

    def __repr__(self):
        return f"<Feedback {self.token} {self.status}>"
