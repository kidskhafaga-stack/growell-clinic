"""A multidisciplinary meeting about one child — GAHAR ACT.11.

*"Information exchange between multidisciplinary management teams describes
the patient's conditions and important findings and is recorded in the
patient's medical record"* (ev. 5), with clear responsibilities among the
treating team (b). So a meeting is: why it was called (a — the hospital's
criteria, in its words), who sat in it, what they looked at and found, what
they decided, and who does what. The family may or may not have been there,
and that is written too.
"""
from datetime import datetime

from app.extensions import db


class MdtMeeting(db.Model):
    __tablename__ = "mdt_meetings"

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"), nullable=False, index=True)
    admission_id = db.Column(db.Integer, db.ForeignKey("admissions.id"), index=True)
    held_at = db.Column(db.DateTime, nullable=False)
    reason = db.Column(db.String(255), nullable=False)
    attendees = db.Column(db.String(255), nullable=False)
    findings = db.Column(db.Text, nullable=False)
    decision = db.Column(db.Text, nullable=False)
    #: (b) who does what, as the meeting assigned it.
    responsibilities = db.Column(db.Text)
    family_present = db.Column(db.Boolean)
    by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    by = db.relationship("User", foreign_keys=[by_id])
