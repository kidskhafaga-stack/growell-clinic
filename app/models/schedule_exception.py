"""Doctor schedule exceptions: time off, holidays and one-off breaks.

A working week is described by :class:`DoctorSchedule` rows. Real clinics also
need to *remove* availability for specific dates — a vacation day, a public
holiday, or a short break within a working day. Each row here blocks
availability for one doctor on one date; slot generation subtracts them so the
booking screen never offers a slot the doctor cannot honour.
"""
from datetime import datetime

from app.extensions import db


class ScheduleException(db.Model):
    __tablename__ = "schedule_exceptions"

    id = db.Column(db.Integer, primary_key=True)
    doctor_id = db.Column(
        db.Integer, db.ForeignKey("users.id"), nullable=False, index=True
    )
    exc_date = db.Column(db.Date, nullable=False, index=True)

    # Full-day off (vacation/holiday) vs. a timed break within the day.
    is_full_day = db.Column(db.Boolean, default=True, nullable=False)
    start_time = db.Column(db.Time)   # used when not full-day
    end_time = db.Column(db.Time)     # used when not full-day

    reason = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    doctor = db.relationship("User", backref="schedule_exceptions")

    def blocks(self, slot_time):
        """True if this exception blocks the given ``time`` slot."""
        if self.is_full_day:
            return True
        if self.start_time and self.end_time:
            return self.start_time <= slot_time < self.end_time
        return False

    def __repr__(self):
        return f"<ScheduleException doc={self.doctor_id} {self.exc_date}>"
