"""What the recovery room holds, and whether it was there — GAHAR SAS.19.

*"The post-anesthesia care unit is equipped according to applicable laws,
regulations, and professional practice guidelines."* Three items of evidence:

1. a post-anaesthesia care unit for each department that operates — read off
   the hospital's own layout (a `Unit` of kind ``recovery``), with the one
   number the standard itself states: *"at least one bed for each operating
   room"*. That number is the book's, like the five minutes in CSS.05, so the
   program measures against it instead of choosing one;
2. equipped with what is required;
3. *"all needed supplies and medications are **identified, available, and
   checked** properly"* — three words, three different things: a list that
   names them, a check that finds them, and a record that says who checked
   and when.

**The list is the hospital's.** What a children's recovery room keeps on its
crash cart is a clinical decision written by the people who run it, so the
program holds no default list. What it does hold is the standard's own five
headings — *"monitoring equipment, a crash cart with a defibrillator, an
oxygen source, recommended medications, and medical supplies"* — and a
heading with nothing under it is named, because that is exactly what a
surveyor walking the room will look for.
"""
from datetime import datetime

from app.extensions import db

#: The standard's own five headings, in its order. Headings, not items.
CATEGORIES = ("monitoring", "crash_cart", "oxygen", "medication", "supply")

#: What a check can find, per item. ``faulty`` is the equipment answer and
#: ``expired`` the drug-and-supply one; both are "here but not usable", and
#: kept apart because they send somebody to two different places.
FINDINGS = ("ok", "missing", "faulty", "expired")

#: How often the hospital checks its recovery rooms, in hours. A `Setting`,
#: unset until the hospital writes one — the program does not choose it.
CHECK_HOURS_SETTING = "recovery_check_hours"


class RecoveryItem(db.Model):
    """One thing one recovery room must hold."""

    __tablename__ = "recovery_items"

    id = db.Column(db.Integer, primary_key=True)
    unit_id = db.Column(db.Integer, db.ForeignKey("care_units.id"),
                        nullable=False, index=True)
    category = db.Column(db.String(12), nullable=False)
    name = db.Column(db.String(160), nullable=False)
    #: How many the room keeps, in the hospital's words ("2", "1 × 10 ml").
    #: Text on purpose: a par level is written the way the cart is stocked.
    quantity = db.Column(db.String(40))
    note = db.Column(db.String(200))
    sort_order = db.Column(db.Integer, default=0, nullable=False)
    #: Taken off the list, never deleted — last month's checks still name it.
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    added_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    added_by = db.Column(db.Integer, db.ForeignKey("users.id"))

    unit = db.relationship("Unit")

    def __repr__(self):
        return f"<RecoveryItem {self.category} {self.name!r}>"


class RecoveryCheck(db.Model):
    """One walk round one recovery room with the list in hand."""

    __tablename__ = "recovery_checks"

    id = db.Column(db.Integer, primary_key=True)
    unit_id = db.Column(db.Integer, db.ForeignKey("care_units.id"),
                        nullable=False, index=True)
    at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False,
                   index=True)
    by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    note = db.Column(db.String(255))

    unit = db.relationship("Unit")
    by = db.relationship("User")
    lines = db.relationship("RecoveryCheckLine", back_populates="check",
                            cascade="all, delete-orphan",
                            order_by="RecoveryCheckLine.id")


class RecoveryCheckLine(db.Model):
    """What one check found for one item."""

    __tablename__ = "recovery_check_lines"

    id = db.Column(db.Integer, primary_key=True)
    check_id = db.Column(db.Integer, db.ForeignKey("recovery_checks.id"),
                         nullable=False, index=True)
    item_id = db.Column(db.Integer, db.ForeignKey("recovery_items.id"),
                        nullable=False, index=True)
    finding = db.Column(db.String(10), nullable=False)
    note = db.Column(db.String(200))

    check = db.relationship("RecoveryCheck", back_populates="lines")
    item = db.relationship("RecoveryItem")
