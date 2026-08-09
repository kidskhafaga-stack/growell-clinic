"""Purchase orders: request → approve → receive (GRN) → stock.

A :class:`PurchaseOrder` is raised against a supplier with a list of items.
Once approved and received, receiving posts ``in`` stock movements for the
received quantities (optionally recording the receipt as a clinic expense).
"""
from datetime import datetime

from app.extensions import db
from app.utils.clock import local_today

PO_STATUSES = ["draft", "approved", "partial", "received", "cancelled"]


class PurchaseOrder(db.Model):
    __tablename__ = "purchase_orders"

    id = db.Column(db.Integer, primary_key=True)
    po_number = db.Column(db.String(40), unique=True, index=True)
    supplier_id = db.Column(db.Integer, db.ForeignKey("suppliers.id"), nullable=True, index=True)
    status = db.Column(db.String(12), default="draft", nullable=False, index=True)

    order_date = db.Column(db.Date, default=local_today, nullable=False)
    expected_date = db.Column(db.Date)
    notes = db.Column(db.Text)

    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    approved_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    approved_at = db.Column(db.DateTime)
    received_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    supplier = db.relationship("Supplier")
    items = db.relationship("PurchaseOrderItem", back_populates="order",
                            cascade="all, delete-orphan")

    @property
    def total(self):
        return round(sum(i.line_total for i in self.items), 2)

    @property
    def received_value(self):
        return round(sum((i.qty_received or 0) * (i.unit_cost or 0) for i in self.items), 2)

    @property
    def is_editable(self):
        return self.status == "draft"

    def recalc_status(self):
        """Move to received / partial based on received vs ordered quantities."""
        if self.status in ("draft", "cancelled"):
            return self.status
        ordered = sum(i.qty_ordered or 0 for i in self.items)
        received = sum(i.qty_received or 0 for i in self.items)
        if received <= 0:
            self.status = "approved"
        elif received >= ordered:
            self.status = "received"
        else:
            self.status = "partial"
        return self.status

    def __repr__(self):
        return f"<PurchaseOrder {self.po_number} {self.status}>"


class PurchaseOrderItem(db.Model):
    __tablename__ = "purchase_order_items"

    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("purchase_orders.id"), nullable=False, index=True)
    store_item_id = db.Column(db.Integer, db.ForeignKey("store_items.id"), nullable=True)
    # A line may instead be a vaccine brand (commercial item); receiving it
    # creates a VaccineInventory batch rather than a general-store movement.
    vaccine_brand_id = db.Column(db.Integer, db.ForeignKey("vaccine_brands.id"), nullable=True)
    description = db.Column(db.String(200), nullable=False)  # snapshot
    qty_ordered = db.Column(db.Integer, default=0, nullable=False)
    qty_received = db.Column(db.Integer, default=0, nullable=False)
    unit_cost = db.Column(db.Float, default=0)

    order = db.relationship("PurchaseOrder", back_populates="items")
    store_item = db.relationship("StoreItem")
    vaccine_brand = db.relationship("VaccineBrand")

    @property
    def is_vaccine(self):
        return self.vaccine_brand_id is not None

    @property
    def line_total(self):
        return round((self.qty_ordered or 0) * (self.unit_cost or 0), 2)

    @property
    def outstanding(self):
        return max((self.qty_ordered or 0) - (self.qty_received or 0), 0)

    def __repr__(self):
        return f"<PurchaseOrderItem {self.description} {self.qty_ordered}>"
