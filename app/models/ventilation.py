"""The breathing machine's settings for a child in a bed (DOCTOR_EASE ٤-ج ع-٢).

One row per change, in the doctor's own numbers — the program suggests no
setting. The latest row is what the machine is on now; the rows before it are
how it got there.
"""
from datetime import datetime

from app.extensions import db


class VentSetting(db.Model):
    __tablename__ = "vent_settings"

    id = db.Column(db.Integer, primary_key=True)
    admission_id = db.Column(db.Integer, db.ForeignKey("admissions.id"),
                             nullable=False, index=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"),
                           nullable=False, index=True)
    at = db.Column(db.DateTime, nullable=False, index=True, default=datetime.utcnow)
    # In the hospital's own words (CPAP, SIMV, PC, HFOV…) — not a list of ours.
    mode = db.Column(db.String(30), nullable=False)
    fio2 = db.Column(db.Integer)            # %
    peep = db.Column(db.Float)              # cmH2O
    rate = db.Column(db.Integer)            # breaths/min
    pip = db.Column(db.Integer)             # cmH2O
    tidal_ml = db.Column(db.Integer)        # mL
    pressure_support = db.Column(db.Integer)  # cmH2O
    ti = db.Column(db.Float)                # seconds
    flow = db.Column(db.Float)              # L/min (CPAP, high flow)
    note = db.Column(db.String(160))
    # Off the machine — the row that says it stopped.
    stopped = db.Column(db.Boolean, default=False, nullable=False)
    by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    recorded_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    admission = db.relationship("Admission", backref="vent_settings")
    by = db.relationship("User", foreign_keys=[by_id])
