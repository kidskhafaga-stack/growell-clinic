"""Visit / examination record (Phase 4).

A visit ties together the encounter context, vital signs, diagnoses and the
clinical narrative. Vital growth measurements taken during the visit are also
mirrored into growth_records for the growth charts (Phase 5).
"""
from datetime import datetime

from app.extensions import db

VISIT_STATUSES = ["open", "completed"]
INVESTIGATION_STATUSES = ["requested", "resulted"]


class Visit(db.Model):
    __tablename__ = "visits"

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(
        db.Integer, db.ForeignKey("patients.id"), nullable=False, index=True
    )
    doctor_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    appointment_id = db.Column(
        db.Integer, db.ForeignKey("appointments.id"), nullable=True
    )

    visit_date = db.Column(db.Date, nullable=False, default=lambda: datetime.utcnow().date())

    chief_complaint = db.Column(db.Text)
    clinical_exam = db.Column(db.Text)
    plan = db.Column(db.Text)
    notes = db.Column(db.Text)

    status = db.Column(db.String(20), default="open", nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    completed_at = db.Column(db.DateTime)

    patient = db.relationship("Patient", backref="visits")
    doctor = db.relationship("User", backref="visits")
    appointment = db.relationship("Appointment", backref="visit", uselist=False)
    vitals = db.relationship(
        "VitalSigns", back_populates="visit", uselist=False,
        cascade="all, delete-orphan",
    )
    diagnoses = db.relationship(
        "Diagnosis", back_populates="visit", cascade="all, delete-orphan",
        order_by="Diagnosis.id",
    )
    investigations = db.relationship(
        "VisitInvestigation", back_populates="visit",
        cascade="all, delete-orphan", order_by="VisitInvestigation.id",
    )
    attachments = db.relationship(
        "PatientAttachment", back_populates="visit",
        order_by="PatientAttachment.id",
    )
    services = db.relationship(
        "VisitService", back_populates="visit",
        cascade="all, delete-orphan", order_by="VisitService.id",
    )

    @property
    def is_completed(self):
        return self.status == "completed"

    def final_diagnoses(self):
        return [d for d in self.diagnoses if d.dx_type == "final"]

    def labs(self):
        return [x for x in self.investigations if x.kind == "lab"]

    def imaging(self):
        return [x for x in self.investigations if x.kind == "imaging"]

    def __repr__(self):
        return f"<Visit {self.id} p={self.patient_id} {self.visit_date}>"


class VisitInvestigation(db.Model):
    """A lab test / imaging study ordered during a visit, with its result.

    Lifecycle: ``requested`` when the doctor orders it, ``resulted`` once the
    result text / comment is entered.
    """
    __tablename__ = "visit_investigations"

    id = db.Column(db.Integer, primary_key=True)
    visit_id = db.Column(db.Integer, db.ForeignKey("visits.id"), nullable=False, index=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"), nullable=False, index=True)
    investigation_id = db.Column(db.Integer, db.ForeignKey("investigations.id"), nullable=True)

    kind = db.Column(db.String(12), default="lab", nullable=False)  # lab | imaging
    name = db.Column(db.String(200), nullable=False)     # Arabic / primary snapshot
    name_en = db.Column(db.String(200))                  # English snapshot (bilingual)
    request_notes = db.Column(db.String(255))

    status = db.Column(db.String(12), default="requested", nullable=False)
    result_text = db.Column(db.Text)        # the doctor's recorded result
    result_comment = db.Column(db.Text)     # the doctor's interpretation
    resulted_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    visit = db.relationship("Visit", back_populates="investigations")
    patient = db.relationship("Patient")
    investigation = db.relationship("Investigation")

    @property
    def has_result(self):
        return bool((self.result_text or "").strip() or (self.result_comment or "").strip())

    def display_name(self, lang="ar"):
        if lang == "en" and (self.name_en or "").strip():
            return self.name_en
        return self.name

    def __repr__(self):
        return f"<VisitInvestigation {self.kind}:{self.name} {self.status}>"


class VisitService(db.Model):
    """A chargeable procedure/service the doctor performs during a visit
    (e.g. echo, nebuliser). It flows into the visit's invoice as a line at the
    doctor's price; the clinical price is resolved at billing time.
    """
    __tablename__ = "visit_services"

    id = db.Column(db.Integer, primary_key=True)
    visit_id = db.Column(db.Integer, db.ForeignKey("visits.id"), nullable=False, index=True)
    service_id = db.Column(db.Integer, db.ForeignKey("services.id"), nullable=True)
    name = db.Column(db.String(200), nullable=False)   # snapshot
    quantity = db.Column(db.Integer, default=1, nullable=False)
    notes = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    visit = db.relationship("Visit", back_populates="services")
    service = db.relationship("Service")

    def __repr__(self):
        return f"<VisitService visit={self.visit_id} {self.name}>"


class PatientAttachment(db.Model):
    """A file uploaded to a patient's record (e.g. a lab/imaging report)."""
    __tablename__ = "patient_attachments"

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"), nullable=False, index=True)
    visit_id = db.Column(db.Integer, db.ForeignKey("visits.id"), nullable=True, index=True)

    filename = db.Column(db.String(255), nullable=False)   # stored name on disk
    original_name = db.Column(db.String(255))              # name shown to users
    kind = db.Column(db.String(20), default="report")      # report | result | other
    label = db.Column(db.String(160))
    uploaded_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    patient = db.relationship("Patient", backref="attachments")
    visit = db.relationship("Visit", back_populates="attachments")
    uploader = db.relationship("User")

    def __repr__(self):
        return f"<PatientAttachment p={self.patient_id} {self.filename}>"
