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
# W2 adds transfers between warehouses (TRF); W3 adds supplier returns (RTN).
DOC_KINDS = ["grn", "issue", "adjust", "waste", "transfer", "return"]
DOC_PREFIXES = {"grn": "GRN", "issue": "ISS", "adjust": "ADJ", "waste": "WST",
                "transfer": "TRF", "return": "RTN"}

WAREHOUSE_KINDS = ["main", "sub", "fridge"]  # رئيسي / فرعي / ثلاجة تطعيمات


# Which users may work in which warehouse (W2 permissions). A user with **no**
# row here is unrestricted — that keeps every existing clinic working exactly
# as before; a user with at least one row sees only those warehouses.
warehouse_users = db.Table(
    "warehouse_users",
    db.Column("warehouse_id", db.Integer, db.ForeignKey("warehouses.id"),
              primary_key=True),
    db.Column("user_id", db.Integer, db.ForeignKey("users.id"), primary_key=True),
)


class Warehouse(db.Model):
    """A physical stock location (W2): main store, a sub-store, or the vaccine
    fridge. Every movement/batch belongs to one; a default warehouse absorbs
    everything recorded before multi-warehouse existed."""

    __tablename__ = "warehouses"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    name_en = db.Column(db.String(120))
    kind = db.Column(db.String(10), default="main", nullable=False)
    is_default = db.Column(db.Boolean, default=False, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    notes = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    # The store keepers allowed to work in this warehouse (empty = everyone).
    keepers = db.relationship("User", secondary="warehouse_users",
                              backref="warehouses")

    def display_name(self, lang="ar"):
        return self.name_en if (lang == "en" and self.name_en) else self.name

    def allows(self, user):
        """Whether ``user`` may work in this warehouse.

        Open by default: a warehouse with no keepers is everyone's, and a user
        with no warehouse assigned anywhere is unrestricted. Restriction only
        starts once someone is deliberately assigned."""
        if user is None:
            return False
        if getattr(user, "is_admin", False):
            return True
        if not self.keepers:
            return not getattr(user, "warehouses", [])
        return any(k.id == user.id for k in self.keepers)

    @classmethod
    def default(cls):
        """The default warehouse, created lazily on first use."""
        wh = cls.query.filter_by(is_default=True).first()
        if wh is None:
            wh = cls.query.order_by(cls.id).first()
        if wh is None:
            wh = cls(name="المخزن الرئيسي", name_en="Main store",
                     kind="main", is_default=True)
            db.session.add(wh)
            db.session.flush()
        return wh

    def __repr__(self):
        return f"<Warehouse {self.name}>"


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
    # Where the document acts (W2); a transfer also has a destination.
    warehouse_id = db.Column(db.Integer, db.ForeignKey("warehouses.id"), nullable=True)
    to_warehouse_id = db.Column(db.Integer, db.ForeignKey("warehouses.id"), nullable=True)
    supplier_id = db.Column(db.Integer, db.ForeignKey("suppliers.id"), nullable=True)
    # What produced it: a PO number, an invoice number, a stocktake…
    reference = db.Column(db.String(80))
    # Purchase-invoice terms for a supplier goods-receipt: the supplier's own
    # invoice number, when the payment falls due, and how it's settled.
    supplier_ref = db.Column(db.String(60))     # supplier's invoice number
    due_date = db.Column(db.Date)
    payment_terms = db.Column(db.String(12))    # cash | credit | installments
    notes = db.Column(db.String(255))
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    supplier = db.relationship("Supplier")
    creator = db.relationship("User")
    warehouse = db.relationship("Warehouse", foreign_keys=[warehouse_id])
    to_warehouse = db.relationship("Warehouse", foreign_keys=[to_warehouse_id])
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
    # Internal program code (ITM-0001…), auto-assigned; doubles as the printed
    # barcode when no supplier barcode is set.
    item_code = db.Column(db.String(40), index=True)
    unit = db.Column(db.String(40))            # dispense/stock unit (قطعة / جرعة)
    # Unit conversion: buy in a bigger pack, stock/dispense in the small unit.
    # e.g. purchase_unit="علبة", unit="قطعة", units_per_purchase=10.
    purchase_unit = db.Column(db.String(40))
    units_per_purchase = db.Column(db.Integer, default=1)
    barcode = db.Column(db.String(60))
    purchase_price = db.Column(db.Float)
    sell_price = db.Column(db.Float)
    # Sell-price policy: "manual" (default) or "auto" — auto refreshes the sell
    # price from each new purchase cost × (1 + margin%). NULL margin = clinic default.
    price_policy = db.Column(db.String(10), default="manual", nullable=False)
    margin_percent = db.Column(db.Float)
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

    def stock_in(self, warehouse):
        """Stock held in one warehouse (W2). Movements with no warehouse —
        and the opening balance — belong to the default warehouse."""
        total = (self.opening_stock or 0) if warehouse.is_default else 0
        for m in self.movements:
            wid = m.warehouse_id
            if wid == warehouse.id or (wid is None and warehouse.is_default):
                total += m.qty or 0
        return total

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
    # Which warehouse the change happened in (W2); NULL = the default one.
    warehouse_id = db.Column(db.Integer, db.ForeignKey("warehouses.id"),
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
    warehouse = db.relationship("Warehouse")

    def __repr__(self):
        return f"<StockMovement item={self.item_id} {self.kind} {self.qty}>"
