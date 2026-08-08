"""The consulting rooms, and which doctor is in which one today.

Called **عيادة** on every screen, never "غرفة" — in an Egyptian clinic the
room *is* the عيادة, and a receptionist told to look at "الغرفة" has to
translate the word before they can answer the question.

The important part of the design is what is **not** here: there is no
``clinic_room_id`` on the doctor. A doctor is not in the same عيادة every day
— they swap by shift, by who is on leave, by which عيادة has the nebuliser
that week — and a column on the doctor would hold only today's answer while
silently rewriting every day before it. Ask "who was in عيادة ٢ last Tuesday"
of such a column and it lies.

So the assignment is a row per day: **(date, doctor) → عيادة**. Yesterday's
row keeps yesterday's truth, one عيادة can hold two doctors on two shifts of
the same day, and a day with no row simply has no assignment — which is the
honest answer for a clinic that never bothered to record one.
"""
from datetime import datetime

from app.extensions import db


class ClinicRoom(db.Model):
    """One consulting عيادة."""

    __tablename__ = "clinic_rooms"

    id = db.Column(db.Integer, primary_key=True)
    # Generated, never typed — the clinic's own rule for everything the
    # program creates. A name is optional on top of it ("عيادة الحضّانة").
    code = db.Column(db.Integer, nullable=False, index=True)
    name_ar = db.Column(db.String(60))
    name_en = db.Column(db.String(60))
    sort_order = db.Column(db.Integer, default=0, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    assignments = db.relationship(
        "RoomAssignment", back_populates="room", cascade="all, delete-orphan")

    def display_name(self, lang="ar"):
        name = (self.name_en if lang == "en" else self.name_ar) or ""
        if name.strip():
            return name.strip()
        return f"Clinic {self.code}" if lang == "en" else f"عيادة {self.code}"

    @staticmethod
    def next_code():
        """The lowest free number, so deleting عيادة ٢ lets the next one reuse
        it rather than climbing forever past gaps nobody can explain."""
        taken = {row.code for row in ClinicRoom.query.all()}
        code = 1
        while code in taken:
            code += 1
        return code

    def __repr__(self):
        return f"<ClinicRoom {self.code}>"


class RoomAssignment(db.Model):
    """Which عيادة a doctor is working in on one specific day."""

    __tablename__ = "room_assignments"
    __table_args__ = (
        # One عيادة per doctor per day. Two rows for the same doctor on the
        # same day is not a richer record, it is an unanswerable question.
        db.UniqueConstraint("on_date", "doctor_id", name="uq_room_day_doctor"),
    )

    id = db.Column(db.Integer, primary_key=True)
    on_date = db.Column(db.Date, nullable=False, index=True)
    doctor_id = db.Column(db.Integer, db.ForeignKey("users.id"),
                          nullable=False, index=True)
    room_id = db.Column(db.Integer, db.ForeignKey("clinic_rooms.id"),
                        nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    doctor = db.relationship("User")
    room = db.relationship("ClinicRoom", back_populates="assignments")

    def __repr__(self):
        return f"<RoomAssignment {self.on_date} d={self.doctor_id} r={self.room_id}>"
