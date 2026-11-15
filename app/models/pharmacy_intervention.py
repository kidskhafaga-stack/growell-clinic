"""A clinical pharmacist's intervention — a row that can be counted.

``HOSPITAL_PLAN.md`` مرحلة ج ٧، ص-١. The owner sent a hospital's «Clinical
Pharmacy Intervention Form» and asked whether it helps the module; it does.
The program already let a pharmacist ask about a running order and the doctor
answer (``MedicationOrder.query_note``) — but in free text, so nothing could
be counted: how many dosing errors on the ward this month, how many the
doctors accepted, how many were urgent. The form's own boxes are the answer,
and they are kept here as they are on the paper:

* **the drug therapy problem**, with its sub-kind where the form has one —
  the dose, the frequency, the route or the rate; a drug–drug, drug–food or
  drug–laboratory interaction;
* **how urgent** the action is;
* **what it is expected to achieve**;
* **what the doctor did with it** — accepted, accepted with a change, or
  rejected;

each with its comment, and who and when on both sides.

**Its own row on the stay**, linked to an order or to a dose when there is
one: «a condition with no drug ordered for it» has no order to hang on, and
«prescribed and not given» is about a dose a nurse recorded, not about the
order. And like the question it extends, **it never stops a drug** — it is a
pharmacist's recommendation and the prescriber's decision.

The classification is the form's, not a clinical rule: nothing here decides
whether a dose is wrong.
"""
from datetime import datetime

from app.extensions import db

#: The form's «Drug therapy problems», in its order, with the sub-kinds it
#: prints under some of them.
PROBLEMS = {
    "no_indication": (),
    "dosage": ("dose", "frequency", "route", "rate"),
    "interaction": ("drug_drug", "drug_food", "drug_lab", "other"),
    "untreated_condition": (),
    "not_administered": (),
    "wrong_drug": (),
    "adverse_reaction": (),
    "other": (),
}
#: «Necessity of taking an action».
SEVERITIES = ("high", "moderate", "minor")
#: «Expected outcome».
OUTCOMES = ("adr_prevented", "enhance_effect", "cost_saving")
#: «Acceptance» — and ``pending`` until the doctor has said.
RESPONSES = ("pending", "accepted", "modified", "rejected")
#: The problems that are about no order at all.
NO_ORDER = ("untreated_condition",)

PREFIX = "PI"


class PharmacyIntervention(db.Model):
    __tablename__ = "pharmacy_interventions"

    id = db.Column(db.Integer, primary_key=True)
    number = db.Column(db.String(30), unique=True, nullable=False, index=True)
    admission_id = db.Column(db.Integer, db.ForeignKey("admissions.id"),
                             nullable=False, index=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"),
                           nullable=False, index=True)
    order_id = db.Column(db.Integer, db.ForeignKey("medication_orders.id"),
                         index=True)
    dose_id = db.Column(db.Integer, db.ForeignKey("medication_doses.id"))

    problem = db.Column(db.String(24), nullable=False, index=True)
    detail = db.Column(db.String(16))
    # «reviewed with the consultant» — printed under «no indication».
    with_consultant = db.Column(db.Boolean, default=False, nullable=False)
    problem_note = db.Column(db.String(500))
    severity = db.Column(db.String(10), nullable=False, index=True)
    severity_note = db.Column(db.String(255))
    outcome = db.Column(db.String(16), nullable=False, index=True)
    outcome_note = db.Column(db.String(255))

    response = db.Column(db.String(10), default="pending", nullable=False,
                         index=True)
    response_note = db.Column(db.String(255))
    responded_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    responded_at = db.Column(db.DateTime)

    created_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow,
                           nullable=False, index=True)

    admission = db.relationship("Admission", backref="interventions")
    patient = db.relationship("Patient")
    order = db.relationship("MedicationOrder")
    dose = db.relationship("MedicationDose")
    pharmacist = db.relationship("User", foreign_keys=[created_by])
    responder = db.relationship("User", foreign_keys=[responded_by])

    @property
    def is_open(self):
        return self.response == "pending"

    def __repr__(self):
        return f"<PharmacyIntervention {self.number} {self.problem}>"


def next_number():
    """``PI-000001``, its own series."""
    from app.utils.sequences import highest

    base = f"{PREFIX}-"
    seq = highest(PharmacyIntervention.number, base) + 1
    candidate = f"{base}{seq:06d}"
    while PharmacyIntervention.query.filter_by(number=candidate).first():
        seq += 1
        candidate = f"{base}{seq:06d}"
    return candidate
