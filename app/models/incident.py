"""An incident report — GAHAR QPI.10 (the incident-reporting system), QPI.11
(sentinel events) and DAS.23 / GSR.13 (the laboratory's incidents).

«أي موظف يبلّغ، بالاسم أو من غير اسم» — anybody with an account reports,
and may leave their name off: **nothing here records who made a mistake**,
the same rule as the medication-error log (``models/med_error``), because a
reporting system that blames collects nothing after the first month.

The report is what happened, when, where, to whom, and what was done at
once. The rest belongs to whoever holds ``incident_manage`` — «الجودة
وسلامة المرضى»: the classification in the standard's own words (near miss,
adverse event with or without harm, sentinel event), the investigation and
the gaps it found, the corrective and preventive action, telling the family
(QPI.10 evidence 5) and, for a sentinel event, the root cause analysis and
the external report (QPI.11).

Medication errors and equipment incidents keep their own screens and appear
beside these on the board — written once, read in one place.
"""
from datetime import datetime

from app.extensions import db

#: What it was about — operational buckets, not clinical judgements.
CATEGORIES = ("patient_care", "fall", "injury", "infection", "security",
              "violence", "facility", "documentation", "laboratory", "other")
#: Who it touched.
AFFECTED = ("patient", "staff", "visitor", "none")
#: QPI.11's own definitions.
NEAR_MISS, NO_HARM, HARM, SENTINEL = ("near_miss", "adverse_no_harm",
                                      "adverse_harm", "sentinel")
CLASSES = (NEAR_MISS, NO_HARM, HARM, SENTINEL)
NEW, INVESTIGATING, CLOSED = ("new", "investigating", "closed")
STATUSES = (NEW, INVESTIGATING, CLOSED)


class Incident(db.Model):
    __tablename__ = "incidents"

    id = db.Column(db.Integer, primary_key=True)
    number = db.Column(db.String(24), unique=True, nullable=False, index=True)
    occurred_at = db.Column(db.DateTime, nullable=False, index=True)
    reported_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    #: Empty when the reporter chose to leave their name off.
    reported_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    unit_id = db.Column(db.Integer, db.ForeignKey("care_units.id"))
    area = db.Column(db.String(120))
    category = db.Column(db.String(20), nullable=False, index=True)
    affected = db.Column(db.String(10), nullable=False)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"), index=True)
    what_happened = db.Column(db.Text, nullable=False)
    immediate_action = db.Column(db.Text)
    #: The reporter's word that someone died or was seriously harmed — QPI.10
    #: (d), told to management at once, before anybody has classified it.
    serious = db.Column(db.Boolean, default=False, nullable=False, index=True)

    status = db.Column(db.String(14), default=NEW, nullable=False, index=True)
    classification = db.Column(db.String(16), index=True)
    findings = db.Column(db.Text)
    root_cause = db.Column(db.Text)
    action = db.Column(db.Text)
    action_owner = db.Column(db.String(160))
    action_due = db.Column(db.Date)
    family_told = db.Column(db.Text)
    external_report = db.Column(db.Text)
    reviewed_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    reviewed_at = db.Column(db.DateTime)
    closed_at = db.Column(db.DateTime)

    unit = db.relationship("Unit")
    patient = db.relationship("Patient")
    reporter = db.relationship("User", foreign_keys=[reported_by])
    reviewer = db.relationship("User", foreign_keys=[reviewed_by])

    def area_name(self, lang="ar"):
        if self.unit is not None:
            return self.unit.display_name(lang)
        return self.area or "—"
