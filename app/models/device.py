"""Medical devices registry (Business Engine).

A generic device catalogue so any diagnostic device (Spirometry, ECG, Echo,
EEG, Ultrasound, Audiometry…) is defined as *data* — its make/model, how it
connects and how results are captured (manual first; auto-import later) — and
linked to the service(s) performed on it. Adding a new device never needs code.
"""
from datetime import date, datetime

from app.extensions import db

DEVICE_TYPES = [
    "spirometry", "ecg", "echo", "eeg", "ultrasound", "audiometry",
    "tympanometry", "holter", "other",
]
CONNECTION_TYPES = ["usb", "serial", "lan", "wifi", "bluetooth", "manual"]
# How results come in — manual entry is the default; the rest are for later
# auto-import phases (folder watch, file export, HL7, vendor SDK/API).
IMPORT_MODES = ["manual", "folder", "csv", "xml", "hl7", "sdk", "api"]


class MedicalDevice(db.Model):
    __tablename__ = "medical_devices"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    name_en = db.Column(db.String(120))
    manufacturer = db.Column(db.String(120))
    model = db.Column(db.String(120))
    device_type = db.Column(db.String(20), default="other", nullable=False)
    connection_type = db.Column(db.String(12), default="manual", nullable=False)
    import_mode = db.Column(db.String(10), default="manual", nullable=False)
    software = db.Column(db.String(120))          # companion app (e.g. WinSpiroPRO)
    serial_number = db.Column(db.String(80))
    purchase_date = db.Column(db.Date)
    warranty_until = db.Column(db.Date)
    notes = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    is_system = db.Column(db.Boolean, default=False, nullable=False)  # seeded default
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    # Services performed on this device.
    services = db.relationship("Service", back_populates="device")
    # The measurements this device's report captures (its result template).
    measurements = db.relationship(
        "DeviceMeasurement", back_populates="device",
        cascade="all, delete-orphan",
        order_by="DeviceMeasurement.sort_order, DeviceMeasurement.id")

    def display_name(self, lang="ar"):
        return self.name_en if (lang == "en" and self.name_en) else self.name

    @property
    def under_warranty(self):
        return bool(self.warranty_until and self.warranty_until >= date.today())

    def __repr__(self):
        return f"<MedicalDevice {self.name}>"


class DeviceMeasurement(db.Model):
    """One field a device's report captures — the measurement template. e.g. a
    spirometer has FEV1, FVC, FEV1/FVC…, each with a unit and a normal range so
    manually-entered results can be flagged in/out of range."""

    __tablename__ = "device_measurements"

    id = db.Column(db.Integer, primary_key=True)
    device_id = db.Column(db.Integer, db.ForeignKey("medical_devices.id"),
                          nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)      # Arabic / primary
    name_en = db.Column(db.String(120))
    unit = db.Column(db.String(30))                       # %, L, mmHg, bpm…
    normal_low = db.Column(db.Float)
    normal_high = db.Column(db.Float)
    sort_order = db.Column(db.Integer, default=0, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    device = db.relationship("MedicalDevice", back_populates="measurements")

    def display_name(self, lang="ar"):
        return self.name_en if (lang == "en" and self.name_en) else self.name

    @property
    def normal_range(self):
        lo, hi = self.normal_low, self.normal_high
        if lo is not None and hi is not None:
            return f"{lo:g}–{hi:g}"
        if lo is not None:
            return f"≥ {lo:g}"
        if hi is not None:
            return f"≤ {hi:g}"
        return ""

    def flag(self, value):
        """'low' / 'high' / 'normal' / '' for a numeric value against range."""
        try:
            v = float(value)
        except (TypeError, ValueError):
            return ""
        if self.normal_low is not None and v < self.normal_low:
            return "low"
        if self.normal_high is not None and v > self.normal_high:
            return "high"
        if self.normal_low is not None or self.normal_high is not None:
            return "normal"
        return ""

    def __repr__(self):
        return f"<DeviceMeasurement {self.name} dev={self.device_id}>"


class DeviceStudy(db.Model):
    """One performed device test for a patient — the manually-entered result of
    running a device (spirometry/ECG/echo…), optionally tied to a visit."""

    __tablename__ = "device_studies"

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"),
                           nullable=False, index=True)
    device_id = db.Column(db.Integer, db.ForeignKey("medical_devices.id"),
                          nullable=False, index=True)
    visit_id = db.Column(db.Integer, db.ForeignKey("visits.id"), nullable=True)
    study_date = db.Column(db.Date, default=date.today, nullable=False, index=True)
    performed_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    conclusion = db.Column(db.Text)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    patient = db.relationship("Patient", backref="device_studies")
    device = db.relationship("MedicalDevice")
    visit = db.relationship("Visit")
    performer = db.relationship("User")
    values = db.relationship("DeviceStudyValue", back_populates="study",
                             cascade="all, delete-orphan",
                             order_by="DeviceStudyValue.id")

    def __repr__(self):
        return f"<DeviceStudy {self.id} patient={self.patient_id}>"


class DeviceStudyValue(db.Model):
    """One measured value in a study. The field name/unit are snapshotted so the
    record stays readable even if the device's template later changes."""

    __tablename__ = "device_study_values"

    id = db.Column(db.Integer, primary_key=True)
    study_id = db.Column(db.Integer, db.ForeignKey("device_studies.id"),
                         nullable=False, index=True)
    measurement_id = db.Column(db.Integer,
                               db.ForeignKey("device_measurements.id"), nullable=True)
    name = db.Column(db.String(120), nullable=False)   # snapshot
    unit = db.Column(db.String(30))                    # snapshot
    value = db.Column(db.String(60))                   # free text (numeric or note)
    flag = db.Column(db.String(10))                    # low|high|normal|'' snapshot

    study = db.relationship("DeviceStudy", back_populates="values")
    measurement = db.relationship("DeviceMeasurement")

    def __repr__(self):
        return f"<DeviceStudyValue {self.name}={self.value}>"
