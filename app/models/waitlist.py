"""Appointment waiting list.

When a patient wants a slot that is full (or has no preference yet), staff add
them to the waiting list instead of losing the request. An entry records the
patient, an optional preferred doctor and a preferred date window. When a slot
frees up, staff promote the entry into a real appointment.
"""
from datetime import datetime

from app.extensions import db

WAITLIST_STATUSES = ["active", "booked", "cancelled"]


class WaitlistEntry(db.Model):
    __tablename__ = "waitlist_entries"

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(
        db.Integer, db.ForeignKey("patients.id"), nullable=False, index=True
    )
    # Optional preferred doctor (None = any doctor).
    doctor_id = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)

    preferred_from = db.Column(db.Date)   # earliest acceptable date
    preferred_to = db.Column(db.Date)     # latest acceptable date
    appt_type = db.Column(db.String(20))
    reason = db.Column(db.String(200))
    note = db.Column(db.String(200))

    status = db.Column(db.String(20), default="active", nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    # Set when promoted into a real appointment.
    appointment_id = db.Column(db.Integer, db.ForeignKey("appointments.id"))

    patient = db.relationship("Patient", backref="waitlist_entries")
    doctor = db.relationship("User", backref="waitlist_entries")

    def __repr__(self):
        return f"<WaitlistEntry p={self.patient_id} {self.status}>"
