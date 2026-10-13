"""Staff certificates — a course a person holds, until when.

First for GAHAR CSS.01 ev. 3, *"At least one physician in each shift is
trained in advanced cardiac life support"*: which courses count is the
hospital's list (``utils/staff_certs.RESUS_SETTING``) — for a children's
hospital that is its own choice of PALS, NRP or ACLS — and the duty rota
says which critical-unit shift has nobody rostered holding one that is
valid on the day. The table is general on purpose: a course is a course,
and the workforce chapter asks for the same record of every licence.
"""
from datetime import datetime

from app.extensions import db


class StaffCertificate(db.Model):
    __tablename__ = "staff_certificates"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    course = db.Column(db.String(80), nullable=False, index=True)
    number = db.Column(db.String(80))
    issued_on = db.Column(db.Date)
    expires_on = db.Column(db.Date, index=True)
    note = db.Column(db.String(255))
    added_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    user = db.relationship("User", foreign_keys=[user_id])
