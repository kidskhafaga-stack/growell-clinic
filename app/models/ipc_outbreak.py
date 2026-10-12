"""Notifiable diseases and outbreaks — GAHAR IPC.18.

* **A report** (ev. 2): a child with a suspected communicable disease the law
  says must be reported — which disease, when it was suspected, and when, to
  whom and under what number it was reported. The list of notifiable
  diseases is the Ministry's; the program keeps the disease in words.
* **An outbreak** (ev. 1, 3, 4): opened by the infection-control team, with
  the multidisciplinary team working it, the case definition, the cases, and
  the standard's ten steps — *"described in the literature"*, quoted, each
  marked with what was done and when — closed with the conclusion and the
  prevention measures. The program declares nothing an outbreak by itself:
  it lists what clusters (more than one alert organism or infection in the
  same unit), and a person decides.
"""
from datetime import datetime

from app.extensions import db

#: IPC.18's ten steps, in the standard's order (see the locale for words).
STEPS = tuple(range(1, 11))


class DiseaseReport(db.Model):
    __tablename__ = "disease_reports"

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"), nullable=False, index=True)
    disease = db.Column(db.String(160), nullable=False)
    suspected_on = db.Column(db.Date, nullable=False, index=True)
    #: Set when it was reported — empty is «still to report».
    reported_on = db.Column(db.Date, index=True)
    reported_to = db.Column(db.String(160))
    reference = db.Column(db.String(80))
    note = db.Column(db.Text)
    written_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    written_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    reported_by = db.Column(db.Integer, db.ForeignKey("users.id"))

    patient = db.relationship("Patient")
    reporter = db.relationship("User", foreign_keys=[reported_by])


class Outbreak(db.Model):
    __tablename__ = "outbreaks"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(160), nullable=False)
    agent = db.Column(db.String(160))
    unit_id = db.Column(db.Integer, db.ForeignKey("care_units.id"), index=True)
    opened_on = db.Column(db.Date, nullable=False, index=True)
    #: Ev. 3 — who works it, from which discipline.
    team = db.Column(db.Text, nullable=False)
    #: Step 3 — who counts as a case.
    case_definition = db.Column(db.Text)
    closed_on = db.Column(db.Date)
    #: Step 7 and step 10 — what was concluded, what was done to stop it.
    conclusion = db.Column(db.Text)
    measures = db.Column(db.Text)
    opened_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    closed_by = db.Column(db.Integer, db.ForeignKey("users.id"))

    unit = db.relationship("Unit")
    steps = db.relationship("OutbreakStep", back_populates="outbreak",
                            order_by="OutbreakStep.step", cascade="all, delete-orphan")
    cases = db.relationship("OutbreakCase", back_populates="outbreak",
                            order_by="OutbreakCase.id", cascade="all, delete-orphan")

    @property
    def is_open(self):
        return self.closed_on is None


class OutbreakStep(db.Model):
    __tablename__ = "outbreak_steps"
    __table_args__ = (db.UniqueConstraint("outbreak_id", "step", name="uq_outbreak_step"),)

    id = db.Column(db.Integer, primary_key=True)
    outbreak_id = db.Column(db.Integer, db.ForeignKey("outbreaks.id"), nullable=False, index=True)
    step = db.Column(db.Integer, nullable=False)
    done_on = db.Column(db.Date, nullable=False)
    note = db.Column(db.Text, nullable=False)
    done_by = db.Column(db.Integer, db.ForeignKey("users.id"))

    outbreak = db.relationship("Outbreak", back_populates="steps")


class OutbreakCase(db.Model):
    __tablename__ = "outbreak_cases"
    __table_args__ = (db.UniqueConstraint("outbreak_id", "patient_id", name="uq_outbreak_patient"),)

    id = db.Column(db.Integer, primary_key=True)
    outbreak_id = db.Column(db.Integer, db.ForeignKey("outbreaks.id"), nullable=False, index=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"), nullable=False, index=True)
    onset_on = db.Column(db.Date)
    note = db.Column(db.String(255))
    added_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    added_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    outbreak = db.relationship("Outbreak", back_populates="cases")
    patient = db.relationship("Patient")
