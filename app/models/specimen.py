"""A tissue that came out of a child, and where it went — GAHAR SAS.10.

*"Surgically removed tissue is sent for pathological examination unless
present in the list of exempted tissues."* Four pieces of evidence, and a row
here carries all four for one specimen:

1. **A clear pathway** — every specimen ends somewhere named: exempt under the
   hospital's list, or labelled → sent → result back.
2. **A list of exempted tissue** — the hospital's own
   (:data:`EXEMPT_DOMAIN`), which starts empty. The program does not decide
   that a foreskin needs no pathologist; the hospital writes that, and an
   exemption can only be taken from what it wrote.
3. **Labelled and sent** — the label carries what the standard names: *date
   and time, patient identification, and tissue type*, and the sender
   confirms it was on the container.
4. **The result in the record within the defined time frame** — the time
   frame is the hospital's too (``pathology_result_days``), and until it is
   written nothing is called late.

**Every word about the tissue is the surgeon's.** What was removed is what
they say it was.
"""
from datetime import datetime

from app.extensions import db

#: The hospital's list of tissues exempt from pathology — a `Lookup` domain,
#: empty until the hospital fills it.
EXEMPT_DOMAIN = "exempt_tissue"

#: Where a specimen is on its way.
STATES = ("to_send", "sent", "late", "resulted", "exempt")


class Specimen(db.Model):
    """One specimen from one operation."""

    __tablename__ = "specimens"

    id = db.Column(db.Integer, primary_key=True)
    operation_id = db.Column(db.Integer, db.ForeignKey("operations.id"),
                             nullable=False, index=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"),
                           nullable=False, index=True)

    # What was removed — the surgeon's words.
    tissue = db.Column(db.String(160), nullable=False)
    taken_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    recorded_by = db.Column(db.Integer, db.ForeignKey("users.id"))

    # **Exempt, under the hospital's list.** The key of the list entry it was
    # exempted under, so the exemption can be traced to the policy line that
    # allowed it — and what was done with the tissue instead.
    exempt_key = db.Column(db.String(40))
    exempt_note = db.Column(db.String(200))
    exempt_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    exempt_at = db.Column(db.DateTime)

    # **Labelled and sent** — one moment: the sender confirms the label was
    # on the container as they sent it.
    lab = db.Column(db.String(120))
    sent_at = db.Column(db.DateTime, index=True)
    sent_by = db.Column(db.Integer, db.ForeignKey("users.id"))

    # **The result, back in the record.** When it arrived — the date on the
    # report, which is what the time frame is measured to — and what it says.
    result_on = db.Column(db.DateTime)
    result_text = db.Column(db.Text)
    result_by = db.Column(db.Integer, db.ForeignKey("users.id"))

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    operation = db.relationship("Operation", backref=db.backref(
        "specimens", cascade="all, delete-orphan", order_by="Specimen.id"))
    patient = db.relationship("Patient")
    recorder = db.relationship("User", foreign_keys=[recorded_by])
    sender = db.relationship("User", foreign_keys=[sent_by])

    @property
    def is_exempt(self):
        return self.exempt_key is not None

    @property
    def is_sent(self):
        return self.sent_at is not None

    @property
    def has_result(self):
        return self.result_on is not None

    def __repr__(self):
        return f"<Specimen op={self.operation_id} {self.tissue!r}>"
