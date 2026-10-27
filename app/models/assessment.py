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


class AssessmentShare(db.Model):
    """An approved assessment sent to the family (ASSESSMENTS_PLAN.md ت-٣) —
    the same way a lab result goes (``models/result_share``): a link that
    asks the child's date of birth, ends after its days and locks after five
    wrong answers when the clinic can be reached from outside; the report
    itself as a file when it cannot."""

    __tablename__ = "assessment_shares"

    id = db.Column(db.Integer, primary_key=True)
    token = db.Column(db.String(48), unique=True, nullable=False, index=True)
    assessment_id = db.Column(db.Integer, db.ForeignKey("assessments.id"),
                              nullable=False, index=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"),
                           nullable=False, index=True)
    mode = db.Column(db.String(6), nullable=False, default="link")
    to_phone = db.Column(db.String(40))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    expires_at = db.Column(db.DateTime, nullable=False)
    opened_at = db.Column(db.DateTime)
    opens = db.Column(db.Integer, default=0, nullable=False)
    failures = db.Column(db.Integer, default=0, nullable=False)
    message_id = db.Column(db.Integer, db.ForeignKey("message_logs.id"))

    assessment = db.relationship("Assessment")
    patient = db.relationship("Patient")
    sender = db.relationship("User", foreign_keys=[created_by])

    @property
    def locked(self):
        from app.models.result_share import MAX_FAILURES

        return (self.failures or 0) >= MAX_FAILURES

    @property
    def expired(self):
        return datetime.utcnow() > self.expires_at


class QuestionnaireText(db.Model):
    """The clinic's wording of one questionnaire (ASSESSMENTS_PLAN.md ت-٤).

    The program carries each questionnaire's **shape** only
    (``data/questionnaires.json``): how many items, each choice's points,
    which items are reversed, and how each part is counted. The questions
    and the choices are words somebody owns, so the clinic types them from
    its own licensed copy, writes whose permission it uses, and a doctor
    opens it. Until then the questionnaire does not appear anywhere.

    Changing the wording of an open questionnaire closes it again until a
    doctor reopens it; a questionnaire already sent keeps the words it was
    sent with (``QuestionnaireRequest.form``).
    """

    __tablename__ = "questionnaire_texts"

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(40), unique=True, nullable=False, index=True)
    #: ``draft`` until a doctor opens it, ``active`` while it may be sent,
    #: ``off`` when the clinic stopped it.
    status = db.Column(db.String(10), nullable=False, default="draft")
    holder = db.Column(db.String(200))
    ref = db.Column(db.String(300))
    notice = db.Column(db.Text)
    intro_ar = db.Column(db.Text)
    intro_en = db.Column(db.Text)
    #: ``[{"ar": ..., "en": ...}]`` in item order.
    items = db.Column(db.JSON, nullable=False, default=list)
    #: ``{scale: [{"ar": ..., "en": ...}]}`` in the order of the scale's points.
    options = db.Column(db.JSON, nullable=False, default=dict)
    approved_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    approved_at = db.Column(db.DateTime)
    approval_note = db.Column(db.String(255))
    updated_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    updated_at = db.Column(db.DateTime, default=datetime.utcnow,
                           onupdate=datetime.utcnow, nullable=False)

    approver = db.relationship("User", foreign_keys=[approved_by])
    editor = db.relationship("User", foreign_keys=[updated_by])


class QuestionnaireRequest(db.Model):
    """One questionnaire handed to a parent, a teacher or the child for one
    assessment (ت-٤): on the clinic's tablet, as a link, or on paper the
    specialist types in afterwards.

    It carries the questionnaire as it was sent (``form``), the answers, and
    the scores those answers make. The scores reach the assessment only when
    the specialist presses «put the scores in» — nothing writes itself into
    a child's record.
    """

    __tablename__ = "questionnaire_requests"

    id = db.Column(db.Integer, primary_key=True)
    token = db.Column(db.String(48), unique=True, nullable=False, index=True)
    key = db.Column(db.String(40), nullable=False, index=True)
    assessment_id = db.Column(db.Integer, db.ForeignKey("assessments.id"),
                              nullable=False, index=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"),
                           nullable=False, index=True)
    #: ``parent``, ``teacher`` or ``self``.
    informant = db.Column(db.String(10), nullable=False, default="parent")
    #: ``tablet``, ``link`` or ``paper``.
    mode = db.Column(db.String(6), nullable=False, default="tablet")
    #: The teacher's or parent's name, when the specialist wrote one.
    respondent = db.Column(db.String(120))
    to_phone = db.Column(db.String(40))
    lang = db.Column(db.String(2), nullable=False, default="ar")
    form = db.Column(db.JSON, nullable=False)
    #: ``{"<item number>": points}`` as answered.
    answers = db.Column(db.JSON)
    #: ``{part: value or None}`` — ``None`` where too few items were answered.
    scores = db.Column(db.JSON)
    #: ``open`` → ``done`` (answered) → ``used`` (in the assessment), or
    #: ``cancelled``.
    status = db.Column(db.String(10), nullable=False, default="open", index=True)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    opened_at = db.Column(db.DateTime)
    answered_at = db.Column(db.DateTime)
    #: Set when the answers were typed in from paper by a member of staff.
    entered_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    used_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    used_at = db.Column(db.DateTime)
    message_id = db.Column(db.Integer, db.ForeignKey("message_logs.id"))

    assessment = db.relationship("Assessment")
    patient = db.relationship("Patient")
    sender = db.relationship("User", foreign_keys=[created_by])
    enterer = db.relationship("User", foreign_keys=[entered_by])
    user = db.relationship("User", foreign_keys=[used_by])

    @property
    def expired(self):
        return datetime.utcnow() > self.expires_at

    @property
    def answerable(self):
        return self.status == "open" and not self.expired
