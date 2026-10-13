"""Moving a child inside the hospital — GAHAR ACT.12 ev. 5.

*"Requirements for transporting patients in critical conditions are
identified, used, and recorded in the patient's medical record."*

A child on oxygen and a monitor going down to the scanner is not a bed move —
they come back to the same bed — and it is the trip where the standard asks
what went with them. So a trip is: where to and why, who went with the child,
what monitoring and equipment went (as the hospital's criteria require them,
in its words), when they left and came back, and anything that happened on
the way.
"""
from datetime import datetime

from app.extensions import db


class StayTransport(db.Model):
    __tablename__ = "stay_transports"

    id = db.Column(db.Integer, primary_key=True)
    admission_id = db.Column(db.Integer, db.ForeignKey("admissions.id"), nullable=False, index=True)
    to_where = db.Column(db.String(160), nullable=False)
    escort = db.Column(db.String(160), nullable=False)
    #: What went with the child — monitor, oxygen, ventilator, drugs.
    requirements = db.Column(db.String(255), nullable=False)
    left_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    back_at = db.Column(db.DateTime)
    events = db.Column(db.String(255))
    by_id = db.Column(db.Integer, db.ForeignKey("users.id"))

    @property
    def is_out(self):
        return self.back_at is None
