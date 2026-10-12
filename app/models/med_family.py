"""The family and the medicines — GAHAR MMS.14 ev. 4, MMS.15 ev. 3 and 5,
MMS.16 ev. 2.

* **counselling** (MMS.14 ev. 4, MMS.15 ev. 3): the family told about a
  medicine on the ward, or counselled by the pharmacist at discharge — to
  whom, and whether they were given the chance to ask;
* **self-administration** (MMS.15 ev. 5): a medicine the child or the family
  gives under the ward's eye — who, who taught them, whether they showed
  they can, and how it is supervised; ended when it stops;
* **first-dose watch** (MMS.16 ev. 2): the hospital's list of medicines whose
  first dose is watched and for what, in its words; a first dose given of
  one of them stays on the stay until somebody writes what was seen.
"""
from datetime import datetime

from app.extensions import db

COUNSEL_KINDS = ("informed", "discharge")
SELF_BY = ("patient", "family")
WATCH_OUTCOMES = ("nothing", "reaction")


class MedCounselling(db.Model):
    __tablename__ = "med_counselling"

    id = db.Column(db.Integer, primary_key=True)
    admission_id = db.Column(db.Integer, db.ForeignKey("admissions.id"), nullable=False, index=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"), nullable=False, index=True)
    kind = db.Column(db.String(10), nullable=False)
    order_id = db.Column(db.Integer, db.ForeignKey("medication_orders.id"))
    to_whom = db.Column(db.String(120), nullable=False)
    questions = db.Column(db.Boolean, default=False, nullable=False)
    note = db.Column(db.String(255))
    by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    by = db.relationship("User", foreign_keys=[by_id])


class SelfAdministration(db.Model):
    __tablename__ = "self_administrations"

    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("medication_orders.id"), nullable=False, index=True)
    by_whom = db.Column(db.String(8), nullable=False)
    taught_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    taught_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    able = db.Column(db.Boolean, nullable=False)
    supervision = db.Column(db.String(255), nullable=False)
    ended_at = db.Column(db.DateTime)

    teacher = db.relationship("User", foreign_keys=[taught_by])


class FirstDoseWatch(db.Model):
    __tablename__ = "first_dose_watch"

    id = db.Column(db.Integer, primary_key=True)
    generic_id = db.Column(db.Integer, db.ForeignKey("generic_drugs.id"), nullable=False, index=True)
    watch_for = db.Column(db.String(255), nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    generic = db.relationship("GenericDrug")


class FirstDoseObservation(db.Model):
    __tablename__ = "first_dose_observations"

    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("medication_orders.id"), nullable=False,
                         unique=True, index=True)
    outcome = db.Column(db.String(10), nullable=False)
    note = db.Column(db.String(255))
    by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
