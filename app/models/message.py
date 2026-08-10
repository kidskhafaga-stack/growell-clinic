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
# delivered = the provider says it reached the handset
# read      = the provider says it was opened
# "sent" only ever meant "the provider accepted it" — a dead number and a read
# message looked identical until these two arrived. See DELIVERY_RANK.
MESSAGE_STATUSES = ["queued", "scheduled", "link", "sent", "delivered",
                    "failed", "skipped", "received", "read"]

# Delivery receipts arrive out of order — Meta will hand you "delivered" after
# "read" often enough that treating them as a simple assignment loses the
# better fact. A status only ever moves *up* this ladder.
DELIVERY_RANK = {"queued": 0, "scheduled": 0, "link": 1, "sent": 2,
                 "delivered": 3, "read": 4}

# Message direction: outbound (we sent) vs inbound (patient replied).
MESSAGE_DIRECTIONS = ["out", "in"]

# Per-notification delivery preference (independent of the global CRM switch).
# auto   = when the clinic is in automatic mode, this type is sent via the API.
# manual = always produce a click-to-send link even in automatic mode.
SEND_MODES = ["manual", "auto"]

# Why a message was not sent. These are clinic states rather than provider
# errors — a file with no number, a family that asked not to be messaged, a
# notification type switched off — so they are shown in words. Anything else
# in ``MessageLog.error`` came from the provider and is shown as it arrived.
SKIP_REASONS = ["missing_phone", "opted_out", "type_off"]

# System (automatic-trigger) template types + manual occasion types.
SYSTEM_TEMPLATE_TYPES = [
    "appointment_confirm", "doctor_schedule", "vaccine_given",
    "vaccine_due", "vaccine_seasonal", "vaccine_changed",
    # "It has arrived" — to the families who were told to come while the
    # shelf was empty. See app/utils/vaccine_back.py.
    "vaccine_back",
    # The prescription itself, sent to the family as a picture of the paper.
    "rx_copy",
    # The one message that reduces no-shows more than any other, and the one
    # this program did not have: a reminder *before* the appointment. The
    # confirmation goes out when the booking is made — often weeks earlier —
    # and by then it is a receipt, not a reminder.
    "appointment_reminder",
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
    "appointment_reminder": ["patient", "clinic", "date", "time", "doctor"],
    "doctor_schedule": ["doctor", "date", "count", "list"],
    "vaccine_given": ["patient", "vaccine", "dose", "next_date", "clinic"],
    "vaccine_due": ["patient", "vaccine", "dose", "due_date", "clinic"],
    "vaccine_seasonal": ["patient", "vaccine", "year", "clinic"],
    "vaccine_changed": ["patient", "old_vaccine", "new_vaccine", "clinic"],
    "vaccine_back": ["patient", "vaccine", "clinic"],
    "rx_copy": ["patient", "doctor", "clinic", "link"],
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
    # Deliberately shorter than the confirmation, and it asks something. The
    # confirmation is a record; this is the message that has to make somebody
    # either come or call — so it names the time, and it says what to do if
    # the time no longer suits them, which is the whole point of sending it a
    # day early rather than an hour.
    "appointment_reminder": (
        "تذكير من {clinic}: عند {patient} موعد يوم {date} الساعة {time} "
        "مع {doctor}.\nلو الموعد مش مناسب، برجاء إبلاغنا بالرد على الرسالة."
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
    "vaccine_back": (
        "خبر كويس من {clinic}: تطعيم {vaccine} بقى متوفر.\n"
        "تقدروا تجيبوا {patient} في أي وقت خلال مواعيد العيادة — "
        "ومعلش على التأخير."
    ),
    "rx_copy": (
        # No "د." in front of {doctor}: the name already arrives with its
        # title, and the two together read "د. Dr. منى حسن".
        "روشتة {patient} من {clinic} — {doctor}.\n"
        "تقدروا تفتحوها وتطبعوها من هنا: {link}\n"
        "سلامته وعافيته."
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
    # Occasion campaigns (عيد الفطر، عيد الأم، ذكرى العيادة…): the date the
    # campaign fires, whether it recurs every year on the same Gregorian day
    # ("yearly") or is set by hand each time ("once" — Hijri events move ~11
    # days back a year, so their next date is entered manually), and the last
    # occasion date already queued (so a campaign is enqueued exactly once).
    occasion_date = db.Column(db.Date)
    repeat_rule = db.Column(db.String(10), default="once", nullable=False)
    last_enqueued_on = db.Column(db.Date)
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
    # The provider's own id for this message ("wamid.…" on Meta). Without it a
    # delivery receipt cannot be matched to the row it belongs to, which is why
    # every message here was stuck at "the provider accepted it".
    provider_msg_id = db.Column(db.String(120), index=True)
    direction = db.Column(db.String(3), default="out", nullable=False, index=True)
    status = db.Column(db.String(12), default="queued", nullable=False)
    link = db.Column(db.Text)
    error = db.Column(db.String(200))
    template_type = db.Column(db.String(30))          # which notification type
    # Which vaccine item a reminder was about. Without it the program can send
    # "your dose is due" and then have no way to answer "who did we tell?" when
    # the stock finally arrives — which is the whole of the call-back feature.
    vaccine_brand_id = db.Column(db.Integer, db.ForeignKey("vaccine_brands.id"),
                                 nullable=True, index=True)
    # The campaign template this message belongs to (occasion blasts) — lets
    # the campaign report count sent/pending/days per occasion.
    template_id = db.Column(db.Integer, db.ForeignKey("message_templates.id"),
                            nullable=True, index=True)
    scheduled_at = db.Column(db.DateTime, index=True)  # future send time (queued)
    sent_at = db.Column(db.DateTime)                    # when actually dispatched
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)

    patient = db.relationship("Patient")
    creator = db.relationship("User")
    vaccine_brand = db.relationship("VaccineBrand")

    def __repr__(self):
        return f"<MessageLog to={self.to_phone} {self.status}>"


class QuickReply(db.Model):
    """A canned answer the front desk sends with one tap.

    Reception answers the same five questions all day — the address, the
    working hours, what a visit costs, when the next vaccine is due. Typing
    them out again each time is how replies get slow and inconsistent, and how
    a wrong price reaches a parent. These are written once, edited from inside
    the program, and inserted into the reply box (never sent behind the user's
    back — the words are still theirs to change before they go).
    """
    __tablename__ = "quick_replies"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(80), nullable=False)
    body = db.Column(db.Text, nullable=False)
    # Same {patient} / {clinic} tokens as every other template.
    sort_order = db.Column(db.Integer, default=100, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    is_system = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self):
        return f"<QuickReply {self.title}>"


# Suggested starting set — created once on install, then the clinic's own.
DEFAULT_QUICK_REPLIES = [
    ("مواعيد العيادة",
     "أهلاً بحضرتك 👋\nمواعيد {clinic}: من السبت للخميس، ٤ م – ١٠ م.\nتحب نحجزلك إمتى؟", 10),
    ("تأكيد الحجز",
     "تمام، حجزنا لـ{patient} ✅\nلو حصل أي تغيير كلّمنا على نفس الرقم ده.", 20),
    ("سعر الكشف",
     "سعر الكشف في {clinic} هو … جنيه، والاستشارة خلال أسبوعين مجانية.\nتحب نحجزلك؟", 30),
    ("عنوان العيادة",
     "عنوان {clinic}: …\nلو تحب نبعتلك اللوكيشن على الخريطة قول لنا.", 40),
    ("موعد التطعيم",
     "تطعيم {patient} الجاي موعده …\nيُفضّل الحجز قبلها بيوم عشان نضمن التوفر.", 50),
    ("تعليمات بعد الزيارة",
     "سلامته يارب 🌿\nلو الحرارة زادت عن ٣٨٫٥ أو ظهر أي عرض جديد، كلّمنا فوراً.", 60),
]


class Conversation(db.Model):
    """Who owns a WhatsApp thread, and whether it still needs an answer.

    "Waiting" is read from the messages themselves — the patient spoke last —
    and that is right almost always. Almost: a thread whose last message is
    "شكراً" would sit in the work list forever. So a conversation can be marked
    done, with the time it was done, and a message arriving after that time
    re-opens it on its own. Nobody has to remember to un-close anything.

    Assignment is the other half: on a desk with three people, "someone will
    answer it" is how a message goes unanswered for two days.
    """
    __tablename__ = "conversations"

    id = db.Column(db.Integer, primary_key=True)
    # The same key the inbox groups by: "p<patient_id>", or the bare number.
    thread_key = db.Column(db.String(40), nullable=False, unique=True, index=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"), nullable=True)
    phone = db.Column(db.String(30))

    assigned_to = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True,
                            index=True)
    assigned_at = db.Column(db.DateTime)
    # When the thread was last declared answered. Compared against the newest
    # inbound message rather than cleared, so it re-opens by itself.
    resolved_at = db.Column(db.DateTime, index=True)
    resolved_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    note = db.Column(db.String(255))
    # What the thread is about, when somebody has said so. "urgent" is the
    # one that changes the order of the list rather than only labelling it.
    topic = db.Column(db.String(16), index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow,
                           onupdate=datetime.utcnow, nullable=False)

    patient = db.relationship("Patient")
    assignee = db.relationship("User", foreign_keys=[assigned_to])
    resolver = db.relationship("User", foreign_keys=[resolved_by])

    def is_resolved_for(self, last_inbound_at):
        """Done, unless the patient has written since."""
        if self.resolved_at is None:
            return False
        return last_inbound_at is None or self.resolved_at >= last_inbound_at

    def __repr__(self):
        return f"<Conversation {self.thread_key}>"
