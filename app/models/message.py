"""Outgoing message log (WhatsApp).

Every WhatsApp message the system prepares is recorded here — whether it was
sent through a provider API or rendered as a click-to-send ``wa.me`` link.
This gives a clear audit trail and lets the UI surface pending links.
"""
from datetime import datetime

from app.extensions import db

# link  = a wa.me click-to-send link was produced (WhatsApp Web)
# sent  = handed to a provider API successfully
# failed/queued = self-explanatory
MESSAGE_STATUSES = ["queued", "link", "sent", "failed"]

# System (automatic-trigger) template types + manual occasion types.
SYSTEM_TEMPLATE_TYPES = ["appointment_confirm", "doctor_schedule", "vaccine_given"]
OCCASION_TYPES = SYSTEM_TEMPLATE_TYPES + ["birthday", "seasonal", "greeting", "custom"]

# Built-in defaults used to seed the registry / fall back when none exists.
TEMPLATE_DEFAULTS = {
    "appointment_confirm": (
        "مرحباً {patient}،\nتم تأكيد موعدك في {clinic} يوم {date} الساعة {time} "
        "مع {doctor}.\nدورك رقم: {queue}\nنتمنى لكم الصحة والعافية."
    ),
    "doctor_schedule": "د. {doctor}، جدول حجوزات اليوم {date} ({count} حجز):\n{list}",
    "vaccine_given": (
        "تم بحمد الله تطعيم {patient} — {vaccine} ({dose}).\n"
        "الجرعة القادمة بتاريخ: {next_date}\nمع تحيات {clinic}."
    ),
    "birthday": (
        "كل سنة و{patient} طيب! 🎉\n"
        "عيلة {clinic} بتتمنالكم يوم سعيد وصحة دايمة. 🎂"
    ),
}

# Used when no active birthday template is configured.
DEFAULT_BIRTHDAY_BODY = (
    "كل سنة و{patient} طيب! 🎉\n"
    "عيلة {clinic} بتتمنالكم يوم سعيد وصحة دايمة. 🎂"
)


class MessageTemplate(db.Model):
    """Reusable CRM message template for occasions (birthdays, greetings…)."""
    __tablename__ = "message_templates"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    occasion = db.Column(db.String(20), default="custom", nullable=False)
    body = db.Column(db.Text, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self):
        return f"<MessageTemplate {self.name}>"


class MessageLog(db.Model):
    __tablename__ = "message_logs"

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"), nullable=True, index=True)
    appointment_id = db.Column(db.Integer, db.ForeignKey("appointments.id"), nullable=True)
    to_phone = db.Column(db.String(30))
    body = db.Column(db.Text, nullable=False)
    provider = db.Column(db.String(20))
    status = db.Column(db.String(12), default="queued", nullable=False)
    link = db.Column(db.Text)
    error = db.Column(db.String(200))
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)

    patient = db.relationship("Patient")
    creator = db.relationship("User")

    def __repr__(self):
        return f"<MessageLog to={self.to_phone} {self.status}>"
