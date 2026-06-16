"""Vital signs captured during a visit."""
from app.extensions import db


class VitalSigns(db.Model):
    __tablename__ = "vital_signs"

    id = db.Column(db.Integer, primary_key=True)
    visit_id = db.Column(
        db.Integer, db.ForeignKey("visits.id"), unique=True, nullable=False
    )

    # Growth measurements (also mirrored into growth_records).
    weight_kg = db.Column(db.Float)
    height_cm = db.Column(db.Float)
    head_circ_cm = db.Column(db.Float)

    # Other vitals.
    temperature_c = db.Column(db.Float)
    pulse_bpm = db.Column(db.Integer)
    resp_rate = db.Column(db.Integer)
    spo2 = db.Column(db.Integer)

    visit = db.relationship("Visit", back_populates="vitals")

    @property
    def bmi(self):
        """Body mass index from weight/height, or None if unavailable."""
        if self.weight_kg and self.height_cm:
            m = self.height_cm / 100.0
            if m > 0:
                return round(self.weight_kg / (m * m), 1)
        return None

    @property
    def has_growth(self):
        return any([self.weight_kg, self.height_cm, self.head_circ_cm])

    def __repr__(self):
        return f"<VitalSigns visit={self.visit_id}>"
