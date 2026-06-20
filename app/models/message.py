"""Outgoing message log (WhatsApp).

Every WhatsApp message the system prepares is recorded here — whether it was
sent through a provider API or rendered as a click-to-send ``wa.me`` link.
This gives a clear audit trail and lets the UI surface pending links.
"""
from datetime import datetime

from app.extensions import db

# link  = a wa.me click-to-send link was produced (WhatsApp Web)
# sent  = handed to a provider API successfully
# failed/queued = self-explanatory
MESSAGE_STATUSES = ["queued", "link", "sent", "failed"]


class MessageLog(db.Model):
    __tablename__ = "message_logs"

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"), nullable=True, index=True)
    appointment_id = db.Column(db.Integer, db.ForeignKey("appointments.id"), nullable=True)
    to_phone = db.Column(db.String(30))
    body = db.Column(db.Text, nullable=False)
    provider = db.Column(db.String(20))
    status = db.Column(db.String(12), default="queued", nullable=False)
    link = db.Column(db.Text)
    error = db.Column(db.String(200))
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)

    patient = db.relationship("Patient")
    creator = db.relationship("User")

    def __repr__(self):
        return f"<MessageLog to={self.to_phone} {self.status}>"
