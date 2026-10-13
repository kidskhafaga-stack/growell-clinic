"""Rapid tranquilization — GAHAR CSS.11 (h), *"Rapid tranquilization
provision and administration guided by evidence-based practices and
guidelines."*

Recorded as an event on the stay: why, what was given and how (as the order
said — the drug itself is ordered and given on the chart like any other),
who gave it, and the monitoring afterwards, which is the part the
guidelines are written around and the part a record most often lacks. What
to monitor and how often is the hospital's protocol, written here as it was
done.
"""
from datetime import datetime

from app.extensions import db


class RapidTranquilization(db.Model):
    __tablename__ = "rapid_tranquilizations"

    id = db.Column(db.Integer, primary_key=True)
    admission_id = db.Column(db.Integer, db.ForeignKey("admissions.id"), nullable=False, index=True)
    at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    reason = db.Column(db.String(255), nullable=False)
    given = db.Column(db.String(160), nullable=False)
    monitoring = db.Column(db.String(255), nullable=False)
    outcome = db.Column(db.String(255))
    by_id = db.Column(db.Integer, db.ForeignKey("users.id"))

    by = db.relationship("User", foreign_keys=[by_id])
