"""An adverse drug reaction in a child — GAHAR MMS.16 ev. 3–5.

*"Actual or potential medication adverse drug effects on patients are
monitored and documented in the patient's record, including the action(s)
to be taken in response"* (3), *"reported in a manner consistent with
national and international guidelines"* (4), and *"a process for informing
the prescriber"* (5).

So one row carries the drug, what happened and when, what was done, who
told the prescriber and when, and the report to the national
pharmacovigilance centre — with its reference, because "reported" without a
number is a claim. Whether the drug goes on the child's allergy line is a
person's decision, ticked on the form; it is never added by the program.
"""
from datetime import datetime

from app.extensions import db

SEVERITIES = ("mild", "moderate", "severe")


class AdverseReaction(db.Model):
    __tablename__ = "adverse_reactions"

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"), nullable=False, index=True)
    admission_id = db.Column(db.Integer, db.ForeignKey("admissions.id"), index=True)
    order_id = db.Column(db.Integer, db.ForeignKey("medication_orders.id"))
    drug_name = db.Column(db.String(160), nullable=False)
    onset_at = db.Column(db.DateTime, nullable=False)
    what_happened = db.Column(db.Text, nullable=False)
    severity = db.Column(db.String(10), nullable=False)
    action_taken = db.Column(db.String(255), nullable=False)
    recorded_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    recorded_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    #: (5) the prescriber told — whom, and when.
    prescriber_told = db.Column(db.String(120))
    prescriber_told_at = db.Column(db.DateTime)
    #: (4) the national report and its reference.
    reported_at = db.Column(db.DateTime)
    report_ref = db.Column(db.String(80))
    reported_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    added_to_allergies = db.Column(db.Boolean, default=False, nullable=False)

    patient = db.relationship("Patient")
    recorder = db.relationship("User", foreign_keys=[recorded_by])
