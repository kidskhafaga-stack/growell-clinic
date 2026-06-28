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
    PurchaseOrder,
    PurchaseOrderItem,
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

    # Quantity may be entered as whole vials (multiplied by the brand's
    # doses-per-vial) or directly as patient doses. Stock is stored in doses.
    per = brand.doses_per_vial or 1
    qty_vials = request.form.get("qty_vials", type=int)
    if qty_vials:
        qty_doses = qty_vials * per
    else:
        qty_doses = request.form.get("qty_received", type=int) or 0

    batch = VaccineInventory(
        brand_id=brand.id,
        supplier_id=request.form.get("supplier_id", type=int) or None,
        lot_number=(request.form.get("lot_number") or "").strip() or None,
        expiry_date=_parse_date("expiry_date"),
        received_date=_parse_date("received_date") or datetime.utcnow().date(),
        qty_received=qty_doses,
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


# ================================================= purchase orders =========
def _po_number():
    """Sequential PO number like PO-2026-0007."""
    year = datetime.utcnow().year
    prefix = f"PO-{year}-"
    last = (PurchaseOrder.query.filter(PurchaseOrder.po_number.like(prefix + "%"))
            .order_by(PurchaseOrder.id.desc()).first())
    seq = 1
    if last and last.po_number:
        try:
            seq = int(last.po_number.rsplit("-", 1)[1]) + 1
        except (ValueError, IndexError):
            seq = PurchaseOrder.query.count() + 1
    return f"{prefix}{seq:04d}"


@inventory_bp.route("/purchase")
@module_required(MODULE)
def purchases():
    status = (request.args.get("status") or "").strip()
    q = PurchaseOrder.query
    if status in ("draft", "approved", "partial", "received", "cancelled"):
        q = q.filter(PurchaseOrder.status == status)
    orders = q.order_by(PurchaseOrder.id.desc()).limit(200).all()
    return render_template("inventory/purchases.html", orders=orders, status=status)


@inventory_bp.route("/purchase/new", methods=["GET", "POST"])
@module_required(MODULE)
def purchase_new():
    if request.method == "POST":
        po = PurchaseOrder(
            po_number=_po_number(),
            supplier_id=request.form.get("supplier_id", type=int) or None,
            order_date=_parse_date("order_date") or datetime.utcnow().date(),
            expected_date=_parse_date("expected_date"),
            notes=(request.form.get("notes") or "").strip() or None,
            created_by=current_user.id, status="draft",
        )
        db.session.add(po)
        db.session.flush()

        names = request.form.getlist("item_desc")
        item_ids = request.form.getlist("item_store_id")
        qtys = request.form.getlist("item_qty")
        costs = request.form.getlist("item_cost")
        count = 0
        for i in range(len(names)):
            desc = (names[i] or "").strip()
            qty = _to_int(qtys[i] if i < len(qtys) else "")
            if not desc or qty <= 0:
                continue
            po.items.append(PurchaseOrderItem(
                store_item_id=_to_int(item_ids[i]) or None if i < len(item_ids) else None,
                description=desc, qty_ordered=qty,
                unit_cost=_to_float(costs[i] if i < len(costs) else ""),
            ))
            count += 1
        if count == 0:
            db.session.rollback()
            flash(t("purchases.need_item"), "warning")
            return redirect(url_for("inventory.purchase_new"))
        ActivityLog.record("po.create", user_id=current_user.id, entity="purchase",
                           entity_id=po.id, detail=po.po_number, ip_address=client_ip())
        db.session.commit()
        flash(t("purchases.created"), "success")
        return redirect(url_for("inventory.purchase_view", po_id=po.id))

    return render_template("inventory/purchase_form.html",
                           suppliers=_suppliers(),
                           items=StoreItem.query.filter_by(is_active=True).order_by(StoreItem.name).all())


@inventory_bp.route("/purchase/<int:po_id>")
@module_required(MODULE)
def purchase_view(po_id):
    po = db.get_or_404(PurchaseOrder, po_id)
    return render_template("inventory/purchase_view.html", po=po)


@inventory_bp.route("/purchase/<int:po_id>/approve", methods=["POST"])
@module_required(MODULE)
def purchase_approve(po_id):
    po = db.get_or_404(PurchaseOrder, po_id)
    if po.status == "draft":
        po.status = "approved"
        po.approved_by = current_user.id
        po.approved_at = datetime.utcnow()
        ActivityLog.record("po.approve", user_id=current_user.id, entity="purchase",
                           entity_id=po.id, detail=po.po_number, ip_address=client_ip())
        db.session.commit()
        flash(t("purchases.approved"), "success")
    return redirect(url_for("inventory.purchase_view", po_id=po.id))


@inventory_bp.route("/purchase/<int:po_id>/receive", methods=["POST"])
@module_required(MODULE)
def purchase_receive(po_id):
    """GRN: post received quantities into stock as 'in' movements."""
    po = db.get_or_404(PurchaseOrder, po_id)
    if po.status not in ("approved", "partial"):
        flash(t("purchases.cannot_receive"), "warning")
        return redirect(url_for("inventory.purchase_view", po_id=po.id))

    posted = 0
    receipt_value = 0.0   # value of THIS GRN only (not cumulative)
    for item in po.items:
        recv = _to_int(request.form.get(f"recv_{item.id}", ""))
        if recv <= 0:
            continue
        # Don't receive more than outstanding.
        recv = min(recv, item.outstanding)
        if recv <= 0:
            continue
        item.qty_received = (item.qty_received or 0) + recv
        receipt_value += recv * (item.unit_cost or 0)
        if item.store_item_id:
            db.session.add(StockMovement(
                item_id=item.store_item_id, kind="in", qty=recv,
                reason=t("purchases.grn_reason", po=po.po_number),
                unit_cost=item.unit_cost, supplier_id=po.supplier_id,
                created_by=current_user.id,
            ))
        posted += 1

    if posted == 0:
        flash(t("purchases.nothing_received"), "warning")
        return redirect(url_for("inventory.purchase_view", po_id=po.id))

    po.recalc_status()
    if po.status == "received":
        po.received_at = datetime.utcnow()

    # Optionally record this receipt's value as a clinic expense.
    if request.form.get("as_expense") and receipt_value > 0:
        from app.models import Expense
        db.session.add(Expense(
            expense_date=datetime.utcnow().date(), category="supplies",
            description=t("purchases.grn_reason", po=po.po_number),
            amount=round(receipt_value, 2),
            vendor=(po.supplier.name if po.supplier else None),
            created_by=current_user.id,
        ))

    ActivityLog.record("po.receive", user_id=current_user.id, entity="purchase",
                       entity_id=po.id, detail=po.po_number, ip_address=client_ip())
    db.session.commit()
    flash(t("purchases.received_ok"), "success")
    return redirect(url_for("inventory.purchase_view", po_id=po.id))


@inventory_bp.route("/purchase/<int:po_id>/cancel", methods=["POST"])
@module_required(MODULE)
def purchase_cancel(po_id):
    po = db.get_or_404(PurchaseOrder, po_id)
    if po.status != "received":
        po.status = "cancelled"
        db.session.commit()
        flash(t("purchases.cancelled"), "info")
    return redirect(url_for("inventory.purchase_view", po_id=po.id))


@inventory_bp.route("/purchase/<int:po_id>/delete", methods=["POST"])
@module_required(MODULE)
def purchase_delete(po_id):
    po = db.get_or_404(PurchaseOrder, po_id)
    if po.status != "draft":
        flash(t("purchases.only_draft_delete"), "warning")
        return redirect(url_for("inventory.purchase_view", po_id=po.id))
    db.session.delete(po)
    db.session.commit()
    flash(t("purchases.deleted"), "info")
    return redirect(url_for("inventory.purchases"))


def _to_int(raw):
    try:
        return int(float((raw or "").strip()))
    except (ValueError, AttributeError):
        return 0


def _to_float(raw):
    try:
        return float((raw or "").strip())
    except (ValueError, AttributeError):
        return 0.0
