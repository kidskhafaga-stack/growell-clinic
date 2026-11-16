"""A form the clinic draws itself, and each time it is filled.

``FORM_BUILDER_PLAN.md``. The program had seven small editors, each shut on
one thing — the satisfaction survey, an insurer's claim form, a specialty's
readings — and none let a clinic make a form of its own. This is that form.

**The fields are JSON on the form**, each ``{"key", "type", "label_ar",
"label_en", "required", "hidden", "options": [{"key", "ar", "en"}], "unit",
"min", "max"}``. A field's ``key`` is made once and never changes, and nor
does its type: answers are stored by key, and a key that meant something
else last month would make last month's numbers lie. A field that has been
answered is hidden, not deleted, and an option somebody chose is never
removed (``utils/custom_forms.py``).

**Each entry keeps the form as it was** (``snapshot`` and ``version``), so
an old entry reads and prints as it was filled, whatever the form became.
"""
import json
from datetime import datetime

from app.extensions import db

#: Where a form is filled. ``admission`` exists only where the wards do.
PLACES = ("patient", "visit", "admission")
#: Who fills it: ``clinical`` needs the medical file; ``desk`` anybody who
#: opens patients.
AUDIENCES = ("clinical", "desk")
#: The kinds of field. ``heading`` holds no answer; it titles a section.
TYPES = ("heading", "text", "textarea", "number", "date", "yesno",
         "choice", "multi")


class CustomForm(db.Model):
    __tablename__ = "custom_forms"

    id = db.Column(db.Integer, primary_key=True)
    name_ar = db.Column(db.String(160), nullable=False)
    name_en = db.Column(db.String(160))
    note = db.Column(db.String(500))
    place = db.Column(db.String(12), nullable=False, default="patient")
    audience = db.Column(db.String(10), nullable=False, default="clinical")
    fields_json = db.Column(db.Text, nullable=False, default="[]")
    # Raised by every change to the fields, so each entry can say which
    # shape it was filled on.
    version = db.Column(db.Integer, nullable=False, default=1)
    # Next number for a field key: ``f1``, ``f2``… never reused.
    next_key = db.Column(db.Integer, nullable=False, default=1)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow,
                           nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow,
                           onupdate=datetime.utcnow)

    entries = db.relationship("FormEntry", back_populates="form",
                              lazy="dynamic")

    @property
    def fields(self):
        try:
            return json.loads(self.fields_json or "[]")
        except ValueError:
            return []

    @fields.setter
    def fields(self, value):
        self.fields_json = json.dumps(value, ensure_ascii=False)

    def display_name(self, lang="ar"):
        return self.name_en if (lang == "en" and self.name_en) \
            else self.name_ar


class FormEntry(db.Model):
    __tablename__ = "form_entries"

    id = db.Column(db.Integer, primary_key=True)
    form_id = db.Column(db.Integer, db.ForeignKey("custom_forms.id"),
                        nullable=False, index=True)
    form_version = db.Column(db.Integer, nullable=False)
    # The fields as they were when this entry was filled.
    snapshot_json = db.Column(db.Text, nullable=False)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"),
                           nullable=False, index=True)
    visit_id = db.Column(db.Integer, db.ForeignKey("visits.id"), index=True)
    admission_id = db.Column(db.Integer, db.ForeignKey("admissions.id"),
                             index=True)
    answers_json = db.Column(db.Text, nullable=False, default="{}")
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow,
                           nullable=False, index=True)
    updated_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    updated_at = db.Column(db.DateTime)

    form = db.relationship("CustomForm", back_populates="entries")
    patient = db.relationship("Patient")

    @property
    def snapshot(self):
        try:
            return json.loads(self.snapshot_json or "[]")
        except ValueError:
            return []

    @property
    def answers(self):
        try:
            return json.loads(self.answers_json or "{}")
        except ValueError:
            return {}

    @answers.setter
    def answers(self, value):
        self.answers_json = json.dumps(value, ensure_ascii=False)
