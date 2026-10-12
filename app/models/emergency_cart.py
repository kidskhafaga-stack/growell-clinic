"""Emergency medication carts — GAHAR MMS.05, *"Emergency medications are
available, accessible, and secured at all times."*

A cart is a medication storage place of kind ``cart`` (``med_storage``).
Three things the standard asks, and how they are held here:

* **uniformly stored** (a, ev. 3) — *one* list, the hospital's, by drawer,
  used for every cart; a cart cannot have its own, which is what "the same
  drawer, laid out the same way" means;
* **secured** (b) — each check writes the seal number found and whether
  everything on the list was there;
* **replaced** (c, ev. 4) — a use opens a line that stays open until the
  cart is restocked and sealed again; the hospital writes how many hours
  that may take, and until it does the wait is shown and never judged.
"""
from datetime import datetime

from app.extensions import db


class CartItem(db.Model):
    __tablename__ = "emergency_cart_items"

    id = db.Column(db.Integer, primary_key=True)
    drawer = db.Column(db.String(40), nullable=False)
    name = db.Column(db.String(160), nullable=False)
    quantity = db.Column(db.String(40))
    sort_order = db.Column(db.Integer, default=0, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)


class CartCheck(db.Model):
    __tablename__ = "emergency_cart_checks"

    id = db.Column(db.Integer, primary_key=True)
    area_id = db.Column(db.Integer, db.ForeignKey("med_storage_areas.id"), nullable=False, index=True)
    seal = db.Column(db.String(40))
    complete = db.Column(db.Boolean, nullable=False)
    missing = db.Column(db.String(255))
    at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    by_id = db.Column(db.Integer, db.ForeignKey("users.id"))

    by = db.relationship("User", foreign_keys=[by_id])


class CartUse(db.Model):
    __tablename__ = "emergency_cart_uses"

    id = db.Column(db.Integer, primary_key=True)
    area_id = db.Column(db.Integer, db.ForeignKey("med_storage_areas.id"), nullable=False, index=True)
    used_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    what = db.Column(db.String(255), nullable=False)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"))
    by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    replaced_at = db.Column(db.DateTime)
    replaced_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    seal_after = db.Column(db.String(40))

    area = db.relationship("StorageArea")
    patient = db.relationship("Patient")
