"""A cost centre (مركز تكلفة): a part of the clinic whose money is counted
by itself.

The accounting engine ran for a year without one, and the income statement it
drew was the clinic's as a whole — one revenue, one set of expenses, one net.
An owner asking *"does the NICU pay for itself?"* had no answer on any screen.

**Where the money came from is already written down.** A bed night knows its
unit, an operation its theatre, a vaccine its dose; so revenue reaches its
centre without anybody choosing one. What is written here is the list of
centres and their names, and a clinic may rename one or add its own.

**Two kinds of row, one table.** The program's own (``key`` like
``outpatient`` or ``unit:3``) are made on demand from what the clinic runs; a
clinic's own (``key`` like ``own:1``) are added on the screen. Neither is ever
deleted — the journal points at it — only switched off.
"""
from datetime import datetime

from app.extensions import db


class CostCentre(db.Model):
    __tablename__ = "cost_centres"

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(40), unique=True, nullable=False, index=True)
    name_ar = db.Column(db.String(80), nullable=False)
    name_en = db.Column(db.String(80))
    # A ward, the NICU, the emergency department: the centre follows the
    # unit, one per unit — two wards are two centres, as they are two budgets.
    unit_id = db.Column(db.Integer, db.ForeignKey("care_units.id"),
                        nullable=True, index=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    sort_order = db.Column(db.Integer, default=0, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    unit = db.relationship("Unit")

    @property
    def is_own(self):
        """Added by the clinic, not made by the program."""
        return self.key.startswith("own:")

    def display_name(self, lang="ar"):
        if lang == "en" and self.name_en:
            return self.name_en
        return self.name_ar

    def __repr__(self):
        return f"<CostCentre {self.key}>"
