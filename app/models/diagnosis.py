"""Diagnosis attached to a visit (ICD-10/11).

The chosen code and title are stored as a snapshot so the record stays stable
even if the reference list changes. ``dx_type`` distinguishes working /
secondary / final diagnoses per the project plan.
"""
from datetime import datetime

from app.extensions import db

DIAGNOSIS_TYPES = ["working", "secondary", "final"]
ICD_VERSIONS = ["10", "11"]


class Diagnosis(db.Model):
    __tablename__ = "diagnoses"

    id = db.Column(db.Integer, primary_key=True)
    visit_id = db.Column(db.Integer, db.ForeignKey("visits.id"), nullable=False, index=True)

    code = db.Column(db.String(20))
    title = db.Column(db.String(255), nullable=False)
    icd_version = db.Column(db.String(2), default="10", nullable=False)
    dx_type = db.Column(db.String(20), default="working", nullable=False)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    visit = db.relationship("Visit", back_populates="diagnoses")

    @staticmethod
    def valid_type(value):
        return value in DIAGNOSIS_TYPES

    @staticmethod
    def valid_version(value):
        return value in ICD_VERSIONS

    def __repr__(self):
        return f"<Diagnosis {self.code} {self.dx_type}>"
