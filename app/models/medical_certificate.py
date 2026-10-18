"""A medical certificate issued from a visit — DOCTOR_EASE_PLAN.md ب-٣.

A sick leave (absence from school or work), a fitness certificate (nursery,
sport, travel…) or a short report of the visit. Written from the visit in a
press, printed under the clinic's letterhead with the doctor's signature and
stamp, and **kept**: every certificate has a number and a row in the
patient's file saying who issued it and when.

What was printed is what is kept. The wording comes from the clinic's own
text for that kind, filled in when it is issued, and stored as it was
printed — so a reprint next year reads the same, whatever the clinic's text
says by then. The diagnosis is kept and printed only when the family agreed
to it appearing.

A certificate is never deleted, only cancelled with a reason: a paper that
left the building has to stay explainable.
"""
from datetime import datetime

from app.extensions import db

CERT_KINDS = ("sick_leave", "fitness", "visit_report")


class MedicalCertificate(db.Model):
    __tablename__ = "medical_certificates"

    id = db.Column(db.Integer, primary_key=True)
    number = db.Column(db.String(20), unique=True, nullable=False, index=True)
    kind = db.Column(db.String(20), nullable=False)
    lang = db.Column(db.String(2), default="ar", nullable=False)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"), nullable=False, index=True)
    visit_id = db.Column(db.Integer, db.ForeignKey("visits.id"), nullable=True, index=True)
    doctor_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    issued_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    issued_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    seen_on = db.Column(db.Date, nullable=False)            # the visit's date
    addressed_to = db.Column(db.String(160))                 # school, employer…
    purpose = db.Column(db.String(160))                      # fitness: for what
    date_from = db.Column(db.Date)                           # sick leave
    days = db.Column(db.Integer)
    date_to = db.Column(db.Date)
    diagnosis = db.Column(db.String(255))                    # only if agreed
    body = db.Column(db.Text, nullable=False)                # as printed
    note = db.Column(db.Text)
    voided_at = db.Column(db.DateTime)
    voided_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    void_reason = db.Column(db.String(255))

    patient = db.relationship("Patient")
    visit = db.relationship("Visit")
    doctor = db.relationship("User", foreign_keys=[doctor_id])
    issuer = db.relationship("User", foreign_keys=[issued_by])

    @property
    def is_void(self):
        return self.voided_at is not None

    def __repr__(self):
        return f"<MedicalCertificate {self.number} {self.kind}>"
