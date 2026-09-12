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

#: The kinds of case a theatre list carries, seeded into :class:`CaseType`.
#: A **price and a fee**, not a label: the same operation by the same surgeon
#: is three different numbers depending which of these it is.
CASE_TYPES = ["private", "hospital", "emergency"]

#: Icon per built-in kind, so a list stays scannable by shape.
CASE_TYPE_ICONS = {
    "private": "bi-person-badge",
    "hospital": "bi-hospital",
    "emergency": "bi-exclamation-triangle",
}

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

    # **Private, hospital, or emergency** — and it is a price, not a label.
    # Reported as *«فيه تسعيرين للعملية اذا كانت خاصة او مستشفى او طوارئ»*,
    # and then again for the people: *«واتعاب الجراح برده علشان الحالات
    # الخاصة وحالات الطوارئ وحالات المستشفى»*. The same appendicectomy by the
    # same surgeon is three different numbers and three different fees.
    #
    # Nullable, and NULL means **nobody said** — every case booked before
    # this column has that answer, and they price exactly as they always did:
    # at the doctor's ordinary rate. It is not "private" with the paperwork
    # missing.
    case_type = db.Column(db.String(30), index=True)

    # The anaesthesia line, when the clinic bills it separately. A second
    # link rather than a second use of ``invoice_item_id``: the two lines are
    # owed to two different people, and one column pointing at whichever was
    # written last is how a surgeon's fee ends up in an anaesthetist's
    # statement.
    anaesthesia_item_id = db.Column(db.Integer,
                                    db.ForeignKey("invoice_items.id"),
                                    nullable=True, index=True)

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
    invoice_item = db.relationship("InvoiceItem",
                                   foreign_keys=[invoice_item_id])
    anaesthesia_item = db.relationship("InvoiceItem",
                                       foreign_keys=[anaesthesia_item_id])
    admission = db.relationship("Admission", backref="operations")
    service = db.relationship("Service")
    surgeon = db.relationship("User", foreign_keys=[surgeon_id])
    anaesthetist = db.relationship("User", foreign_keys=[anaesthetist_id])
    reviews = db.relationship("PreOpReview", back_populates="operation",
                              cascade="all, delete-orphan")
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


#: Who has to look at the child before the day, and what each is answering.
#: The surgeon confirms the operation is still the right one; the anaesthetist
#: confirms this child can be given an anaesthetic. Two different questions,
#: asked by two different people, and a screen that merged them would let one
#: signature stand for both.
REVIEW_KINDS = ("surgeon", "anaesthesia")

#: What a review concluded. ``conditions`` is the answer that actually happens
#: — "yes, once the chest is clear" — and a scheme with only fit and unfit
#: forces it to be recorded as one of the two, which loses the condition.
REVIEW_VERDICTS = ("fit", "conditions", "unfit")


class PreOpReview(db.Model):
    """The surgeon's and the anaesthetist's look at a case **before the day**.

    The checklist already has a stop for this — ``anaesthesia_check`` in the
    sign-in — and it is ticked **with the child in the room**. A case that
    should never have been listed is then found on the table, which is the
    most expensive possible moment to find it, and the reason a pre-operative
    assessment exists as its own thing in every hospital that has one.

    So this is not a second checklist. It is the same question moved to where
    the answer can still change something, and the list is what makes that
    workable: the anaesthetist opens it, sees who has not been looked at, and
    works through them on a day when nobody is waiting.

    **It does not refuse.** ``start()`` holds the one hard stop in this module
    and that is deliberate — a bleeding child does not wait for a form, and a
    program that blocked an emergency would be dangerous in the other
    direction. What this does instead is what ``finish()`` does about a missing
    sign-out: say the gap is there, and keep saying it. A gap that is visible
    is worth more than a refusal that gets worked around.
    """

    __tablename__ = "preop_reviews"
    __table_args__ = (
        # One review per kind per case, for the same reason the checklist has
        # one sign-off per stop: two people recording from two screens in the
        # same minute is how a case ends up reviewed twice with nobody able to
        # say which answer was the real one.
        db.UniqueConstraint("operation_id", "kind", name="uq_preop_kind"),
    )

    id = db.Column(db.Integer, primary_key=True)
    operation_id = db.Column(db.Integer, db.ForeignKey("operations.id"),
                             nullable=False, index=True)
    kind = db.Column(db.String(12), nullable=False)
    verdict = db.Column(db.String(12), nullable=False)

    # What the condition is, or why not. Required by the caller for any
    # verdict but ``fit`` — "not fit" with no reason stops a list and tells
    # the next person nothing.
    note = db.Column(db.String(500))

    at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    by_id = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    operation = db.relationship("Operation", back_populates="reviews")
    by = db.relationship("User", foreign_keys=[by_id])

    def __repr__(self):
        return f"<PreOpReview {self.kind} {self.verdict}>"


class CaseType(db.Model):
    """The kinds of case this clinic prices differently.

    Seeded with private, hospital and emergency because those are the three
    the clinic named — and **open**, like the bill sections and unlike the
    accounting category, for the same reason: nothing reads one by name. A
    rate is found by matching whatever key the case carries against whatever
    key the rate carries, so a hospital that also prices «تعاقد» gets a
    working fourth kind the minute somebody types it.
    """

    __tablename__ = "case_types"

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(30), unique=True, nullable=False, index=True)
    name_ar = db.Column(db.String(60))
    name_en = db.Column(db.String(60))
    icon = db.Column(db.String(40))
    sort_order = db.Column(db.Integer, default=0, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    # Seeded rows keep their key, because a clinic renaming «طوارئ» must not
    # thereby detach every emergency rate already set under it.
    is_system = db.Column(db.Boolean, default=False, nullable=False)

    def display_name(self, lang="ar"):
        name = self.name_en if lang == "en" else self.name_ar
        if name:
            return name
        from app.i18n import t

        key = "case_types." + self.key
        try:
            label = t(key)
        except RuntimeError:
            return self.key
        return label if label != key else self.key

    def __repr__(self):
        return f"<CaseType {self.key}>"


class DoctorCaseRate(db.Model):
    """What one doctor charges for one service **on one kind of case**.

    A third key on a pairing that already had two, and deliberately its own
    table rather than a column on :class:`DoctorServiceCommission`. That table
    is unique on ``(doctor, service)``, and a clinic's existing database
    carries that constraint: adding a case type there would work perfectly in
    tests — which build their schema from the models — and raise on the second
    rate every real clinic tried to save. A new table is created by
    ``create_all`` on every machine, old and new.

    So the two tables say two different things, and both are true:
    :class:`DoctorServiceCommission` is *this doctor's ordinary rate*, and
    this is *the exception for emergencies* (or for private cases, or for
    whatever fourth kind a hospital invents).

    **NULL is not zero, in both columns here.** A row that overrides only the
    price leaves ``commission_type`` NULL and the doctor's ordinary commission
    stands; a row that says ``none`` means they are paid nothing on this kind
    of case, which is a different and deliberate statement. One empty value
    standing for both is the bug this project keeps meeting.
    """

    __tablename__ = "doctor_case_rates"
    __table_args__ = (
        db.UniqueConstraint("doctor_id", "service_id", "case_type",
                            name="uq_doctor_service_case"),
    )

    id = db.Column(db.Integer, primary_key=True)
    doctor_id = db.Column(db.Integer, db.ForeignKey("users.id"),
                          nullable=False, index=True)
    service_id = db.Column(db.Integer, db.ForeignKey("services.id"),
                           nullable=False, index=True)
    case_type = db.Column(db.String(30), nullable=False, index=True)
    # NULL = the doctor's ordinary price stands. 0 = they do this kind of
    # case for nothing, which a hospital list genuinely says.
    price_override = db.Column(db.Float)
    # NULL = their ordinary commission stands. "none" = nothing on this kind.
    commission_type = db.Column(db.String(10))
    commission_value = db.Column(db.Float)

    doctor = db.relationship("User")
    service = db.relationship("Service")

    def __repr__(self):
        return (f"<DoctorCaseRate doc={self.doctor_id} "
                f"svc={self.service_id} {self.case_type}>")
