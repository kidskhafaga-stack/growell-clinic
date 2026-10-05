"""Where medicines are kept, and the records that show they are kept well —
GAHAR MMS.04 / GSR.19.

* :class:`StorageArea` — a place medicines are stored: a store or pharmacy
  (optionally the warehouse it is), a ward's cupboard or cart, a fridge. Its
  temperature range and how many readings a day are **the hospital's**,
  copied from the manufacturer's labels and its own policy; until it writes
  them, readings are kept and nothing is called out of range.
* :class:`StorageInspection` — evidence 4: *"periodically (at least monthly)
  inspected"*. A checklist, what was found, what was done.
* :class:`TempReading` — the temperature (and humidity) as read, against the
  range the area had that day.
* :class:`PowerOutage` and :class:`OutageDecision` — evidence 3: *"a clear
  process to deal with an electric power outage to ensure the integrity of
  any affected medications before use"*. When, which areas, and the
  pharmacist's decision for each medicine.

Kept, never edited or deleted: these are the records a surveyor reads.
"""
from datetime import datetime

from app.extensions import db

AREA_KINDS = ("store", "pharmacy", "ward", "fridge", "cart", "other")

#: Evidence 1, 2, 4 and 5 and the intent, in the order an inspector walks
#: them. Each is answered yes, no, or not applicable.
INSPECTION_ITEMS = ("clean_organized", "temperature_ok", "light_humidity_ok",
                    "no_expired", "labelled", "multidose_dated", "secured",
                    "high_alert_apart")
ANSWERS = ("yes", "no", "na")

OUTAGE_DECISIONS = ("use", "discard", "quarantine")


class StorageArea(db.Model):
    __tablename__ = "med_storage_areas"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    kind = db.Column(db.String(12), nullable=False, default="store")
    warehouse_id = db.Column(db.Integer, db.ForeignKey("warehouses.id"))
    #: The hospital's range for this place, in °C — empty until written.
    temp_min = db.Column(db.Float)
    temp_max = db.Column(db.Float)
    #: The hospital's upper limit for relative humidity, %, if it keeps one.
    humidity_max = db.Column(db.Float)
    #: How many readings a day the hospital asks for here — empty, no gap
    #: is ever counted.
    readings_per_day = db.Column(db.Integer)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    warehouse = db.relationship("Warehouse")

    @property
    def has_range(self):
        return self.temp_min is not None or self.temp_max is not None

    def __repr__(self):
        return f"<StorageArea {self.name}>"


class StorageInspection(db.Model):
    __tablename__ = "med_storage_inspections"

    id = db.Column(db.Integer, primary_key=True)
    area_id = db.Column(db.Integer, db.ForeignKey("med_storage_areas.id"),
                        nullable=False, index=True)
    inspected_on = db.Column(db.Date, nullable=False, index=True)
    #: ``{item: "yes" | "no" | "na"}`` over :data:`INSPECTION_ITEMS`.
    answers = db.Column(db.JSON, nullable=False, default=dict)
    findings = db.Column(db.String(1000))
    action = db.Column(db.String(1000))
    inspector_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    written_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    area = db.relationship("StorageArea")
    inspector = db.relationship("User")

    @property
    def failed(self):
        return [k for k in INSPECTION_ITEMS if (self.answers or {}).get(k) == "no"]


class TempReading(db.Model):
    __tablename__ = "med_temp_readings"

    id = db.Column(db.Integer, primary_key=True)
    area_id = db.Column(db.Integer, db.ForeignKey("med_storage_areas.id"),
                        nullable=False, index=True)
    taken_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False,
                         index=True)
    temp_c = db.Column(db.Float, nullable=False)
    humidity = db.Column(db.Float)
    #: The area's range at the time, copied — a range changed next month does
    #: not re-judge this reading.
    temp_min = db.Column(db.Float)
    temp_max = db.Column(db.Float)
    out_of_range = db.Column(db.Boolean, default=False, nullable=False)
    #: What was done about a reading out of range — required then.
    action = db.Column(db.String(500))
    taken_by = db.Column(db.Integer, db.ForeignKey("users.id"))

    area = db.relationship("StorageArea")
    reader = db.relationship("User")


class PowerOutage(db.Model):
    __tablename__ = "med_power_outages"

    id = db.Column(db.Integer, primary_key=True)
    started_at = db.Column(db.DateTime, nullable=False, index=True)
    ended_at = db.Column(db.DateTime)
    #: Comma-separated :class:`StorageArea` ids.
    area_ids = db.Column(db.String(400), nullable=False, default="")
    #: The highest temperature seen in the affected places, if read.
    highest_temp = db.Column(db.Float)
    note = db.Column(db.String(500))
    recorded_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    recorded_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    #: Closed once the pharmacist has decided for what was affected.
    closed_at = db.Column(db.DateTime)
    closed_by = db.Column(db.Integer, db.ForeignKey("users.id"))

    decisions = db.relationship("OutageDecision", back_populates="outage",
                                order_by="OutageDecision.id",
                                cascade="all, delete-orphan")
    recorder = db.relationship("User", foreign_keys=[recorded_by])

    @property
    def area_list(self):
        return [int(x) for x in (self.area_ids or "").split(",") if x.strip().isdigit()]

    @property
    def minutes(self):
        if self.ended_at is None:
            return None
        return max(0, int((self.ended_at - self.started_at).total_seconds() // 60))


class OutageDecision(db.Model):
    __tablename__ = "med_outage_decisions"

    id = db.Column(db.Integer, primary_key=True)
    outage_id = db.Column(db.Integer, db.ForeignKey("med_power_outages.id"),
                          nullable=False, index=True)
    store_item_id = db.Column(db.Integer, db.ForeignKey("store_items.id"))
    #: The medicine as named, when it is not a store item (or as well).
    medicine = db.Column(db.String(200))
    lot_number = db.Column(db.String(60))
    decision = db.Column(db.String(12), nullable=False)
    reason = db.Column(db.String(400), nullable=False)
    decided_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    decided_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    outage = db.relationship("PowerOutage", back_populates="decisions")
    item = db.relationship("StoreItem")
    decider = db.relationship("User")
