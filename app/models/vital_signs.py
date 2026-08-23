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

    # **Blood pressure, and it lives here rather than in a specialty panel.**
    #
    # Three of the survey's specialties asked for it — cardiology, endocrine
    # and nephrology — which is the argument against giving it to any of them.
    # It is a vital sign: the nurse measures it before the child goes in, with
    # the pulse and the temperature, and putting it on the cardiology panel
    # would mean a nephrologist typing it into a screen headed "cardiology" or
    # a second copy of it existing somewhere else.
    #
    # Which arm, because the survey asked for *"ضغط الدم الذراعان"* and it is
    # not a detail: a difference between the arms is the finding, in coarctation
    # especially, and a reading with no arm recorded cannot be compared with the
    # next one.
    bp_systolic = db.Column(db.Integer)
    bp_diastolic = db.Column(db.Integer)
    bp_arm = db.Column(db.String(10))          # right | left

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
    def blood_pressure(self):
        """``"110/70"`` or ``None`` — both halves or neither.

        A systolic with no diastolic is not half a reading, it is a typing
        accident, and showing it as one invites somebody to act on it.
        """
        if self.bp_systolic and self.bp_diastolic:
            return f"{self.bp_systolic}/{self.bp_diastolic}"
        return None

    @property
    def has_growth(self):
        return any([self.weight_kg, self.height_cm, self.head_circ_cm])

    def __repr__(self):
        return f"<VitalSigns visit={self.visit_id}>"
