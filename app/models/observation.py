"""Readings taken again and again on the same child, at the doctor's interval.

**The thing that made this necessary**, said on the screen it was missing
from: *"الطوارئ والحضانة بيقيسوا vital signs حسب ما الدكتور بيطلب كل ربع ساعة
او كل ساعة"*.

Today that is not difficult, it is **impossible**: ``VitalSigns.visit_id`` is
declared ``unique=True``, one row per visit, and the table itself refuses the
second reading. A child under observation in emergency for six hours has one
temperature on file — the one taken when they arrived.

**Why a new table rather than lifting that constraint.** Dropping the unique
key would turn ``visit.vitals`` from an object into a list, and every screen
in the program reads it as an object — the visit record, the print-out, the
board, the red-flag assessment, the growth mirror. The clinic's single reading
is not wrong; it is the *first* observation, and it stays exactly where it is.
Nothing here migrates anything, and no screen that works today changes.

**The columns are named after ``VitalSigns`` on purpose.** ``temperature_c``,
``pulse_bpm``, ``resp_rate``, ``spo2`` — the same spellings, so that
``red_flags.assess`` and ``vital_bands.read`` judge an observation without
being told it is one. Those two hold every clinical number this program owns,
and the rule that keeps them trustworthy is that there is only ever one copy
of each. A table with its own ``temp_c`` would have needed its own thresholds
within a week.

**Attached to the child, and to whatever the child is currently in.** The
visit is nullable because the encounter this hangs off is not always a visit:
an admission is coming (see ``HOSPITAL_PLAN.md``, أساس ٢), and when it lands
it is one more nullable column here, not a second observations table.
"""
from datetime import datetime, timedelta

from app.extensions import db

# What a doctor may ask for, in minutes. A fixed list rather than a typed
# number, because the doctor typing less is the whole design brief — and
# because "every 37 minutes" is not an order anybody gives, it is a typo that
# would then drive a lateness alarm for the rest of the shift.
INTERVALS = (15, 30, 60, 120, 240, 480)

# How the child was breathing when the reading was taken. Recorded because a
# saturation of 96% means one thing in room air and something else entirely on
# CPAP, and a column of numbers with no support beside them reads as a child
# who is getting better.
OXYGEN_SUPPORT = ("room_air", "nasal", "mask", "cpap", "ventilator")

# Level of consciousness, the AVPU scale — Alert, responds to Voice, responds
# to Pain, Unresponsive. Four letters, taught everywhere, and the one
# observation on this list that needs no equipment at three in the morning.
AVPU = ("A", "V", "P", "U")


class ObservationOrder(db.Model):
    """The doctor's instruction: this child, this often, from now.

    Separate from the readings because it is a different act by a different
    person. The doctor orders quarter-hourly observations once; the nurse
    records twenty-four of them. Keeping the order as a row is what lets the
    station screen say *nothing has been recorded for this child in fifty
    minutes* — a question no pile of readings can answer on its own, because
    the absence of a reading is invisible unless something says one was due.
    """

    __tablename__ = "observation_orders"

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"),
                           nullable=False, index=True)
    visit_id = db.Column(db.Integer, db.ForeignKey("visits.id"),
                         nullable=True, index=True)

    every_minutes = db.Column(db.Integer, nullable=False)
    reason = db.Column(db.String(120))

    started_at = db.Column(db.DateTime, default=datetime.utcnow,
                           nullable=False, index=True)
    ordered_by = db.Column(db.Integer, db.ForeignKey("users.id"))

    # Stopped, never deleted. The six hours a child was watched quarter-hourly
    # is a fact about their care, and a clinic that stops the rounds must not
    # thereby lose the record that they were ordered — same rule as a consent,
    # which is withdrawn and kept for exactly this reason.
    stopped_at = db.Column(db.DateTime, index=True)
    stopped_by = db.Column(db.Integer, db.ForeignKey("users.id"))

    patient = db.relationship("Patient", backref="observation_orders")
    visit = db.relationship("Visit", backref="observation_orders")

    @property
    def is_running(self):
        return self.stopped_at is None

    def __repr__(self):
        return (f"<ObservationOrder patient={self.patient_id} "
                f"every={self.every_minutes}m>")


class Observation(db.Model):
    """One set of readings, at one moment, by one person."""

    __tablename__ = "observations"

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"),
                           nullable=False, index=True)
    visit_id = db.Column(db.Integer, db.ForeignKey("visits.id"),
                         nullable=True, index=True)
    order_id = db.Column(db.Integer, db.ForeignKey("observation_orders.id"),
                         nullable=True, index=True)

    # **Two times, and they are not the same time.** ``taken_at`` is when the
    # thermometer came out; ``recorded_at`` is when somebody typed it in. A
    # nurse writes four readings on paper at the bedside and enters them at
    # the desk twenty minutes later, and if the program only kept the typing
    # time it would show a round as missed that was not missed, and place
    # every reading on the chart at the wrong hour.
    taken_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False,
                         index=True)
    recorded_at = db.Column(db.DateTime, default=datetime.utcnow,
                            nullable=False)
    recorded_by = db.Column(db.Integer, db.ForeignKey("users.id"))

    # The same names as `vital_signs`, deliberately — see the module docstring.
    temperature_c = db.Column(db.Float)
    pulse_bpm = db.Column(db.Integer)
    resp_rate = db.Column(db.Integer)
    spo2 = db.Column(db.Integer)
    bp_systolic = db.Column(db.Integer)
    bp_diastolic = db.Column(db.Integer)
    bp_arm = db.Column(db.String(10))

    # The ones a ward needs and a clinic never asks for.
    glucose_mgdl = db.Column(db.Integer)
    avpu = db.Column(db.String(1))
    pain_score = db.Column(db.Integer)          # 0–10, the faces/numeric scale
    oxygen_support = db.Column(db.String(12))
    note = db.Column(db.String(255))

    patient = db.relationship("Patient", backref="observations")
    visit = db.relationship("Visit", backref="observations")
    order = db.relationship("ObservationOrder", backref="observations")
    recorder = db.relationship("User", foreign_keys=[recorded_by])

    @property
    def blood_pressure(self):
        """``"110/70"`` or ``None`` — both halves or neither.

        Same rule as the clinic's own vitals: a systolic with no diastolic is
        a typing accident, not half a reading, and showing it as one invites
        somebody to act on it.
        """
        if self.bp_systolic and self.bp_diastolic:
            return f"{self.bp_systolic}/{self.bp_diastolic}"
        return None

    @property
    def is_empty(self):
        """Nothing was actually measured.

        A round where the nurse looked at a sleeping child and wrote nothing
        is not an observation, and saving it would make the chart claim a
        reading exists and quiet the lateness warning at the same time —
        which is the one failure this whole table is here to prevent.
        """
        return not any([
            self.temperature_c, self.pulse_bpm, self.resp_rate, self.spo2,
            self.bp_systolic, self.bp_diastolic, self.glucose_mgdl,
            self.avpu, self.pain_score is not None and self.pain_score >= 0,
            # Not measurements, and still observations: "alert", "moved on to
            # CPAP at four", "sleeping and comfortable" are all things
            # somebody saw by going to the child, which is what the round is.
            self.oxygen_support, (self.note or "").strip(),
        ])

    def __repr__(self):
        return f"<Observation patient={self.patient_id} at={self.taken_at}>"


def due_at(order, last_taken):
    """When the next reading is owed, in UTC.

    Counted from the last reading actually taken, not from the top of the
    hour: a round taken late moves the next one, because the interval is "every
    fifteen minutes", not "at :00 :15 :30 :45". Counted from the order itself
    when nothing has been recorded yet, which is what makes the first missed
    reading visible instead of the second.
    """
    if order is None:
        return None
    start = last_taken or order.started_at
    return start + timedelta(minutes=order.every_minutes)


def lateness_grace(every_minutes):
    """How long past due is still "on time".

    A quarter of the interval, and never more than fifteen minutes. Not a
    clinical number — nothing here decides anything about a child — but it
    still has to be defensible: a fixed grace cannot serve both a
    quarter-hourly round, where three minutes late is late, and a four-hourly
    one, where three minutes is nothing. Capped so that a twelve-hourly order
    cannot drift by three hours and still read as punctual.
    """
    return min(15, max(1, every_minutes // 4))
