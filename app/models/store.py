"""General store / warehouse (beyond vaccines).

A ``StoreItem`` is any stockable item (medical supplies, consumables…). Stock
is the opening balance plus a ledger of signed ``StockMovement`` rows
(receipts, issues, adjustments, wastage). A stocktake records a physical count
and posts adjustment movements for the differences.
"""
from datetime import datetime

from app.extensions import db

MOVEMENT_KINDS = ["in", "out", "adjust", "waste"]


class StoreItem(db.Model):
    __tablename__ = "store_items"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False)
    name_en = db.Column(db.String(160))
    category = db.Column(db.String(80))
    unit = db.Column(db.String(40))            # dispense/stock unit (قطعة / جرعة)
    # Unit conversion: buy in a bigger pack, stock/dispense in the small unit.
    # e.g. purchase_unit="علبة", unit="قطعة", units_per_purchase=10.
    purchase_unit = db.Column(db.String(40))
    units_per_purchase = db.Column(db.Integer, default=1)
    barcode = db.Column(db.String(60))
    purchase_price = db.Column(db.Float)
    sell_price = db.Column(db.Float)
    reorder_level = db.Column(db.Integer, default=0)
    opening_stock = db.Column(db.Integer, default=0, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    movements = db.relationship("StockMovement", back_populates="item",
                                cascade="all, delete-orphan")

    def display_name(self, lang="ar"):
        return self.name_en if (lang == "en" and self.name_en) else self.name

    @property
    def current_stock(self):
        return (self.opening_stock or 0) + sum(m.qty or 0 for m in self.movements)

    @property
    def is_low(self):
        return self.current_stock <= (self.reorder_level or 0)

    def stock_from_purchase(self, packs):
        """Convert a purchased quantity (in purchase units) to stock units."""
        return int(packs or 0) * (self.units_per_purchase or 1)

    @property
    def stock_value(self):
        return round(self.current_stock * (self.purchase_price or 0), 2)

    def __repr__(self):
        return f"<StoreItem {self.name}>"


class StockMovement(db.Model):
    __tablename__ = "stock_movements"

    id = db.Column(db.Integer, primary_key=True)
    item_id = db.Column(db.Integer, db.ForeignKey("store_items.id"), nullable=False, index=True)
    kind = db.Column(db.String(10), default="in", nullable=False)
    qty = db.Column(db.Integer, default=0, nullable=False)   # signed
    reason = db.Column(db.String(160))
    unit_cost = db.Column(db.Float)
    supplier_id = db.Column(db.Integer, db.ForeignKey("suppliers.id"), nullable=True)
    note = db.Column(db.String(200))
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)

    item = db.relationship("StoreItem", back_populates="movements")
    supplier = db.relationship("Supplier")

    def __repr__(self):
        return f"<StockMovement item={self.item_id} {self.kind} {self.qty}>"
