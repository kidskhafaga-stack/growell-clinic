"""Radiology's quality records — GAHAR DAS.05, and the yearly review of a
diagnostic service (DAS.01 ev. 4 for imaging, DAS.10 ev. 4 for the lab).

DAS.05: *"All quality control processes are performed and recorded"* (ev.
3), *"responsible authorized staff member reviews quality control function
and checks data"* (ev. 4), and *"corrective action is taken whenever targets
are unmet"* (ev. 5). So a QC check is the test as the department's procedure
names it, on which machine, pass or fail against the department's own
target, and — on a fail — what was done. The month's checks are reviewed and
signed. The program names no test and holds no target.
"""
from datetime import datetime

from app.extensions import db

SERVICES = ("imaging", "lab")


class ImagingQc(db.Model):
    __tablename__ = "imaging_qc"

    id = db.Column(db.Integer, primary_key=True)
    equipment_id = db.Column(db.Integer, db.ForeignKey("equipment.id"), index=True)
    #: When the machine is not in the equipment register — as written.
    device = db.Column(db.String(120))
    held_on = db.Column(db.Date, nullable=False, index=True)
    test = db.Column(db.String(160), nullable=False)
    passed = db.Column(db.Boolean, nullable=False)
    value = db.Column(db.String(80))
    action = db.Column(db.Text)
    by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    equipment = db.relationship("Equipment")
    by = db.relationship("User", foreign_keys=[by_id])


class ImagingQcReview(db.Model):
    """DAS.05 ev. 4 — the month's QC data reviewed by the responsible person."""
    __tablename__ = "imaging_qc_reviews"

    id = db.Column(db.Integer, primary_key=True)
    month = db.Column(db.String(7), nullable=False, index=True)
    note = db.Column(db.String(255), nullable=False)
    by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    by = db.relationship("User", foreign_keys=[by_id])


class ServiceReview(db.Model):
    """The yearly evaluation of a diagnostic service and its scope — DAS.01
    ev. 4 (imaging, *"evaluated annually"*) and DAS.10 ev. 4 (the lab's scope
    *"periodically reviewed and modified"*)."""
    __tablename__ = "service_reviews"

    id = db.Column(db.Integer, primary_key=True)
    service = db.Column(db.String(10), nullable=False, index=True)
    year = db.Column(db.Integer, nullable=False, index=True)
    text = db.Column(db.Text, nullable=False)
    by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    by = db.relationship("User", foreign_keys=[by_id])
