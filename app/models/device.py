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

    def display_name(self, lang="ar"):
        return self.name_en if (lang == "en" and self.name_en) else self.name

    @property
    def under_warranty(self):
        return bool(self.warranty_until and self.warranty_until >= date.today())

    def __repr__(self):
        return f"<MedicalDevice {self.name}>"
