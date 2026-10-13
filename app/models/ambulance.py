"""The hospital's own ambulance — GAHAR ICD.02, pre-hospital care.

*"There is a process of recording and monitoring of response times"* (ev. 4),
*"pre-hospital care records are complete and kept in the patient's medical
record"* (ev. 3), continuous readiness (b) and drills (f).

A call is the record of one run: when it was received and from where, which
vehicle and crew went, the four moments that make a response time (sent,
reached the child, left the scene, arrived here), what the crew found and did
on the way, and how it ended. The moments are one press each — the crew is
busy — and the time targets are the hospital's numbers; until they are
written the program measures and does not judge. The national ambulance
system is not this: a child it brings is an ordinary ambulance arrival in the
emergency department.
"""
from datetime import datetime

from app.extensions import db

PROVIDERS = ("own", "contracted")
#: The four moments of a run, in order.
STEPS = ("dispatched_at", "at_scene_at", "left_scene_at", "arrived_at")
OUTCOMES = ("brought", "treated", "refused", "cancelled", "other")
READINESS_KINDS = ("check", "drill")


class AmbulanceVehicle(db.Model):
    __tablename__ = "ambulance_vehicles"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False)
    plate = db.Column(db.String(40))
    provider = db.Column(db.String(12), nullable=False, default="own")
    contractor = db.Column(db.String(160))
    is_active = db.Column(db.Boolean, default=True, nullable=False)


class AmbulanceCall(db.Model):
    __tablename__ = "ambulance_calls"

    id = db.Column(db.Integer, primary_key=True)
    received_at = db.Column(db.DateTime, nullable=False, index=True)
    caller = db.Column(db.String(160))
    phone = db.Column(db.String(40))
    location = db.Column(db.String(255), nullable=False)
    complaint = db.Column(db.String(255), nullable=False)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"), index=True)
    #: Before the child has a file — as the caller gave it.
    patient_name = db.Column(db.String(120))
    vehicle_id = db.Column(db.Integer, db.ForeignKey("ambulance_vehicles.id"))
    crew = db.Column(db.String(255))
    dispatched_at = db.Column(db.DateTime)
    at_scene_at = db.Column(db.DateTime)
    left_scene_at = db.Column(db.DateTime)
    arrived_at = db.Column(db.DateTime)
    #: (d) screening and assessment at the scene; reassessment on the way.
    assessment = db.Column(db.Text)
    reassessment = db.Column(db.Text)
    #: (e) care at the scene and during transfer.
    care = db.Column(db.Text)
    condition_on_arrival = db.Column(db.String(255))
    handed_to = db.Column(db.String(160))
    outcome = db.Column(db.String(12))
    outcome_note = db.Column(db.String(255))
    closed_at = db.Column(db.DateTime)
    by_id = db.Column(db.Integer, db.ForeignKey("users.id"))

    patient = db.relationship("Patient")
    vehicle = db.relationship("AmbulanceVehicle")

    @property
    def is_open(self):
        return self.closed_at is None

    @property
    def next_step(self):
        for step in STEPS:
            if getattr(self, step) is None:
                return step
        return None

    def minutes(self, step):
        moment = getattr(self, step)
        if moment is None:
            return None
        return int((moment - self.received_at).total_seconds() // 60)


class AmbulanceReadiness(db.Model):
    """(b) a readiness check of one vehicle — equipment, oxygen, drugs,
    fuel, as the hospital's list has it — or (f) a drill."""
    __tablename__ = "ambulance_readiness"

    id = db.Column(db.Integer, primary_key=True)
    vehicle_id = db.Column(db.Integer, db.ForeignKey("ambulance_vehicles.id"), index=True)
    kind = db.Column(db.String(6), nullable=False, default="check")
    held_on = db.Column(db.Date, nullable=False, index=True)
    ok = db.Column(db.Boolean, nullable=False, default=True)
    #: What was missing or wrong — required when not ok.
    missing = db.Column(db.Text)
    action = db.Column(db.Text)
    note = db.Column(db.Text)
    by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    vehicle = db.relationship("AmbulanceVehicle")
