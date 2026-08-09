"""Vaccine inventory & suppliers (Phase 6.2).

Tracks stock as lot/batch records (lot number, expiry, quantities, storage
temperature) per vaccine brand, plus the suppliers they come from. Stock
alerts (near-expiry, low/out of stock) are derived from these.
"""
from datetime import date, datetime, timedelta

from app.extensions import db
from app.utils.clock import local_today

# Alerting thresholds (overridable later via settings if needed).
NEAR_EXPIRY_DAYS = 60
LOW_STOCK_QTY = 5

# Why stock was added outside a purchase order (Goods Receipt document).
# "transfer" batches are created by warehouse transfers (W2), not by the form.
RECEIPT_REASONS = ["purchase", "opening", "gift", "donation", "return", "adjustment",
                   "transfer"]


class Supplier(db.Model):
    __tablename__ = "suppliers"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False)
    contact_person = db.Column(db.String(120))
    phone = db.Column(db.String(40))
    email = db.Column(db.String(120))
    address = db.Column(db.String(255))
    notes = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    batches = db.relationship("VaccineInventory", back_populates="supplier")

    def __repr__(self):
        return f"<Supplier {self.name}>"


class VaccineInventory(db.Model):
    __tablename__ = "vaccine_inventory"

    id = db.Column(db.Integer, primary_key=True)
    brand_id = db.Column(db.Integer, db.ForeignKey("vaccine_brands.id"), nullable=False, index=True)
    supplier_id = db.Column(db.Integer, db.ForeignKey("suppliers.id"), nullable=True)

    lot_number = db.Column(db.String(60))
    expiry_date = db.Column(db.Date)
    mfg_date = db.Column(db.Date)
    received_date = db.Column(db.Date, default=local_today)
    # How this batch entered stock (Goods Receipt document reason).
    receipt_reason = db.Column(db.String(20), default="opening")
    # The numbered warehouse document (GRN) this batch arrived on (W1).
    document_id = db.Column(db.Integer, db.ForeignKey("store_documents.id"),
                            nullable=True, index=True)
    # Which warehouse holds this batch (W2); NULL = the default one.
    warehouse_id = db.Column(db.Integer, db.ForeignKey("warehouses.id"),
                             nullable=True, index=True)
    warehouse = db.relationship("Warehouse")
    qty_received = db.Column(db.Integer, default=0, nullable=False)
    qty_used = db.Column(db.Integer, default=0, nullable=False)
    unit_cost = db.Column(db.Float)
    storage_temp = db.Column(db.String(40))
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    brand = db.relationship("VaccineBrand", back_populates="batches")
    supplier = db.relationship("Supplier", back_populates="batches")
    # The numbered receipt this batch arrived on. The column was here; without
    # the relationship the item card could not name the document a receipt
    # came from, which is half of what a store card is for.
    document = db.relationship("StoreDocument")

    @property
    def qty_remaining(self):
        return max((self.qty_received or 0) - (self.qty_used or 0), 0)

    @property
    def value(self):
        """Remaining stock value for this batch."""
        return round(self.qty_remaining * (self.unit_cost or 0), 2)

    @property
    def is_expired(self):
        return bool(self.expiry_date and self.expiry_date < date.today())

    @property
    def is_near_expiry(self):
        if not self.expiry_date or self.is_expired:
            return False
        return self.expiry_date <= date.today() + timedelta(days=NEAR_EXPIRY_DAYS)

    @property
    def status(self):
        if self.is_expired:
            return "expired"
        if self.qty_remaining <= 0:
            return "out"
        if self.is_near_expiry:
            return "near_expiry"
        if self.qty_remaining <= LOW_STOCK_QTY:
            return "low"
        return "ok"

    def __repr__(self):
        return f"<VaccineInventory brand={self.brand_id} lot={self.lot_number}>"


class VaccineAdjustment(db.Model):
    """What a stocktake found, kept.

    Counting the fridge used to rewrite ``qty_used`` and say nothing: no
    document, no time, no counter, and no way to tell a correction from a dose
    that went into a child. The clinic asked for the count to show its timing;
    what it really needs is for the count to exist as a record at all, because
    a stock figure nobody can explain is a stock figure nobody trusts.

    One row per batch that actually moved, under the numbered adjustment
    document for that count. Batches that matched are not recorded — a list of
    everything that was fine is noise, and the document already says the whole
    warehouse was counted.
    """

    __tablename__ = "vaccine_adjustments"

    id = db.Column(db.Integer, primary_key=True)
    batch_id = db.Column(db.Integer, db.ForeignKey("vaccine_inventory.id"),
                         nullable=False, index=True)
    document_id = db.Column(db.Integer, db.ForeignKey("store_documents.id"),
                            nullable=True, index=True)
    warehouse_id = db.Column(db.Integer, db.ForeignKey("warehouses.id"),
                             nullable=True)
    # What the shelf held before and after, in patient doses. Both, because
    # "adjusted by -3" and "counted 12 where the program said 15" are the same
    # fact and only the second one can be checked against a paper count.
    was = db.Column(db.Integer, default=0, nullable=False)
    counted = db.Column(db.Integer, default=0, nullable=False)
    reason = db.Column(db.String(200))
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False,
                           index=True)

    batch = db.relationship("VaccineInventory")
    document = db.relationship("StoreDocument")
    warehouse = db.relationship("Warehouse")
    counter = db.relationship("User")

    @property
    def diff(self):
        return (self.counted or 0) - (self.was or 0)

    def __repr__(self):
        return f"<VaccineAdjustment batch={self.batch_id} {self.diff:+d}>"
