"""Growth measurement point.

Created automatically from a visit's vital signs (and later, manually) so the
growth charts in Phase 5 have a single time series to plot. Percentile/Z-score
columns are reserved for Phase 5.
"""
from datetime import datetime

from app.extensions import db
from app.utils.clock import local_today


class GrowthRecord(db.Model):
    __tablename__ = "growth_records"

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(
        db.Integer, db.ForeignKey("patients.id"), nullable=False, index=True
    )
    visit_id = db.Column(db.Integer, db.ForeignKey("visits.id"), nullable=True)

    record_date = db.Column(db.Date, nullable=False, default=local_today)
    weight_kg = db.Column(db.Float)
    height_cm = db.Column(db.Float)
    head_circ_cm = db.Column(db.Float)
    bmi = db.Column(db.Float)
    source = db.Column(db.String(20), default="visit", nullable=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    patient = db.relationship("Patient", backref="growth_records")
    visit = db.relationship("Visit", backref="growth_records")

    def __repr__(self):
        return f"<GrowthRecord p={self.patient_id} {self.record_date}>"
