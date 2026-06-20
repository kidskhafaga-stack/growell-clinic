"""Finance module — Services & Commissions (foundation).

Manages the clinic's chargeable services: pricing, max discount, doctor
commission (default + per-doctor overrides) and service bundles. Later
phases build invoices, doctor statements and discount claims on top.
"""
from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user

from app.blueprints.finance import finance_bp
from app.extensions import db
from app.i18n import t
from app.models import (
    COMMISSION_TYPES,
    SERVICE_CATEGORIES,
    ActivityLog,
    DoctorServiceCommission,
    Service,
    ServiceBundleItem,
    User,
)
from app.utils.decorators import client_ip, module_required

MODULE = "finance"


def _doctors():
    return User.query.filter_by(role="doctor").order_by(User.full_name).all()


def _clean_commission():
    """Read & sanitise commission type/value from the request form."""
    ctype = (request.form.get("commission_type") or "none").strip()
    if ctype not in COMMISSION_TYPES:
        ctype = "none"
    cval = request.form.get("commission_value", type=float) or 0
    return ctype, cval


@finance_bp.route("/")
@module_required(MODULE)
def index():
    services = Service.query.order_by(Service.sort_order, Service.name).all()
    return render_template("finance/index.html", services=services)


@finance_bp.route("/services")
@module_required(MODULE)
def services():
    services = Service.query.order_by(Service.sort_order, Service.name).all()
    return render_template(
        "finance/services.html", services=services,
        categories=SERVICE_CATEGORIES, commission_types=COMMISSION_TYPES,
        doctors=_doctors(),
    )


@finance_bp.route("/services/new", methods=["POST"])
@module_required(MODULE)
def service_new():
    name = (request.form.get("name") or "").strip()
    if not name:
        flash(t("common.required") + ": " + t("services.name"), "danger")
        return redirect(url_for("finance.services"))
    ctype, cval = _clean_commission()
    category = (request.form.get("category") or "other").strip()
    svc = Service(
        name=name,
        name_en=(request.form.get("name_en") or "").strip() or None,
        code=(request.form.get("code") or "").strip() or None,
        category=category if category in SERVICE_CATEGORIES else "other",
        price=request.form.get("price", type=float) or 0,
        max_discount=request.form.get("max_discount", type=float),
        commission_type=ctype, commission_value=cval,
        is_bundle=bool(request.form.get("is_bundle")),
        notes=(request.form.get("notes") or "").strip() or None,
    )
    db.session.add(svc)
    ActivityLog.record("service.add", user_id=current_user.id, entity="service",
                       detail=name, ip_address=client_ip())
    db.session.commit()
    flash(t("services.added"), "success")
    return redirect(url_for("finance.services"))


@finance_bp.route("/services/<int:service_id>/edit", methods=["POST"])
@module_required(MODULE)
def service_edit(service_id):
    svc = db.get_or_404(Service, service_id)
    svc.name = (request.form.get("name") or svc.name).strip()
    svc.name_en = (request.form.get("name_en") or "").strip() or None
    svc.code = (request.form.get("code") or "").strip() or None
    category = (request.form.get("category") or svc.category).strip()
    svc.category = category if category in SERVICE_CATEGORIES else svc.category
    svc.price = request.form.get("price", type=float) or 0
    svc.max_discount = request.form.get("max_discount", type=float)
    svc.commission_type, svc.commission_value = _clean_commission()
    svc.is_active = bool(request.form.get("is_active"))
    db.session.commit()
    flash(t("services.updated"), "success")
    return redirect(url_for("finance.services"))


@finance_bp.route("/services/<int:service_id>/delete", methods=["POST"])
@module_required(MODULE)
def service_delete(service_id):
    svc = db.get_or_404(Service, service_id)
    db.session.delete(svc)
    db.session.commit()
    flash(t("services.deleted"), "info")
    return redirect(url_for("finance.services"))


@finance_bp.route("/services/<int:service_id>/commissions", methods=["POST"])
@module_required(MODULE)
def service_commissions(service_id):
    """Set per-doctor commission overrides for a service."""
    svc = db.get_or_404(Service, service_id)
    existing = {oc.doctor_id: oc for oc in svc.doctor_commissions}
    for doc in _doctors():
        ctype = (request.form.get(f"type_{doc.id}") or "none").strip()
        if ctype not in COMMISSION_TYPES:
            ctype = "none"
        cval = request.form.get(f"value_{doc.id}", type=float) or 0
        oc = existing.get(doc.id)
        if ctype == "none":
            if oc:  # clearing an override falls back to the service default
                db.session.delete(oc)
            continue
        if oc is None:
            oc = DoctorServiceCommission(doctor_id=doc.id, service_id=svc.id)
            db.session.add(oc)
        oc.commission_type, oc.commission_value = ctype, cval
    db.session.commit()
    flash(t("services.commissions_saved"), "success")
    return redirect(url_for("finance.services"))


@finance_bp.route("/services/<int:service_id>/bundle", methods=["POST"])
@module_required(MODULE)
def service_bundle(service_id):
    """Replace a bundle's component services."""
    svc = db.get_or_404(Service, service_id)
    svc.is_bundle = True
    # Reset and rebuild components from the submitted checkboxes.
    svc.bundle_items.clear()
    db.session.flush()
    for cid in request.form.getlist("component_id", type=int):
        if cid != svc.id:
            db.session.add(ServiceBundleItem(bundle_id=svc.id, component_id=cid))
    db.session.commit()
    flash(t("services.bundle_saved"), "success")
    return redirect(url_for("finance.services"))
