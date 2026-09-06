"""A medication error, or one that was caught before it reached anybody.

**The loop the standards describe.** The high-alert list is supposed to be
built *from a hospital's own near misses and errors* — which means somebody
has to be recording them, and this program had nowhere to. So the list would
have been written once from memory and never revised, which is the state most
paper systems are in.

**A near miss is the valuable half.** An error caught at the counter harmed
nobody and is the cheapest possible lesson; a system that only records the
ones that reached a child collects the expensive lessons only. So "did it
reach the patient" is a field rather than a filter, and the list is called
what happened rather than what went wrong.

**The outcome bands are NCC MERP's**, the published index this classification
has used since 2001: **A** is a circumstance that could cause an error but did
not, **B–D** are errors that caused no harm, **E–H** are errors that caused
harm or needed intervention, and **I** is one that contributed to a death.
Letters rather than a severity number, because that is what the index is and
because a hospital comparing its own quarters needs the same buckets everyone
else uses. They are an outcome taxonomy — steps, not clinical figures — which
is why the program may own them, the same argument the WHO surgical checklist
was taken on.

**And nothing here blames.** There is no field for who made the mistake. A
reporting system with one collects nothing after the first month, which is the
oldest finding in patient safety and the reason near-miss reporting exists at
all. What is recorded is the stage it happened at, the drug, and what
happened — because that is what a list of high-alert medicines is built from.
"""
from datetime import datetime

from app.extensions import db

# Where in the chain it happened. The standard's own stages, and the reason
# the field exists: a hospital whose errors are all at *administration* has a
# different problem from one whose errors are all at *prescribing*, and the
# two are fixed by completely different things.
ERROR_STAGES = ("prescribing", "transcribing", "dispensing",
                "administering", "monitoring")

#: The NCC MERP index. The letters are the index's; the words here are a plain
#: rendering of each band rather than a quotation, and the grouping below is
#: what a hospital actually reports on.
ERROR_OUTCOMES = ("A", "B", "C", "D", "E", "F", "G", "H", "I")

#: The four bands every summary is drawn in.
OUTCOME_BANDS = {
    "A": "no_error",          # a circumstance that could cause one
    "B": "no_harm", "C": "no_harm", "D": "no_harm",
    "E": "harm", "F": "harm", "G": "harm", "H": "harm",
    "I": "death",
}


class MedicationError(db.Model):
    """One thing that went wrong, or nearly did."""

    __tablename__ = "medication_errors"

    id = db.Column(db.Integer, primary_key=True)

    # Who it happened to, when it is known. **Nullable**, because a near miss
    # caught on the bench belongs to no child — the wrong box was picked up
    # and put back — and refusing to record it until somebody names a patient
    # would lose exactly the reports that cost nothing to learn from.
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"),
                           nullable=True, index=True)
    admission_id = db.Column(db.Integer, db.ForeignKey("admissions.id"),
                             nullable=True, index=True)
    # The order or the prescription line it concerns, when it is one of ours.
    order_id = db.Column(db.Integer, db.ForeignKey("medication_orders.id"),
                         nullable=True, index=True)

    # The drug, by ingredient where we can resolve one — because that is what
    # the high-alert list is keyed on, and this table is what that list is
    # supposed to be built from.
    generic_id = db.Column(db.Integer, db.ForeignKey("generic_drugs.id"),
                           nullable=True, index=True)
    drug_name = db.Column(db.String(200))

    stage = db.Column(db.String(16), nullable=False, index=True)
    outcome = db.Column(db.String(1), nullable=False, index=True)
    # Whether it got as far as the child. Recorded rather than derived from
    # the outcome letter: "reached them and did no harm" and "was caught" are
    # different lessons, and the letters blur them at the edges.
    reached_patient = db.Column(db.Boolean, default=False, nullable=False,
                                index=True)

    what_happened = db.Column(db.Text, nullable=False)
    # What was done about it — the half that turns a report into a change.
    action_taken = db.Column(db.Text)

    happened_at = db.Column(db.DateTime, default=datetime.utcnow,
                            nullable=False, index=True)
    reported_at = db.Column(db.DateTime, default=datetime.utcnow,
                            nullable=False)
    # Who wrote the report — **not** who made the mistake. There is no column
    # for that, deliberately: a reporting system that names the person
    # collects nothing after the first month.
    reported_by = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    patient = db.relationship("Patient")
    generic = db.relationship("GenericDrug")
    order = db.relationship("MedicationOrder")
    reporter = db.relationship("User", foreign_keys=[reported_by])

    @property
    def band(self):
        """Which of the four a summary counts this in."""
        return OUTCOME_BANDS.get(self.outcome, "no_harm")

    @property
    def is_near_miss(self):
        """Caught before it reached anybody — the cheapest lesson there is."""
        return not self.reached_patient

    def __repr__(self):
        return f"<MedicationError {self.stage} {self.outcome}>"
