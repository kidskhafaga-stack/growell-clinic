"""The assessment before the knife — GAHAR SAS.03.

*"Comprehensive medical and nursing assessment is performed before surgical
and invasive procedures."* Five pieces of evidence:

1. a complete pre-operative **medical** assessment;
2. a complete pre-operative **nursing** assessment;
3. investigation results available before the procedure — answered by the
   work-up already attached to the case (SAS.06 e), not asked again;
4. the patient's identified **risks documented** before the procedure;
5. **action taken** to manage them before the procedure.

The program already had a *verdict* (`PreOpReview`: fit · with conditions ·
unfit) and no assessment behind it. A verdict with nothing under it is the
end of an assessment with the assessment missing, and a surveyor reading the
record cannot see what "fit" was concluded from.

**What the record knows is not typed again.** Allergies, the medicines the
child is on and the active problem list are shown beside the form; the
surgeon writes what only an examination can say.

**And the risk scale is the hospital's.** A risk class is picked from a list
the hospital writes (:data:`RISK_CLASS_DOMAIN`), empty until it does — the
program does not choose a classification for it, as it chose no pain tool.
"""
from datetime import datetime

from app.extensions import db

MEDICAL, NURSING = "medical", "nursing"
KINDS = (MEDICAL, NURSING)

#: The hospital's risk classification — a `Lookup` domain, empty at first.
RISK_CLASS_DOMAIN = "surgical_risk_class"


class PreOpAssessment(db.Model):
    """One case's medical or nursing assessment before the procedure."""

    __tablename__ = "preop_assessments"
    __table_args__ = (
        # One of each per case. A second medical assessment on the same
        # booking would leave two accounts and no way to say which the team
        # went into theatre on. A postponed case is a new booking, and starts
        # its own — which is the standard's "reviewed and repeated".
        db.UniqueConstraint("operation_id", "kind", name="uq_preop_assessment"),
    )

    id = db.Column(db.Integer, primary_key=True)
    operation_id = db.Column(db.Integer, db.ForeignKey("operations.id"),
                             nullable=False, index=True)
    kind = db.Column(db.String(10), nullable=False)

    # ---- medical (EOC 1) — the surgeon's words ----
    indication = db.Column(db.Text)       # why this operation, this child
    history = db.Column(db.Text)          # medical · surgical · anaesthetic · bleeding
    examination = db.Column(db.Text)
    risk_class = db.Column(db.String(40))  # a key from the hospital's list
    # "I looked, and there is nothing to manage" — a real answer, and not the
    # same as a list nobody filled. Nullable: nobody said.
    risks_none = db.Column(db.Boolean)

    # ---- nursing (EOC 2) ----
    fasting_food_at = db.Column(db.DateTime)   # last solid food, UTC
    fasting_fluid_at = db.Column(db.DateTime)  # last clear fluid, UTC
    weight_kg = db.Column(db.Float)
    vitals = db.Column(db.String(200))
    # The allergies on file were read back to the family. Tri-state.
    allergies_checked = db.Column(db.Boolean)
    general = db.Column(db.Text)          # skin · loose teeth · general state

    at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    by_id = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)

    operation = db.relationship("Operation", backref=db.backref(
        "preop_assessments", cascade="all, delete-orphan"))
    by = db.relationship("User")

    def __repr__(self):
        return f"<PreOpAssessment {self.kind} op={self.operation_id}>"


class PreOpRisk(db.Model):
    """One identified risk (EOC 4), and what was done about it (EOC 5)."""

    __tablename__ = "preop_risks"

    id = db.Column(db.Integer, primary_key=True)
    operation_id = db.Column(db.Integer, db.ForeignKey("operations.id"),
                             nullable=False, index=True)
    risk = db.Column(db.String(255), nullable=False)
    noted_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    noted_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    # The action, and the moment it was taken. Separate from the risk because
    # "anaemia" is written on Monday and "transfused, Hb 11" on Wednesday.
    action = db.Column(db.String(255))
    managed_at = db.Column(db.DateTime)
    managed_by = db.Column(db.Integer, db.ForeignKey("users.id"))

    operation = db.relationship("Operation", backref=db.backref(
        "preop_risks", cascade="all, delete-orphan",
        order_by="PreOpRisk.noted_at"))

    @property
    def managed(self):
        return self.managed_at is not None

    def __repr__(self):
        return f"<PreOpRisk op={self.operation_id} {self.risk!r}>"
