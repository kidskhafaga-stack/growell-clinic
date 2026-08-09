"""Vaccine inventory & suppliers (Phase 6.2).

Lot/batch stock with expiry tracking, stock alerts (near-expiry / low / out),
and supplier management. Optional (clinic-provided) vaccines carry stock;
mandatory (government) vaccines do not.
"""
from datetime import datetime

from flask import flash, g, redirect, render_template, request, url_for
from flask_login import current_user

from app.blueprints.inventory import inventory_bp
from app.extensions import db
from app.i18n import t
from app.models import (
    DOC_KINDS,
    MOVEMENT_KINDS,
    RECEIPT_REASONS,
    WAREHOUSE_KINDS,
    ActivityLog,
    PurchaseOrder,
    PurchaseOrderItem,
    StockMovement,
    StoreDocument,
    StoreItem,
    Supplier,
    Vaccine,
    VaccineBrand,
    VaccineInventory,
    VaccineAdjustment,
    Warehouse,
)
from app.utils.costing import (apply_purchase_cost, default_margin,
                               issue_unit_cost)
from app.utils.decorators import client_ip, module_required
from app.utils.paging import paginate
from app.utils.periods import period_blocked

MODULE = "inventory"


def _parse_date(name):
    return _parse_date_str(request.form.get(name))


def _parse_date_str(raw):
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        return None


def _optional_brands(q=None):
    """Brands of optional (clinic-provided) vaccines — these carry stock.

    ``q`` filters by scientific name, trade name (ar/en), manufacturer,
    barcode or item code — the ERP item search box.
    """
    query = (VaccineBrand.query.join(Vaccine)
             .filter(Vaccine.is_mandatory.is_(False)))
    if q:
        like = f"%{q.strip()}%"
        query = query.filter(db.or_(
            VaccineBrand.name.ilike(like),
            VaccineBrand.name_en.ilike(like),
            VaccineBrand.manufacturer.ilike(like),
            VaccineBrand.barcode.ilike(like),
            VaccineBrand.item_code.ilike(like),
            Vaccine.name_ar.ilike(like),
            Vaccine.name_en.ilike(like),
        ))
    return query.order_by(Vaccine.sort_order, VaccineBrand.name).all()


@inventory_bp.route("/")
@module_required(MODULE)
def index():
    q = (request.args.get("q") or "").strip()
    brands = _optional_brands(q)
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
        alerts=alerts, stats=stats, suppliers=suppliers, q=q,
        receipt_reasons=RECEIPT_REASONS,
    )


@inventory_bp.route("/items")
@module_required(MODULE)
def items():
    """Unified item catalogue (تعريف الأصناف): vaccine items and general-store
    items in one searchable, filterable list, with quick-add for both. Deep
    editing still happens on each item's own card."""
    from flask import g
    lang = getattr(g, "lang", "ar")
    q = (request.args.get("q") or "").strip()
    kind = (request.args.get("kind") or "").strip()
    like = f"%{q}%" if q else None

    rows = []
    if kind in ("", "vaccine"):
        vq = VaccineBrand.query.join(Vaccine)
        if like:
            vq = vq.filter(db.or_(
                VaccineBrand.name.ilike(like), VaccineBrand.name_en.ilike(like),
                VaccineBrand.manufacturer.ilike(like), VaccineBrand.barcode.ilike(like),
                VaccineBrand.item_code.ilike(like),
                Vaccine.name_ar.ilike(like), Vaccine.name_en.ilike(like)))
        for b in vq.all():
            rows.append({
                "kind": "vaccine", "name": b.display_name(lang),
                "subtitle": b.vaccine.display_name(lang),
                "code": b.barcode or b.item_code, "purchase": b.purchase_price,
                "sell": b.price, "stock": b.stock, "active": not b.is_discontinued,
                "url": url_for("inventory.item_card", brand_id=b.id)})
    if kind in ("", "store"):
        sq = StoreItem.query
        if like:
            sq = sq.filter(db.or_(
                StoreItem.name.ilike(like), StoreItem.name_en.ilike(like),
                StoreItem.category.ilike(like), StoreItem.barcode.ilike(like)))
        for it in sq.all():
            rows.append({
                "kind": "store", "name": it.name, "subtitle": it.category or "—",
                "code": it.barcode, "purchase": it.purchase_price,
                "sell": it.sell_price, "stock": it.current_stock, "active": it.is_active,
                "url": url_for("inventory.store_item", item_id=it.id)})

    rows.sort(key=lambda r: (r["name"] or "").lower())
    counts = {"all": len(rows),
              "vaccine": sum(1 for r in rows if r["kind"] == "vaccine"),
              "store": sum(1 for r in rows if r["kind"] == "store")}
    vaccines = Vaccine.query.order_by(Vaccine.sort_order, Vaccine.name_ar).all()
    return render_template("inventory/items.html", rows=rows, q=q, kind=kind,
                           counts=counts, vaccines=vaccines)


@inventory_bp.route("/items/new", methods=["POST"])
@module_required(MODULE)
def item_new():
    """Create an item from the unified catalogue — dispatched by kind to the
    right underlying model (vaccine brand under a master vaccine, or store item)."""
    kind = (request.form.get("item_kind") or "store").strip()
    name = (request.form.get("name") or "").strip()
    if not name:
        flash(t("common.required") + ": " + t("store.name"), "danger")
        return redirect(url_for("inventory.items"))

    if kind == "vaccine":
        from app.utils.item_codes import next_brand_code

        vaccine = db.session.get(Vaccine, request.form.get("vaccine_id", type=int))
        if vaccine is None:
            flash(t("common.required") + ": " + t("inventory.master_vaccine"), "danger")
            return redirect(url_for("inventory.items"))
        brand = VaccineBrand(
            vaccine_id=vaccine.id, name=name,
            name_en=(request.form.get("name_en") or "").strip() or None,
            manufacturer=(request.form.get("manufacturer") or "").strip() or None,
            barcode=(request.form.get("barcode") or "").strip() or None,
            # Generated, like a store item's. It was the one creation form
            # left asking a person for an internal code, and left blank the
            # brand had none at all until the next update ran the backfill —
            # so the barcode screen could not find a product created today.
            # The supplier's own number has its own field: barcode.
            item_code=next_brand_code(),
            purchase_price=request.form.get("purchase_price", type=float),
            price=request.form.get("price", type=float),
            doses_per_vial=max(request.form.get("doses_per_vial", type=int) or 1, 1),
            min_stock=request.form.get("min_stock", type=int),
            is_default=not vaccine.brands)
        db.session.add(brand)
        ActivityLog.record("inventory.item_define", user_id=current_user.id,
                           entity="vaccine_brand", detail=name, ip_address=client_ip())
        db.session.commit()
        flash(t("vaccinations.brand_added"), "success")
        return redirect(url_for("inventory.item_card", brand_id=brand.id))

    from app.utils.item_codes import next_store_code
    item = StoreItem(
        name=name, name_en=(request.form.get("name_en") or "").strip() or None,
        item_code=next_store_code(),
        category=(request.form.get("category") or "").strip() or None,
        unit=(request.form.get("unit") or "").strip() or None,
        purchase_unit=(request.form.get("purchase_unit") or "").strip() or None,
        units_per_purchase=request.form.get("units_per_purchase", type=int) or 1,
        barcode=(request.form.get("barcode") or "").strip() or None,
        purchase_price=request.form.get("purchase_price", type=float),
        sell_price=request.form.get("price", type=float),
        reorder_level=request.form.get("min_stock", type=int) or 0,
        opening_stock=request.form.get("opening_stock", type=int) or 0)
    db.session.add(item)
    ActivityLog.record("inventory.item_define", user_id=current_user.id,
                       entity="store_item", detail=name, ip_address=client_ip())
    db.session.commit()
    flash(t("store.item_added"), "success")
    return redirect(url_for("inventory.store_item", item_id=item.id))


def _receiving_warehouse():
    """Where a vaccine receipt lands: what the form said, else the fridge.

    A posted ``warehouse_id`` is honoured only if this user may work there —
    a store keeper restricted to one warehouse must not be able to put stock
    into somebody else's by editing a form field.
    """
    wh_id = request.values.get("warehouse_id", type=int)
    posted = db.session.get(Warehouse, wh_id) if wh_id else None
    if posted is not None and posted.is_active and posted.allows(current_user):
        return posted
    return Warehouse.for_vaccines()


@inventory_bp.route("/batch/new", methods=["POST"])
@module_required(MODULE)
def batch_new():
    """Goods Receipt (إذن إضافة): add stock outside a purchase order (opening
    balance, gift, donation, return, adjustment) — always with a documented
    reason. A batch is the *result* of the receipt, tagged with its source."""
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

    reason = (request.form.get("receipt_reason") or "opening").strip()
    if reason not in RECEIPT_REASONS:
        reason = "opening"

    # Stock is money on a shelf: receiving a box into January after January's
    # books are signed changes January's closing stock value. The store obeys
    # the same period lock the till does.
    received_on = _parse_date("received_date") or datetime.utcnow().date()
    if period_blocked(received_on):
        return redirect(url_for("inventory.index"))

    from app.utils.store_docs import open_document

    grn = open_document("grn", reference=t(f"receipt_reasons.{reason}"),
                        supplier_id=request.form.get("supplier_id", type=int) or None)
    batch = VaccineInventory(
        brand_id=brand.id,
        supplier_id=request.form.get("supplier_id", type=int) or None,
        lot_number=(request.form.get("lot_number") or "").strip() or None,
        expiry_date=_parse_date("expiry_date"),
        mfg_date=_parse_date("mfg_date"),
        received_date=_parse_date("received_date") or datetime.utcnow().date(),
        receipt_reason=reason,
        qty_received=qty_doses,
        unit_cost=request.form.get("unit_cost", type=float),
        storage_temp=(request.form.get("storage_temp") or "").strip() or None,
        notes=(request.form.get("notes") or "").strip() or None,
        document_id=grn.id,
        # Where it physically goes. Defaults to the fridge when the clinic has
        # one — receiving vaccines into the general store is what made the
        # fridge a warehouse you could only ever transfer *into*.
        warehouse_id=_receiving_warehouse().id,
    )
    grn.warehouse_id = batch.warehouse_id
    db.session.add(batch)
    ActivityLog.record("inventory.goods_receipt", user_id=current_user.id,
                       entity="vaccine_inventory",
                       detail=f"{brand.name}:{reason}:{qty_doses}", ip_address=client_ip())
    db.session.commit()
    # Purchases feed the inventory asset (W3); gifts/opening carry no debt.
    if reason == "purchase":
        _post_doc_safe(grn)
    flash(t("inventory.receipt_added"), "success")
    return redirect(url_for("inventory.item_card", brand_id=brand.id))


@inventory_bp.route("/receipt/new", methods=["GET", "POST"])
@module_required(MODULE)
def receipt_new():
    """Multi-item Goods Receipt (إذن إضافة مخزني): one receipt document that adds
    stock for SEVERAL vaccine items at once — each line becomes its own batch,
    all sharing the receipt's reason, supplier and date. This replaces the old
    one-item-at-a-time form so a whole delivery can be posted in a single go."""
    brands = _optional_brands()
    if request.method == "POST":
        reason = (request.form.get("receipt_reason") or "opening").strip()
        if reason not in RECEIPT_REASONS:
            reason = "opening"
        supplier_id = request.form.get("supplier_id", type=int) or None
        received = _parse_date("received_date") or datetime.utcnow().date()
        if period_blocked(received):
            return redirect(url_for("inventory.receipt_new"))
        header_note = (request.form.get("notes") or "").strip() or None

        brand_ids = request.form.getlist("line_brand_id")
        qtys = request.form.getlist("line_qty")
        units = request.form.getlist("line_unit")
        lots = request.form.getlist("line_lot")
        exps = request.form.getlist("line_expiry")
        mfgs = request.form.getlist("line_mfg")
        costs = request.form.getlist("line_cost")

        from app.utils.store_docs import open_document

        by_id = {b.id: b for b in brands}
        added = 0
        touched = []
        grn = None  # one numbered GRN for the whole delivery
        into = _receiving_warehouse()   # the fridge, unless the form says else
        for i in range(len(brand_ids)):
            brand = by_id.get(_to_int(brand_ids[i]))
            qty = _to_int(qtys[i] if i < len(qtys) else "")
            if brand is None or qty <= 0:
                continue
            if grn is None:
                grn = open_document("grn", reference=t(f"receipt_reasons.{reason}"),
                                    supplier_id=supplier_id, notes=header_note,
                                    doc_date=received)
                grn.warehouse_id = into.id
            unit = (units[i] if i < len(units) else "") or "doses"
            per = brand.doses_per_vial or 1
            qty_doses = qty * per if unit == "vials" else qty
            line_cost = _to_float(costs[i]) if i < len(costs) and costs[i].strip() else None
            if line_cost:
                # New purchase cost: auto-refresh the sell price when the
                # brand's pricing policy asks for it (آخر سعر شراء + هامش).
                from app.utils.costing import apply_purchase_cost
                apply_purchase_cost(brand, line_cost)
            db.session.add(VaccineInventory(
                brand_id=brand.id, supplier_id=supplier_id,
                lot_number=(lots[i].strip() if i < len(lots) else "") or None,
                expiry_date=_parse_date_str(exps[i] if i < len(exps) else ""),
                mfg_date=_parse_date_str(mfgs[i] if i < len(mfgs) else ""),
                received_date=received, receipt_reason=reason,
                qty_received=qty_doses,
                unit_cost=line_cost,
                notes=header_note, document_id=grn.id,
                warehouse_id=into.id,
            ))
            added += 1
            if brand not in touched:
                touched.append(brand)

        if added == 0:
            flash(t("purchases.need_item"), "warning")
            return redirect(url_for("inventory.receipt_new"))

        ActivityLog.record("inventory.goods_receipt", user_id=current_user.id,
                           entity="vaccine_inventory",
                           detail=f"{reason}:{added} lines", ip_address=client_ip())
        for brand in touched:
            brand.recompute_avg_cost()
        db.session.commit()
        if reason == "purchase" and grn is not None:
            _post_doc_safe(grn)
        flash(t("inventory.receipt_multi_added", n=added), "success")
        return redirect(url_for("inventory.index"))

    return render_template(
        "inventory/receipt_form.html", brands=brands, suppliers=_suppliers(),
        receipt_reasons=RECEIPT_REASONS, today=datetime.utcnow().date().isoformat(),
        warehouses=_warehouses(), into=_receiving_warehouse(),
    )


@inventory_bp.route("/item/<int:brand_id>")
@module_required(MODULE)
def item_card(brand_id):
    """Item Card: one commercial item (brand) with its master vaccine, on-hand,
    valuation and every batch (soonest expiry first) with its receipt source."""
    brand = db.get_or_404(VaccineBrand, brand_id)
    batches = sorted(
        brand.batches,
        key=lambda b: (b.expiry_date is None, b.expiry_date or datetime.max.date()),
    )
    doses_given = (VaccineInventory.query
                   .with_entities(db.func.coalesce(db.func.sum(VaccineInventory.qty_used), 0))
                   .filter(VaccineInventory.brand_id == brand.id).scalar()) or 0
    # The card was a photograph of now — batches and what is left in them. A
    # store card is the history that explains now, which is what somebody
    # reaches for when the shelf and the screen disagree.
    from app.utils import item_card as card

    return render_template(
        "inventory/item_card.html", brand=brand, batches=batches,
        doses_given=int(doses_given), suppliers=_suppliers(),
        receipt_reasons=RECEIPT_REASONS,
        ledger=card.ledger(brand), held=card.by_warehouse(brand),
        warehouses=_warehouses(),
        default_margin=default_margin(),
    )


@inventory_bp.route("/item/<int:brand_id>/pricing", methods=["POST"])
@module_required(MODULE)
def item_pricing(brand_id):
    """Edit an item's commercial data straight from its card: cost (شراء) and
    sell (بيع) price, the doctor's fee, max discount, reorder level, and the
    purchase/dispense unit labels with the doses-per-purchase-unit conversion.
    The profit margin is derived from cost & sell, so it isn't stored."""
    brand = db.get_or_404(VaccineBrand, brand_id)
    brand.purchase_price = request.form.get("purchase_price", type=float)
    brand.price = request.form.get("price", type=float)
    brand.doctor_fee = request.form.get("doctor_fee", type=float)
    brand.max_discount = request.form.get("max_discount", type=float)
    brand.min_stock = request.form.get("min_stock", type=int)
    # Auto-pricing. The engine has always understood vaccines — a purchase
    # receipt calls the same ``apply_purchase_cost`` for a brand as for a
    # store item — but there was nowhere to *switch it on* for one, so the
    # columns sat at their defaults and the feature existed only for the
    # general store. This is the switch.
    brand.price_policy = ("auto" if request.form.get("price_policy") == "auto"
                          else "manual")
    brand.margin_percent = request.form.get("margin_percent", type=float)
    brand.doses_per_vial = max(request.form.get("doses_per_vial", type=int) or 1, 1)
    brand.purchase_unit = (request.form.get("purchase_unit") or "").strip() or None
    brand.dispense_unit = (request.form.get("dispense_unit") or "").strip() or None
    ActivityLog.record("inventory.item_pricing", user_id=current_user.id,
                       entity="vaccine_brand", entity_id=brand.id,
                       detail=brand.name, ip_address=client_ip())
    db.session.commit()
    flash(t("inventory.pricing_saved"), "success")
    return redirect(url_for("inventory.item_card", brand_id=brand.id))


@inventory_bp.route("/vaccine-stocktake", methods=["GET", "POST"])
@module_required(MODULE)
def vaccine_stocktake():
    """Count one warehouse of vaccines, and keep the count.

    Two things were wrong with what this did before, and they are the same
    thing twice. It counted **every** batch the clinic owns, so a clinic with a
    fridge and a sub-store was asked to count them as one shelf and could not
    say which one it had walked. And it wrote the result by silently rewriting
    ``qty_used``: no document, no time, no counter — *"الجرد يوضّح توقيته"*.

    So: a warehouse is chosen, only its batches are listed, and a difference
    becomes a numbered adjustment document with a row per batch that moved,
    saying what the shelf held, what was counted, when, and by whom.
    """
    from app.utils import item_card as card
    from app.utils.store_docs import open_document

    warehouses = _warehouses()
    wh_id = request.values.get("warehouse_id", type=int)
    warehouse = next((w for w in warehouses if w.id == wh_id), None)
    if warehouse is None:
        if wh_id:
            if _warehouse_denied(db.session.get(Warehouse, wh_id)):
                return redirect(url_for("inventory.vaccine_stocktake"))
        # The fridge first: it is where the vaccines are, and counting them is
        # the only reason anybody opens this screen.
        warehouse = next((w for w in warehouses if w.kind == "fridge"),
                         warehouses[0] if warehouses else Warehouse.default())
    if _warehouse_denied(warehouse):
        return redirect(url_for("inventory.index"))

    batches = card.batches_in(warehouse)
    if request.method == "POST":
        if period_blocked(datetime.utcnow().date()):
            return redirect(url_for("inventory.vaccine_stocktake",
                                    warehouse_id=warehouse.id))
        doc = None
        adjusted = 0
        for batch in batches:
            raw = request.form.get(f"count_{batch.id}")
            if raw is None or raw.strip() == "":
                continue
            try:
                counted = int(raw)
            except ValueError:
                continue
            counted = max(counted, 0)
            was = batch.qty_remaining
            if counted == was:
                continue
            if doc is None:
                doc = open_document("adjust",
                                    reference=t("inventory.vaccine_stocktake"))
                doc.warehouse_id = warehouse.id
            db.session.add(VaccineAdjustment(
                batch_id=batch.id, document_id=doc.id,
                warehouse_id=warehouse.id, was=was, counted=counted,
                reason=(request.form.get("reason") or "").strip() or None,
                created_by=current_user.id))
            # Keep qty_received; set used so remaining == counted.
            batch.qty_used = max((batch.qty_received or 0) - counted, 0)
            adjusted += 1
        if adjusted:
            ActivityLog.record("inventory.vaccine_stocktake", user_id=current_user.id,
                               entity="vaccine_inventory",
                               detail=f"{warehouse.id}:{adjusted}",
                               ip_address=client_ip())
            db.session.commit()
        flash(t("inventory.stocktake_done", n=adjusted), "success")
        return redirect(url_for("inventory.vaccine_stocktake",
                                warehouse_id=warehouse.id))
    return render_template("inventory/vaccine_stocktake.html", batches=batches,
                           warehouses=warehouses, warehouse=warehouse,
                           last=card.last_count(warehouse),
                           elsewhere=VaccineInventory.query.count() - len(batches))


@inventory_bp.route("/batch/<int:batch_id>/delete", methods=["POST"])
@module_required(MODULE)
def batch_delete(batch_id):
    batch = db.get_or_404(VaccineInventory, batch_id)
    # Deleting a batch received inside a signed month rewrites that month's
    # closing stock — same rule as deleting one of its invoices.
    if period_blocked(batch.received_date or datetime.utcnow().date()):
        return redirect(url_for("inventory.index"))
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
    from app.utils.costing import default_margin, store_dispense_policy
    from app.utils.store_seed import (store_categories, store_purchase_units,
                                       store_units)
    return render_template("inventory/store.html", items=items, low=low,
                           stats=stats, suppliers=_suppliers(),
                           categories=store_categories(), units=store_units(),
                           purchase_units=store_purchase_units(),
                           item_types=_item_types(),
                           dispense_policy=store_dispense_policy(),
                           margin_default=default_margin())


@inventory_bp.route("/store/policy", methods=["POST"])
@module_required(MODULE)
def store_policy():
    """Save the general store's issue-costing policy (FIFO/LIFO) and the
    clinic-wide default profit margin for auto-priced items. Vaccines always
    dispense FEFO (soonest expiry first) — that isn't configurable."""
    from app.models import Setting
    from app.utils.costing import DISPENSE_POLICIES
    pol = (request.form.get("dispense_policy") or "fifo").strip()
    Setting.set("store_dispense_policy",
                pol if pol in DISPENSE_POLICIES else "fifo")
    margin = request.form.get("default_margin", type=float)
    if margin is not None and margin >= 0:
        Setting.set("default_margin_percent", str(margin))
    db.session.commit()
    flash(t("store.policy_saved"), "success")
    return redirect(url_for("inventory.store"))


@inventory_bp.route("/store/load-defaults", methods=["POST"])
@module_required(MODULE)
def store_load_defaults():
    """Seed the default clinic consumables (fill-only) so the store isn't empty
    on a fresh setup. Never touches or duplicates items already defined."""
    from app.utils.store_seed import seed_store_items
    n = seed_store_items()
    db.session.commit()
    flash(t("store.defaults_loaded").replace("{n}", str(n)), "success")
    return redirect(url_for("inventory.store"))


@inventory_bp.route("/store/new", methods=["POST"])
@module_required(MODULE)
def store_item_new():
    name = (request.form.get("name") or "").strip()
    if not name:
        flash(t("common.required") + ": " + t("store.name"), "danger")
        return redirect(url_for("inventory.store"))
    from app.utils.item_codes import next_store_code
    item = StoreItem(
        name=name,
        item_code=next_store_code(),
        name_en=(request.form.get("name_en") or "").strip() or None,
        category=(request.form.get("category") or "").strip() or None,
        unit=(request.form.get("unit") or "").strip() or None,
        purchase_unit=(request.form.get("purchase_unit") or "").strip() or None,
        units_per_purchase=request.form.get("units_per_purchase", type=int) or 1,
        barcode=(request.form.get("barcode") or "").strip() or None,
        purchase_price=request.form.get("purchase_price", type=float),
        sell_price=request.form.get("sell_price", type=float),
        item_type=(request.form.get("item_type") or "").strip() or None,
        price_policy=("auto" if request.form.get("price_policy") == "auto" else "manual"),
        margin_percent=request.form.get("margin_percent", type=float),
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
    item.purchase_unit = (request.form.get("purchase_unit") or "").strip() or None
    item.units_per_purchase = request.form.get("units_per_purchase", type=int) or 1
    item.barcode = (request.form.get("barcode") or "").strip() or None
    item.purchase_price = request.form.get("purchase_price", type=float)
    item.sell_price = request.form.get("sell_price", type=float)
    item.item_type = (request.form.get("item_type") or "").strip() or None
    item.price_policy = "auto" if request.form.get("price_policy") == "auto" else "manual"
    item.margin_percent = request.form.get("margin_percent", type=float)
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
    if period_blocked(datetime.utcnow().date()):
        return redirect(url_for("inventory.store"))
    # Receipts add, issues/wastage subtract — each under a numbered document.
    from app.utils.store_docs import open_document

    signed = qty if kind == "in" else -qty
    doc_kind = {"in": "grn", "out": "issue", "waste": "waste"}.get(kind, "adjust")
    doc = open_document(doc_kind,
                        reference=(request.form.get("reason") or "").strip() or None,
                        supplier_id=request.form.get("supplier_id", type=int) or None)
    db.session.add(StockMovement(
        item_id=item.id, kind=kind, qty=signed, document_id=doc.id,
        reason=(request.form.get("reason") or "").strip() or None,
        # Issues/wastage are costed by the store's dispensing policy (FIFO by
        # default, LIFO if configured); a typed cost always wins.
        unit_cost=request.form.get("unit_cost", type=float)
                  or (issue_unit_cost(item) if kind != "in" else None),
        supplier_id=request.form.get("supplier_id", type=int) or None,
        created_by=current_user.id,
    ))
    # A costed receipt is a new purchase price → honour the item's sell-price
    # policy (auto margin) and stamp آخر سعر شراء.
    if kind == "in":
        apply_purchase_cost(item, request.form.get("unit_cost", type=float))
    db.session.commit()
    # W3 journal: consumption (out) hits COGS, wastage hits expenses. A manual
    # "in" stays document-only (its financing depends on why it arrived).
    if kind in ("out", "waste"):
        _post_doc_safe(doc)
    flash(t("store.move_done_doc", doc=doc.doc_number), "success")
    return redirect(url_for("inventory.store_item", item_id=item.id))


@inventory_bp.route("/store/<int:item_id>")
@module_required(MODULE)
def store_item(item_id):
    item = db.get_or_404(StoreItem, item_id)
    movements = (
        StockMovement.query.filter_by(item_id=item.id)
        .order_by(StockMovement.created_at.desc()).all()
    )
    from app.utils.store_seed import (store_categories, store_purchase_units,
                                       store_units)
    return render_template("inventory/store_item.html", item=item,
                           movements=movements, suppliers=_suppliers(),
                           categories=store_categories(), units=store_units(),
                           purchase_units=store_purchase_units(),
                           item_types=_item_types())


@inventory_bp.route("/scan")
@module_required(MODULE)
def scan():
    """Resolve a scanned (or typed) barcode to its item card.

    One entry point for both ways a code arrives: a USB/Bluetooth scanner types
    it and presses Enter, a phone reads it with the camera — either way it is
    just a string looked up against the item code and the supplier barcode, for
    store items and vaccine brands alike."""
    code = (request.args.get("code") or "").strip()
    if not code:
        return redirect(url_for("inventory.items"))
    item = (StoreItem.query.filter(db.or_(StoreItem.item_code == code,
                                          StoreItem.barcode == code)).first())
    if item is not None:
        return redirect(url_for("inventory.store_item", item_id=item.id))
    brand = (VaccineBrand.query.filter(db.or_(VaccineBrand.item_code == code,
                                              VaccineBrand.barcode == code)).first())
    if brand is not None:
        return redirect(url_for("inventory.item_card", brand_id=brand.id))
    flash(t("scan.not_found").replace("{code}", code), "warning")
    return redirect(url_for("inventory.items", q=code))


def _item_by_code(code):
    """The store item a scanned code belongs to, if any."""
    code = (code or "").strip()
    if not code:
        return None
    return StoreItem.query.filter(db.or_(StoreItem.item_code == code,
                                         StoreItem.barcode == code)).first()


@inventory_bp.route("/store/stocktake", methods=["GET", "POST"])
@module_required(MODULE)
def stocktake():
    """Count one warehouse at a time.

    Counting the clinic-wide total is useless when the stock sits in several
    places: you stand in *one* store with the shelf in front of you. The screen
    therefore counts the selected warehouse — system quantity, counted quantity
    and the correction all belong to it, and the adjustment movements are
    tagged with it so the other warehouses are never touched."""
    from app.utils.store_docs import open_document

    warehouses = _warehouses()
    wh_id = request.values.get("warehouse_id", type=int)
    warehouse = next((w for w in warehouses if w.id == wh_id), None)
    if warehouse is None:
        if wh_id:                       # asked for one they may not touch
            if _warehouse_denied(db.session.get(Warehouse, wh_id)):
                return redirect(url_for("inventory.store"))
        warehouse = warehouses[0] if warehouses else Warehouse.default()
    if _warehouse_denied(warehouse):
        return redirect(url_for("inventory.store"))
    items = StoreItem.query.filter_by(is_active=True).order_by(StoreItem.name).all()
    if request.method == "POST":
        if period_blocked(datetime.utcnow().date()):
            return redirect(url_for("inventory.stocktake",
                                    warehouse_id=warehouse.id))
        adjusted = 0
        doc = None  # one adjustment document for the whole count
        for item in items:
            raw = request.form.get(f"count_{item.id}")
            if raw is None or raw.strip() == "":
                continue
            try:
                counted = int(raw)
            except ValueError:
                continue
            diff = counted - item.stock_in(warehouse)
            if diff != 0:
                if doc is None:
                    doc = open_document("adjust", reference=t("store.stocktake"))
                    doc.warehouse_id = warehouse.id
                db.session.add(StockMovement(
                    item_id=item.id, kind="adjust", qty=diff, document_id=doc.id,
                    warehouse_id=warehouse.id,
                    reason=f"{t('store.stocktake')} — {warehouse.name}",
                    created_by=current_user.id,
                ))
                adjusted += 1
        ActivityLog.record("store.stocktake", user_id=current_user.id,
                           entity="store", detail=f"{warehouse.id}:{adjusted}",
                           ip_address=client_ip())
        db.session.commit()
        flash(t("store.stocktake_done").replace("{n}", str(adjusted)), "success")
        return redirect(url_for("inventory.stocktake", warehouse_id=warehouse.id))
    rows = [{"item": i, "system": i.stock_in(warehouse), "total": i.current_stock}
            for i in items]
    # Scanned an item while standing at the shelf? Jump straight to its row.
    code = (request.args.get("code") or "").strip()
    scanned = _item_by_code(code)
    if code and scanned is None:
        flash(t("scan.not_found").replace("{code}", code), "warning")
    return render_template("inventory/stocktake.html", items=items, rows=rows,
                           warehouses=warehouses, warehouse=warehouse,
                           scanned_id=scanned.id if scanned else None)


# ===================================================== warehouses (W2) =====
def _warehouses(all_of_them=False):
    """Active warehouses this user may work in (the default one is ensured).

    A big organisation gives each store its own keeper: once a warehouse has
    keepers, only they work in it, and a keeper only sees their own stores.
    Clinics that never assign anyone keep seeing everything."""
    Warehouse.default()
    db.session.commit()
    rows = Warehouse.query.filter_by(is_active=True).order_by(Warehouse.id).all()
    if all_of_them:
        return rows
    return [w for w in rows if w.allows(current_user)]


def _warehouse_denied(warehouse):
    """Refuse a warehouse this user isn't a keeper of (and say so)."""
    if warehouse is not None and warehouse.allows(current_user):
        return False
    flash(t("warehouses.no_access"), "danger")
    return True


@inventory_bp.route("/warehouses", methods=["GET", "POST"])
@module_required(MODULE)
def warehouses():
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        if not name:
            flash(t("common.required") + ": " + t("warehouses.name"), "danger")
            return redirect(url_for("inventory.warehouses"))
        kind = (request.form.get("kind") or "sub").strip()
        db.session.add(Warehouse(
            name=name, name_en=(request.form.get("name_en") or "").strip() or None,
            kind=kind if kind in WAREHOUSE_KINDS else "sub",
            notes=(request.form.get("notes") or "").strip() or None,
        ))
        db.session.commit()
        flash(t("warehouses.added"), "success")
        return redirect(url_for("inventory.warehouses"))
    whs = _warehouses(all_of_them=current_user.is_admin)
    items = StoreItem.query.filter_by(is_active=True).order_by(StoreItem.name).all()
    # Per-warehouse stock snapshot for the overview table.
    stock = {w.id: sum(1 for i in items if i.stock_in(w) > 0) for w in whs}
    from app.models import User
    staff = (User.query.filter_by(is_active=True)
             .order_by(User.full_name).all()) if current_user.is_admin else []
    return render_template("inventory/warehouses.html", warehouses=whs,
                           warehouse_kinds=WAREHOUSE_KINDS, stock=stock,
                           staff=staff)


@inventory_bp.route("/warehouses/<int:wh_id>/keepers", methods=["POST"])
@module_required(MODULE)
def warehouse_keepers(wh_id):
    """Set who works in this warehouse. Empty = open to everyone (the default),
    which is why an existing clinic notices nothing until it assigns someone."""
    from app.models import User

    if not current_user.is_admin:
        from flask import abort
        abort(403)
    wh = db.get_or_404(Warehouse, wh_id)
    ids = [i for i in request.form.getlist("user_ids") if str(i).isdigit()]
    wh.keepers = User.query.filter(User.id.in_([int(i) for i in ids])).all() \
        if ids else []
    ActivityLog.record("warehouse.keepers", user_id=current_user.id,
                       entity="warehouse", entity_id=wh.id,
                       detail=str(len(wh.keepers)), ip_address=client_ip())
    db.session.commit()
    flash(t("warehouses.keepers_saved"), "success")
    return redirect(url_for("inventory.warehouses"))


@inventory_bp.route("/warehouses/<int:wh_id>/toggle", methods=["POST"])
@module_required(MODULE)
def warehouse_toggle(wh_id):
    wh = db.get_or_404(Warehouse, wh_id)
    if wh.is_default:
        flash(t("warehouses.cannot_disable_default"), "warning")
    else:
        wh.is_active = not wh.is_active
        db.session.commit()
        flash(t("common.saved"), "success")
    return redirect(url_for("inventory.warehouses"))


@inventory_bp.route("/transfer/new", methods=["GET", "POST"])
@module_required(MODULE)
def transfer_new():
    """Transfer stock between warehouses under one numbered TRF document:
    general-store items move as an out+in movement pair; a vaccine batch
    moves by consuming from the source batch and opening a linked batch in
    the destination (lot/expiry/cost preserved)."""
    from app.utils.store_docs import open_document

    whs = _warehouses()
    items = StoreItem.query.filter_by(is_active=True).order_by(StoreItem.name).all()
    batches = [b for b in VaccineInventory.query.order_by(VaccineInventory.id.desc()).all()
               if b.qty_remaining > 0 and not b.is_expired]

    if request.method == "POST":
        src = db.session.get(Warehouse, request.form.get("from_id", type=int))
        dst = db.session.get(Warehouse, request.form.get("to_id", type=int))
        if src is None or dst is None or src.id == dst.id:
            flash(t("warehouses.bad_pair"), "danger")
            return redirect(url_for("inventory.transfer_new"))
        # Stock may only leave a store its keeper is responsible for.
        if _warehouse_denied(src):
            return redirect(url_for("inventory.transfer_new"))
        if period_blocked(datetime.utcnow().date()):
            return redirect(url_for("inventory.transfer_new"))

        doc = None
        moved = 0

        # General-store lines: item_id[] + qty[]
        item_ids = request.form.getlist("line_item_id")
        qtys = request.form.getlist("line_item_qty")
        by_id = {i.id: i for i in items}
        for i in range(len(item_ids)):
            item = by_id.get(_to_int(item_ids[i]))
            qty = _to_int(qtys[i] if i < len(qtys) else "")
            if item is None or qty <= 0:
                continue
            if item.stock_in(src) < qty:
                flash(t("warehouses.not_enough", item=item.name), "danger")
                db.session.rollback()
                return redirect(url_for("inventory.transfer_new"))
            if doc is None:
                doc = open_document("transfer")
                doc.warehouse_id, doc.to_warehouse_id = src.id, dst.id
            reason = t("warehouses.trf_reason", doc=doc.doc_number)
            trf_cost = issue_unit_cost(item)  # both legs carry the same value
            db.session.add(StockMovement(
                item_id=item.id, kind="out", qty=-qty, document_id=doc.id,
                warehouse_id=src.id, reason=reason,
                unit_cost=trf_cost, created_by=current_user.id))
            db.session.add(StockMovement(
                item_id=item.id, kind="in", qty=qty, document_id=doc.id,
                warehouse_id=dst.id, reason=reason,
                unit_cost=trf_cost, created_by=current_user.id))
            moved += 1

        # Vaccine batch lines: batch_id[] + qty[]
        b_ids = request.form.getlist("line_batch_id")
        b_qtys = request.form.getlist("line_batch_qty")
        by_bid = {b.id: b for b in batches}
        default_wh = Warehouse.default()
        for i in range(len(b_ids)):
            batch = by_bid.get(_to_int(b_ids[i]))
            qty = _to_int(b_qtys[i] if i < len(b_qtys) else "")
            if batch is None or qty <= 0:
                continue
            b_wh = batch.warehouse_id or default_wh.id
            if b_wh != src.id or batch.qty_remaining < qty:
                flash(t("warehouses.not_enough",
                        item=batch.brand.name if batch.brand else "?"), "danger")
                db.session.rollback()
                return redirect(url_for("inventory.transfer_new"))
            if doc is None:
                doc = open_document("transfer")
                doc.warehouse_id, doc.to_warehouse_id = src.id, dst.id
            batch.qty_used = (batch.qty_used or 0) + qty
            db.session.add(VaccineInventory(
                brand_id=batch.brand_id, supplier_id=batch.supplier_id,
                lot_number=batch.lot_number, expiry_date=batch.expiry_date,
                mfg_date=batch.mfg_date,
                received_date=datetime.utcnow().date(),
                receipt_reason="transfer", qty_received=qty,
                unit_cost=batch.unit_cost, warehouse_id=dst.id,
                document_id=doc.id,
                notes=t("warehouses.trf_from_batch", n=batch.id)))
            moved += 1

        if moved == 0:
            db.session.rollback()
            flash(t("purchases.need_item"), "warning")
            return redirect(url_for("inventory.transfer_new"))

        ActivityLog.record("store.transfer", user_id=current_user.id,
                           entity="store", entity_id=doc.id,
                           detail=doc.doc_number, ip_address=client_ip())
        db.session.commit()
        flash(t("warehouses.transferred", doc=doc.doc_number), "success")
        return redirect(url_for("inventory.document_view", doc_id=doc.id))

    lang = getattr(g, "lang", "ar")
    return render_template("inventory/transfer_form.html", warehouses=whs,
                           items=items, batches=batches, lang=lang)


def _post_doc_safe(doc):
    """Best-effort inventory journal (W3): Dr/Cr المخزون حسب نوع الإذن —
    a bookkeeping hiccup must never block store work."""
    try:
        from app.utils import accounting as acct

        acct.post_store_doc(doc, user_id=current_user.id)
    except Exception:  # noqa: BLE001
        db.session.rollback()


@inventory_bp.route("/return/new", methods=["GET", "POST"])
@module_required(MODULE)
def return_new():
    """Return stock to a supplier under a numbered RTN document (W3): store
    items post an out movement; a vaccine batch is consumed at its cost.
    The journal recovers the value from the supplier (Dr 2010 / Cr 1040)."""
    from app.utils.store_docs import open_document

    whs = _warehouses()
    items = StoreItem.query.filter_by(is_active=True).order_by(StoreItem.name).all()
    batches = [b for b in VaccineInventory.query.order_by(VaccineInventory.id.desc()).all()
               if b.qty_remaining > 0]

    if request.method == "POST":
        if period_blocked(datetime.utcnow().date()):
            return redirect(url_for("inventory.return_new"))
        src = db.session.get(Warehouse, request.form.get("from_id", type=int)) \
            or Warehouse.default()
        supplier_id = request.form.get("supplier_id", type=int) or None
        reason = (request.form.get("reason") or "").strip() or None

        doc = None
        moved = 0

        item_ids = request.form.getlist("line_item_id")
        qtys = request.form.getlist("line_item_qty")
        by_id = {i.id: i for i in items}
        for i in range(len(item_ids)):
            item = by_id.get(_to_int(item_ids[i]))
            qty = _to_int(qtys[i] if i < len(qtys) else "")
            if item is None or qty <= 0:
                continue
            if item.stock_in(src) < qty:
                flash(t("warehouses.not_enough", item=item.name), "danger")
                db.session.rollback()
                return redirect(url_for("inventory.return_new"))
            if doc is None:
                doc = open_document("return", reference=reason,
                                    supplier_id=supplier_id)
                doc.warehouse_id = src.id
            db.session.add(StockMovement(
                item_id=item.id, kind="out", qty=-qty, document_id=doc.id,
                warehouse_id=src.id, unit_cost=issue_unit_cost(item),
                supplier_id=supplier_id, created_by=current_user.id,
                reason=t("returns.reason", doc=doc.doc_number)))
            moved += 1

        b_ids = request.form.getlist("line_batch_id")
        b_qtys = request.form.getlist("line_batch_qty")
        by_bid = {b.id: b for b in batches}
        default_wh = Warehouse.default()
        for i in range(len(b_ids)):
            batch = by_bid.get(_to_int(b_ids[i]))
            qty = _to_int(b_qtys[i] if i < len(b_qtys) else "")
            if batch is None or qty <= 0:
                continue
            if batch.qty_remaining < qty:
                flash(t("warehouses.not_enough",
                        item=batch.brand.name if batch.brand else "?"), "danger")
                db.session.rollback()
                return redirect(url_for("inventory.return_new"))
            if doc is None:
                doc = open_document("return", reference=reason,
                                    supplier_id=supplier_id or batch.supplier_id)
                doc.warehouse_id = batch.warehouse_id or default_wh.id
            batch.qty_used = (batch.qty_used or 0) + qty
            # Marker row carrying the returned qty/cost on the document:
            # received == used so it holds no stock, but the document (and the
            # journal) see the returned value.
            db.session.add(VaccineInventory(
                brand_id=batch.brand_id, supplier_id=supplier_id or batch.supplier_id,
                lot_number=batch.lot_number, expiry_date=batch.expiry_date,
                received_date=datetime.utcnow().date(),
                receipt_reason="return", qty_received=qty, qty_used=qty,
                unit_cost=batch.unit_cost, document_id=doc.id,
                warehouse_id=doc.warehouse_id,
                notes=t("returns.batch_note", qty=qty, n=batch.id)))
            moved += 1

        if moved == 0:
            db.session.rollback()
            flash(t("purchases.need_item"), "warning")
            return redirect(url_for("inventory.return_new"))

        ActivityLog.record("store.return", user_id=current_user.id,
                           entity="store", entity_id=doc.id,
                           detail=doc.doc_number, ip_address=client_ip())
        db.session.commit()
        _post_doc_safe(doc)
        flash(t("returns.done", doc=doc.doc_number), "success")
        return redirect(url_for("inventory.document_view", doc_id=doc.id))

    return render_template("inventory/return_form.html", warehouses=whs,
                           items=items, batches=batches, suppliers=_suppliers())


# ============================================== warehouse documents (W1) ===
@inventory_bp.route("/documents")
@module_required(MODULE)
def documents():
    """The store's documentary ledger: every GRN / issue / adjustment / waste
    as a numbered document, filterable by kind."""
    kind = (request.args.get("kind") or "").strip()
    q = StoreDocument.query
    if kind in DOC_KINDS:
        q = q.filter(StoreDocument.kind == kind)
    pagination = paginate(q.order_by(StoreDocument.id.desc()))
    return render_template("inventory/documents.html", pagination=pagination,
                           documents=pagination.items, kind=kind,
                           doc_kinds=DOC_KINDS)


@inventory_bp.route("/documents/<int:doc_id>")
@module_required(MODULE)
def document_view(doc_id):
    """One warehouse document, printable: header + its stock lines (general
    store movements and/or vaccine batches)."""
    doc = db.get_or_404(StoreDocument, doc_id)
    batches = VaccineInventory.query.filter_by(document_id=doc.id).all()
    total_value = round(doc.total_value + sum(
        (b.qty_received or 0) * (b.unit_cost or 0) for b in batches), 2)
    return render_template("inventory/document_view.html", doc=doc,
                           batches=batches, total_value=total_value)


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
        vaccine_ids = request.form.getlist("item_vaccine_id")
        qtys = request.form.getlist("item_qty")
        costs = request.form.getlist("item_cost")
        count = 0
        for i in range(len(names)):
            desc = (names[i] or "").strip()
            qty = _to_int(qtys[i] if i < len(qtys) else "")
            if not desc or qty <= 0:
                continue
            vbid = _to_int(vaccine_ids[i]) or None if i < len(vaccine_ids) else None
            po.items.append(PurchaseOrderItem(
                store_item_id=(_to_int(item_ids[i]) or None if i < len(item_ids) else None)
                if not vbid else None,
                vaccine_brand_id=vbid,
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
                           items=StoreItem.query.filter_by(is_active=True).order_by(StoreItem.name).all(),
                           vaccine_brands=_optional_brands())


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
    # A GRN is a purchase: it raises stock value and the supplier's balance.
    # Neither belongs in a month that has already been signed off.
    if period_blocked(datetime.utcnow().date()):
        return redirect(url_for("inventory.purchase_view", po_id=po.id))

    from app.utils.store_docs import open_document

    posted = 0
    receipt_value = 0.0   # value of THIS GRN only (not cumulative)
    grn = None            # opened lazily so an empty submit leaves no document
    for item in po.items:
        recv = _to_int(request.form.get(f"recv_{item.id}", ""))
        if recv <= 0:
            continue
        # Don't receive more than outstanding.
        recv = min(recv, item.outstanding)
        if recv <= 0:
            continue
        if grn is None:
            grn = open_document("grn", reference=po.po_number,
                                supplier_id=po.supplier_id)
        item.qty_received = (item.qty_received or 0) + recv
        receipt_value += recv * (item.unit_cost or 0)
        if item.vaccine_brand_id:
            # A vaccine line becomes a real inventory batch (document → batch),
            # tagged as a purchase receipt, then refresh the item's avg cost.
            batch = VaccineInventory(
                brand_id=item.vaccine_brand_id, supplier_id=po.supplier_id,
                lot_number=(request.form.get(f"lot_{item.id}") or "").strip() or None,
                expiry_date=_parse_date(f"exp_{item.id}"),
                mfg_date=_parse_date(f"mfg_{item.id}"),
                received_date=datetime.utcnow().date(), receipt_reason="purchase",
                qty_received=recv, unit_cost=item.unit_cost,
                document_id=grn.id,
                # A delivery of vaccines goes in the fridge, like every other
                # way of receiving them.
                warehouse_id=Warehouse.for_vaccines().id,
            )
            db.session.add(batch)
            if item.vaccine_brand:
                item.vaccine_brand.recompute_avg_cost()
                apply_purchase_cost(item.vaccine_brand, item.unit_cost)
        elif item.store_item_id:
            db.session.add(StockMovement(
                item_id=item.store_item_id, kind="in", qty=recv,
                reason=t("purchases.grn_reason", po=po.po_number),
                unit_cost=item.unit_cost, supplier_id=po.supplier_id,
                created_by=current_user.id, document_id=grn.id,
            ))
            if item.store_item:
                apply_purchase_cost(item.store_item, item.unit_cost)
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
    # Inventory journal (W3): Dr 1040 المخزون / Cr 2010 الموردون for this GRN.
    if grn is not None:
        _post_doc_safe(grn)
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


@inventory_bp.route("/store/<int:item_id>/label")
@module_required(MODULE)
def store_item_label(item_id):
    """Printable barcode label for a general-store item (Code 39, offline)."""
    item = db.get_or_404(StoreItem, item_id)
    from app.utils.barcode39 import svg
    code = item.barcode or item.item_code or str(item.id)
    copies = min(max(request.args.get("copies", 1, type=int) or 1, 1), 40)
    return render_template(
        "inventory/label.html", name=item.display_name(getattr(g, "lang", "ar")),
        code=code, price=item.sell_price, barcode_svg=svg(code), copies=copies)


@inventory_bp.route("/brand/<int:brand_id>/label")
@module_required(MODULE)
def brand_label(brand_id):
    """Printable barcode label for a vaccine brand (Code 39, offline)."""
    brand = db.get_or_404(VaccineBrand, brand_id)
    from app.utils.barcode39 import svg
    code = brand.barcode or brand.item_code or str(brand.id)
    copies = min(max(request.args.get("copies", 1, type=int) or 1, 1), 40)
    lang = getattr(g, "lang", "ar")
    name = (f"{brand.vaccine.display_name(lang)} — {brand.display_name(lang)}"
            if brand.vaccine else brand.display_name(lang))
    return render_template(
        "inventory/label.html", name=name, code=code,
        price=brand.price, barcode_svg=svg(code), copies=copies)


def _item_types():
    """The clinic's item types, for the add/edit pickers."""
    from app.utils.lookups import ensure_seeded, options

    try:
        if ensure_seeded():
            db.session.commit()
        return options("item_type")
    except Exception:                      # noqa: BLE001 - table not created
        return []


# --------------------------------------------------- the clinic's own lists --
@inventory_bp.route("/lookups")
@module_required(MODULE)
def lookups():
    """Item types, categories, units and warehouse kinds — all editable.

    The fourth fixed list to be opened up, and the first to be done once
    rather than four times. What was wrong with each differed usefully:
    ``WAREHOUSE_KINDS`` was a Python list nobody could extend, while the
    categories and units *looked* editable — the picker offered the defaults
    plus everything ever typed — but nothing could be removed. One "قطعه"
    typed instead of "قطعة" sat beside the correct one for the life of the
    installation, and everybody after chose between them at random.
    """
    from app.utils.lookups import DOMAINS, ensure_seeded, options, usage_counts

    ensure_seeded()
    db.session.commit()
    domain = (request.args.get("domain") or "item_type").strip()
    if domain not in DOMAINS:
        domain = "item_type"
    from app.utils.lookups import BUILT_IN, can_delete

    counts = usage_counts(domain)
    rows = options(domain, include_inactive=True)
    return render_template(
        "inventory/lookups.html", domain=domain, domains=DOMAINS, rows=rows,
        counts=counts,
        deletable={r.id: can_delete(r, counts)[0] for r in rows},
        # Categories sit under a type, so the form has to offer the types.
        types=options("item_type") if domain == "item_category" else [],
        built_in=BUILT_IN,
    )


@inventory_bp.route("/lookups/add", methods=["POST"])
@module_required(MODULE)
def lookup_add():
    from app.models import Lookup
    from app.utils.lookups import DOMAINS, make_key

    domain = (request.form.get("domain") or "").strip()
    name_ar = (request.form.get("name_ar") or "").strip()
    if domain not in DOMAINS or not name_ar:
        flash(t("common.required"), "danger")
        return redirect(url_for("inventory.lookups", domain=domain or None))
    last = (Lookup.query.filter_by(domain=domain)
            .order_by(Lookup.sort_order.desc()).first())
    db.session.add(Lookup(
        domain=domain, key=make_key(request.form.get("name_en") or name_ar, domain),
        name_ar=name_ar,
        name_en=(request.form.get("name_en") or "").strip() or None,
        parent_key=(request.form.get("parent_key") or "").strip() or None,
        sort_order=(last.sort_order + 1) if last else 0,
    ))
    ActivityLog.record("lookup.create", user_id=current_user.id, entity="lookup",
                       detail=f"{domain}:{name_ar}", ip_address=client_ip())
    db.session.commit()
    flash(t("lookups.added"), "success")
    return redirect(url_for("inventory.lookups", domain=domain))


@inventory_bp.route("/lookups/<int:row_id>/edit", methods=["POST"])
@module_required(MODULE)
def lookup_edit(row_id):
    """Reword or reclassify an entry — never re-key it.

    The key is what every item row stored. Changing it would orphan them all
    silently, so this edits the label and the parent and leaves the key alone,
    which is the rule the three catalogues before this one arrived at too.
    """
    from app.models import Lookup

    row = db.get_or_404(Lookup, row_id)
    row.name_ar = (request.form.get("name_ar") or row.name_ar or "").strip()
    row.name_en = (request.form.get("name_en") or "").strip() or None
    row.parent_key = (request.form.get("parent_key") or "").strip() or None
    row.is_active = bool(request.form.get("is_active"))
    db.session.commit()
    flash(t("lookups.saved"), "success")
    return redirect(url_for("inventory.lookups", domain=row.domain))


@inventory_bp.route("/lookups/<int:row_id>/delete", methods=["POST"])
@module_required(MODULE)
def lookup_delete(row_id):
    """Remove an entry, unless something depends on it.

    A built-in stays, and so does anything in use — deleting either would
    leave items pointing at a value that no longer exists, which is a report
    that quietly drops rows rather than an error anybody sees. Both cases fall
    back to switching it off, which keeps the history readable and still takes
    it off tomorrow's list.
    """
    from app.models import Lookup
    from app.utils.lookups import can_delete

    row = db.get_or_404(Lookup, row_id)
    domain = row.domain
    allowed, reason = can_delete(row)
    if allowed:
        db.session.delete(row)
        flash(t("lookups.deleted"), "success")
    else:
        row.is_active = False
        flash(t("lookups.deactivated_" + reason), "warning")
    ActivityLog.record("lookup.delete", user_id=current_user.id, entity="lookup",
                       entity_id=row_id, detail=reason, ip_address=client_ip())
    db.session.commit()
    return redirect(url_for("inventory.lookups", domain=domain))
