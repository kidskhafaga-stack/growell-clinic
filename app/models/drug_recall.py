"""A drug recall — GAHAR MMS.08, *"The hospital has a system in place for
medication recall."*

The intent names four things the process covers (a–d): retrieving the
recalled lot, labelling and separating it, telling the patients who had it
(when applicable), and its disposal or removal. A recall is one store item
and one lot, with the notice that started it (from the authority, the
manufacturer or another body, and its reference), and each of the four
written as it is done. While it is open, the lot cannot be picked on the
shelf or issued; it can still be removed — that is the point.

Who received it is read from what the program already holds: the box
handed over at the counter and the dose given on the ward each carry the
stock movement they came from, and the movement carries the lot. Issues
written without a lot are counted and shown, because "nobody had it" and
"nobody wrote down which lot" are different answers.
"""
from datetime import datetime

from app.extensions import db


class DrugRecall(db.Model):
    __tablename__ = "drug_recalls"

    id = db.Column(db.Integer, primary_key=True)
    item_id = db.Column(db.Integer, db.ForeignKey("store_items.id"), nullable=False, index=True)
    lot_number = db.Column(db.String(60), nullable=False, index=True)
    notice_from = db.Column(db.String(120), nullable=False)
    notice_ref = db.Column(db.String(80))
    reason = db.Column(db.String(255))
    opened_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    opened_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    #: (a)(b) retrieved, labelled and separated — where it is held.
    separated_at = db.Column(db.DateTime)
    separated_note = db.Column(db.String(255))
    #: (c) the patients — what was decided and done.
    patients_note = db.Column(db.String(255))
    patients_at = db.Column(db.DateTime)
    #: (d) disposed of or returned — how.
    disposed_at = db.Column(db.DateTime)
    disposed_note = db.Column(db.String(255))
    closed_at = db.Column(db.DateTime)
    closed_by = db.Column(db.Integer, db.ForeignKey("users.id"))

    item = db.relationship("StoreItem")
    opener = db.relationship("User", foreign_keys=[opened_by])

    @property
    def is_open(self):
        return self.closed_at is None
