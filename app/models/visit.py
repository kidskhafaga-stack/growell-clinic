"""Visit / examination record (Phase 4).

A visit ties together the encounter context, vital signs, diagnoses and the
clinical narrative. Vital growth measurements taken during the visit are also
mirrored into growth_records for the growth charts (Phase 5).
"""
from datetime import datetime

from app.extensions import db
from app.utils.clock import local_today

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

    visit_date = db.Column(db.Date, nullable=False, default=local_today)

    chief_complaint = db.Column(db.Text)
    clinical_exam = db.Column(db.Text)
    plan = db.Column(db.Text)
    notes = db.Column(db.Text)

    status = db.Column(db.String(20), default="open", nullable=False, index=True)
    # Where the encounter happened. A decision taken over WhatsApp is a real
    # consultation and belongs in the child's history like any other — but
    # *which* it was is part of the record, not a detail: a year later,
    # whoever reads the file has to understand why the medicine changed on a
    # day the child never came in.
    channel = db.Column(db.String(12), default="clinic", nullable=False,
                        index=True)              # clinic | whatsapp
    # What the doctor decided, when this visit is a remote follow-up.
    decision = db.Column(db.String(16))          # continue | change | investigate
    # The result it was decided on — so the answer, the decision and the
    # question it came from are one chain rather than three loose rows.
    based_on_id = db.Column(db.Integer,
                            db.ForeignKey("visit_investigations.id"),
                            nullable=True, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    completed_at = db.Column(db.DateTime)

    # What the doctor wants the nurse to do — written in the room, read at the
    # station. It was being said out loud across a corridor, which is how an
    # instruction reaches the wrong child or nobody at all.
    nurse_instructions = db.Column(db.Text)

    # Sent to emergency. Recorded rather than remembered: the child leaves the
    # clinic mid-encounter, and the visit that stays behind has to say where
    # they went and why, or it reads as a consultation somebody abandoned.
    referred_at = db.Column(db.DateTime)
    referred_to = db.Column(db.String(120))
    referral_note = db.Column(db.Text)

    @property
    def is_referred(self):
        return self.referred_at is not None

    patient = db.relationship("Patient", backref="visits")
    doctor = db.relationship("User", backref="visits")
    based_on = db.relationship("VisitInvestigation",
                               foreign_keys=[based_on_id])
    appointment = db.relationship("Appointment", backref="visit", uselist=False)
    vitals = db.relationship(
        "VitalSigns", back_populates="visit", uselist=False,
        cascade="all, delete-orphan",
    )
    diagnoses = db.relationship(
        "Diagnosis", back_populates="visit", cascade="all, delete-orphan",
        order_by="Diagnosis.id",
    )
    # Two foreign keys now run between these tables — the orders raised *in*
    # this visit, and (on a remote follow-up) the one result it was decided
    # *on*. Each relationship has to say which key it means.
    investigations = db.relationship(
        "VisitInvestigation", back_populates="visit",
        foreign_keys="VisitInvestigation.visit_id",
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
    medications = db.relationship(
        "VisitMedication", back_populates="visit",
        cascade="all, delete-orphan", order_by="VisitMedication.id",
    )
    # Device studies performed in this visit (spirometry, echo, ultrasound…).
    # Kept without cascade: a study is a clinical record of its own and must
    # outlive the visit row it happened in.
    studies = db.relationship(
        "DeviceStudy", back_populates="visit", order_by="DeviceStudy.id",
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

    visit = db.relationship("Visit", back_populates="investigations",
                            foreign_keys=[visit_id])
    patient = db.relationship("Patient")
    investigation = db.relationship("Investigation")

    @property
    def has_result(self):
        return bool((self.result_text or "").strip() or (self.result_comment or "").strip())

    @property
    def result_state(self):
        """Where this order has got to — three states, not two.

        ``requested``  nothing has come back yet;
        ``arrived``    the family sent the film/report, nobody has read it;
        ``resulted``   a doctor read it and wrote what it says.

        The middle one is the one that used to be invisible. An order that
        has been answered but not read is neither "waiting on the patient"
        nor "done", and treating it as the first is how a film sits unread
        while everyone assumes the family never went.
        """
        if self.has_result:
            return "resulted"
        return "arrived" if self.files else "requested"

    @property
    def arrived_at(self):
        """When the first answer to this order reached the clinic."""
        times = [f.created_at for f in (self.files or []) if f.created_at]
        return min(times) if times else None

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
    # Set once the line lands on an invoice — the "billed" marker that keeps a
    # doctor-added service from being charged twice (same guard vaccines have).
    invoice_id = db.Column(db.Integer, db.ForeignKey("invoices.id"), nullable=True)
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
    # The order this file answers, when it answers one. A chest film that
    # arrives on WhatsApp belongs *to* the chest film the doctor asked for —
    # filed loose in the documents folder, somebody has to remember it exists.
    investigation_id = db.Column(db.Integer,
                                 db.ForeignKey("visit_investigations.id"),
                                 nullable=True, index=True)

    filename = db.Column(db.String(255), nullable=False)   # stored name on disk
    original_name = db.Column(db.String(255))              # name shown to users
    kind = db.Column(db.String(20), default="report")      # report | result | other
    label = db.Column(db.String(160))
    # How it reached the clinic. "The mother sent it on WhatsApp on Tuesday"
    # is a different fact from "somebody scanned it at the desk", and the
    # doctor reading it wants to know which.
    source = db.Column(db.String(20), default="upload")     # whatsapp | upload
    uploaded_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    # Who tied this file to an order. NULL while the link is only the
    # program's guess — a guess a doctor should be able to see as a guess.
    linked_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    linked_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    patient = db.relationship("Patient", backref="attachments")
    visit = db.relationship("Visit", back_populates="attachments")
    investigation = db.relationship("VisitInvestigation", backref="files")
    uploader = db.relationship("User", foreign_keys=[uploaded_by])
    linker = db.relationship("User", foreign_keys=[linked_by])

    @property
    def arrived_by_whatsapp(self):
        return self.source == "whatsapp"

    @property
    def link_is_a_guess(self):
        """Linked by the matcher, not by a person who looked at it."""
        return self.investigation_id is not None and self.linked_by is None

    def __repr__(self):
        return f"<PatientAttachment p={self.patient_id} {self.filename}>"


class VisitMedication(db.Model):
    """A medicine the doctor wrote **during the visit**.

    Drugs used to exist only on a prescription, so a doctor who wrote them in
    the room had to type them again to print. They now behave like the visit's
    investigations: recorded in the exam, carried over to the prescription,
    and checked for interactions and paediatric dosing on the spot.
    """
    __tablename__ = "visit_medications"

    id = db.Column(db.Integer, primary_key=True)
    visit_id = db.Column(db.Integer, db.ForeignKey("visits.id"), nullable=False, index=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"), nullable=False, index=True)
    drug_id = db.Column(db.Integer, db.ForeignKey("drugs.id"), nullable=True)
    generic_id = db.Column(db.Integer, db.ForeignKey("generic_drugs.id"), nullable=True)

    name = db.Column(db.String(200), nullable=False)     # snapshot as written
    dose = db.Column(db.String(120))
    frequency = db.Column(db.String(120))
    duration = db.Column(db.String(120))
    instructions = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    visit = db.relationship("Visit", back_populates="medications")
    patient = db.relationship("Patient")
    drug = db.relationship("Drug")
    generic = db.relationship("GenericDrug")

    def line(self):
        """"Cetal 5 ml · كل 6 ساعات · 3 أيام" — one printable line."""
        parts = [self.name]
        for extra in (self.dose, self.frequency, self.duration):
            if (extra or "").strip():
                parts.append(extra.strip())
        return " · ".join(parts)

    def __repr__(self):
        return f"<VisitMedication {self.name}>"
