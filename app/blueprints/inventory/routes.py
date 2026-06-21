"""Vaccine inventory & suppliers (Phase 6.2).

Lot/batch stock with expiry tracking, stock alerts (near-expiry / low / out),
and supplier management. Optional (clinic-provided) vaccines carry stock;
mandatory (government) vaccines do not.
"""
from datetime import datetime

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user

from app.blueprints.inventory import inventory_bp
from app.extensions import db
from app.i18n import t
from app.models import (
    MOVEMENT_KINDS,
    ActivityLog,
    StockMovement,
    StoreItem,
    Supplier,
    Vaccine,
    VaccineBrand,
    VaccineInventory,
)
from app.utils.decorators import client_ip, module_required

MODULE = "inventory"


def _parse_date(name):
    raw = (request.form.get(name) or "").strip()
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        return None


def _optional_brands():
    """Brands of optional (clinic-provided) vaccines — these carry stock."""
    return (
        VaccineBrand.query.join(Vaccine)
        .filter(Vaccine.is_mandatory.is_(False))
        .order_by(Vaccine.sort_order, VaccineBrand.name)
        .all()
    )


@inventory_bp.route("/")
@module_required(MODULE)
def index():
    brands = _optional_brands()
    batches = (
        VaccineInventory.query.order_by(VaccineInventory.expiry_date).all()
    )
    alerts = {
        "expired": [b for b in batches if b.status == "expired"],
        "near_expiry": [b for b in batches if b.status == "near_expiry"],
        "low": [b for b in batches if b.status == "low"],
        "out": [b for b in batches if b.status == "out"],
    }
    stats = {
        "brands": len(brands),
        "total_stock": sum(b.stock for b in brands),
        "alerts": len(alerts["expired"]) + len(alerts["near_expiry"]) + len(alerts["low"]),
    }
    suppliers = Supplier.query.filter_by(is_active=True).order_by(Supplier.name).all()
    return render_template(
        "inventory/index.html", brands=brands, batches=batches,
        alerts=alerts, stats=stats, suppliers=suppliers,
    )


@inventory_bp.route("/batch/new", methods=["POST"])
@module_required(MODULE)
def batch_new():
    brand = db.session.get(VaccineBrand, request.form.get("brand_id", type=int))
    if brand is None:
        flash(t("common.required") + ": " + t("vaccinations.brand"), "danger")
        return redirect(url_for("inventory.index"))

    batch = VaccineInventory(
        brand_id=brand.id,
        supplier_id=request.form.get("supplier_id", type=int) or None,
        lot_number=(request.form.get("lot_number") or "").strip() or None,
        expiry_date=_parse_date("expiry_date"),
        received_date=_parse_date("received_date") or datetime.utcnow().date(),
        qty_received=request.form.get("qty_received", type=int) or 0,
        unit_cost=request.form.get("unit_cost", type=float),
        storage_temp=(request.form.get("storage_temp") or "").strip() or None,
        notes=(request.form.get("notes") or "").strip() or None,
    )
    db.session.add(batch)
    ActivityLog.record("inventory.batch_add", user_id=current_user.id,
                       entity="vaccine_inventory", detail=brand.name, ip_address=client_ip())
    db.session.commit()
    flash(t("inventory.batch_added"), "success")
    return redirect(url_for("inventory.index"))


@inventory_bp.route("/batch/<int:batch_id>/delete", methods=["POST"])
@module_required(MODULE)
def batch_delete(batch_id):
    batch = db.get_or_404(VaccineInventory, batch_id)
    db.session.delete(batch)
    db.session.commit()
    flash(t("inventory.batch_deleted"), "info")
    return redirect(url_for("inventory.index"))


@inventory_bp.route("/suppliers", methods=["GET", "POST"])
@module_required(MODULE)
def suppliers():
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        if not name:
            flash(t("common.required") + ": " + t("inventory.supplier_name"), "danger")
            return redirect(url_for("inventory.suppliers"))
        db.session.add(Supplier(
            name=name,
            contact_person=(request.form.get("contact_person") or "").strip() or None,
            phone=(request.form.get("phone") or "").strip() or None,
            email=(request.form.get("email") or "").strip() or None,
            address=(request.form.get("address") or "").strip() or None,
            notes=(request.form.get("notes") or "").strip() or None,
        ))
        db.session.commit()
        flash(t("inventory.supplier_added"), "success")
        return redirect(url_for("inventory.suppliers"))

    suppliers = Supplier.query.order_by(Supplier.name).all()
    return render_template("inventory/suppliers.html", suppliers=suppliers)


@inventory_bp.route("/suppliers/<int:supplier_id>/delete", methods=["POST"])
@module_required(MODULE)
def supplier_delete(supplier_id):
    supplier = db.get_or_404(Supplier, supplier_id)
    if supplier.batches:
        supplier.is_active = False  # keep history, just deactivate
    else:
        db.session.delete(supplier)
    db.session.commit()
    flash(t("inventory.supplier_deleted"), "info")
    return redirect(url_for("inventory.suppliers"))


# =======================================================================
# General store / warehouse (non-vaccine items)
# =======================================================================
def _suppliers():
    return Supplier.query.filter_by(is_active=True).order_by(Supplier.name).all()


@inventory_bp.route("/store")
@module_required(MODULE)
def store():
    items = StoreItem.query.order_by(StoreItem.is_active.desc(), StoreItem.name).all()
    low = [i for i in items if i.is_active and i.is_low]
    stats = {
        "items": len([i for i in items if i.is_active]),
        "low": len(low),
        "value": round(sum(i.stock_value for i in items if i.is_active), 2),
    }
    return render_template("inventory/store.html", items=items, low=low,
                           stats=stats, suppliers=_suppliers())


@inventory_bp.route("/store/new", methods=["POST"])
@module_required(MODULE)
def store_item_new():
    name = (request.form.get("name") or "").strip()
    if not name:
        flash(t("common.required") + ": " + t("store.name"), "danger")
        return redirect(url_for("inventory.store"))
    item = StoreItem(
        name=name,
        name_en=(request.form.get("name_en") or "").strip() or None,
        category=(request.form.get("category") or "").strip() or None,
        unit=(request.form.get("unit") or "").strip() or None,
        barcode=(request.form.get("barcode") or "").strip() or None,
        purchase_price=request.form.get("purchase_price", type=float),
        sell_price=request.form.get("sell_price", type=float),
        reorder_level=request.form.get("reorder_level", type=int) or 0,
        opening_stock=request.form.get("opening_stock", type=int) or 0,
    )
    db.session.add(item)
    ActivityLog.record("store.item_add", user_id=current_user.id, entity="store_item",
                       detail=name, ip_address=client_ip())
    db.session.commit()
    flash(t("store.item_added"), "success")
    return redirect(url_for("inventory.store"))


@inventory_bp.route("/store/<int:item_id>/edit", methods=["POST"])
@module_required(MODULE)
def store_item_edit(item_id):
    item = db.get_or_404(StoreItem, item_id)
    item.name = (request.form.get("name") or item.name).strip()
    item.name_en = (request.form.get("name_en") or "").strip() or None
    item.category = (request.form.get("category") or "").strip() or None
    item.unit = (request.form.get("unit") or "").strip() or None
    item.barcode = (request.form.get("barcode") or "").strip() or None
    item.purchase_price = request.form.get("purchase_price", type=float)
    item.sell_price = request.form.get("sell_price", type=float)
    item.reorder_level = request.form.get("reorder_level", type=int) or 0
    item.is_active = bool(request.form.get("is_active"))
    db.session.commit()
    flash(t("store.item_updated"), "success")
    return redirect(url_for("inventory.store"))


@inventory_bp.route("/store/<int:item_id>/move", methods=["POST"])
@module_required(MODULE)
def store_move(item_id):
    item = db.get_or_404(StoreItem, item_id)
    kind = (request.form.get("kind") or "in").strip()
    if kind not in MOVEMENT_KINDS:
        kind = "in"
    qty = request.form.get("qty", type=int) or 0
    if qty <= 0:
        flash(t("store.bad_qty"), "danger")
        return redirect(url_for("inventory.store"))
    # Receipts add, issues/wastage subtract.
    signed = qty if kind == "in" else -qty
    db.session.add(StockMovement(
        item_id=item.id, kind=kind, qty=signed,
        reason=(request.form.get("reason") or "").strip() or None,
        unit_cost=request.form.get("unit_cost", type=float),
        supplier_id=request.form.get("supplier_id", type=int) or None,
        created_by=current_user.id,
    ))
    db.session.commit()
    flash(t("store.move_done"), "success")
    return redirect(url_for("inventory.store_item", item_id=item.id))


@inventory_bp.route("/store/<int:item_id>")
@module_required(MODULE)
def store_item(item_id):
    item = db.get_or_404(StoreItem, item_id)
    movements = (
        StockMovement.query.filter_by(item_id=item.id)
        .order_by(StockMovement.created_at.desc()).all()
    )
    return render_template("inventory/store_item.html", item=item,
                           movements=movements, suppliers=_suppliers())


@inventory_bp.route("/store/stocktake", methods=["GET", "POST"])
@module_required(MODULE)
def stocktake():
    items = StoreItem.query.filter_by(is_active=True).order_by(StoreItem.name).all()
    if request.method == "POST":
        adjusted = 0
        for item in items:
            raw = request.form.get(f"count_{item.id}")
            if raw is None or raw.strip() == "":
                continue
            try:
                counted = int(raw)
            except ValueError:
                continue
            diff = counted - item.current_stock
            if diff != 0:
                db.session.add(StockMovement(
                    item_id=item.id, kind="adjust", qty=diff,
                    reason=t("store.stocktake"), created_by=current_user.id,
                ))
                adjusted += 1
        ActivityLog.record("store.stocktake", user_id=current_user.id,
                           entity="store", detail=str(adjusted), ip_address=client_ip())
        db.session.commit()
        flash(t("store.stocktake_done").replace("{n}", str(adjusted)), "success")
        return redirect(url_for("inventory.store"))
    return render_template("inventory/stocktake.html", items=items)
