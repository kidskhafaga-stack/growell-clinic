"""Visit / examination record (Phase 4).

A visit ties together the encounter context, vital signs, diagnoses and the
clinical narrative. Vital growth measurements taken during the visit are also
mirrored into growth_records for the growth charts (Phase 5).
"""
from datetime import datetime

from app.extensions import db
from app.utils.clock import local_today

VISIT_STATUSES = ["open", "completed"]
# Where an order is. ``collected`` sits between the other two and arrived with
# the lab bench: the sample has been drawn and nobody has run it yet.
#
# **It is a third state, not a second meaning for the first**, and everything
# that used to ask ``status == "requested"`` to mean *no answer yet* has to ask
# ``status != "resulted"`` instead. Four places did — the doctor's results
# inbox, the pending list on the consultation screen, the WhatsApp file
# matcher, and this list — and every one of them would have made an order
# vanish the moment a clinic switched its lab on.
INVESTIGATION_STATUSES = ["requested", "collected", "resulted"]

# The ones still waiting for an answer. The predicate every screen outside the
# lab actually wants: "has this been answered", never "which of the states
# before the answer is it in" — that question belongs to the bench alone.
INVESTIGATION_OPEN = ["requested", "collected"]


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
    # Which specialty panel was on the screen. Recorded rather than derived,
    # because the readings taken belong to the panel that was open — a visit
    # whose doctor later changes specialty must not have its measurements
    # re-labelled underneath it. See app/utils/panels.py.
    specialty_panel = db.Column(db.String(40))

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

    # **The number, when there is one.**
    #
    # The result has always been Text, which is right for an X-ray report and
    # useless for HbA1c. "Show me this as a curve" is asked for by every
    # specialty in the survey — ferritin, eGFR, INR, IgE, drug levels, eye
    # pressure — and not one of them could be drawn, because you cannot plot
    # prose.
    #
    # Added beside the text rather than instead of it. A culture result and a
    # radiology report are not numbers and never will be; the value is filled
    # where a value exists, and the curve is drawn from the visits that have
    # one.
    result_value = db.Column(db.Float)
    result_unit = db.Column(db.String(20))

    # The reference range **this lab printed on this report**, and that is the
    # whole reason it lives on the result and not in the catalogue.
    #
    # A paediatric range moves with age, and often with the assay the lab
    # happens to run. One range stored centrally and shown for every child
    # would be the program inventing a clinical number — the failure the
    # vaccine tables exist to avoid — so nothing is defaulted here. The doctor
    # copies what the report says, or leaves it blank and the curve simply has
    # no band.
    result_low = db.Column(db.Float)
    result_high = db.Column(db.Float)

    resulted_at = db.Column(db.DateTime)

    # ---- the bench ------------------------------------------------------
    # What happens between the doctor asking and the answer coming back, and
    # what the program had nothing at all for: the order went straight from
    # `requested` to `resulted` because the only hands it passed through were
    # the doctor's, typing what a paper report said.
    #
    # In a hospital there is a step in the middle, and it is the one that goes
    # wrong: **the sample**. A test nobody drew blood for and a test whose
    # blood is sitting in a rack look identical when the only fact stored is
    # "requested" — and the second one is answered by waiting while the first
    # needs somebody to go to the bed.
    sample_code = db.Column(db.String(24), index=True)
    collected_at = db.Column(db.DateTime)
    collected_by = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)
    # Who ran it. Separate from the doctor who reads it: the person who put
    # the number in is the person a query about the number goes to, and on the
    # old flow that was always the doctor because there was nobody else.
    resulted_by = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)

    # The line that paid for it, once something has. Same stamp the bed
    # nights, the ward doses and the theatre cases carry: the order knows what
    # charged it, so asking twice charges once.
    invoice_item_id = db.Column(db.Integer, db.ForeignKey("invoice_items.id"),
                                nullable=True, index=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    visit = db.relationship("Visit", back_populates="investigations",
                            foreign_keys=[visit_id])
    collector = db.relationship("User", foreign_keys=[collected_by])
    resulter = db.relationship("User", foreign_keys=[resulted_by])
    invoice_item = db.relationship("InvoiceItem")
    patient = db.relationship("Patient")
    investigation = db.relationship("Investigation")

    @property
    def has_result(self):
        return bool((self.result_text or "").strip()
                    or (self.result_comment or "").strip()
                    or self.result_value is not None)

    @property
    def has_number(self):
        """Whether this one can be a point on a curve."""
        return self.result_value is not None

    @property
    def out_of_range(self):
        """Outside the range the report itself gave — or ``None`` if it gave
        none. Three answers, not two: "we were not told" is not "normal"."""
        if self.result_value is None:
            return None
        if self.result_low is None and self.result_high is None:
            return None
        if self.result_low is not None and self.result_value < self.result_low:
            return True
        if self.result_high is not None and self.result_value > self.result_high:
            return True
        return False

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
