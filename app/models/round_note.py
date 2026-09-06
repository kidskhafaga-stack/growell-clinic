"""The ward round: what somebody decided about this child today.

**The one question a round answers.** A doctor walks the ward at nine and
stops at every bed. Almost everything they look at is already in the program —
the night's readings, the drugs, the last result. What is nowhere is the
sentence they say out loud at the end of each bed: *better, the same, or
worse* — and what we are doing about it. Without that, a stay is a pile of
numbers with no thread through it, and the next doctor on has to re-derive
yesterday's thinking from yesterday's observations.

**Why it is not a visit.** ``Visit`` is an encounter that opens and closes on
one date and carries a complaint, a diagnosis and a bill. A round note is a
line in a stay that is already open, written eleven times over eleven days by
whoever is on. Making each one a visit would put eleven consultations in the
child's file and eleven rows on their account.

**Written for a doctor who types little.** The trend is one press, and it is
the only required field — an assessment and a plan are both optional, because
on the ninth quiet day of a stay "still stable, carry on" is the whole truth
and forcing a paragraph out of somebody produces a paragraph nobody reads.

**And a blank round is refused**, which is the same rule the observations
already keep and for the same reason. A row with nothing in it would clear
"today's round is not done" from the board without anybody having gone near
the child — the flag would go quiet exactly when it was telling the truth.

**Not one per day, deliberately.** No unique constraint on (stay, date): a
child who deteriorates at six in the evening is seen again, and the second
note is the important one. What the board asks is "has anybody written today",
which is a question about existence and needs no constraint to answer.
"""
from datetime import datetime

from app.extensions import db

# Better, the same, or worse — the sentence said at the foot of the bed. Three
# and not five: a scale a person has to think about is a scale they stop
# filling in, and the numbers that deserve fine grading are already graded by
# `vital_bands` and `red_flags`.
ROUND_TRENDS = ("improving", "stable", "worse")


class RoundNote(db.Model):
    """One stop on the round: this child, today, and what we decided."""

    __tablename__ = "round_notes"

    id = db.Column(db.Integer, primary_key=True)
    admission_id = db.Column(db.Integer, db.ForeignKey("admissions.id"),
                             nullable=False, index=True)
    # Carried alongside the admission for the same reason ``Observation``
    # carries it: the child's own file lists their rounds across every stay
    # they have had, and that read should not have to go through the stays to
    # find out whose they are.
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"),
                           nullable=False, index=True)

    # When the round happened, not when it was typed. The round is at nine and
    # the notes are written at the desk at eleven, and a board that asks "was
    # this child seen today" has to ask about the first of those. Same two
    # clocks as ``Observation.taken_at`` / ``recorded_at``, and the same
    # reason: the paper in the doctor's hand carries the earlier time.
    at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False,
                   index=True)
    recorded_at = db.Column(db.DateTime, default=datetime.utcnow,
                            nullable=False)

    trend = db.Column(db.String(16), nullable=False)
    # How they are, and what we are doing. Both optional — see the module
    # docstring. Free text on purpose: this is the one place in a stay where a
    # clinician's own words are the content rather than a field to be parsed.
    assessment = db.Column(db.Text)
    plan = db.Column(db.Text)

    # When we think they are going home. A ward manager's first question every
    # morning, and until now a thing kept in somebody's head. It lives on the
    # note rather than on the stay so that changing it leaves a trail: "we
    # said Thursday on Monday and Saturday on Wednesday" is the history, and a
    # single column on the admission would have overwritten it each time.
    expected_discharge = db.Column(db.Date)

    # The line this round went onto the family's bill as, once the clinic
    # charges for it. Empty for almost every round and that is the normal
    # state: a resident walking the ward every morning is not a chargeable
    # event, and nothing here changes unless the clinic has put a price on a
    # particular doctor's round. Same shape as ``Operation.invoice_item_id`` —
    # the clinical row carries the link, and "not billed yet" is the link
    # being empty rather than a flag anybody has to set.
    invoice_item_id = db.Column(db.Integer, db.ForeignKey("invoice_items.id"),
                                nullable=True, index=True)

    by_id = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow,
                           nullable=False)

    admission = db.relationship("Admission", backref="round_notes")
    invoice_item = db.relationship("InvoiceItem", foreign_keys=[invoice_item_id])
    patient = db.relationship("Patient")
    by = db.relationship("User", foreign_keys=[by_id])

    @property
    def is_empty(self):
        """A note that says nothing. Never stored — see the module docstring;
        this exists so the refusal has one definition and the test has
        something to aim at."""
        return self.trend not in ROUND_TRENDS

    def __repr__(self):
        return f"<RoundNote admission={self.admission_id} {self.trend}>"
