"""The drug round: what a child in a bed is on, and what was actually given.

**Not a prescription.** ``Prescription`` is a piece of paper a family carries
out of a room: written once, printed, and then the clinic never hears what
happened to it. An inpatient order is the opposite shape — it is standing
instruction, and the interesting record is the *administrations*: eight
o'clock given, two o'clock held because the child was vomiting, eight o'clock
given late. Trying to hold that on a prescription item would have meant a
prescription per dose, and a child's file full of scripts nobody wrote.

**Two tables for the same reason the stay has two.** The order is what the
doctor decided; the dose is one act by one nurse at one hour. Overwriting a
"last given" column on the order would answer *is it due* and would answer
*what happened at two o'clock* with tonight's answer for every night of the
stay — which is exactly the question a drug error inquiry asks.

**Nothing here schedules ahead.** There are no rows for doses that have not
happened yet. Due-ness is worked out from the order and the last dose, the
same way a late observation is — because a table of future doses is a table
that has to be kept in step with an order that changed at midnight, and the
first thing it does when it drifts is say a child was given something they
were not. See ``utils/drug_round.py``; the rule is the project's own
*المحسوب أحسن من المتخزّن*.

**A held dose is a record, not a gap.** Holding is a decision — the child was
nil by mouth, the cannula had tissued, the family refused — and it moves the
clock on to the next dose exactly as giving does. What must never exist is a
dose nobody wrote anything about: that absence is the finding the board is
built to show, and a "held" row with no reason on it would hide it while
looking like care.

**The dose itself is text, and deliberately.** A paediatric dose is
milligrams per kilogram and the arithmetic already has one home in
``utils/dosing.py`` — the screen computes it there and writes the answer here
as the words a nurse reads off the chart. A second calculation living on this
table would be a second clinical number free to disagree with the first.
"""
from datetime import datetime, timedelta

from app.extensions import db

# How it goes in. A list rather than free text because the board reads it —
# an intravenous dose late is not the same event as a cream late — and short
# enough that nobody has to hunt.
ROUTES = ("oral", "iv", "im", "sc", "inhaled", "nebulised", "rectal",
          "topical", "eye", "ear", "ng")

# What happened when the hour came round.
GIVEN, HELD, REFUSED = "given", "held", "refused"
DOSE_OUTCOMES = (GIVEN, HELD, REFUSED)

# The intervals a ward actually writes. Data on the order, not a rule in code:
# a doctor who needs every three hours types three.
COMMON_HOURS = (4, 6, 8, 12, 24)


class MedicationOrder(db.Model):
    """One standing instruction: this drug, this dose, this often."""

    __tablename__ = "medication_orders"

    id = db.Column(db.Integer, primary_key=True)
    admission_id = db.Column(db.Integer, db.ForeignKey("admissions.id"),
                             nullable=False, index=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"),
                           nullable=False, index=True)

    # The catalogue entry when the doctor picked one, and always the name they
    # saw. Snapshotted like every other printed name in this program: a
    # catalogue row renamed next year must not silently rewrite what a nurse
    # was told to give last March.
    drug_id = db.Column(db.Integer, db.ForeignKey("drugs.id"), nullable=True)
    drug_name = db.Column(db.String(200), nullable=False)
    dose = db.Column(db.String(80))
    route = db.Column(db.String(16), default="oral", nullable=False)

    # Regular, or when needed — never both. ``every_hours`` drives the clock;
    # a PRN order has no clock and instead has a floor under how soon it may
    # be repeated, which is the only safety number a PRN carries.
    every_hours = db.Column(db.Integer)
    is_prn = db.Column(db.Boolean, default=False, nullable=False)
    min_gap_hours = db.Column(db.Integer)

    started_at = db.Column(db.DateTime, default=datetime.utcnow,
                           nullable=False, index=True)
    stopped_at = db.Column(db.DateTime, index=True)
    stop_reason = db.Column(db.String(200))
    ordered_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    stopped_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    note = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow,
                           nullable=False)

    admission = db.relationship("Admission", backref="medication_orders")
    patient = db.relationship("Patient")
    drug = db.relationship("Drug")
    orderer = db.relationship("User", foreign_keys=[ordered_by])
    doses = db.relationship("MedicationDose", back_populates="order",
                            order_by="MedicationDose.at, MedicationDose.id")

    @property
    def is_running(self):
        return self.stopped_at is None

    @property
    def name(self):
        """What ``rx_safety`` reads a written line by. Named to match
        ``VisitMedication`` and ``PrescriptionItem`` so the interaction and
        dose checks work on an inpatient order without being taught about
        it — the same trick the observations play on ``red_flags`` by naming
        their columns after ``VitalSigns``."""
        return self.drug_name

    def label(self):
        parts = [self.drug_name, self.dose]
        if self.is_prn:
            parts.append("PRN")
        elif self.every_hours:
            parts.append(f"q{self.every_hours}h")
        return " · ".join(p for p in parts if p)

    def __repr__(self):
        return f"<MedicationOrder {self.drug_name} p={self.patient_id}>"


class MedicationDose(db.Model):
    """One hour, one nurse, one answer: given, held, or refused."""

    __tablename__ = "medication_doses"

    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("medication_orders.id"),
                         nullable=False, index=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"),
                           nullable=False, index=True)

    # Which dose this was for, and when it was actually dealt with. Both, and
    # not one: "the eight o'clock dose, given at nine twenty" is a fact about
    # a ward and the two halves of it say different things.
    due_at = db.Column(db.DateTime, index=True)
    at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False,
                   index=True)
    recorded_at = db.Column(db.DateTime, default=datetime.utcnow,
                            nullable=False)

    outcome = db.Column(db.String(12), default=GIVEN, nullable=False)
    # Why it was not given. Required for a hold or a refusal and refused
    # without one — see ``utils/drug_round.give``. A hold with no reason is
    # indistinguishable from a dose somebody forgot, and it silences the board
    # either way.
    reason = db.Column(db.String(200))
    note = db.Column(db.String(255))
    by_id = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow,
                           nullable=False)

    order = db.relationship("MedicationOrder", back_populates="doses")
    patient = db.relationship("Patient")
    by = db.relationship("User", foreign_keys=[by_id])

    @property
    def minutes_late(self):
        """How far off the hour it was, or ``None`` for a dose with no hour
        (a PRN, or a first dose given before the clock started)."""
        if not self.due_at:
            return None
        return int((self.at - self.due_at).total_seconds() // 60)

    def __repr__(self):
        return f"<MedicationDose {self.outcome} order={self.order_id}>"


def due_at(order, last_dose_at):
    """When this order's next dose falls due.

    From the last dose if there was one, otherwise from the moment the order
    was written — the same shape as an observation order, and for the same
    reason: a child started on something at two in the afternoon is due their
    next at six, not at whatever hour a fixed timetable happens to name.
    """
    if order is None or not order.is_running:
        return None
    # One test, and it answers two questions at once. A "when needed" order
    # has no interval **by construction** — ``drug_round.order`` clears it,
    # because the only rhythm a PRN has is its ``min_gap_hours`` floor and a
    # second number beside it would be a second rule about the same thing. So
    # "has no interval" and "is when-needed" are the same row, and asking
    # twice would have been two guards that only look independent.
    if not order.every_hours:
        return None
    return (last_dose_at or order.started_at) + timedelta(
        hours=order.every_hours)


def lateness_grace(every_hours):
    """How many minutes past the hour still counts as on time.

    A quarter of the interval, never under fifteen minutes and never over an
    hour. Administrative rather than clinical, but it still has to have a
    reason: ten minutes late on an hourly infusion is a real gap, and ten
    minutes late on a once-a-day tablet is a nurse walking down a corridor.
    The same shape as the observations' grace, which is the point — a ward
    that measured lateness two different ways would be teaching its staff that
    the word means nothing.
    """
    if not every_hours:
        return 60
    return min(60, max(15, int(every_hours) * 15))
