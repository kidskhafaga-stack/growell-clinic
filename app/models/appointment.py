"""Appointment model and its status lifecycle.

Status flow (per the project plan):
    scheduled -> waiting -> in_progress -> completed
    scheduled/waiting -> no_show
    any (except completed) -> cancelled
"""
from datetime import datetime

from app.extensions import db

# Ordered for display; values are stored in the DB.
APPOINTMENT_STATUSES = [
    "scheduled",
    "waiting",
    "in_progress",
    "completed",
    "no_show",
    "cancelled",
]

# Visit types with a sensible default duration (minutes) and a board colour.
# Keys are stored in ``Appointment.appt_type``; labels live in i18n
# (``appt_types.<key>``). New types can be added here without a schema change.
APPOINTMENT_TYPES = {
    "new":          {"minutes": 20, "color": "blue"},
    "followup":     {"minutes": 15, "color": "green"},
    "consultation": {"minutes": 20, "color": "teal"},
    "vaccination":  {"minutes": 10, "color": "purple"},
    "procedure":    {"minutes": 30, "color": "orange"},
    "urgent":       {"minutes": 15, "color": "red"},
}
DEFAULT_APPT_TYPE = "new"


def type_minutes(appt_type, fallback=15):
    """Default slot length for a visit type. Reads the DB catalogue first
    (admin-editable), falling back to the built-in defaults."""
    try:
        from app.utils.visit_types import minutes as _resolved
        return _resolved(appt_type, fallback)
    except Exception:  # noqa: BLE001 - pre-DB / import cycles
        meta = APPOINTMENT_TYPES.get(appt_type)
        return meta["minutes"] if meta else fallback

# Statuses that occupy a time slot (block double-booking).
ACTIVE_STATUSES = {"scheduled", "waiting", "in_progress", "completed"}

# Allowed transitions for guarding status-change actions.
STATUS_TRANSITIONS = {
    "scheduled": {"waiting", "in_progress", "no_show", "cancelled"},
    "waiting": {"in_progress", "no_show", "cancelled"},
    "in_progress": {"completed", "waiting", "cancelled"},
    "completed": set(),
    "no_show": {"scheduled"},
    "cancelled": {"scheduled"},
}


class Appointment(db.Model):
    __tablename__ = "appointments"

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(
        db.Integer, db.ForeignKey("patients.id"), nullable=False, index=True
    )
    doctor_id = db.Column(
        db.Integer, db.ForeignKey("users.id"), nullable=False, index=True
    )

    appt_date = db.Column(db.Date, nullable=False, index=True)
    appt_time = db.Column(db.Time, nullable=False)
    duration_minutes = db.Column(db.Integer, default=15, nullable=False)

    reason = db.Column(db.String(200))
    status = db.Column(db.String(20), default="scheduled", nullable=False, index=True)
    notes = db.Column(db.Text)

    # Visit type (drives default duration / board colour) and booking metadata.
    appt_type = db.Column(db.String(20), default=DEFAULT_APPT_TYPE, nullable=False)
    # For a vaccination booking: which vaccine brand + dose the patient is here for.
    vaccine_brand_id = db.Column(db.Integer, db.ForeignKey("vaccine_brands.id"), nullable=True)
    vaccine_dose = db.Column(db.Integer)
    # Extra services requested at booking (comma-separated Service ids) — they
    # flow into the checkout as additional lines alongside the base charge.
    extra_service_ids = db.Column(db.String(200))
    is_walk_in = db.Column(db.Boolean, default=False, nullable=False)
    cancel_reason = db.Column(db.String(200))      # why cancelled / no-show
    rescheduled_from = db.Column(db.String(120))   # audit: original date/time

    # Lifecycle timestamps.
    checked_in_at = db.Column(db.DateTime)
    # The nurse finished the vitals. Without this moment the wait is one
    # number covering two different queues — the one at reception and the one
    # at the doctor's door — and a clinic cannot tell which of them is slow.
    vitals_at = db.Column(db.DateTime)
    started_at = db.Column(db.DateTime)
    completed_at = db.Column(db.DateTime)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    patient = db.relationship("Patient", backref="appointments")
    doctor = db.relationship("User", backref="appointments")
    vaccine_brand = db.relationship("VaccineBrand")

    def can_transition_to(self, new_status):
        return new_status in STATUS_TRANSITIONS.get(self.status, set())

    def apply_status(self, new_status):
        """Apply a status change and stamp the relevant lifecycle time."""
        self.status = new_status
        now = datetime.utcnow()
        if new_status == "waiting" and self.checked_in_at is None:
            self.checked_in_at = now
        elif new_status == "in_progress" and self.started_at is None:
            self.started_at = now
        elif new_status == "completed":
            self.completed_at = now

    @property
    def time_label(self):
        return self.appt_time.strftime("%H:%M") if self.appt_time else ""

    @property
    def type_color(self):
        try:
            from app.utils.visit_types import color as _resolved
            return _resolved(self.appt_type)
        except Exception:  # noqa: BLE001
            meta = APPOINTMENT_TYPES.get(self.appt_type)
            return meta["color"] if meta else "blue"

    @staticmethod
    def valid_status(value):
        return value in APPOINTMENT_STATUSES

    def __repr__(self):
        return f"<Appointment {self.appt_date} {self.time_label} p={self.patient_id}>"


# Colours a visit type may use (map to the board's ``tt-*`` / ``edge-*`` classes).
VISIT_TYPE_COLORS = ["blue", "green", "teal", "purple", "orange", "red",
                     "yellow", "pink", "gray"]


class VisitType(db.Model):
    """Admin-editable catalogue of visit types (كشف / متابعة / تطعيم / …).

    Replaces the hardcoded ``APPOINTMENT_TYPES`` dict: the built-in types are
    seeded as ``is_system`` rows (their ``key`` is stable because some flows
    special-case it, e.g. ``vaccination``/``consultation``), while the clinic
    can add its own types and tune the label / duration / colour of any of them.
    """
    __tablename__ = "visit_types"

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(30), unique=True, nullable=False, index=True)
    name_ar = db.Column(db.String(60))
    name_en = db.Column(db.String(60))
    minutes = db.Column(db.Integer, default=15, nullable=False)
    color = db.Column(db.String(12), default="blue", nullable=False)
    sort_order = db.Column(db.Integer, default=0, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    is_system = db.Column(db.Boolean, default=False, nullable=False)

    def display_name(self, lang="ar"):
        name = self.name_en if lang == "en" else self.name_ar
        if name:
            return name
        # System types fall back to their i18n label; custom types to the key.
        from app.i18n import t
        label = t("appt_types." + self.key)
        return label if label != "appt_types." + self.key else self.key

    def __repr__(self):
        return f"<VisitType {self.key}>"
