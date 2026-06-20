"""Finance module — Services & Commissions (foundation).

Manages the clinic's chargeable services: pricing, max discount, doctor
commission (default + per-doctor overrides) and service bundles. Later
phases build invoices, doctor statements and discount claims on top.
"""
from datetime import datetime

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user

from app.blueprints.finance import finance_bp
from app.extensions import db
from app.i18n import t
from app.models import (
    COMMISSION_TYPES,
    COVERAGE_TYPES,
    PAYER_TYPES,
    PAYMENT_METHODS,
    SERVICE_CATEGORIES,
    ActivityLog,
    DoctorServiceCommission,
    Invoice,
    InvoiceItem,
    Patient,
    PayerEntity,
    PayerServiceRate,
    Payment,
    Service,
    ServiceBundleItem,
    User,
)
from app.utils.decorators import client_ip, module_required
from app.utils.finance import generate_invoice_number

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


# =======================================================================
# Invoices & payments
# =======================================================================
def _doctors_active():
    return User.query.filter_by(role="doctor", is_active=True).order_by(User.full_name).all()


def _add_item_from_form(invoice, prefix=""):
    """Build an InvoiceItem from form fields; returns it or None if empty."""
    service_id = request.form.get(f"{prefix}service_id", type=int)
    desc = (request.form.get(f"{prefix}description") or "").strip()
    price = request.form.get(f"{prefix}unit_price", type=float)
    service = db.session.get(Service, service_id) if service_id else None

    if service and not desc:
        desc = service.name
    if service and price is None:
        price = service.price
    if not desc or price is None:
        return None

    qty = request.form.get(f"{prefix}quantity", type=int) or 1
    disc_val = request.form.get(f"{prefix}discount_value", type=float) or 0
    disc_pct = bool(request.form.get(f"{prefix}discount_is_percent"))

    item = InvoiceItem(
        service_id=service.id if service else None,
        description=desc, unit_price=price, quantity=qty,
        discount_value=disc_val, discount_is_percent=disc_pct,
    )
    # Snapshot the doctor commission for this line's net amount.
    if service is not None:
        item.commission_amount = service.doctor_share(item.net, invoice.doctor)
    return item


@finance_bp.route("/invoices")
@module_required(MODULE)
def invoices():
    status = (request.args.get("status") or "").strip()
    q = Invoice.query
    if status in ("unpaid", "partial", "paid"):
        q = q.filter_by(status=status)
    page = request.args.get("page", 1, type=int)
    pagination = q.order_by(Invoice.id.desc()).paginate(page=page, per_page=25, error_out=False)
    return render_template("finance/invoices.html", pagination=pagination,
                           invoices=pagination.items, status=status)


def _apply_coverage(invoice, patient):
    """Auto-apply a member's per-service coverage to the invoice lines.

    For each covered line the entity's share becomes the line discount (so the
    patient pays the rest and the entity share is claimable). Uncovered
    services are left untouched (patient pays full — option ب). An expired card
    is not applied automatically; the user is warned instead.
    """
    coverage = patient.active_coverage if patient else None
    # If the card exists but is expired/inactive, warn and skip auto-apply.
    if coverage is None:
        expired = [c for c in getattr(patient, "coverages", []) if not c.is_valid]
        if expired:
            flash(t("coverage.expired_warn"), "warning")
        return

    payer = coverage.payer
    invoice.payer_id = payer.id
    invoice.coverage_card = coverage.membership_number
    invoice.coverage_expiry = coverage.expiry_date

    for item in invoice.items:
        if not item.service_id or (item.discount_value or 0) > 0:
            continue  # keep manual discounts; skip free-text lines
        covered = payer.covers(item.service, item.gross)
        if covered > 0:
            item.discount_value = covered
            item.discount_is_percent = False
            if item.service is not None:
                item.commission_amount = item.service.doctor_share(item.net, invoice.doctor)


@finance_bp.route("/invoices/new", methods=["GET", "POST"])
@module_required(MODULE)
def invoice_new():
    if request.method == "POST":
        patient = db.session.get(Patient, request.form.get("patient_id", type=int))
        if patient is None:
            flash(t("invoices.need_patient"), "danger")
            return redirect(url_for("finance.invoice_new"))

        invoice = Invoice(
            invoice_number=generate_invoice_number(),
            patient_id=patient.id,
            doctor_id=request.form.get("doctor_id", type=int) or None,
            visit_id=request.form.get("visit_id", type=int) or None,
            payer_id=request.form.get("payer_id", type=int) or None,
            created_by=current_user.id,
            notes=(request.form.get("notes") or "").strip() or None,
        )
        db.session.add(invoice)
        db.session.flush()

        # Multiple line rows submitted as service_id[], etc.
        count = 0
        for idx in range(len(request.form.getlist("line_service_id"))):
            item = _build_line(invoice, idx)
            if item:
                invoice.items.append(item)
                count += 1
        if count == 0:
            db.session.rollback()
            flash(t("invoices.need_item"), "warning")
            return redirect(url_for("finance.invoice_new", patient_id=patient.id))

        # Apply the patient's membership/insurance coverage automatically.
        _apply_coverage(invoice, patient)

        invoice.recalc_status()
        ActivityLog.record("invoice.create", user_id=current_user.id, entity="invoice",
                           detail=invoice.invoice_number, ip_address=client_ip())
        db.session.commit()
        flash(t("invoices.created"), "success")
        return redirect(url_for("finance.invoice_view", invoice_id=invoice.id))

    patient = db.session.get(Patient, request.args.get("patient_id", type=int))
    return render_template(
        "finance/invoice_form.html", patient=patient,
        doctors=_doctors_active(),
        services=Service.query.filter_by(is_active=True).order_by(Service.name).all(),
        patients=Patient.query.filter_by(is_active=True).order_by(Patient.full_name).limit(500).all(),
        payers=PayerEntity.query.filter_by(is_active=True).order_by(PayerEntity.name).all(),
        visit_id=request.args.get("visit_id", type=int),
        doctor_id=request.args.get("doctor_id", type=int),
    )


def _build_line(invoice, idx):
    services = request.form.getlist("line_service_id")
    descs = request.form.getlist("line_description")
    prices = request.form.getlist("line_unit_price")
    qtys = request.form.getlist("line_quantity")
    discs = request.form.getlist("line_discount_value")
    dpcts = request.form.getlist("line_discount_is_percent")

    def _num(lst, i, cast, default=None):
        try:
            return cast(lst[i]) if i < len(lst) and lst[i] != "" else default
        except (ValueError, TypeError):
            return default

    sid = _num(services, idx, int)
    service = db.session.get(Service, sid) if sid else None
    desc = (descs[idx].strip() if idx < len(descs) else "")
    if service and not desc:
        desc = service.name
    price = _num(prices, idx, float)
    if service and price is None:
        price = service.price
    if not desc or price is None:
        return None

    item = InvoiceItem(
        service_id=service.id if service else None,
        description=desc, unit_price=price,
        quantity=_num(qtys, idx, int, 1) or 1,
        discount_value=_num(discs, idx, float, 0) or 0,
        discount_is_percent=(idx < len(dpcts) and dpcts[idx] in ("1", "on", "true")),
    )
    if service is not None:
        item.commission_amount = service.doctor_share(item.net, invoice.doctor)
    return item


@finance_bp.route("/invoices/<int:invoice_id>")
@module_required(MODULE)
def invoice_view(invoice_id):
    invoice = db.get_or_404(Invoice, invoice_id)
    return render_template(
        "finance/invoice_view.html", invoice=invoice, methods=PAYMENT_METHODS,
        services_active=Service.query.filter_by(is_active=True).order_by(Service.name).all(),
        payers=PayerEntity.query.filter_by(is_active=True).order_by(PayerEntity.name).all(),
        doctors=_doctors_active(),
        patients=Patient.query.filter_by(is_active=True).order_by(Patient.full_name).limit(500).all(),
    )


@finance_bp.route("/invoices/<int:invoice_id>/payment", methods=["POST"])
@module_required(MODULE)
def invoice_payment(invoice_id):
    invoice = db.get_or_404(Invoice, invoice_id)
    amount = request.form.get("amount", type=float)
    if not amount or amount <= 0:
        flash(t("invoices.bad_amount"), "danger")
        return redirect(url_for("finance.invoice_view", invoice_id=invoice.id))
    method = (request.form.get("method") or "cash").strip()
    invoice.payments.append(Payment(
        amount=round(amount, 2),
        method=method if method in PAYMENT_METHODS else "cash",
        received_by=current_user.id,
        notes=(request.form.get("notes") or "").strip() or None,
    ))
    invoice.recalc_status()
    ActivityLog.record("invoice.payment", user_id=current_user.id, entity="invoice",
                       detail=f"{invoice.invoice_number}:{amount}", ip_address=client_ip())
    db.session.commit()
    flash(t("invoices.payment_added"), "success")
    return redirect(url_for("finance.invoice_view", invoice_id=invoice.id))


@finance_bp.route("/invoices/<int:invoice_id>/item/add", methods=["POST"])
@module_required(MODULE)
def invoice_item_add(invoice_id):
    invoice = db.get_or_404(Invoice, invoice_id)
    item = _add_item_from_form(invoice)
    if item is None:
        flash(t("invoices.need_item"), "warning")
    else:
        invoice.items.append(item)
        invoice.recalc_status()
        db.session.commit()
        flash(t("invoices.item_added"), "success")
    return redirect(url_for("finance.invoice_view", invoice_id=invoice.id))


@finance_bp.route("/invoices/<int:invoice_id>/item/<int:item_id>/delete", methods=["POST"])
@module_required(MODULE)
def invoice_item_delete(invoice_id, item_id):
    invoice = db.get_or_404(Invoice, invoice_id)
    item = db.session.get(InvoiceItem, item_id)
    if item and item.invoice_id == invoice.id:
        db.session.delete(item)
        db.session.flush()
        invoice.recalc_status()
        db.session.commit()
        flash(t("invoices.item_removed"), "info")
    return redirect(url_for("finance.invoice_view", invoice_id=invoice.id))


@finance_bp.route("/invoices/<int:invoice_id>/item/<int:item_id>/edit", methods=["POST"])
@module_required(MODULE)
def invoice_item_edit(invoice_id, item_id):
    invoice = db.get_or_404(Invoice, invoice_id)
    item = db.session.get(InvoiceItem, item_id)
    if not item or item.invoice_id != invoice.id:
        return redirect(url_for("finance.invoice_view", invoice_id=invoice.id))

    desc = (request.form.get("description") or "").strip()
    price = request.form.get("unit_price", type=float)
    if desc:
        item.description = desc
    if price is not None:
        item.unit_price = price
    item.quantity = request.form.get("quantity", type=int) or 1
    item.discount_value = request.form.get("discount_value", type=float) or 0
    item.discount_is_percent = bool(request.form.get("discount_is_percent"))
    # Refresh the doctor-commission snapshot for the new net.
    if item.service is not None:
        item.commission_amount = item.service.doctor_share(item.net, invoice.doctor)
    invoice.recalc_status()
    db.session.commit()
    flash(t("invoices.item_updated"), "success")
    return redirect(url_for("finance.invoice_view", invoice_id=invoice.id))


@finance_bp.route("/invoices/<int:invoice_id>/edit", methods=["POST"])
@module_required(MODULE)
def invoice_edit(invoice_id):
    """Edit invoice header fields (patient, doctor, payer, date, notes)."""
    invoice = db.get_or_404(Invoice, invoice_id)
    patient = db.session.get(Patient, request.form.get("patient_id", type=int))
    if patient is not None:
        invoice.patient_id = patient.id
    invoice.doctor_id = request.form.get("doctor_id", type=int) or None
    invoice.payer_id = request.form.get("payer_id", type=int) or None
    invoice.notes = (request.form.get("notes") or "").strip() or None
    raw_date = (request.form.get("invoice_date") or "").strip()
    if raw_date:
        try:
            invoice.invoice_date = datetime.strptime(raw_date, "%Y-%m-%d").date()
        except ValueError:
            pass
    # Re-snapshot commissions against the (possibly new) doctor.
    for item in invoice.items:
        if item.service is not None:
            item.commission_amount = item.service.doctor_share(item.net, invoice.doctor)
    invoice.recalc_status()
    ActivityLog.record("invoice.edit", user_id=current_user.id, entity="invoice",
                       detail=invoice.invoice_number, ip_address=client_ip())
    db.session.commit()
    flash(t("invoices.updated"), "success")
    return redirect(url_for("finance.invoice_view", invoice_id=invoice.id))


@finance_bp.route("/invoices/<int:invoice_id>/delete", methods=["POST"])
@module_required(MODULE)
def invoice_delete(invoice_id):
    invoice = db.get_or_404(Invoice, invoice_id)
    db.session.delete(invoice)
    db.session.commit()
    flash(t("invoices.deleted"), "info")
    return redirect(url_for("finance.invoices"))


# =======================================================================
# Payer entities & discount claims
# =======================================================================
@finance_bp.route("/payers", methods=["GET", "POST"])
@module_required(MODULE)
def payers():
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        if not name:
            flash(t("common.required") + ": " + t("claims.entity_name"), "danger")
            return redirect(url_for("finance.payers"))
        etype = (request.form.get("entity_type") or "club").strip()
        db.session.add(PayerEntity(
            name=name,
            name_en=(request.form.get("name_en") or "").strip() or None,
            entity_type=etype if etype in PAYER_TYPES else "club",
            discount_percent=request.form.get("discount_percent", type=float) or 0,
            contact_person=(request.form.get("contact_person") or "").strip() or None,
            phone=(request.form.get("phone") or "").strip() or None,
            email=(request.form.get("email") or "").strip() or None,
            address=(request.form.get("address") or "").strip() or None,
        ))
        db.session.commit()
        flash(t("claims.entity_added"), "success")
        return redirect(url_for("finance.payers"))

    return render_template(
        "finance/payers.html",
        payers=PayerEntity.query.order_by(PayerEntity.name).all(),
        types=PAYER_TYPES, coverage_types=COVERAGE_TYPES,
        services=Service.query.filter_by(is_active=True).order_by(Service.name).all(),
    )


@finance_bp.route("/payers/<int:payer_id>/rates", methods=["POST"])
@module_required(MODULE)
def payer_rates(payer_id):
    """Set an entity's per-service coverage (benefits table)."""
    payer = db.get_or_404(PayerEntity, payer_id)
    existing = {r.service_id: r for r in payer.service_rates}
    for svc in Service.query.filter_by(is_active=True).all():
        ctype = (request.form.get(f"type_{svc.id}") or "none").strip()
        cval = request.form.get(f"value_{svc.id}", type=float) or 0
        rate = existing.get(svc.id)
        if ctype not in COVERAGE_TYPES or cval <= 0:
            if rate:  # clearing a rule means "not covered"
                db.session.delete(rate)
            continue
        if rate is None:
            rate = PayerServiceRate(payer_id=payer.id, service_id=svc.id)
            db.session.add(rate)
        rate.coverage_type, rate.coverage_value = ctype, cval
    db.session.commit()
    flash(t("coverage.rates_saved"), "success")
    return redirect(url_for("finance.payers"))


@finance_bp.route("/payers/<int:payer_id>/edit", methods=["POST"])
@module_required(MODULE)
def payer_edit(payer_id):
    p = db.get_or_404(PayerEntity, payer_id)
    p.name = (request.form.get("name") or p.name).strip()
    p.name_en = (request.form.get("name_en") or "").strip() or None
    etype = (request.form.get("entity_type") or p.entity_type).strip()
    p.entity_type = etype if etype in PAYER_TYPES else p.entity_type
    p.discount_percent = request.form.get("discount_percent", type=float) or 0
    p.contact_person = (request.form.get("contact_person") or "").strip() or None
    p.phone = (request.form.get("phone") or "").strip() or None
    p.is_active = bool(request.form.get("is_active"))
    db.session.commit()
    flash(t("claims.entity_updated"), "success")
    return redirect(url_for("finance.payers"))


@finance_bp.route("/payers/<int:payer_id>/delete", methods=["POST"])
@module_required(MODULE)
def payer_delete(payer_id):
    p = db.get_or_404(PayerEntity, payer_id)
    if p.invoices:
        p.is_active = False  # keep history
    else:
        db.session.delete(p)
    db.session.commit()
    flash(t("claims.entity_deleted"), "info")
    return redirect(url_for("finance.payers"))


@finance_bp.route("/invoices/<int:invoice_id>/payer", methods=["POST"])
@module_required(MODULE)
def invoice_set_payer(invoice_id):
    invoice = db.get_or_404(Invoice, invoice_id)
    invoice.payer_id = request.form.get("payer_id", type=int) or None
    db.session.commit()
    flash(t("claims.payer_set"), "success")
    return redirect(url_for("finance.invoice_view", invoice_id=invoice.id))


@finance_bp.route("/claims")
@module_required(MODULE)
def claims():
    today = datetime.utcnow().date()
    date_from = _parse_date_arg("date_from", today.replace(day=1))
    date_to = _parse_date_arg("date_to", today)

    rows = []
    for entity in PayerEntity.query.order_by(PayerEntity.name).all():
        q = Invoice.query.filter(Invoice.payer_id == entity.id)
        if date_from:
            q = q.filter(Invoice.invoice_date >= date_from)
        if date_to:
            q = q.filter(Invoice.invoice_date <= date_to)
        invs = q.all()
        claim = round(sum(i.discount_total for i in invs), 2)
        rows.append({"entity": entity, "count": len(invs), "claim": claim})
    return render_template("finance/claims.html", rows=rows,
                           date_from=date_from, date_to=date_to)


@finance_bp.route("/claims/<int:payer_id>")
@module_required(MODULE)
def claim_detail(payer_id):
    entity = db.get_or_404(PayerEntity, payer_id)
    today = datetime.utcnow().date()
    date_from = _parse_date_arg("date_from", today.replace(day=1))
    date_to = _parse_date_arg("date_to", today)

    q = Invoice.query.filter(Invoice.payer_id == entity.id)
    if date_from:
        q = q.filter(Invoice.invoice_date >= date_from)
    if date_to:
        q = q.filter(Invoice.invoice_date <= date_to)
    invoices = q.order_by(Invoice.invoice_date, Invoice.id).all()
    total_claim = round(sum(i.discount_total for i in invoices), 2)
    return render_template("finance/claim_detail.html", entity=entity,
                           invoices=invoices, total_claim=total_claim,
                           date_from=date_from, date_to=date_to)


# =======================================================================
# Doctor account statement
# =======================================================================
def _parse_date_arg(name, default=None):
    raw = (request.args.get(name) or "").strip()
    if not raw:
        return default
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        return default


@finance_bp.route("/statements")
@module_required(MODULE)
def statements():
    today = datetime.utcnow().date()
    date_from = _parse_date_arg("date_from", today.replace(day=1))
    date_to = _parse_date_arg("date_to", today)
    paid_only = request.args.get("paid_only") == "1"
    doctor_id = request.args.get("doctor_id", type=int)

    doctor = db.session.get(User, doctor_id) if doctor_id else None
    invoices, totals = [], None
    if doctor is not None:
        q = Invoice.query.filter(Invoice.doctor_id == doctor.id)
        if date_from:
            q = q.filter(Invoice.invoice_date >= date_from)
        if date_to:
            q = q.filter(Invoice.invoice_date <= date_to)
        if paid_only:
            q = q.filter(Invoice.status == "paid")
        invoices = q.order_by(Invoice.invoice_date, Invoice.id).all()
        totals = {
            "count": len(invoices),
            "billed": round(sum(i.total for i in invoices), 2),
            "collected": round(sum(i.paid for i in invoices), 2),
            "doctor_share": round(sum(i.doctor_share_total for i in invoices), 2),
            "clinic_share": round(sum(i.clinic_share_total for i in invoices), 2),
        }

    return render_template(
        "finance/statements.html", doctors=_doctors_active(), doctor=doctor,
        invoices=invoices, totals=totals, paid_only=paid_only,
        date_from=date_from, date_to=date_to,
    )
