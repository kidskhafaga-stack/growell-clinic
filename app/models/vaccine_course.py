"""A course of a vaccine given because something happened — rabies first.

Asked as: *«تطعيم داء الكلب ده مش المفروض بيتاخد لو حالة طلبته بجدول معين
مش جرعة واحدة»*, and decided: *«اكتب الاثنين والطبيب يحدد»*.

Rabies is not a schedule by age. It is given after a bite (or before, for a
child at risk), on a protocol counted in **days from the first dose**, and the
number of doses depends on the protocol and on whether the child had the
vaccine before — never on how old they are. Until this, the catalogue held it
as one dose at birth: the first needle finished the "course", the day-3 dose
was never due, and no reminder ever went.

So the doctor opens a course and picks its protocol
(``utils/vaccine_protocols``); the program dates every dose from day 0 and
from then on the child's file, the reminders and the register-wide sweep all
read the same dates. One open course per child and vaccine; a course is closed
with a reason (finished, or stopped by the doctor), never deleted.
"""
from datetime import datetime

from app.extensions import db


class VaccineCourse(db.Model):
    __tablename__ = "vaccine_courses"

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"),
                           nullable=False, index=True)
    vaccine_id = db.Column(db.Integer, db.ForeignKey("vaccines.id"),
                           nullable=False, index=True)
    # The protocol's key in ``utils/vaccine_protocols.PROTOCOLS``.
    protocol = db.Column(db.String(30), nullable=False)
    # The protocol as it was when the course opened (JSON: days, names, RIG).
    # The clinic can change its protocols later; a child half-way through a
    # course keeps the dates the doctor gave them.
    protocol_data = db.Column(db.Text)
    # Day 0. Moves to the first dose's real date once it is given, so a
    # course opened today and started tomorrow is dated from tomorrow.
    start_date = db.Column(db.Date, nullable=False)
    # The course's first dose number. A child bitten twice, years apart, has
    # the first course's doses on file already; the second is numbered after
    # them rather than colliding with them.
    first_dose_number = db.Column(db.Integer, default=1, nullable=False)
    # What the doctor answered when choosing. Recorded because the protocol
    # depends on it, and the next doctor needs to see why this one was chosen.
    previously_vaccinated = db.Column(db.Boolean)
    # WHO exposure category: "I" / "II" / "III", or empty (pre-exposure).
    exposure_category = db.Column(db.String(4))
    # Rabies immunoglobulin: "assess" (to be decided), "needed", "given",
    # "not_needed". The program does not decide it; it asks the question.
    rig = db.Column(db.String(12))
    rig_given_on = db.Column(db.Date)
    notes = db.Column(db.String(300))
    chosen_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    # Open while NULL. Closing is "finished" or "stopped" with the doctor's
    # reason — the animal stayed well, the family went elsewhere.
    closed_at = db.Column(db.DateTime)
    close_reason = db.Column(db.String(200))
    closed_by = db.Column(db.Integer, db.ForeignKey("users.id"))

    vaccine = db.relationship("Vaccine")
    patient = db.relationship("Patient")

    @property
    def is_open(self):
        return self.closed_at is None

    def __repr__(self):
        return f"<VaccineCourse p={self.patient_id} v={self.vaccine_id} {self.protocol}>"
