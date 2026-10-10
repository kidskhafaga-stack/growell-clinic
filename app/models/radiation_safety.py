"""The radiation safety program's records — GAHAR DAS.09 / GSR.12.

The patient's own dose is already on the order (``utils/radiation``, point
d). These are the rest of what evidence 4 and the intent ask to see:

* :class:`RadiationWorker` — who is monitored;
* :class:`DoseBadgeReading` — each period's TLD or film-badge report, as the
  reading service reported it;
* :class:`StaffBloodCount` — the CBC the standard asks for twice a year, and
  when a result is borderline, what further investigation was ordered;
* :class:`AreaMeasurement` — environmental radiation readings in an area;
* :class:`ApronCheck` — the lead apron inspection a surveyor asks for;
* :class:`MriScreening` — (f) the pre-exposure screening for metals, implants
  and devices before an MRI, against the hospital's own questions.

The limits are the hospital's, written in the program; without one, a
number is recorded and nothing is called over. Kept, never edited or
deleted.
"""
from datetime import datetime

from app.extensions import db

#: A CBC's reading, in the standard's own words: within range, borderline
#: (further investigation), or abnormal.
CBC_RESULTS = ("normal", "borderline", "abnormal")
APRON_RESULTS = ("pass", "fail")
MRI_OUTCOMES = ("cleared", "not_cleared")


class RadiationWorker(db.Model):
    __tablename__ = "radiation_workers"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False,
                        unique=True)
    area = db.Column(db.String(120))
    badge_number = db.Column(db.String(60))
    since = db.Column(db.Date)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    user = db.relationship("User")


class DoseBadgeReading(db.Model):
    __tablename__ = "dose_badge_readings"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False,
                        index=True)
    period_from = db.Column(db.Date, nullable=False)
    period_to = db.Column(db.Date, nullable=False, index=True)
    #: Millisievert, as the reading service reported it.
    dose_msv = db.Column(db.Float, nullable=False)
    reported_by = db.Column(db.String(160))
    #: Required when the reading is over the hospital's investigation level.
    action = db.Column(db.Text)
    recorded_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    recorded_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    user = db.relationship("User", foreign_keys=[user_id])


class StaffBloodCount(db.Model):
    __tablename__ = "staff_blood_counts"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False,
                        index=True)
    done_on = db.Column(db.Date, nullable=False, index=True)
    result = db.Column(db.String(12), nullable=False)
    note = db.Column(db.Text)
    #: The further investigation ordered — required unless the result is
    #: within range.
    action = db.Column(db.Text)
    recorded_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    recorded_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    user = db.relationship("User", foreign_keys=[user_id])


class AreaMeasurement(db.Model):
    __tablename__ = "radiation_area_measurements"

    id = db.Column(db.Integer, primary_key=True)
    area = db.Column(db.String(120), nullable=False, index=True)
    measured_on = db.Column(db.Date, nullable=False, index=True)
    #: Microsievert per hour, as the meter read.
    value_usv_h = db.Column(db.Float, nullable=False)
    #: The limit for this area in the hospital's program, written beside the
    #: reading — areas differ (a control room is not a corridor).
    limit_usv_h = db.Column(db.Float)
    action = db.Column(db.Text)
    measured_by = db.Column(db.String(160))
    recorded_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    recorded_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    @property
    def over(self):
        return self.limit_usv_h is not None and self.value_usv_h > self.limit_usv_h


class ApronCheck(db.Model):
    __tablename__ = "lead_apron_checks"

    id = db.Column(db.Integer, primary_key=True)
    apron = db.Column(db.String(80), nullable=False, index=True)
    checked_on = db.Column(db.Date, nullable=False, index=True)
    #: How it was checked, in the hospital's words (visual, fluoroscopy…).
    method = db.Column(db.String(120))
    result = db.Column(db.String(8), nullable=False)
    action = db.Column(db.Text)
    recorded_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    recorded_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class MriScreening(db.Model):
    __tablename__ = "mri_screenings"

    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("visit_investigations.id"),
                         nullable=False, index=True)
    #: ``[[question, "yes"|"no"], …]`` — the hospital's questions as they
    #: were asked that day, so a later edit of the list does not rewrite it.
    answers = db.Column(db.Text, nullable=False)
    outcome = db.Column(db.String(12), nullable=False)
    #: Required when any answer is yes: what was decided and by whom.
    decision = db.Column(db.Text)
    screened_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    screened_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    order = db.relationship("VisitInvestigation")
    screener = db.relationship("User")
