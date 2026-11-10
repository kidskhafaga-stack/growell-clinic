"""Fluid balance on the ward — what went in and what came out, in millilitres
(DOCTOR_EASE ٤-ب د-٥).

One row per amount the nurse writes: «in» (by mouth, a feed by tube, IV
fluids, blood…) or «out» (urine, vomit, stool, a drain…). The totals are
worked out from the rows every time — never stored beside them — and the
program sets no limit of its own: the numbers are the chart, the reading of
them is the doctor's.
"""
from datetime import datetime

from app.extensions import db

IN, OUT = "in", "out"
DIRECTIONS = (IN, OUT)
KINDS_IN = ("oral", "feed", "iv", "blood", "other_in")
KINDS_OUT = ("urine", "vomit", "stool", "drain", "aspirate", "other_out")


class FluidEntry(db.Model):
    __tablename__ = "fluid_entries"

    id = db.Column(db.Integer, primary_key=True)
    admission_id = db.Column(db.Integer, db.ForeignKey("admissions.id"),
                             nullable=False, index=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"),
                           nullable=False, index=True)
    # When it went in or came out — the hour the nurse writes, not the hour
    # they typed it (a whole shift is often written at its end).
    at = db.Column(db.DateTime, nullable=False, index=True, default=datetime.utcnow)
    direction = db.Column(db.String(3), nullable=False)
    kind = db.Column(db.String(12), nullable=False)
    ml = db.Column(db.Integer, nullable=False)
    note = db.Column(db.String(160))
    by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    recorded_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    # Struck through, never deleted — a wrong amount is corrected, and the
    # chart keeps that it was.
    struck_at = db.Column(db.DateTime)
    struck_by = db.Column(db.Integer, db.ForeignKey("users.id"))

    admission = db.relationship("Admission", backref="fluid_entries")
    by = db.relationship("User", foreign_keys=[by_id])

    def __repr__(self):
        return f"<FluidEntry {self.direction} {self.kind} {self.ml}ml>"
