"""Antimicrobial stewardship — GAHAR MMS.02.

The intent lists the interventions a programme may choose (a–f) and how it
is tracked (g–k). Three of them are the program's to carry, and only with
the hospital's own choices in them:

* **restricted agents** (c, d) — the hospital's list, each with its own
  rule as the hospital words it; an order for one waits for the
  stewardship team's decision. *It is never held*: the dose is given while
  the decision is pending, because an antibiotic for a septic child does not
  wait for a signature, and the board shows the wait instead;
* **review once a culture is back** (d) — a running antimicrobial on a child
  whose culture was reported after the order started, with no review since;
* **consumption** (j) — days of therapy per 1000 patient-days, from the
  doses actually given.

Which drug classes count as antimicrobial is the hospital's choice too
(``utils/stewardship.CLASS_SETTING``); until it is made the consumption
says so instead of guessing.
"""
from datetime import datetime

from app.extensions import db

DECISIONS = ("approved", "continue", "change", "deescalate", "iv_to_po", "stop")
KINDS = ("approval", "culture")


class RestrictedAntimicrobial(db.Model):
    __tablename__ = "restricted_antimicrobials"

    id = db.Column(db.Integer, primary_key=True)
    generic_id = db.Column(db.Integer, db.ForeignKey("generic_drugs.id"), index=True)
    drug_id = db.Column(db.Integer, db.ForeignKey("drugs.id"), index=True)
    #: The hospital's rule, as it words it.
    rule = db.Column(db.String(255), nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)
    added_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    generic = db.relationship("GenericDrug")
    drug = db.relationship("Drug")

    def display_name(self, lang="ar"):
        if self.generic is not None:
            return self.generic.display_name(lang)
        if self.drug is not None:
            return getattr(self.drug, "trade_name", None) or ""
        return ""


class StewardshipReview(db.Model):
    __tablename__ = "stewardship_reviews"

    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("medication_orders.id"), nullable=False, index=True)
    kind = db.Column(db.String(10), nullable=False)
    decision = db.Column(db.String(12), nullable=False)
    note = db.Column(db.String(255))
    by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)

    order = db.relationship("MedicationOrder")
    by = db.relationship("User", foreign_keys=[by_id])
