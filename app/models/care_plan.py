"""The one plan the other eleven standards point at — ICD.15.

> **ICD.15** An individualized plan of care is developed for **every patient**.
>
> a) Developed by all relevant disciplines providing care **under the
>    supervision of the most responsible physician**.
> b) **Based on assessments** of the patient performed by the various
>    healthcare disciplines… **including the result of diagnostic tests**.
> c) Developed with the **involvement of the patient and/or family** through
>    shared decision-making.
> d) Developed and updated according to **guidelines and patient needs and
>    preferences**.
> e) Includes **identified needs, interventions, and desired outcomes with
>    timeframes**.
> f) **Updated** as appropriate based on the reassessment of the patient.
> g) The **progress** of the patient in achieving the desired outcomes is
>    monitored.

**Seven elements, and three of them are already written down elsewhere.**
That split is the whole design, and it is the answer to «الاتنين»: the program
assembles what the record already holds, and a person writes only what nothing
in the record could know.

* **(ب) is read, entirely.** The assessments this plan stands on are the
  problem list, the risk assessments, the observations, the results and the
  medicines — all of them rows somebody already wrote. The plan **points at
  them and never copies them**, for the reason this codebase has given about
  the device studies and the lab curves: two copies of one reading are two
  chances to disagree, and the one on the plan would be the stale one.
* **(أ) is read but for one stamp.** Which disciplines contributed is the list
  of people who wrote those rows. *"Under the supervision of the most
  responsible physician"* is not derivable from anything — it is a claim about
  a named person, so it is a signature, like the operative report's.
* **(و) is derived.** "Updated as appropriate based on the reassessment" is a
  comparison of two moments: the newest assessment in the record against the
  last time anybody touched the plan. Stored, it would be a flag somebody has
  to remember to set; derived, it is right the second a nurse writes a reading.

What is left for a person is (ج), (د), (هـ) and (ز) — and (هـ) is the body.

---

**(هـ) is a list, not a paragraph.** *"identified needs, interventions, and
desired outcomes with timeframes"* — four things, and they belong to each
other one need at a time. One free-text box would hold all of them and let
nobody ask *which* outcome is overdue, which is exactly what (ز) then asks to
monitor. So the goals are rows, and the plan is their cover.
"""
from datetime import datetime

from app.extensions import db

#: (ز) — how one goal is going.
#:
#: ``open`` is the default and is honest as one: a goal written this morning
#: has no progress yet, and that is a different thing from a goal somebody
#: looked at and found unmet. The three-state nullable pattern is not used
#: here because "nobody said" **is** ``open`` — the absence has a name.
OPEN, PROGRESSING, MET, NOT_MET = ("open", "progressing", "met", "not_met")
GOAL_PROGRESS = (OPEN, PROGRESSING, MET, NOT_MET)


class CarePlan(db.Model):
    """One child's plan of care — the cover; the goals are the body."""

    __tablename__ = "care_plans"

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"),
                           nullable=False, index=True)
    # The stay it was written on, when there was one. **Nullable, and the
    # standard is why**: ICD.15 says *every patient*, not every inpatient, so a
    # plan that could only hang off an admission would have no room for the
    # child with asthma who is never admitted at all.
    admission_id = db.Column(db.Integer, db.ForeignKey("admissions.id"),
                             nullable=True, index=True)

    written_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    written_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    #: Touched whenever the plan or any of its goals changes. **(و) is read
    #: off this**, against the newest assessment in the record — see
    #: ``utils.care_plan.needs_update``.
    updated_at = db.Column(db.DateTime, default=datetime.utcnow,
                           onupdate=datetime.utcnow, nullable=False)

    # (أ) — its own stamp and its own person, like the operative report's.
    # Written and supervised are two events: a registrar drafts the plan, the
    # consultant signs it, and one stamp for both would be a claim about a
    # person rather than a record of one.
    mrp_signed_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    mrp_signed_at = db.Column(db.DateTime)

    # (ج) — ``None`` nobody said · ``False`` they were not involved · ``True``
    # they were. Evidence 3 asks a surveyor to *interview* the family about
    # this, so an empty box standing for "no" would be the program telling a
    # hospital it had done something the family will say it did not.
    family_involved = db.Column(db.Boolean)
    family_note = db.Column(db.Text)

    # (د) — the guideline this plan follows and what the family asked for.
    # Two boxes because they are two different sentences: `ICD.16` is the
    # hospital's adopted guideline, `PCC.12` is this child's preferences, and
    # one box would let either stand in for both.
    guideline = db.Column(db.String(200))
    preferences = db.Column(db.Text)

    patient = db.relationship("Patient", backref="care_plans")
    admission = db.relationship("Admission", backref="care_plans")
    author = db.relationship("User", foreign_keys=[written_by])
    signer = db.relationship("User", foreign_keys=[mrp_signed_by])
    goals = db.relationship("CarePlanGoal", back_populates="plan",
                            cascade="all, delete-orphan",
                            order_by="CarePlanGoal.id")

    @property
    def is_signed(self):
        """(أ) — whether the responsible physician has put their name to it."""
        return self.mrp_signed_at is not None

    @property
    def open_goals(self):
        """The goals still being worked on.

        Defined as *not closed* rather than by listing the two open words
        again. Spelling the same rule twice is how the two spellings come to
        disagree — a sweep found exactly that here: ``CarePlanGoal.is_closed``
        had no caller, so it could be made wrong with nothing noticing.
        """
        return [g for g in self.goals if not g.is_closed]

    @property
    def overdue_goals(self):
        """Goals whose timeframe has passed with the outcome not reached.

        **(هـ) is the reason this can be asked at all.** The standard asks for
        desired outcomes *with timeframes*, and a timeframe nothing ever
        compares against is a date in a box.
        """
        from app.utils.clock import local_today

        today = local_today()
        return [g for g in self.open_goals
                if g.by_when is not None and g.by_when < today]

    def __repr__(self):
        return f"<CarePlan patient={self.patient_id} goals={len(self.goals)}>"


class CarePlanGoal(db.Model):
    """One identified need, what is being done about it, and how it is going.

    Elements (هـ) and (ز) of ICD.15, in one row because they are one thought:
    the outcome being monitored is *this* need's outcome, and a table that
    kept them apart could not say which.
    """

    __tablename__ = "care_plan_goals"

    id = db.Column(db.Integer, primary_key=True)
    plan_id = db.Column(db.Integer, db.ForeignKey("care_plans.id"),
                        nullable=False, index=True)

    # (هـ) — the four the standard names, in its own order.
    need = db.Column(db.String(255), nullable=False)
    intervention = db.Column(db.Text)
    outcome = db.Column(db.Text)
    #: The timeframe. A date and not a duration: "in two weeks" is a sentence
    #: whose meaning moves every day it is read.
    by_when = db.Column(db.Date)

    # (ز)
    progress = db.Column(db.String(12), default=OPEN, nullable=False)
    progress_note = db.Column(db.Text)
    progress_at = db.Column(db.DateTime)
    progress_by = db.Column(db.Integer, db.ForeignKey("users.id"))

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    plan = db.relationship("CarePlan", back_populates="goals")
    reviewer = db.relationship("User", foreign_keys=[progress_by])

    @property
    def is_closed(self):
        return self.progress in (MET, NOT_MET)

    def __repr__(self):
        return f"<CarePlanGoal {self.need!r} {self.progress}>"
