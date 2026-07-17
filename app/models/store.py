"""General store / warehouse (beyond vaccines).

A ``StoreItem`` is any stockable item (medical supplies, consumables…). Stock
is the opening balance plus a ledger of signed ``StockMovement`` rows
(receipts, issues, adjustments, wastage). A stocktake records a physical count
and posts adjustment movements for the differences.
"""
from datetime import datetime

from app.extensions import db

MOVEMENT_KINDS = ["in", "out", "adjust", "waste"]

# Documentary cycle (W1): every stock change belongs to a numbered document.
DOC_KINDS = ["grn", "issue", "adjust", "waste"]  # إذن إضافة / صرف / تسوية / هالك
DOC_PREFIXES = {"grn": "GRN", "issue": "ISS", "adjust": "ADJ", "waste": "WST"}


class StoreDocument(db.Model):
    """A numbered warehouse document (إذن مخزني) grouping stock changes.

    One GRN per goods receipt, one issue per dispense/consumption, one
    adjustment per stocktake — so the audit trail reads like a paper store:
    documents first, quantities inside them. Vaccine batches and general-store
    movements both link back to the document that created them.
    """

    __tablename__ = "store_documents"

    id = db.Column(db.Integer, primary_key=True)
    doc_number = db.Column(db.String(40), unique=True, nullable=False, index=True)
    kind = db.Column(db.String(10), default="grn", nullable=False, index=True)
    doc_date = db.Column(db.Date, default=lambda: datetime.utcnow().date(),
                         nullable=False, index=True)
    supplier_id = db.Column(db.Integer, db.ForeignKey("suppliers.id"), nullable=True)
    # What produced it: a PO number, an invoice number, a stocktake…
    reference = db.Column(db.String(80))
    notes = db.Column(db.String(255))
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    supplier = db.relationship("Supplier")
    creator = db.relationship("User")
    movements = db.relationship("StockMovement", back_populates="document")

    @property
    def total_value(self):
        return round(sum(abs(m.qty or 0) * (m.unit_cost or 0)
                         for m in self.movements), 2)

    def __repr__(self):
        return f"<StoreDocument {self.doc_number} {self.kind}>"


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
    # The warehouse document this change belongs to (W1 documentary cycle).
    document_id = db.Column(db.Integer, db.ForeignKey("store_documents.id"),
                            nullable=True, index=True)
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
    document = db.relationship("StoreDocument", back_populates="movements")

    def __repr__(self):
        return f"<StockMovement item={self.item_id} {self.kind} {self.qty}>"
