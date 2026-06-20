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
    ActivityLog,
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
