"""Special care programmes — GAHAR CSS.06 (dialysis), CSS.07 (chemotherapy),
CSS.10 (rehabilitation).

All three standards ask for the same shape — *"assessment, plan of care,
and monitoring of progress are documented in the patient's medical record"*
— so one **enrolment** per child per programme carries the plan (the
dialysis modality and access, the chemotherapy protocol and its cycles, the
rehabilitation goals), the family's education (CSS.07 ev. 4, CSS.06 f) and,
for rehabilitation, the discharge plan (CSS.10 ev. 5); and each **session**
carries the check before it (pre-dialysis assessment, pre-chemotherapy
evaluation, the therapist's assessment), whether the person responsible
cleared it, what was seen during it, complications and what was done.

**Dialysis's viral markers** (CSS.06 ev. 5) are their own rows: the
interval is the hospital's, and a positive after a negative —
seroconversion — is shown, never decided.

Nothing clinical is chosen here: no protocol, no threshold, no interval.
"""
from datetime import datetime

from app.extensions import db

PROGRAMS = ("dialysis", "chemo", "rehab")
MARKERS = ("hbsag", "hcv", "hiv")
RESULTS = ("negative", "positive")


class ProgramEnrollment(db.Model):
    __tablename__ = "program_enrollments"

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"), nullable=False, index=True)
    program = db.Column(db.String(10), nullable=False, index=True)
    started_on = db.Column(db.Date, nullable=False)
    #: The plan, in the team's words — modality and access; protocol and
    #: cycles; goals.
    plan = db.Column(db.Text, nullable=False)
    #: Chemotherapy: how many cycles the protocol has, if it says.
    cycles = db.Column(db.Integer)
    educated_at = db.Column(db.DateTime)
    educated_whom = db.Column(db.String(120))
    discharge_plan = db.Column(db.Text)
    ended_on = db.Column(db.Date)
    by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    patient = db.relationship("Patient")
    sessions = db.relationship("ProgramSession", back_populates="enrollment",
                               order_by="ProgramSession.at.desc()", lazy="dynamic")

    @property
    def is_active(self):
        return self.ended_on is None


class ProgramSession(db.Model):
    __tablename__ = "program_sessions"

    id = db.Column(db.Integer, primary_key=True)
    enrollment_id = db.Column(db.Integer, db.ForeignKey("program_enrollments.id"), nullable=False, index=True)
    at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    cycle_no = db.Column(db.Integer)
    pre_check = db.Column(db.Text, nullable=False)
    #: The person responsible cleared the session after the check.
    cleared = db.Column(db.Boolean, nullable=False)
    during = db.Column(db.Text)
    complications = db.Column(db.String(255))
    action = db.Column(db.String(255))
    progress = db.Column(db.String(255))
    by_id = db.Column(db.Integer, db.ForeignKey("users.id"))

    enrollment = db.relationship("ProgramEnrollment", back_populates="sessions")
    by = db.relationship("User", foreign_keys=[by_id])


class ViralMarker(db.Model):
    __tablename__ = "viral_markers"

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"), nullable=False, index=True)
    taken_on = db.Column(db.Date, nullable=False)
    hbsag = db.Column(db.String(8))
    hcv = db.Column(db.String(8))
    hiv = db.Column(db.String(8))
    note = db.Column(db.String(255))
    by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
