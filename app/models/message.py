"""Outgoing message log (WhatsApp).

Every WhatsApp message the system prepares is recorded here — whether it was
sent through a provider API or rendered as a click-to-send ``wa.me`` link.
This gives a clear audit trail and lets the UI surface pending links.
"""
from datetime import datetime

from app.extensions import db

# link      = a wa.me click-to-send link was produced (WhatsApp Web)
# sent      = handed to a provider API successfully
# scheduled = queued for a future send time (dispatched by dispatch_due)
# skipped   = intentionally not sent (patient opted out)
# received  = an inbound message from a patient (direction=in)
# failed/queued = self-explanatory
MESSAGE_STATUSES = ["queued", "scheduled", "link", "sent", "failed", "skipped", "received", "read"]

# Message direction: outbound (we sent) vs inbound (patient replied).
MESSAGE_DIRECTIONS = ["out", "in"]

# Per-notification delivery preference (independent of the global CRM switch).
# auto   = when the clinic is in automatic mode, this type is sent via the API.
# manual = always produce a click-to-send link even in automatic mode.
SEND_MODES = ["manual", "auto"]

# System (automatic-trigger) template types + manual occasion types.
SYSTEM_TEMPLATE_TYPES = [
    "appointment_confirm", "doctor_schedule", "vaccine_given",
    "vaccine_due", "vaccine_seasonal", "vaccine_changed",
]
# Notification types the clinic manages centrally (each has one canonical
# template with its own body/image/auto-or-manual toggle). Birthday is an
# automation-capable occasion, so it joins the managed set.
AUTOMATION_TYPES = SYSTEM_TEMPLATE_TYPES + ["birthday", "feedback"]
OCCASION_TYPES = SYSTEM_TEMPLATE_TYPES + ["birthday", "feedback", "seasonal", "greeting", "custom"]

# Variables each template type understands. Surfaced in the templates UI so
# staff can compose messages without guessing the tokens.
TEMPLATE_VARIABLES = {
    "appointment_confirm": ["patient", "clinic", "date", "time", "doctor", "queue"],
    "doctor_schedule": ["doctor", "date", "count", "list"],
    "vaccine_given": ["patient", "vaccine", "dose", "next_date", "clinic"],
    "vaccine_due": ["patient", "vaccine", "dose", "due_date", "clinic"],
    "vaccine_seasonal": ["patient", "vaccine", "year", "clinic"],
    "vaccine_changed": ["patient", "old_vaccine", "new_vaccine", "clinic"],
    "birthday": ["patient", "clinic"],
    "feedback": ["patient", "clinic", "doctor", "link"],
    "seasonal": ["patient", "clinic"],
    "greeting": ["patient", "clinic"],
    "custom": ["patient", "clinic"],
}

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
    "vaccine_due": (
        "تذكير من {clinic}: تطعيم {patient} — {vaccine} ({dose}) "
        "مستحق بتاريخ {due_date}.\nبرجاء الحجز في الموعد المناسب."
    ),
    "vaccine_seasonal": (
        "تذكير موسمي من {clinic}: حان وقت تطعيم {vaccine} لـ{patient} "
        "لموسم {year}.\nيُكرَّر سنوياً للوقاية."
    ),
    "vaccine_changed": (
        "إشعار من {clinic}: تطعيم {old_vaccine} لم يعد متاحاً، "
        "وتم استبداله بـ{new_vaccine} لـ{patient}.\nبرجاء التواصل لمتابعة الجدول."
    ),
    "birthday": (
        "كل سنة و{patient} طيب! 🎉\n"
        "عيلة {clinic} بتتمنالكم يوم سعيد وصحة دايمة. 🎂"
    ),
    "feedback": (
        "شكراً لزيارتكم {clinic} 🌟\n"
        "رأيكم يهمنا — قيّموا خدمتنا والدكتور {doctor} في أقل من دقيقة:\n{link}"
    ),
}

# Used when no active birthday template is configured.
DEFAULT_BIRTHDAY_BODY = (
    "كل سنة و{patient} طيب! 🎉\n"
    "عيلة {clinic} بتتمنالكم يوم سعيد وصحة دايمة. 🎂"
)


def _template_schedule(tpl, base=None):
    """Compute when a template's message should go out, from its delay + fixed
    hour settings. Returns a future datetime, or None for 'as soon as due'."""
    from datetime import datetime as _dt, timedelta as _td
    now = _dt.utcnow()
    at = base or now
    delay = (tpl.delay_days or 0, tpl.delay_hours or 0)
    if delay != (0, 0):
        at = at + _td(days=tpl.delay_days or 0, hours=tpl.delay_hours or 0)
    if tpl.send_hour is not None:
        at = at.replace(hour=max(0, min(23, tpl.send_hour)), minute=0,
                        second=0, microsecond=0)
        # If a fixed hour with no delay has already passed today, push to it
        # anyway (dispatch_due will pick it up); keep it simple and forward-only.
        if delay == (0, 0) and at < now:
            at = at + _td(days=1)
    return at if at > now else None


class MessageTemplate(db.Model):
    """Reusable CRM message template for occasions (birthdays, greetings…).

    Also holds the single canonical template for each managed notification
    type — the one place staff edit body/image and choose auto vs manual.
    ``is_system`` marks those canonical rows (seeded, one per type).
    """
    __tablename__ = "message_templates"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    occasion = db.Column(db.String(20), default="custom", nullable=False)
    body = db.Column(db.Text, nullable=False)
    image_url = db.Column(db.String(300))          # optional attached image
    send_mode = db.Column(db.String(10), default="manual", nullable=False)
    # Scheduling: delay after the trigger event (e.g. feedback N days/hours after
    # the visit) and/or a fixed hour-of-day to send (e.g. birthday at 10:00).
    delay_days = db.Column(db.Integer, default=0)
    delay_hours = db.Column(db.Integer, default=0)
    send_hour = db.Column(db.Integer)          # 0–23, or NULL for "as soon as due"
    is_system = db.Column(db.Boolean, default=False, nullable=False)
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
    image_url = db.Column(db.String(300))
    provider = db.Column(db.String(20))
    direction = db.Column(db.String(3), default="out", nullable=False, index=True)
    status = db.Column(db.String(12), default="queued", nullable=False)
    link = db.Column(db.Text)
    error = db.Column(db.String(200))
    template_type = db.Column(db.String(30))          # which notification type
    scheduled_at = db.Column(db.DateTime, index=True)  # future send time (queued)
    sent_at = db.Column(db.DateTime)                    # when actually dispatched
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)

    patient = db.relationship("Patient")
    creator = db.relationship("User")

    def __repr__(self):
        return f"<MessageLog to={self.to_phone} {self.status}>"
