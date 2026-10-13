"""Telemedicine — GAHAR ACT.16.

A remote encounter between a doctor and a family, by video, phone or
message. The standard asks for the triage that decides whether a child is
eligible for it at all (i), *"verifying and documenting patient/provider
identities and physical locations for each telemedicine encounter"* (g), the
platform used (b), and *"periodical evaluation of telemedicine services based
on quality indicators"* (l).

So an encounter is refused a start until somebody has written how the
child's identity was checked and where both ends are. Starting it opens an
ordinary visit, on its own channel, so the examination, the diagnosis and
any prescription are written on the visit screen every doctor already uses
and the encounter sits in the child's file like any other. The eligibility
criteria and the platforms are the hospital's, in its words.
"""
from datetime import datetime

from app.extensions import db

MODALITIES = ("video", "phone", "message")
OUTCOMES = ("advice", "prescription", "investigation", "in_person", "emergency")
#: ``Visit.channel`` for an encounter that happened this way.
CHANNEL = "tele"


class TeleEncounter(db.Model):
    __tablename__ = "tele_encounters"

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"), nullable=False, index=True)
    requested_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    reason = db.Column(db.String(255), nullable=False)
    modality = db.Column(db.String(8), nullable=False, default="video")
    #: (i) by the hospital's criteria — eligible, or not and what the family
    #: was told to do instead.
    eligible = db.Column(db.Boolean, nullable=False, default=True)
    not_eligible_note = db.Column(db.String(255))
    doctor_id = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)
    scheduled_for = db.Column(db.DateTime, index=True)
    platform = db.Column(db.String(80))
    #: (g) how the child's identity was checked — which two identifiers.
    identity_how = db.Column(db.String(160))
    patient_location = db.Column(db.String(160))
    doctor_location = db.Column(db.String(160))
    started_at = db.Column(db.DateTime)
    ended_at = db.Column(db.DateTime)
    outcome = db.Column(db.String(14))
    note = db.Column(db.Text)
    visit_id = db.Column(db.Integer, db.ForeignKey("visits.id"))
    cancelled_at = db.Column(db.DateTime)
    by_id = db.Column(db.Integer, db.ForeignKey("users.id"))

    patient = db.relationship("Patient")
    doctor = db.relationship("User", foreign_keys=[doctor_id])

    @property
    def state(self):
        if self.cancelled_at:
            return "cancelled"
        if not self.eligible:
            return "not_eligible"
        if self.ended_at:
            return "done"
        if self.started_at:
            return "running"
        return "waiting"

    @property
    def minutes(self):
        if self.started_at and self.ended_at:
            return int((self.ended_at - self.started_at).total_seconds() // 60)
        return None


class TeleReview(db.Model):
    """(l) the periodic evaluation — the period's figures, and what the
    director made of them."""
    __tablename__ = "tele_reviews"

    id = db.Column(db.Integer, primary_key=True)
    period_from = db.Column(db.Date, nullable=False)
    period_to = db.Column(db.Date, nullable=False)
    text = db.Column(db.Text, nullable=False)
    by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    by = db.relationship("User", foreign_keys=[by_id])
