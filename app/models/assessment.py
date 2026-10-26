"""Assessments — ASSESSMENTS_PLAN.md ت-١.

*«بتاعت الأعصاب شغالة على الحاجات دي وعايز أسهّل استخدامهم … يشيّك حاجة في
التقييم ويحط الدرجات، ويبقى في شكل افتراضي حسب الجايدلاين ويقدر يعدّل هو
عليه.»*

* **AssessmentForm** — the clinic's own copy of one kind's form, when it
  edited it. Absent, the default from ``data/assessments.json`` is used.
* **Assessment** — one child's assessment: the form it was filled on (a copy,
  so editing the form tomorrow never changes what was written today), the
  answers, who wrote it, and the doctor who approved it.

The program records and adds up; it never interprets (`utils/assessments`).
"""
from datetime import datetime

from app.extensions import db

DRAFT, REVIEW, APPROVED = "draft", "review", "approved"
STATES = (DRAFT, REVIEW, APPROVED)


class AssessmentForm(db.Model):
    __tablename__ = "assessment_forms"

    id = db.Column(db.Integer, primary_key=True)
    kind = db.Column(db.String(40), unique=True, nullable=False, index=True)
    #: The edited form, the same shape as the default's.
    form = db.Column(db.JSON, nullable=False)
    updated_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    updated_at = db.Column(db.DateTime, default=datetime.utcnow,
                           onupdate=datetime.utcnow, nullable=False)

    editor = db.relationship("User")


class Assessment(db.Model):
    __tablename__ = "assessments"

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"),
                           nullable=False, index=True)
    visit_id = db.Column(db.Integer, db.ForeignKey("visits.id"), index=True)
    kind = db.Column(db.String(40), nullable=False, index=True)
    #: The form as it stood when this assessment was started.
    form = db.Column(db.JSON, nullable=False)
    #: ``{section_key: value}``; tools as ``{"tools": {tool_key: {field: n}}}``.
    answers = db.Column(db.JSON, nullable=False, default=dict)
    assessed_on = db.Column(db.Date, nullable=False, index=True)
    status = db.Column(db.String(10), nullable=False, default=DRAFT, index=True)
    assessor_id = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)
    approved_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    approved_at = db.Column(db.DateTime)
    #: The approving doctor's own words, beside the specialist's impression.
    doctor_note = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow,
                           onupdate=datetime.utcnow, nullable=False)

    patient = db.relationship("Patient")
    visit = db.relationship("Visit")
    assessor = db.relationship("User", foreign_keys=[assessor_id])
    approver = db.relationship("User", foreign_keys=[approved_by])

    @property
    def is_approved(self):
        return self.status == APPROVED

    def __repr__(self):
        return f"<Assessment {self.kind} {self.patient_id} {self.status}>"
