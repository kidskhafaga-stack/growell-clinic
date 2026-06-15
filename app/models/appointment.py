"""Appointment model and its status lifecycle.

Status flow (per the project plan):
    scheduled -> waiting -> in_progress -> completed
    scheduled/waiting -> no_show
    any (except completed) -> cancelled
"""
from datetime import datetime

from app.extensions import db

# Ordered for display; values are stored in the DB.
APPOINTMENT_STATUSES = [
    "scheduled",
    "waiting",
    "in_progress",
    "completed",
    "no_show",
    "cancelled",
]

# Statuses that occupy a time slot (block double-booking).
ACTIVE_STATUSES = {"scheduled", "waiting", "in_progress", "completed"}

# Allowed transitions for guarding status-change actions.
STATUS_TRANSITIONS = {
    "scheduled": {"waiting", "in_progress", "no_show", "cancelled"},
    "waiting": {"in_progress", "no_show", "cancelled"},
    "in_progress": {"completed", "waiting", "cancelled"},
    "completed": set(),
    "no_show": {"scheduled"},
    "cancelled": {"scheduled"},
}


class Appointment(db.Model):
    __tablename__ = "appointments"

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(
        db.Integer, db.ForeignKey("patients.id"), nullable=False, index=True
    )
    doctor_id = db.Column(
        db.Integer, db.ForeignKey("users.id"), nullable=False, index=True
    )

    appt_date = db.Column(db.Date, nullable=False, index=True)
    appt_time = db.Column(db.Time, nullable=False)
    duration_minutes = db.Column(db.Integer, default=15, nullable=False)

    reason = db.Column(db.String(200))
    status = db.Column(db.String(20), default="scheduled", nullable=False, index=True)
    notes = db.Column(db.Text)

    # Lifecycle timestamps.
    checked_in_at = db.Column(db.DateTime)
    started_at = db.Column(db.DateTime)
    completed_at = db.Column(db.DateTime)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    patient = db.relationship("Patient", backref="appointments")
    doctor = db.relationship("User", backref="appointments")

    def can_transition_to(self, new_status):
        return new_status in STATUS_TRANSITIONS.get(self.status, set())

    def apply_status(self, new_status):
        """Apply a status change and stamp the relevant lifecycle time."""
        self.status = new_status
        now = datetime.utcnow()
        if new_status == "waiting" and self.checked_in_at is None:
            self.checked_in_at = now
        elif new_status == "in_progress" and self.started_at is None:
            self.started_at = now
        elif new_status == "completed":
            self.completed_at = now

    @property
    def time_label(self):
        return self.appt_time.strftime("%H:%M") if self.appt_time else ""

    @staticmethod
    def valid_status(value):
        return value in APPOINTMENT_STATUSES

    def __repr__(self):
        return f"<Appointment {self.appt_date} {self.time_label} p={self.patient_id}>"
