"""The hospital's medical equipment, and what happened to each piece —
GAHAR EFS.10 / GSR.27 and CSS.02 / GSR.08.

**Not the devices list.** ``MedicalDevice`` is the catalogue of diagnostic
studies a clinic books (ECG, echo, spirometry) and every booking picker reads
it; a ventilator there would be offered as a study. So the equipment has its
own register, and a piece that *is* a study device points at it.

* :class:`Equipment` — the inventory (EFS.10 (أ-٤)): what, where, serial,
  the company and its emergency contact, the test on installation, whether
  it is critical and its backup (أ-٥), and — for equipment with a critical
  alarm (CSS.02) — the settings the hospital agreed for it. The preventive
  maintenance and calibration intervals are the manufacturer's, written by
  the hospital; without one, nothing is called overdue.
* :class:`EquipmentEvent` — evidence 5–6 of EFS.10 and 4–5 of CSS.02: each
  preventive maintenance, calibration, malfunction, repair, adverse
  incident, alarm test and alarm event, with who did it and what was done.
* :class:`EquipmentTraining` — EFS.10 (أ-٣) and evidence 4: who was trained
  on this equipment, when, by whom, until when.

Kept, never edited or deleted: these are the records a surveyor reads.
"""
from datetime import datetime

from app.extensions import db

IN_SERVICE, OUT_OF_SERVICE, RETIRED = ("in_service", "out_of_service", "retired")
STATUSES = (IN_SERVICE, OUT_OF_SERVICE, RETIRED)

PPM, CALIBRATION, MALFUNCTION, REPAIR, INCIDENT, ALARM_TEST, ALARM_EVENT = (
    "ppm", "calibration", "malfunction", "repair", "incident", "alarm_test",
    "alarm_event")
EVENT_KINDS = (PPM, CALIBRATION, MALFUNCTION, REPAIR, INCIDENT, ALARM_TEST,
               ALARM_EVENT)
#: Kinds that carry a pass/fail and a next due date.
SCHEDULED = (PPM, CALIBRATION, ALARM_TEST)
RESULTS = ("pass", "fail")


class Equipment(db.Model):
    __tablename__ = "equipment"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False)
    category = db.Column(db.String(80), index=True)
    manufacturer = db.Column(db.String(120))
    model = db.Column(db.String(120))
    serial_number = db.Column(db.String(80), index=True)
    #: The hospital's own asset number, on the equipment's identification card.
    asset_tag = db.Column(db.String(60), index=True)
    location = db.Column(db.String(160))
    medical_device_id = db.Column(db.Integer, db.ForeignKey("medical_devices.id"))
    #: EFS.10 (أ-٥) — must be available to the operator, with a backup.
    is_critical = db.Column(db.Boolean, default=False, nullable=False)
    backup = db.Column(db.String(200))
    #: CSS.02 — carries a critical alarm, and the settings agreed for it
    #: (values and volume), in the hospital's words.
    has_critical_alarm = db.Column(db.Boolean, default=False, nullable=False)
    alarm_settings = db.Column(db.Text)
    company = db.Column(db.String(160))
    company_contact = db.Column(db.String(160))
    installed_on = db.Column(db.Date)
    installation_test = db.Column(db.String(400))
    #: The manufacturer's intervals, in days — empty, nothing is overdue.
    ppm_every_days = db.Column(db.Integer)
    calibration_every_days = db.Column(db.Integer)
    alarm_test_every_days = db.Column(db.Integer)
    status = db.Column(db.String(16), default=IN_SERVICE, nullable=False, index=True)
    retired_on = db.Column(db.Date)
    retired_reason = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    device = db.relationship("MedicalDevice")
    events = db.relationship("EquipmentEvent", back_populates="equipment",
                             order_by="EquipmentEvent.at.desc()",
                             cascade="all, delete-orphan")
    trainings = db.relationship("EquipmentTraining", back_populates="equipment",
                                order_by="EquipmentTraining.trained_on.desc()",
                                cascade="all, delete-orphan")

    def interval(self, kind):
        return {PPM: self.ppm_every_days, CALIBRATION: self.calibration_every_days,
                ALARM_TEST: self.alarm_test_every_days}.get(kind)

    def __repr__(self):
        return f"<Equipment {self.name}>"


class EquipmentEvent(db.Model):
    __tablename__ = "equipment_events"

    id = db.Column(db.Integer, primary_key=True)
    equipment_id = db.Column(db.Integer, db.ForeignKey("equipment.id"),
                             nullable=False, index=True)
    kind = db.Column(db.String(16), nullable=False, index=True)
    at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    #: The engineer or the company that did it, as named.
    done_by = db.Column(db.String(160))
    result = db.Column(db.String(8))
    details = db.Column(db.Text, nullable=False)
    #: What was done about it — required for a malfunction, an incident, a
    #: failed check and an alarm event.
    action = db.Column(db.Text)
    #: An adverse incident is reported (EFS.10 دليل ٦) — to whom.
    reported_to = db.Column(db.String(160))
    #: When this check is due again — from the interval unless written.
    next_due = db.Column(db.Date)
    recorded_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    recorded_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    equipment = db.relationship("Equipment", back_populates="events")
    recorder = db.relationship("User")


class EquipmentTraining(db.Model):
    __tablename__ = "equipment_training"

    id = db.Column(db.Integer, primary_key=True)
    equipment_id = db.Column(db.Integer, db.ForeignKey("equipment.id"),
                             nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False,
                        index=True)
    trained_on = db.Column(db.Date, nullable=False)
    trainer = db.Column(db.String(160))
    valid_until = db.Column(db.Date)
    recorded_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    recorded_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    equipment = db.relationship("Equipment", back_populates="trainings")
    user = db.relationship("User", foreign_keys=[user_id])
