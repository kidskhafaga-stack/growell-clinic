"""The controlled-drug register — GAHAR MMS.09 ev. 4, *"Narcotics and
psychotropic agents are procured, stored, prescribed, dispensed,
administered, and monitored according to law and regulations."*

The paper book every ward cabinet and pharmacy keeps, one page per drug per
place: what came in and from where, what went out and to which child, what
was wasted and who watched, and the running balance after every line. A
count is a line too — the book's balance beside what is on the shelf, and a
difference needs what was done about it and a witness.

**Which drugs are in the book is the hospital's list**, by the law it works
under; the program ships none. A wasted dose and a count that does not match
need a second person, and the program refuses the recorder as their own
witness — the same rule as the surgical count.
"""
from datetime import datetime

from app.extensions import db

ENTRY_KINDS = ("received", "given", "wasted", "transfer_out", "transfer_in", "count")
#: The kinds that need a witness — a second, different person.
WITNESSED = ("wasted", "count")


class ControlledItem(db.Model):
    __tablename__ = "controlled_items"

    id = db.Column(db.Integer, primary_key=True)
    #: As the book writes it — the drug, the strength and the form.
    name = db.Column(db.String(160), nullable=False)
    #: The unit the book counts in — ampoule, tablet, ml.
    unit = db.Column(db.String(30), nullable=False)
    drug_id = db.Column(db.Integer, db.ForeignKey("drugs.id"))
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class ControlledEntry(db.Model):
    __tablename__ = "controlled_entries"

    id = db.Column(db.Integer, primary_key=True)
    item_id = db.Column(db.Integer, db.ForeignKey("controlled_items.id"), nullable=False, index=True)
    area_id = db.Column(db.Integer, db.ForeignKey("med_storage_areas.id"), nullable=False, index=True)
    kind = db.Column(db.String(14), nullable=False)
    #: Always positive; the kind says which way it went. On a count, the
    #: difference found (``counted - book``), signed.
    qty = db.Column(db.Float, nullable=False)
    #: The book's balance after this line.
    balance = db.Column(db.Float, nullable=False)
    #: A count: what was on the shelf.
    counted = db.Column(db.Float)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"), index=True)
    admission_id = db.Column(db.Integer, db.ForeignKey("admissions.id"))
    #: Received: from where and the document; a transfer: the other place.
    source = db.Column(db.String(160))
    other_area_id = db.Column(db.Integer, db.ForeignKey("med_storage_areas.id"))
    note = db.Column(db.String(255))
    at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    witness_id = db.Column(db.Integer, db.ForeignKey("users.id"))

    item = db.relationship("ControlledItem")
    area = db.relationship("StorageArea", foreign_keys=[area_id])
    other_area = db.relationship("StorageArea", foreign_keys=[other_area_id])
    patient = db.relationship("Patient")
    by = db.relationship("User", foreign_keys=[by_id])
    witness = db.relationship("User", foreign_keys=[witness_id])
