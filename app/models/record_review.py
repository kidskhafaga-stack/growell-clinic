"""The review that reads the records back — GAHAR IMT.09.

> **IMT.09** The hospital establishes the patient's medical record review
> process.
>
> The hospital shall develop and implement a policy and procedures that assess
> the content and the completeness of a patient's medical record that
> addresses at least the following:
> a) Random sampling and selecting approximately **5%** of patient's medical
>    records.
> b) Review of a representative sample of **all services**.
> c) Review of a representative sample of **all disciplines/staff**.
> d) **Involvement of representatives** of all disciplines who make entries.
> e) Review of the **completeness and legibility** of entries.
> f) Review occurs **at least quarterly**.

**The program's half is the counting.** The policy is the hospital's (evidence
1) and so is staff awareness of it (evidence 2); this holds the *rounds* — who
was sampled, what was found, who took part, what was reported to the leaders
(evidence 3) and what was done about it (evidence 4).

---

**Stored, not derived — and that is the exception it looks like.**

Almost everything in this program is worked out from the record when somebody
asks, so an answer can never go stale. A review is the opposite and has to be:
it is *what was found on the day*, and the whole value of it is that it does
**not** move. Re-deriving a March review in June would quietly rewrite it as
the gaps were filled, and a clinic that fixed twelve records would end up with
evidence that it had never found any — the exact opposite of what evidence 4
asks it to show.

So a finding is a row, frozen, like ``SafetyCheck``.

---

**Four tables, and each answers a question one of the others cannot:**

* ``RecordReview`` — the round. Its period, its population and its sample, so
  the 5% is a number somebody can check rather than a claim.
* ``RecordReviewMember`` — who took part (d). One name on a review is not a
  review by representatives of all disciplines, and only the list can show it.
* ``RecordReviewItem`` — one sampled file. **It exists so that a file with
  nothing wrong is still recorded as having been looked at**: without it the
  sample would be only the files with findings, and a clean quarter would read
  as a quarter nobody reviewed.
* ``RecordReviewFinding`` — one observation against one entry.
"""
from datetime import datetime

from app.extensions import db


class RecordReview(db.Model):
    """One round of the medical record review (IMT.09)."""

    __tablename__ = "record_reviews"

    id = db.Column(db.Integer, primary_key=True)

    # The period the sample was drawn from. Quarterly is the standard's floor
    # — *"at least quarterly"* — and the dates are the clinic's, never a
    # cadence this program invented.
    period_from = db.Column(db.Date, nullable=False, index=True)
    period_to = db.Column(db.Date, nullable=False, index=True)

    # **How big the pool was, and how many came out of it.** Both stored,
    # because "approximately 5%" is a claim a surveyor checks, and a review
    # that recorded only the sample would leave them no way to.
    population = db.Column(db.Integer, nullable=False, default=0)
    sampled = db.Column(db.Integer, nullable=False, default=0)

    run_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False,
                       index=True)
    run_by = db.Column(db.Integer, db.ForeignKey("users.id"))

    # (e)'s second half. **The program computes nothing for legibility and
    # says so**: its own entries are typed, and where a clinic scans paper
    # into a file only a person can judge whether it can be read. So this is a
    # box somebody fills in, not a number.
    legibility_note = db.Column(db.Text)

    # Evidence 3 — *"The hospital leaders are reported on the medical record
    # review's findings."* A stamp rather than a flag: when they were told is
    # the evidence, and a boolean could not carry it.
    reported_at = db.Column(db.DateTime)
    reported_by = db.Column(db.Integer, db.ForeignKey("users.id"))

    # Evidence 4 — *"Corrective interventions are taken when needed."* Written
    # by a person, because what to do about a gap is the clinic's decision and
    # nothing here is qualified to propose one.
    action = db.Column(db.Text)
    action_at = db.Column(db.DateTime)
    action_by = db.Column(db.Integer, db.ForeignKey("users.id"))

    runner = db.relationship("User", foreign_keys=[run_by])
    reporter = db.relationship("User", foreign_keys=[reported_by])
    actor = db.relationship("User", foreign_keys=[action_by])

    @property
    def percent(self):
        """What share of the pool was actually sampled, to one decimal.

        Derived — this one genuinely is, because it is two stored numbers
        divided, and a third column could disagree with them.
        """
        if not self.population:
            return 0.0
        return round(100.0 * self.sampled / self.population, 1)

    @property
    def reported(self):
        return self.reported_at is not None

    def __repr__(self):
        return f"<RecordReview {self.period_from}..{self.period_to}>"


class RecordReviewMember(db.Model):
    """Somebody who took part in a review — IMT.09 (d).

    *"Involvement of representatives of all disciplines who make entries."*
    One name against a review is not that, and the only thing that can show
    otherwise is the list.

    ``discipline`` is free text and stays free text: the disciplines that make
    entries are this hospital's own, and a fixed list here would be the
    program deciding what a discipline is.
    """

    __tablename__ = "record_review_members"

    id = db.Column(db.Integer, primary_key=True)
    review_id = db.Column(db.Integer, db.ForeignKey("record_reviews.id"),
                          nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False,
                        index=True)
    discipline = db.Column(db.String(80))

    review = db.relationship("RecordReview",
                             backref=db.backref("members",
                                                cascade="all, delete-orphan"))
    user = db.relationship("User")

    def __repr__(self):
        return f"<RecordReviewMember review={self.review_id}>"


class RecordReviewItem(db.Model):
    """One patient's file, as it was sampled into one review.

    **A row even when nothing was found**, which is the point of the table.
    Recording only the files with findings would make the sample look like the
    findings, and a quarter in which every record was complete would read as a
    quarter nobody reviewed.
    """

    __tablename__ = "record_review_items"

    id = db.Column(db.Integer, primary_key=True)
    review_id = db.Column(db.Integer, db.ForeignKey("record_reviews.id"),
                          nullable=False, index=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"),
                           nullable=False, index=True)
    # How many entries in the period this file had — the size of what was
    # actually read, so "no findings" can be told from "nothing to look at".
    entries = db.Column(db.Integer, nullable=False, default=0)

    review = db.relationship("RecordReview",
                             backref=db.backref("items",
                                                cascade="all, delete-orphan"))
    patient = db.relationship("Patient")

    @property
    def clean(self):
        return not self.findings

    def __repr__(self):
        return f"<RecordReviewItem review={self.review_id}>"


class RecordReviewFinding(db.Model):
    """One observation against one entry in a sampled file.

    **An observation, never a verdict.** Each finding names the entry and the
    check that produced it, and every check in
    ``app/utils/record_review.py`` is a fact this program already derives for
    its own screens against a standard already implemented here. Whether a
    given finding matters is the review committee's to say — which is exactly
    what (d) puts people in the room for.
    """

    __tablename__ = "record_review_findings"

    id = db.Column(db.Integer, primary_key=True)
    item_id = db.Column(db.Integer, db.ForeignKey("record_review_items.id"),
                        nullable=False, index=True)

    #: Which check saw it — a key from ``record_review.CHECKS``.
    check = db.Column(db.String(40), nullable=False, index=True)
    #: Which entry it was seen on: ``visit`` · ``admission`` · ``operation``.
    entry_kind = db.Column(db.String(16), nullable=False)
    entry_id = db.Column(db.Integer, nullable=False)
    #: The date of the entry, copied in so a finding reads without a join to
    #: a row somebody may have corrected since.
    entry_on = db.Column(db.Date)

    item = db.relationship("RecordReviewItem",
                           backref=db.backref("findings",
                                              cascade="all, delete-orphan"))

    def __repr__(self):
        return f"<RecordReviewFinding {self.check}>"
