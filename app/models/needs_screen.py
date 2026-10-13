"""Screening for further assessment needs — GAHAR ICD.08.

*"Patient's needs for further assessment are identified based on defined
screening processes"*, for five needs the intent names: nutritional,
functional, psychosocial, discharge needs, and victims of abuse and neglect.

Nutrition already has its own record (``NutritionAssessment``, ICD.13), so
this holds the other four. One row is one need screened on one stay: positive
or negative **as the nurse or doctor judged it by the hospital's criteria** —
the criteria are the hospital's words, written once in settings (b), and the
program scores nothing. A positive screen is referred to the service that
assesses it (d), and that service's finding is written back on the same row
(ev. 5). The timeframe (c) is the hospital's number too; until it is written
nothing is called late.
"""
from datetime import datetime

from app.extensions import db

FUNCTIONAL, PSYCHOSOCIAL, DISCHARGE, ABUSE = ("functional", "psychosocial", "discharge", "abuse")
KINDS = (FUNCTIONAL, PSYCHOSOCIAL, DISCHARGE, ABUSE)


class NeedsScreen(db.Model):
    __tablename__ = "needs_screens"

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"), nullable=False, index=True)
    admission_id = db.Column(db.Integer, db.ForeignKey("admissions.id"), nullable=False, index=True)
    kind = db.Column(db.String(14), nullable=False)
    positive = db.Column(db.Boolean, nullable=False)
    note = db.Column(db.String(255))
    #: (d) the service it was sent to — a dietitian, a physiotherapist, the
    #: social worker, the child-protection committee — in the hospital's words.
    referred_to = db.Column(db.String(160))
    referred_at = db.Column(db.DateTime)
    #: Ev. 5 — what the service found and did.
    seen_note = db.Column(db.String(255))
    seen_at = db.Column(db.DateTime)
    seen_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)

    by = db.relationship("User", foreign_keys=[by_id])
    seer = db.relationship("User", foreign_keys=[seen_by])

    @property
    def needs_referral(self):
        return self.positive and not self.referred_to

    @property
    def awaiting_service(self):
        return self.positive and bool(self.referred_to) and self.seen_at is None
