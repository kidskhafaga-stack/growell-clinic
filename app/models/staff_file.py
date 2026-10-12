"""The staff file — GAHAR WFM.04–09, WFM.13, WFM.14.

WFM.06 lists what a staff file holds (b i–vii), and each has its own row
here:

* **credentials** (i, iii; WFM.05) — licence, degree, registration, each
  with its number, its expiry, and the **primary-source verification**: who
  verified it, when, and against what source;
* **jobs** (ii, iv; WFM.04) — the work history here, each with its job
  description and when the staff member signed it;
* **orientation** (v; WFM.07) — general, departmental and job-specific,
  each completed on a date;
* **education** (vi; WFM.08) — continuing education and in-service
  training;
* **evaluations** (vii; WFM.09, WFM.13, WFM.14) — provisional, annual, the
  medical staff's ongoing professional practice evaluation, and peer
  review: the result, the employee's feedback, and the action taken.

Confidential (WFM.06 ev. 3): the screens are the admin's.
"""
from datetime import datetime

from app.extensions import db

CREDENTIAL_KINDS = ("licence", "degree", "registration", "other")
ORIENTATION_LEVELS = ("general", "department", "job")
EVALUATION_KINDS = ("provisional", "annual", "oppe", "peer_review")


class StaffCredential(db.Model):
    __tablename__ = "staff_credentials"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    kind = db.Column(db.String(14), nullable=False)
    title = db.Column(db.String(160), nullable=False)
    number = db.Column(db.String(80))
    issuer = db.Column(db.String(160))
    issued_on = db.Column(db.Date)
    expires_on = db.Column(db.Date, index=True)
    verified_at = db.Column(db.DateTime)
    verified_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    verification_source = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class StaffJob(db.Model):
    __tablename__ = "staff_jobs"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    title = db.Column(db.String(120), nullable=False)
    department = db.Column(db.String(120))
    started_on = db.Column(db.Date, nullable=False)
    ended_on = db.Column(db.Date)
    job_description = db.Column(db.Text)
    jd_signed_on = db.Column(db.Date)


class StaffOrientation(db.Model):
    __tablename__ = "staff_orientations"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    level = db.Column(db.String(10), nullable=False)
    completed_on = db.Column(db.Date, nullable=False)
    note = db.Column(db.String(255))


class StaffEducation(db.Model):
    __tablename__ = "staff_education"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    title = db.Column(db.String(200), nullable=False)
    on = db.Column("held_on", db.Date, nullable=False)
    hours = db.Column(db.Float)
    provider = db.Column(db.String(160))


class StaffEvaluation(db.Model):
    __tablename__ = "staff_evaluations"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    kind = db.Column(db.String(12), nullable=False)
    on = db.Column("done_on", db.Date, nullable=False)
    evaluator = db.Column(db.String(120), nullable=False)
    result = db.Column(db.Text, nullable=False)
    feedback = db.Column(db.Text)
    actions = db.Column(db.Text)
