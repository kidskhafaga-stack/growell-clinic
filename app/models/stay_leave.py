"""Temporary discharge — GAHAR ACT.14.

*"Temporary discharge is when a patient may require a brief time off unit
absence during their admission"*, and the order for it *"is clearly recorded
in the patient's medical record"* (ev. 3) by *"a qualified individual"* (b).

The stay does not end and the bed is not given away: a leave is a row on the
open stay — who ordered it, why, what the family was told to do, when the
child is due back, and when they came back. An open leave past its time is
late, and says so.
"""
from datetime import datetime

from app.extensions import db


class StayLeave(db.Model):
    __tablename__ = "stay_leaves"

    id = db.Column(db.Integer, primary_key=True)
    admission_id = db.Column(db.Integer, db.ForeignKey("admissions.id"), nullable=False, index=True)
    out_at = db.Column(db.DateTime, nullable=False)
    back_by = db.Column(db.DateTime, nullable=False)
    ordered_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    reason = db.Column(db.String(255), nullable=False)
    #: What the family takes and watches for — medicines, warning signs.
    instructions = db.Column(db.Text)
    returned_at = db.Column(db.DateTime)
    return_note = db.Column(db.String(255))
    by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    orderer = db.relationship("User", foreign_keys=[ordered_by])

    @property
    def is_open(self):
        return self.returned_at is None

    def is_late(self, now=None):
        return self.is_open and (now or datetime.utcnow()) > self.back_by
