"""Tubes on their way to the lab — LAB_GLAB360_PLAN.md م-٣.

A sample drawn in the incubator unit, intensive care, the emergency
procedure room or the ward is carried to the lab. Until now the program knew
when it was drawn and when the lab received it, and nothing in between: a
tube that never arrived looked exactly like one nobody had drawn yet.

* **the batch** — the tubes that left one place together, numbered, with a
  list to print and carry with them, who sent them and when;
* **each tube on it** — the number it carried when it left, and when it
  reached the lab and who took it (received, or refused at the door). A tube
  still empty there is a tube on the way — or lost, and the batch says so.

Why the tube's number is kept on the line and not only the order: a refused
tube is drawn again under a new number (`lab_reception.reject`), and the
batch that carried the first one must go on saying it carried the first one.
"""
from datetime import datetime

from app.extensions import db


class SampleBatch(db.Model):
    """Tubes that left one place for the lab together."""

    __tablename__ = "sample_batches"

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(24), unique=True, index=True)
    # Where they were drawn (`lab_transfer.PLACES`), and where they went.
    from_place = db.Column(db.String(16), nullable=False, index=True)
    to_place = db.Column(db.String(16), default="lab", nullable=False)
    sent_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False,
                        index=True)
    sent_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    note = db.Column(db.String(200))

    sender = db.relationship("User", foreign_keys=[sent_by])
    items = db.relationship("SampleBatchItem", back_populates="batch",
                            order_by="SampleBatchItem.id",
                            cascade="all, delete-orphan")

    def __repr__(self):
        return f"<SampleBatch {self.code} {self.from_place}>"


class SampleBatchItem(db.Model):
    """One tube on a batch, and whether it arrived."""

    __tablename__ = "sample_batch_items"

    id = db.Column(db.Integer, primary_key=True)
    batch_id = db.Column(db.Integer, db.ForeignKey("sample_batches.id"),
                         nullable=False, index=True)
    order_id = db.Column(db.Integer, db.ForeignKey("visit_investigations.id"),
                         nullable=False, index=True)
    sample_code = db.Column(db.String(24), index=True)
    arrived_at = db.Column(db.DateTime, index=True)
    arrived_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    # received | rejected — what the lab's door said when it came.
    outcome = db.Column(db.String(10))

    batch = db.relationship("SampleBatch", back_populates="items")
    order = db.relationship("VisitInvestigation")
    arriver = db.relationship("User", foreign_keys=[arrived_by])

    def __repr__(self):
        return f"<SampleBatchItem {self.sample_code} {self.outcome or 'on the way'}>"
