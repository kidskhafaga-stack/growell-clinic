"""Doctor working-hours schedule.

Each row is a working window for a doctor on a given weekday. A doctor may
have several windows per day (e.g. a morning and an evening shift). Slot
generation for smart booking reads these windows.
"""
from datetime import datetime, timedelta

from app.extensions import db

# Weekday convention follows Python's date.weekday(): Monday=0 .. Sunday=6.
# Display order starts on Saturday to match the Egyptian working week.
WEEKDAY_ORDER = [5, 6, 0, 1, 2, 3, 4]


class DoctorSchedule(db.Model):
    __tablename__ = "doctor_schedules"

    id = db.Column(db.Integer, primary_key=True)
    doctor_id = db.Column(
        db.Integer, db.ForeignKey("users.id"), nullable=False, index=True
    )
    weekday = db.Column(db.Integer, nullable=False)  # 0=Mon .. 6=Sun
    start_time = db.Column(db.Time, nullable=False)
    end_time = db.Column(db.Time, nullable=False)
    slot_minutes = db.Column(db.Integer, default=15, nullable=False)
    max_patients = db.Column(db.Integer)  # optional daily cap
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    doctor = db.relationship("User", backref="schedules")

    def iter_slots(self):
        """Yield ``time`` objects from start to end stepped by slot length."""
        anchor = datetime.combine(datetime.today(), self.start_time)
        end = datetime.combine(datetime.today(), self.end_time)
        step = timedelta(minutes=self.slot_minutes or 15)
        while anchor < end:
            yield anchor.time()
            anchor += step

    def __repr__(self):
        return f"<DoctorSchedule doc={self.doctor_id} wd={self.weekday}>"
