"""The operating theatres — a schedule, and the checklist that guards it.

**Not a department with beds.** ``HOSPITAL_PLAN.md`` ٤-ج settled that:
*"العمليات جدول، مش مكان بينام فيه حد: غرفة عمليات × وقت × فريق."* Everything
this program already built for the wards is about a child *staying* somewhere;
a theatre is booked, used for ninety minutes, and cleaned. So it is not a
``Unit`` with ``Bed`` rows — modelling it as one would have made every bed
report count the operating table.

The place a child goes *afterwards* is a bed, and that one already exists:
``recovery`` has been a ``UNIT_KINDS`` value since the wards were built, and
the repeated readings that a recovery room runs on are ``Observation`` at a
five-minute interval. Nothing new is needed for either.

**The checklist is the point, not the schedule.** The plan is explicit about
this: *"اللي بيخليها «بشكل ذكي» مش الجدول نفسه — ده الجزء السهل — ده إن قايمة
الفحص قبل العملية تكون هي قلب الشاشة مش ورقة جنبها."* The WHO Surgical Safety
Checklist is published, free, translated, and has three stops: before
anaesthesia, before the first cut, and before the team leaves the room. It is
**steps, not numbers** — so the program may own it outright without breaking
the rule that says the program does not invent clinical figures.

**And the stops are recorded, never inferred.** A checklist that a screen
merely *displays* is a poster. What makes it a checklist is that each stop is
signed off by somebody at a moment, and that the program can say which stop
has not been done — the same shape as the observation that leaves no row and
the round nobody walked.
"""
from datetime import datetime

from app.extensions import db

# Where an operation is in its day. Recorded rather than derived from times:
# "booked for ten" and "actually started at ten past eleven" are different
# facts, and a list of today's operations has to be able to say which of them
# are still to come — a question no timestamp answers on its own.
OPERATION_STATUSES = ("scheduled", "in_theatre", "done", "cancelled")

# The WHO Surgical Safety Checklist's three stops, in the order they happen.
# The names are the WHO's own; the program keeps them as keys and translates
# them, so a clinic reads them in its own language and nothing here has to
# hold two copies of the wording.
SIGN_IN, TIME_OUT, SIGN_OUT = "sign_in", "time_out", "sign_out"
CHECK_STOPS = (SIGN_IN, TIME_OUT, SIGN_OUT)

# What is asked at each stop. **Data, and the program's to hold**: these are
# steps rather than clinical numbers, which is exactly why owning them does
# not break the rule that the program never invents a threshold.
#
# Kept short on purpose. The published list is longer, and a checklist nobody
# finishes is a checklist that gets ticked without being read — which is worse
# than no checklist, because it produces a signature saying it was done.
CHECK_ITEMS = {
    SIGN_IN: ("identity", "site_marked", "consent", "allergy", "airway",
              "anaesthesia_check", "pulse_oximeter"),
    TIME_OUT: ("team_introduced", "patient_site_procedure", "antibiotic",
               "imaging_ready", "critical_steps", "anticipated_blood_loss"),
    SIGN_OUT: ("procedure_recorded", "counts_correct", "specimen_labelled",
               "equipment_problems", "recovery_concerns"),
}


class Theatre(db.Model):
    """One operating room."""

    __tablename__ = "theatres"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False)
    sort_order = db.Column(db.Integer, default=0, nullable=False)
    # Out of use — being serviced, or its air handling is down. Never deleted,
    # for the reason a bed is never deleted: last month's list of what was
    # done in it is a thing a hospital reports on.
    is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)
    note = db.Column(db.String(160))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self):
        return f"<Theatre {self.name}>"


class Operation(db.Model):
    """One booking: this child, this theatre, this hour, this team."""

    __tablename__ = "operations"

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"),
                           nullable=False, index=True)
    theatre_id = db.Column(db.Integer, db.ForeignKey("theatres.id"),
                           nullable=False, index=True)
    # The stay this belongs to, when there is one. Nullable because a day-case
    # child comes in, is operated on and goes home without ever being
    # admitted — and refusing the booking until somebody invents an admission
    # would put a fictional stay in their file.
    admission_id = db.Column(db.Integer, db.ForeignKey("admissions.id"),
                             nullable=True, index=True)

    # **The clinic's date, not a UTC one.** A theatre list is a day somebody
    # prints and pins up; for a Cairo clinic on a UTC server the first three
    # hours of every day belong to yesterday in UTC, and a seven o'clock start
    # would print on the wrong list.
    on_date = db.Column(db.Date, nullable=False, index=True)
    start_time = db.Column(db.Time)
    minutes = db.Column(db.Integer)

    # What is being done, and what it is charged as. The procedure is a
    # ``Service`` like everything else that costs money in this program, so
    # the price list, the payers, the doctor's share, the tax code — and the
    # consumables it burns — all work on it with nothing added. See
    # ``ServiceConsumable``: a theatre case burning its own store items is a
    # thing this program has been able to do since PR #89.
    service_id = db.Column(db.Integer, db.ForeignKey("services.id"),
                           nullable=True, index=True)
    procedure = db.Column(db.String(200), nullable=False)

    surgeon_id = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)
    anaesthetist_id = db.Column(db.Integer, db.ForeignKey("users.id"),
                                index=True)
    team = db.Column(db.String(255))

    status = db.Column(db.String(16), default="scheduled", nullable=False,
                       index=True)
    started_at = db.Column(db.DateTime)
    finished_at = db.Column(db.DateTime)
    cancel_reason = db.Column(db.String(200))

    # The operation note. Free text on purpose: this is the surgeon's own
    # account of what they found and did, and it is the one document a later
    # doctor reads before touching the same child again.
    findings = db.Column(db.Text)
    notes = db.Column(db.Text)

    invoice_item_id = db.Column(db.Integer, db.ForeignKey("invoice_items.id"),
                                nullable=True, index=True)

    booked_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    patient = db.relationship("Patient")
    theatre = db.relationship("Theatre")
    invoice_item = db.relationship("InvoiceItem")
    admission = db.relationship("Admission", backref="operations")
    service = db.relationship("Service")
    surgeon = db.relationship("User", foreign_keys=[surgeon_id])
    anaesthetist = db.relationship("User", foreign_keys=[anaesthetist_id])
    checks = db.relationship("SafetyCheck", back_populates="operation",
                             cascade="all, delete-orphan",
                             order_by="SafetyCheck.at, SafetyCheck.id")

    @property
    def is_open(self):
        return self.status in ("scheduled", "in_theatre")

    def check_for(self, stop):
        """The signed-off stop, or ``None`` — which is the finding."""
        return next((c for c in self.checks if c.stop == stop), None)

    def __repr__(self):
        return f"<Operation {self.procedure} p={self.patient_id}>"


class SafetyCheck(db.Model):
    """One of the three stops, signed off by somebody at a moment.

    **A row, not a flag on the operation.** Three booleans would have said
    *that* the checks were done and nothing about *when* or *by whom* — which
    is the whole of what a safety checklist is for afterwards. And the missing
    row is the finding: an operation with no ``time_out`` is one where nobody
    stopped before the first cut, and that is a sentence a screen can say.
    """

    __tablename__ = "surgical_safety_checks"
    __table_args__ = (
        # One sign-off per stop. Not a convention: two people running the
        # checklist from two screens in the same minute is exactly how a stop
        # ends up signed twice and nobody knows which one was real.
        db.UniqueConstraint("operation_id", "stop", name="uq_safety_stop"),
    )

    id = db.Column(db.Integer, primary_key=True)
    operation_id = db.Column(db.Integer, db.ForeignKey("operations.id"),
                             nullable=False, index=True)
    stop = db.Column(db.String(12), nullable=False)

    at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    by_id = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)

    # Which items were ticked, as a comma-separated list of their keys. A
    # column each would have meant a migration every time the WHO revises the
    # list, and a table of rows would have meant four queries to draw one
    # screen. What is stored is what was actually confirmed, so a stop signed
    # with items missing still says which ones.
    confirmed = db.Column(db.String(500))
    note = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    operation = db.relationship("Operation", back_populates="checks")
    by = db.relationship("User", foreign_keys=[by_id])

    @property
    def items(self):
        return [i for i in (self.confirmed or "").split(",") if i]

    def has(self, item):
        return item in self.items

    @property
    def missed(self):
        """The items of this stop that were *not* confirmed.

        Kept visible rather than hidden: a stop signed off with two items
        unticked is a real event, and a screen that shows only a green tick
        would be reporting a checklist that was not completed as one that was.
        """
        return [i for i in CHECK_ITEMS.get(self.stop, ()) if i not in self.items]

    def __repr__(self):
        return f"<SafetyCheck {self.stop} op={self.operation_id}>"
