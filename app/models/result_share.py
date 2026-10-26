"""A lab result sent to the family, or to the doctor who referred the child.

LAB_GLAB360_PLAN.md م-٤, with the owner's three decisions: the result goes
**after the doctor has seen it**; a critical result or a sensitive test
**waits until the doctor has spoken to the family**; and the referring
doctor gets the same link, with the same protection.

What leaves is a **link** when the clinic can be reached from outside (its
public address is set): it opens the laboratory's own report — nothing
added, no interpretation — after the child's date of birth is typed; it ends
after a number of days; and five wrong tries lock it. **When it cannot** —
the program running on the clinic's own network — a link would open nothing
on the family's phone, so the report itself goes as a file
(«ملف التقرير على الواتساب»), and the referring doctor gets the numbers in the
message as well («الاتنين»). Every send, and every opening of a link, is
kept here.
"""
from datetime import datetime

from app.extensions import db

FAMILY, DOCTOR = "family", "doctor"
#: How it went: a link to the clinic's page (the clinic has a public
#: address), or the report itself as a file (it does not).
LINK, FILE = "link", "file"
#: Wrong answers before the link stops answering.
MAX_FAILURES = 5


class ResultShare(db.Model):
    __tablename__ = "lab_result_shares"

    id = db.Column(db.Integer, primary_key=True)
    token = db.Column(db.String(48), unique=True, nullable=False, index=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"),
                           nullable=False, index=True)
    #: The lab orders on this report (one child's), as a list of ids.
    order_ids = db.Column(db.JSON, nullable=False)
    audience = db.Column(db.String(10), nullable=False, default=FAMILY)
    mode = db.Column(db.String(6), nullable=False, default=LINK)
    external_doctor_id = db.Column(db.Integer, db.ForeignKey("external_doctors.id"))
    to_phone = db.Column(db.String(40))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False,
                           index=True)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    expires_at = db.Column(db.DateTime, nullable=False)
    opened_at = db.Column(db.DateTime)
    opens = db.Column(db.Integer, default=0, nullable=False)
    failures = db.Column(db.Integer, default=0, nullable=False)
    message_id = db.Column(db.Integer, db.ForeignKey("message_logs.id"))

    patient = db.relationship("Patient")
    sender = db.relationship("User", foreign_keys=[created_by])
    external_doctor = db.relationship("ExternalDoctor")
    message = db.relationship("MessageLog")

    @property
    def locked(self):
        return (self.failures or 0) >= MAX_FAILURES

    @property
    def expired(self):
        return datetime.utcnow() > self.expires_at

    def __repr__(self):
        return f"<ResultShare {self.audience} {self.order_ids}>"
