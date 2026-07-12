"""Finance module — Services & Commissions (foundation).

Manages the clinic's chargeable services: pricing, max discount, doctor
commission (default + per-doctor overrides) and service bundles. Later
phases build invoices, doctor statements and discount claims on top.
"""
import calendar
from datetime import date, datetime

from flask import flash, g, redirect, render_template, request, url_for
from flask_login import current_user

from app.blueprints.finance import finance_bp
from app.extensions import db
from app.i18n import t
from app.models import (
    APPOINTMENT_TYPES,
    CLIENT_CATEGORIES,
    COMMISSION_TYPES,
    COVERAGE_TYPES,
    DISCOUNT_TYPES,
    EXPENSE_CATEGORIES,
    NamedDiscount,
    PAYER_TYPES,
    PAYMENT_METHODS,
    SERVICE_CATEGORIES,
    ActivityLog,
    CashDrawerDay,
    CashierShift,
    DoctorServiceCommission,
    EInvoiceDocument,
    Expense,
    Invoice,
    InvoiceItem,
    Patient,
    PatientVaccine,
    PayerEntity,
    PayerServiceRate,
    Payment,
    Service,
    ServiceBundleItem,
    Setting,
    User,
    Visit,
)
from app.utils.decorators import client_ip, module_required
from app.utils.finance import generate_invoice_number
from app.utils.pricing import (
    save_visit_type_service_map,
    service_for_visit_type,
    visit_type_service_map,
)
from app.utils import einvoice as eta

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
    from app.models import ETA_ITEM_TYPES
    return render_template(
        "finance/services.html", services=services,
        categories=SERVICE_CATEGORIES, commission_types=COMMISSION_TYPES,
        item_types=ETA_ITEM_TYPES, doctors=_doctors(),
        appt_types=list(APPOINTMENT_TYPES), visit_type_map=visit_type_service_map(),
    )


@finance_bp.route("/services/visit-types", methods=["POST"])
@module_required(MODULE)
def visit_type_services():
    """Map each visit type (كشف / استشارة / …) to its base-charge service."""
    from app.utils.visit_types import active_types
    mapping = {}
    for vt in active_types():
        sid = request.form.get(f"vt_{vt.key}", type=int)
        if sid:
            mapping[vt.key] = sid
    save_visit_type_service_map(mapping)
    db.session.commit()
    flash(t("services.visit_types_saved"), "success")
    return redirect(url_for("finance.services"))


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
        eta_item_type=("GS1" if request.form.get("eta_item_type") == "GS1" else "EGS"),
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
    svc.eta_item_type = "GS1" if request.form.get("eta_item_type") == "GS1" else "EGS"
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
        # Blank price = no override (default); "0" = free for this doctor.
        raw_price = (request.form.get(f"price_{doc.id}") or "").strip()
        price = request.form.get(f"price_{doc.id}", type=float) if raw_price != "" else None

        oc = existing.get(doc.id)
        # A row is only worth keeping if it sets a commission or a price.
        if ctype == "none" and price is None:
            if oc:  # clearing both falls back to the service default
                db.session.delete(oc)
            continue
        if oc is None:
            oc = DoctorServiceCommission(doctor_id=doc.id, service_id=svc.id)
            db.session.add(oc)
        oc.commission_type, oc.commission_value = ctype, cval
        oc.price_override = price
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


def _cashier_date():
    raw = (request.values.get("date") or "").strip()
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date() if raw else date.today()
    except ValueError:
        return date.today()


def _current_shift_id():
    """The open shift this cashier's money should be booked into, if any."""
    shift = CashierShift.open_for(current_user.id) or CashierShift.any_open()
    return shift.id if shift else None


@finance_bp.route("/cashier")
@module_required(MODULE)
def cashier():
    """Reception's till for the day: opening float, money taken in (by method),
    expected cash to reconcile, and who still owes — with one-click collect."""
    from collections import Counter

    on_date = _cashier_date()
    start = datetime.combine(on_date, datetime.min.time())
    end = datetime.combine(on_date, datetime.max.time())

    # Drawer: money moved on this day — payments in, refunds out.
    pays = Payment.query.filter(Payment.paid_at >= start, Payment.paid_at <= end).all()
    by_method = Counter()
    refunds = 0.0
    cash_in = cash_out = 0.0
    for p in pays:
        amt = p.amount or 0
        if p.kind == "refund":
            refunds += amt
            if p.method == "cash":
                cash_out += amt
        else:
            by_method[p.method] += amt
            if p.method == "cash":
                cash_in += amt
    collected = round(sum(v for v in by_method.values()), 2)
    refunds = round(refunds, 2)
    cash_collected = round(cash_in - cash_out, 2)

    drawer = CashDrawerDay.query.filter_by(drawer_date=on_date).first()
    opening_float = drawer.opening_float if drawer else 0
    expected_cash = round(opening_float + cash_collected, 2)

    todays = Invoice.query.filter(Invoice.invoice_date == on_date).all()
    billed_today = round(sum(i.total for i in todays), 2)
    outstanding = (Invoice.query.filter(Invoice.status.in_(["unpaid", "partial"]))
                   .order_by(Invoice.id.desc()).limit(100).all())
    outstanding_total = round(sum(i.balance for i in outstanding), 2)

    open_shift = CashierShift.open_for(current_user.id) or CashierShift.any_open()
    recent_shifts = (CashierShift.query.order_by(CashierShift.opened_at.desc())
                     .limit(8).all())

    return render_template(
        "finance/cashier.html", on_date=on_date, drawer=drawer,
        opening_float=opening_float, by_method=dict(by_method),
        collected=collected, cash_collected=cash_collected, refunds=refunds,
        expected_cash=expected_cash, billed_today=billed_today,
        outstanding=outstanding, outstanding_total=outstanding_total,
        payment_methods=PAYMENT_METHODS,
        open_shift=open_shift, recent_shifts=recent_shifts,
    )


@finance_bp.route("/cashier/float", methods=["POST"])
@module_required(MODULE)
def cashier_float():
    """Set the opening change float reception is handed at the start of the day."""
    on_date = _cashier_date()
    amount = request.form.get("opening_float", type=float) or 0
    drawer = CashDrawerDay.query.filter_by(drawer_date=on_date).first()
    if drawer is None:
        drawer = CashDrawerDay(drawer_date=on_date, opened_by=current_user.id)
        db.session.add(drawer)
    drawer.opening_float = round(amount, 2)
    db.session.commit()
    flash(t("cashier.float_saved"), "success")
    return redirect(url_for("finance.cashier", date=on_date.isoformat()))


# ----------------------------------------------------- cashier shifts ------
@finance_bp.route("/shift/open", methods=["POST"])
@module_required(MODULE)
def shift_open():
    """Open a till session (وردية) with a change float. One open shift per
    cashier at a time — money collected from now on is booked into it."""
    if CashierShift.open_for(current_user.id):
        flash(t("shifts.already_open"), "warning")
        return redirect(url_for("finance.cashier"))
    shift = CashierShift(
        opening_float=round(request.form.get("opening_float", type=float) or 0, 2),
        label=(request.form.get("label") or "").strip() or None,
        opened_by=current_user.id,
    )
    db.session.add(shift)
    db.session.flush()
    ActivityLog.record("shift.open", user_id=current_user.id, entity="cashier_shift",
                       detail=str(shift.id), ip_address=client_ip())
    db.session.commit()
    flash(t("shifts.opened"), "success")
    return redirect(url_for("finance.cashier"))


@finance_bp.route("/shift/<int:shift_id>/close", methods=["POST"])
@module_required(MODULE)
def shift_close(shift_id):
    """Close a shift against the counted cash and record over/short."""
    shift = db.get_or_404(CashierShift, shift_id)
    if shift.status == "closed":
        flash(t("shifts.already_closed"), "warning")
        return redirect(url_for("finance.shift_report", shift_id=shift.id))
    shift.counted_cash = request.form.get("counted_cash", type=float)
    shift.notes = (request.form.get("notes") or "").strip() or None
    shift.status = "closed"
    shift.closed_by = current_user.id
    shift.closed_at = datetime.utcnow()
    ActivityLog.record("shift.close", user_id=current_user.id, entity="cashier_shift",
                       detail=f"{shift.id}:{shift.variance}", ip_address=client_ip())
    db.session.commit()
    flash(t("shifts.closed"), "success")
    return redirect(url_for("finance.shift_report", shift_id=shift.id))


@finance_bp.route("/shifts")
@module_required(MODULE)
def shifts():
    """History of till sessions (Z-reports)."""
    page = request.args.get("page", 1, type=int)
    pagination = (CashierShift.query.order_by(CashierShift.opened_at.desc())
                  .paginate(page=page, per_page=25, error_out=False))
    return render_template("finance/shifts.html", pagination=pagination,
                           shifts=pagination.items,
                           open_shift=CashierShift.open_for(current_user.id))


@finance_bp.route("/shift/<int:shift_id>")
@module_required(MODULE)
def shift_report(shift_id):
    """One shift's X/Z report: float, money by method, expected vs counted."""
    shift = db.get_or_404(CashierShift, shift_id)
    pays = sorted(shift.payments, key=lambda p: p.paid_at)
    return render_template("finance/shift_report.html", shift=shift, pays=pays,
                           payment_methods=PAYMENT_METHODS)


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

    # If the entity works by contracts, one must be in force on the invoice date.
    if payer.contracts and payer.active_contract(invoice.invoice_date) is None:
        flash(t("contracts.none_active_warn"), "warning")
        return

    for item in invoice.items:
        if not item.service_id or (item.discount_value or 0) > 0:
            continue  # keep manual discounts; skip free-text lines
        covered = payer.covers(item.service, item.gross, invoice.invoice_date)
        if covered > 0:
            item.discount_value = covered
            item.discount_is_percent = False
            if item.service is not None:
                item.commission_amount = item.service.doctor_share(item.net, invoice.doctor)


def _uncharged_vaccines(patient_id, days=2):
    """Recently-given, priced, not-yet-billed doses for a patient (charge on exit)."""
    from datetime import timedelta

    since = date.today() - timedelta(days=days)
    doses = (PatientVaccine.query.filter(
        PatientVaccine.patient_id == patient_id,
        PatientVaccine.event_type == "given",
        PatientVaccine.given_outside.is_(False),
        PatientVaccine.invoice_id.is_(None),
        PatientVaccine.given_date >= since).all())
    return [d for d in doses if d.brand and (d.brand.price or 0) > 0]


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

        # Apply a chosen named discount first (campaign/doctor/category/special),
        # then insurance coverage fills any remaining undiscounted lines.
        disc = db.session.get(NamedDiscount, request.form.get("discount_id", type=int)) \
            if request.form.get("discount_id", type=int) else None
        if disc and disc.is_active:
            _apply_named_discount(invoice, disc)
        _apply_coverage(invoice, patient)

        # Mark the patient's recently-given uncharged vaccines as billed here so
        # they aren't charged twice (they were pre-filled as lines above).
        for dose in _uncharged_vaccines(patient.id):
            dose.invoice_id = invoice.id

        invoice.recalc_status()
        ActivityLog.record("invoice.create", user_id=current_user.id, entity="invoice",
                           detail=invoice.invoice_number, ip_address=client_ip())
        db.session.commit()
        flash(t("invoices.created"), "success")
        return redirect(url_for("finance.invoice_view", invoice_id=invoice.id))

    pid = request.args.get("patient_id", type=int)
    patient = db.session.get(Patient, pid) if pid else None
    visit_id = request.args.get("visit_id", type=int)
    doctor_id = request.args.get("doctor_id", type=int)

    # Coming from a visit: default the patient + doctor and pre-fill the lines —
    # the base visit-type charge plus every procedure the doctor added — each at
    # this doctor's price. The cashier then just collects.
    prefill_lines = []
    lang = getattr(g, "lang", "ar")
    visit = db.session.get(Visit, visit_id) if visit_id else None
    if visit is not None:
        patient = patient or visit.patient
        if doctor_id is None:
            doctor_id = visit.doctor_id
        appt_type = visit.appointment.appt_type if visit.appointment else None
        base = service_for_visit_type(appt_type) if appt_type else None
        if base is not None:
            prefill_lines.append({
                "service_id": str(base.id),
                "description": base.display_name(lang),
                "unit_price": base.price_for(visit.doctor),
            })
        for vs in visit.services:
            prefill_lines.append({
                "service_id": str(vs.service_id) if vs.service_id else "",
                "description": vs.name,
                "unit_price": vs.service.price_for(visit.doctor) if vs.service else 0,
                "quantity": vs.quantity or 1,
            })

    # Any vaccines given to this patient that haven't been charged yet (so the
    # cashier collects them on exit).
    if patient is not None:
        for dose in _uncharged_vaccines(patient.id):
            b = dose.brand
            name = (b.vaccine.display_name(lang) if b.vaccine else
                    dose.vaccine.display_name(lang))
            prefill_lines.append({
                "service_id": "",
                "description": name + " — " + b.display_name(lang),
                "unit_price": b.price or 0,
            })

    return render_template(
        "finance/invoice_form.html", patient=patient,
        doctors=_doctors_active(),
        services=Service.query.filter_by(is_active=True).order_by(Service.name).all(),
        patients=Patient.query.filter_by(is_active=True).order_by(Patient.full_name).limit(500).all(),
        payers=PayerEntity.query.filter_by(is_active=True).order_by(PayerEntity.name).all(),
        discounts=NamedDiscount.query.filter_by(is_active=True).order_by(NamedDiscount.name).all(),
        visit_id=visit_id, doctor_id=doctor_id, prefill_lines=prefill_lines or None,
    )


@finance_bp.route("/collect/appointment/<int:appt_id>", methods=["POST"])
@module_required(MODULE)
def collect_appointment(appt_id):
    """One-click reception collect: build this appointment's invoice (base
    visit-type charge at the doctor's price + any uncharged vaccines already
    given to the patient), take the full payment, and jump to the printable
    receipt — so booking and collecting happen from the same screen instead of
    a separate cashier trip.
    """
    from app.models import Appointment

    appt = db.get_or_404(Appointment, appt_id)
    patient = appt.patient
    lang = getattr(g, "lang", "ar")

    invoice = Invoice(
        invoice_number=generate_invoice_number(),
        patient_id=patient.id, doctor_id=appt.doctor_id,
        created_by=current_user.id,
    )
    db.session.add(invoice)
    db.session.flush()

    base = service_for_visit_type(appt.appt_type)
    if base is not None:
        price = base.price_for(appt.doctor) if appt.doctor else base.price
        if price is not None:
            item = InvoiceItem(service_id=base.id, description=base.display_name(lang),
                               unit_price=price, quantity=1)
            item.commission_amount = base.doctor_share(item.net, invoice.doctor)
            invoice.items.append(item)

    # Vaccines given but not yet billed — collect them here (never twice).
    for dose in _uncharged_vaccines(patient.id):
        b = dose.brand
        if b and b.price:
            name = (b.vaccine.display_name(lang) if b.vaccine else
                    dose.vaccine.display_name(lang))
            invoice.items.append(InvoiceItem(
                description=name + " — " + b.display_name(lang),
                unit_price=b.price, quantity=1))
        dose.invoice_id = invoice.id

    if not invoice.items:
        db.session.rollback()
        flash(t("cashier.nothing_to_collect"), "warning")
        return redirect(url_for("appointments.index", date=appt.appt_date.isoformat()))

    _apply_coverage(invoice, patient)
    invoice.recalc_status()

    # Reception collected the balance now (default cash).
    method = (request.form.get("method") or "cash").strip()
    if invoice.balance > 0:
        invoice.payments.append(Payment(
            amount=invoice.balance,
            method=method if method in PAYMENT_METHODS else "cash",
            received_by=current_user.id, shift_id=_current_shift_id(),
        ))
        invoice.recalc_status()

    ActivityLog.record("invoice.collect_appt", user_id=current_user.id, entity="invoice",
                       detail=invoice.invoice_number, ip_address=client_ip())
    db.session.commit()
    flash(t("invoices.created"), "success")
    return redirect(url_for("finance.invoice_receipt", invoice_id=invoice.id))


def _apply_named_discount(invoice, disc):
    """Apply a named discount to lines that have no manual discount yet."""
    invoice.discount_id = disc.id
    invoice.discount_name = disc.display_name()
    for item in invoice.items:
        if (item.discount_value or 0) > 0:
            continue  # keep manual discounts
        amount = disc.amount_for(item.gross)
        # Respect a service's max discount cap (percentage of gross).
        if item.service and item.service.max_discount:
            cap = round(item.gross * item.service.max_discount / 100.0, 2)
            amount = min(amount, cap)
        if amount > 0:
            item.discount_value = amount
            item.discount_is_percent = False
            if item.service is not None:
                item.commission_amount = item.service.doctor_share(item.net, invoice.doctor)


# ------------------------------------------------------ named discounts ----
@finance_bp.route("/discounts", methods=["GET", "POST"])
@module_required(MODULE)
def discounts():
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        if not name:
            flash(t("common.required") + ": " + t("discounts.name"), "danger")
            return redirect(url_for("finance.discounts"))
        dtype = (request.form.get("dtype") or "special").strip()
        db.session.add(NamedDiscount(
            name=name,
            name_en=(request.form.get("name_en") or "").strip() or None,
            dtype=dtype if dtype in DISCOUNT_TYPES else "special",
            value=request.form.get("value", type=float) or 0,
            is_percent=(request.form.get("unit") or "percent") == "percent",
            doctor_id=request.form.get("doctor_id", type=int) or None,
            client_category=(request.form.get("client_category") or "").strip() or None,
            start_date=_parse_date_arg("start_date"),
            end_date=_parse_date_arg("end_date"),
        ))
        db.session.commit()
        flash(t("discounts.added"), "success")
        return redirect(url_for("finance.discounts"))

    return render_template(
        "finance/discounts.html",
        discounts=NamedDiscount.query.order_by(NamedDiscount.is_active.desc(),
                                               NamedDiscount.name).all(),
        types=DISCOUNT_TYPES, categories=CLIENT_CATEGORIES, doctors=_doctors_active())


@finance_bp.route("/discounts/<int:discount_id>/toggle", methods=["POST"])
@module_required(MODULE)
def discount_toggle(discount_id):
    d = db.get_or_404(NamedDiscount, discount_id)
    d.is_active = not d.is_active
    db.session.commit()
    return redirect(url_for("finance.discounts"))


@finance_bp.route("/discounts/<int:discount_id>/delete", methods=["POST"])
@module_required(MODULE)
def discount_delete(discount_id):
    d = db.get_or_404(NamedDiscount, discount_id)
    db.session.delete(d)
    db.session.commit()
    flash(t("discounts.deleted"), "info")
    return redirect(url_for("finance.discounts"))


def _parse_date_arg(name):
    raw = (request.form.get(name) or "").strip()
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        return None


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


@finance_bp.route("/invoices/<int:invoice_id>/receipt")
@module_required(MODULE)
def invoice_receipt(invoice_id):
    """Compact 80mm thermal receipt — clinic logo on top, PediaPro mark below,
    plus an admin-configurable footer line."""
    from app.models import Setting

    invoice = db.get_or_404(Invoice, invoice_id)
    return render_template(
        "finance/receipt_thermal.html", invoice=invoice,
        thermal_footer=(Setting.get("thermal_footer_text") or "").strip(),
    )


@finance_bp.route("/invoices/<int:invoice_id>/payment", methods=["POST"])
@module_required(MODULE)
def invoice_payment(invoice_id):
    invoice = db.get_or_404(Invoice, invoice_id)
    # One invoice can be settled with several methods at once (e.g. 500 cash +
    # 1000 card + 500 instapay). The form submits parallel amount[]/method[]
    # lists; a single quick-pay is just a one-element list.
    amounts = request.form.getlist("amount")
    methods = request.form.getlist("method")
    notes = (request.form.get("notes") or "").strip() or None
    added = 0.0
    shift_id = _current_shift_id()
    for amt_raw, m in zip(amounts, methods):
        try:
            amt = float(amt_raw)
        except (TypeError, ValueError):
            continue
        if amt <= 0:
            continue
        invoice.payments.append(Payment(
            amount=round(amt, 2),
            method=m if m in PAYMENT_METHODS else "cash",
            received_by=current_user.id, notes=notes, shift_id=shift_id,
        ))
        added += amt
    if added <= 0:
        flash(t("invoices.bad_amount"), "danger")
        return redirect(url_for("finance.invoice_view", invoice_id=invoice.id))
    invoice.recalc_status()
    ActivityLog.record("invoice.payment", user_id=current_user.id, entity="invoice",
                       detail=f"{invoice.invoice_number}:{round(added, 2)}",
                       ip_address=client_ip())
    db.session.commit()
    flash(t("invoices.payment_added"), "success")
    if (request.form.get("next") or "") == "cashier":
        return redirect(url_for("finance.cashier"))
    return redirect(url_for("finance.invoice_view", invoice_id=invoice.id))


@finance_bp.route("/invoices/<int:invoice_id>/refund", methods=["POST"])
@module_required(MODULE)
def invoice_refund(invoice_id):
    """Return money to the patient (e.g. an exam re-billed as a consultation)
    and reconcile the cashier drawer."""
    invoice = db.get_or_404(Invoice, invoice_id)
    amount = request.form.get("amount", type=float)
    if not amount or amount <= 0:
        flash(t("invoices.bad_amount"), "danger")
        return redirect(url_for("finance.invoice_view", invoice_id=invoice.id))
    if amount > invoice.paid:  # can't refund more than was actually collected
        amount = invoice.paid
    method = (request.form.get("method") or "cash").strip()
    invoice.payments.append(Payment(
        amount=round(amount, 2), kind="refund",
        method=method if method in PAYMENT_METHODS else "cash",
        received_by=current_user.id, shift_id=_current_shift_id(),
        notes=(request.form.get("notes") or "").strip() or None,
    ))
    invoice.recalc_status()
    ActivityLog.record("invoice.refund", user_id=current_user.id, entity="invoice",
                       detail=f"{invoice.invoice_number}:-{amount}", ip_address=client_ip())
    db.session.commit()
    flash(t("invoices.refund_added"), "success")
    if (request.form.get("next") or "") == "cashier":
        return redirect(url_for("finance.cashier"))
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


# Invoices are never deleted (financial integrity + audit trail). A billing
# mistake is corrected with a refund, not a deletion.


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


@finance_bp.route("/payers/<int:payer_id>/contract/new", methods=["POST"])
@module_required(MODULE)
def contract_new(payer_id):
    from app.models import PayerContract

    payer = db.get_or_404(PayerEntity, payer_id)
    db.session.add(PayerContract(
        payer_id=payer.id,
        number=(request.form.get("number") or "").strip() or None,
        start_date=_parse_date_arg2(request.form.get("start_date")),
        end_date=_parse_date_arg2(request.form.get("end_date")),
        is_active=True,
    ))
    db.session.commit()
    flash(t("contracts.added"), "success")
    return redirect(url_for("finance.payers"))


@finance_bp.route("/contract/<int:contract_id>/edit", methods=["POST"])
@module_required(MODULE)
def contract_edit(contract_id):
    from app.models import PayerContract

    c = db.get_or_404(PayerContract, contract_id)
    c.number = (request.form.get("number") or "").strip() or None
    c.start_date = _parse_date_arg2(request.form.get("start_date"))
    c.end_date = _parse_date_arg2(request.form.get("end_date"))
    c.is_active = bool(request.form.get("is_active"))
    db.session.commit()
    flash(t("contracts.updated"), "success")
    return redirect(url_for("finance.payers"))


@finance_bp.route("/contract/<int:contract_id>/delete", methods=["POST"])
@module_required(MODULE)
def contract_delete(contract_id):
    from app.models import PayerContract

    c = db.get_or_404(PayerContract, contract_id)
    db.session.delete(c)
    db.session.commit()
    flash(t("contracts.deleted"), "info")
    return redirect(url_for("finance.payers"))


def _parse_date_arg2(raw):
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        return None


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


# =======================================================================
# ETA e-invoicing
# =======================================================================
import time as _time


@finance_bp.route("/einvoice")
@module_required(MODULE)
def einvoice():
    status = (request.args.get("status") or "").strip()
    q = EInvoiceDocument.query
    if status in ("queued", "submitted", "valid", "rejected", "cancelled"):
        q = q.filter_by(status=status)
    docs = q.order_by(EInvoiceDocument.id.desc()).limit(300).all()
    counts = {s: EInvoiceDocument.query.filter_by(status=s).count()
              for s in ("queued", "valid", "rejected")}
    return render_template("finance/einvoice.html", docs=docs, status=status,
                           cfg=eta.get_config(), counts=counts)


@finance_bp.route("/invoices/<int:invoice_id>/tax", methods=["POST"])
@module_required(MODULE)
def invoice_mark_tax(invoice_id):
    """Flag an invoice as a tax invoice and queue it for ETA submission."""
    invoice = db.get_or_404(Invoice, invoice_id)
    if request.form.get("unmark"):
        invoice.is_tax = False
        doc = EInvoiceDocument.query.filter_by(invoice_id=invoice.id).first()
        if doc and doc.status in ("queued", "rejected"):
            db.session.delete(doc)
        db.session.commit()
        flash(t("einvoice.unmarked"), "info")
        return redirect(url_for("finance.invoice_view", invoice_id=invoice.id))

    eta.queue_for_invoice(invoice, user_id=current_user.id)
    ActivityLog.record("einvoice.queue", user_id=current_user.id, entity="invoice",
                       detail=invoice.invoice_number, ip_address=client_ip())
    db.session.commit()
    flash(t("einvoice.queued"), "success")
    return redirect(url_for("finance.invoice_view", invoice_id=invoice.id))


@finance_bp.route("/einvoice/send", methods=["POST"])
@module_required(MODULE)
def einvoice_send():
    """Send queued documents in a batch, with a configurable time gap."""
    ids = request.form.getlist("doc_id", type=int)
    if ids:
        docs = EInvoiceDocument.query.filter(EInvoiceDocument.id.in_(ids)).all()
    else:
        docs = EInvoiceDocument.query.filter_by(status="queued").all()

    cfg = eta.get_config()
    try:
        gap = float(Setting.get("eta_send_gap", "0") or 0)
    except ValueError:
        gap = 0
    gap = max(0, min(gap, 5))  # keep request responsive

    sent = 0
    for i, doc in enumerate(docs):
        if doc.status not in ("queued", "rejected"):
            continue
        eta.submit(doc, user_id=current_user.id, cfg=cfg)
        sent += 1
        if gap and i < len(docs) - 1:
            _time.sleep(gap)
    db.session.commit()
    flash(t("einvoice.sent_n").replace("{n}", str(sent)), "success")
    return redirect(url_for("finance.einvoice"))


@finance_bp.route("/einvoice/<int:doc_id>")
@module_required(MODULE)
def einvoice_doc(doc_id):
    doc = db.get_or_404(EInvoiceDocument, doc_id)
    return render_template("finance/einvoice_doc.html", doc=doc)


# ============================================================ expenses =====
def _month_bounds(year, month):
    """First and last date of a given month."""
    last = calendar.monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last)


def _parse_month(arg):
    """Parse a 'YYYY-MM' arg, defaulting to the current month."""
    today = datetime.utcnow().date()
    raw = (arg or "").strip()
    try:
        y, m = raw.split("-")
        return int(y), int(m)
    except (ValueError, AttributeError):
        return today.year, today.month


@finance_bp.route("/expenses")
@module_required(MODULE)
def expenses():
    year, month = _parse_month(request.args.get("month"))
    start, end = _month_bounds(year, month)

    one_off = (Expense.query
               .filter(Expense.is_recurring.is_(False))
               .filter(Expense.expense_date >= start, Expense.expense_date <= end)
               .order_by(Expense.expense_date.desc()).all())
    recurring = (Expense.query.filter(Expense.is_recurring.is_(True))
                 .order_by(Expense.category).all())
    month_total = round(sum(e.amount for e in one_off)
                        + sum(e.amount for e in recurring), 2)
    return render_template(
        "finance/expenses.html", one_off=one_off, recurring=recurring,
        categories=EXPENSE_CATEGORIES, methods=PAYMENT_METHODS,
        month=f"{year:04d}-{month:02d}", month_total=month_total,
    )


def _read_expense(form):
    cat = (form.get("category") or "other").strip()
    return {
        "category": cat if cat in EXPENSE_CATEGORIES else "other",
        "description": (form.get("description") or "").strip() or None,
        "amount": form.get("amount", type=float) or 0,
        "is_recurring": bool(form.get("is_recurring")),
        "vendor": (form.get("vendor") or "").strip() or None,
        "payment_method": (form.get("payment_method") or "").strip() or None,
        "notes": (form.get("notes") or "").strip() or None,
    }


@finance_bp.route("/expenses/new", methods=["POST"])
@module_required(MODULE)
def expense_new():
    data = _read_expense(request.form)
    if data["amount"] <= 0:
        flash(t("expenses.need_amount"), "danger")
        return redirect(url_for("finance.expenses", month=request.form.get("month")))
    exp = Expense(created_by=current_user.id, **data)
    exp.expense_date = parse_date_or_today(request.form.get("expense_date"))
    db.session.add(exp)
    ActivityLog.record("expense.create", user_id=current_user.id, entity="expense",
                       detail=data["category"], ip_address=client_ip())
    db.session.commit()
    flash(t("expenses.added"), "success")
    return redirect(url_for("finance.expenses", month=request.form.get("month")))


@finance_bp.route("/expenses/<int:expense_id>/edit", methods=["POST"])
@module_required(MODULE)
def expense_edit(expense_id):
    exp = db.get_or_404(Expense, expense_id)
    for k, v in _read_expense(request.form).items():
        setattr(exp, k, v)
    exp.expense_date = parse_date_or_today(request.form.get("expense_date"), exp.expense_date)
    db.session.commit()
    flash(t("expenses.updated"), "success")
    return redirect(url_for("finance.expenses", month=request.form.get("month")))


@finance_bp.route("/expenses/<int:expense_id>/delete", methods=["POST"])
@module_required(MODULE)
def expense_delete(expense_id):
    exp = db.get_or_404(Expense, expense_id)
    db.session.delete(exp)
    db.session.commit()
    flash(t("expenses.deleted"), "info")
    return redirect(url_for("finance.expenses", month=request.form.get("month")))


def parse_date_or_today(raw, default=None):
    try:
        return datetime.strptime((raw or "").strip(), "%Y-%m-%d").date()
    except ValueError:
        return default or datetime.utcnow().date()


# ================================================================= P&L =====
@finance_bp.route("/pnl")
@module_required(MODULE)
def pnl():
    year, month = _parse_month(request.args.get("month"))
    start, end = _month_bounds(year, month)
    start_dt = datetime(year, month, 1)
    end_dt = datetime(end.year, end.month, end.day, 23, 59, 59)

    # Revenue = cash collected in the month (payments). Invoiced shown too.
    payments = (Payment.query
                .filter(Payment.paid_at >= start_dt, Payment.paid_at <= end_dt).all())
    collected = round(sum(p.amount or 0 for p in payments), 2)
    month_invoices = (Invoice.query
                      .filter(Invoice.invoice_date >= start, Invoice.invoice_date <= end).all())
    invoiced = round(sum(i.total for i in month_invoices), 2)

    # Expenses = one-off this month + fixed recurring; grouped by category.
    one_off = (Expense.query.filter(Expense.is_recurring.is_(False))
               .filter(Expense.expense_date >= start, Expense.expense_date <= end).all())
    recurring = Expense.query.filter(Expense.is_recurring.is_(True)).all()
    by_category = {c: 0.0 for c in EXPENSE_CATEGORIES}
    for e in one_off + recurring:
        by_category[e.category] = round(by_category.get(e.category, 0) + e.amount, 2)
    expenses_total = round(sum(by_category.values()), 2)

    net = round(collected - expenses_total, 2)
    margin = round((net / collected * 100), 1) if collected > 0 else 0
    cats = [(c, by_category[c]) for c in EXPENSE_CATEGORIES if by_category[c]]

    return render_template(
        "finance/pnl.html", month=f"{year:04d}-{month:02d}",
        collected=collected, invoiced=invoiced, expenses_total=expenses_total,
        net=net, margin=margin, cats=cats,
    )
