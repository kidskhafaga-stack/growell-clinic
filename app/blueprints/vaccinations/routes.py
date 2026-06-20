"""Vaccinations module — Phase 6, Part 1.

Per-patient vaccination plan with brand selection (no mixing brands), the
Egyptian schedule, visual due/done/upcoming states, next-due suggestion, dose
recording (with lot number), and a printable vaccination certificate.
"""
from datetime import datetime

from flask import (
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user

from app.blueprints.vaccinations import vaccinations_bp
from app.extensions import db
from app.i18n import t
from app.models import (
    ActivityLog,
    Patient,
    PatientVaccine,
    Vaccine,
    VaccineBrand,
    VaccineBrandDose,
)
from app.utils.decorators import client_ip, module_required
from app.utils.vaccines import (
    chosen_brand,
    next_due_dose,
    next_undone_dose_number,
    patient_plan,
    plan_summary,
)

MODULE = "vaccinations"


@vaccinations_bp.route("/")
@module_required(MODULE)
def index():
    pagination = (
        Patient.query.filter_by(is_active=True).order_by(Patient.full_name)
        .paginate(page=request.args.get("page", 1, type=int), per_page=25, error_out=False)
    )
    return render_template(
        "vaccinations/index.html", patients=pagination.items, pagination=pagination
    )


@vaccinations_bp.route("/<int:patient_id>")
@module_required(MODULE)
def view(patient_id):
    patient = db.get_or_404(Patient, patient_id)
    lang = request.cookies.get("lang", "ar")
    plan = patient_plan(patient, lang)
    summary = plan_summary(plan)
    nxt = next_due_dose(plan)
    return render_template(
        "vaccinations/view.html",
        patient=patient, plan=plan, summary=summary, next_due=nxt,
        today=datetime.utcnow().date().isoformat(),
    )


@vaccinations_bp.route("/<int:patient_id>/record", methods=["POST"])
@module_required(MODULE)
def record(patient_id):
    patient = db.get_or_404(Patient, patient_id)
    vaccine = db.get_or_404(Vaccine, request.form.get("vaccine_id", type=int))

    # Resolve the brand: locked brand if any dose given, else the posted choice.
    locked_brand, is_locked = chosen_brand(patient.id, vaccine)
    if is_locked:
        brand = locked_brand
    else:
        brand_id = request.form.get("brand_id", type=int)
        brand = next((b for b in vaccine.brands if b.id == brand_id), vaccine.default_brand)

    if brand is None:
        flash(t("vaccinations.no_brand"), "danger")
        return redirect(url_for("vaccinations.view", patient_id=patient.id))

    dose_number = request.form.get("dose_number", type=int) or \
        next_undone_dose_number(patient.id, vaccine, brand)
    if dose_number is None:
        flash(t("vaccinations.all_done"), "info")
        return redirect(url_for("vaccinations.view", patient_id=patient.id))

    # Guard against double-recording the same dose.
    existing = PatientVaccine.query.filter_by(
        patient_id=patient.id, vaccine_id=vaccine.id, dose_number=dose_number
    ).first()
    if existing:
        flash(t("vaccinations.dose_exists"), "warning")
        return redirect(url_for("vaccinations.view", patient_id=patient.id))

    raw_date = (request.form.get("given_date") or "").strip()
    try:
        given_date = datetime.strptime(raw_date, "%Y-%m-%d").date() if raw_date \
            else datetime.utcnow().date()
    except ValueError:
        given_date = datetime.utcnow().date()

    lot_number = (request.form.get("lot_number") or "").strip() or None
    pv = PatientVaccine(
        patient_id=patient.id, vaccine_id=vaccine.id, brand_id=brand.id,
        dose_number=dose_number, given_date=given_date,
        lot_number=lot_number,
        notes=(request.form.get("notes") or "").strip() or None,
    )
    db.session.add(pv)

    # Deduct from inventory for clinic-provided (optional) vaccines using
    # first-expiry-first-out; record the batch and its lot number.
    if not vaccine.is_mandatory:
        batches = brand.available_batches
        if batches:
            batch = batches[0]
            batch.qty_used = (batch.qty_used or 0) + 1
            pv.inventory_id = batch.id
            if not pv.lot_number:
                pv.lot_number = batch.lot_number

    ActivityLog.record(
        "vaccine.record", user_id=current_user.id, entity="patient",
        entity_id=patient.id, detail=f"{vaccine.code}#{dose_number}",
        ip_address=client_ip(),
    )
    db.session.commit()
    flash(t("vaccinations.recorded"), "success")
    return redirect(url_for("vaccinations.view", patient_id=patient.id))


@vaccinations_bp.route("/dose/<int:pv_id>/delete", methods=["POST"])
@module_required(MODULE)
def delete_dose(pv_id):
    pv = db.get_or_404(PatientVaccine, pv_id)
    patient_id = pv.patient_id
    db.session.delete(pv)
    db.session.commit()
    flash(t("vaccinations.dose_removed"), "info")
    return redirect(url_for("vaccinations.view", patient_id=patient_id))


# =================================================================
#  Vaccine catalogue management (add/edit vaccines, brands, schedules)
# =================================================================
def _parse_ages(raw):
    """Parse a comma/Arabic-comma separated list of month ages into ints."""
    ages = []
    for part in (raw or "").replace("،", ",").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            ages.append(int(float(part)))
        except ValueError:
            continue
    return sorted(set(ages))


def _set_brand_doses(brand, ages):
    VaccineBrandDose.query.filter_by(brand_id=brand.id).delete()
    for i, age in enumerate(ages, start=1):
        db.session.add(VaccineBrandDose(brand_id=brand.id, dose_number=i, age_months=age))


@vaccinations_bp.route("/manage")
@module_required(MODULE)
def manage():
    vaccines = Vaccine.query.order_by(Vaccine.is_mandatory.desc(), Vaccine.sort_order).all()
    return render_template("vaccinations/manage.html", vaccines=vaccines)


@vaccinations_bp.route("/manage/vaccine/new", methods=["POST"])
@module_required(MODULE)
def vaccine_new():
    code = (request.form.get("code") or "").strip().upper()
    name_ar = (request.form.get("name_ar") or "").strip()
    if not code or not name_ar:
        flash(t("common.required") + ": " + t("vaccinations.vaccine_name_ar"), "danger")
        return redirect(url_for("vaccinations.manage"))
    if Vaccine.query.filter_by(code=code).first():
        flash(t("vaccinations.code_taken"), "warning")
        return redirect(url_for("vaccinations.manage"))

    is_mandatory = (request.form.get("category") or "mandatory") == "mandatory"
    vaccine = Vaccine(
        code=code, name_ar=name_ar,
        name_en=(request.form.get("name_en") or "").strip() or None,
        is_mandatory=is_mandatory,
        sort_order=request.form.get("sort_order", type=int) or 100,
    )
    db.session.add(vaccine)
    db.session.flush()

    # Create the first brand (government for mandatory) + its dose schedule.
    brand = VaccineBrand(
        vaccine_id=vaccine.id,
        name=(request.form.get("brand_name") or ("حكومي" if is_mandatory else name_ar)).strip(),
        manufacturer=(request.form.get("manufacturer") or "").strip() or None,
        price=request.form.get("price", type=float),
        purchase_price=request.form.get("purchase_price", type=float),
        max_discount=request.form.get("max_discount", type=float),
        is_default=True,
    )
    db.session.add(brand)
    db.session.flush()
    _set_brand_doses(brand, _parse_ages(request.form.get("dose_ages")))

    ActivityLog.record("vaccine.create", user_id=current_user.id, entity="vaccine",
                       entity_id=vaccine.id, detail=code, ip_address=client_ip())
    db.session.commit()
    flash(t("vaccinations.vaccine_added"), "success")
    return redirect(url_for("vaccinations.manage"))


@vaccinations_bp.route("/manage/vaccine/<int:vaccine_id>/edit", methods=["POST"])
@module_required(MODULE)
def vaccine_edit(vaccine_id):
    vaccine = db.get_or_404(Vaccine, vaccine_id)
    vaccine.name_ar = (request.form.get("name_ar") or vaccine.name_ar).strip()
    vaccine.name_en = (request.form.get("name_en") or "").strip() or None
    vaccine.is_mandatory = (request.form.get("category") or "mandatory") == "mandatory"
    if request.form.get("sort_order", type=int) is not None:
        vaccine.sort_order = request.form.get("sort_order", type=int)
    db.session.commit()
    flash(t("vaccinations.vaccine_updated"), "success")
    return redirect(url_for("vaccinations.manage"))


@vaccinations_bp.route("/manage/vaccine/<int:vaccine_id>/delete", methods=["POST"])
@module_required(MODULE)
def vaccine_delete(vaccine_id):
    vaccine = db.get_or_404(Vaccine, vaccine_id)
    if PatientVaccine.query.filter_by(vaccine_id=vaccine.id).first():
        flash(t("vaccinations.cannot_delete_used"), "warning")
        return redirect(url_for("vaccinations.manage"))
    db.session.delete(vaccine)
    db.session.commit()
    flash(t("vaccinations.vaccine_deleted"), "info")
    return redirect(url_for("vaccinations.manage"))


@vaccinations_bp.route("/manage/vaccine/<int:vaccine_id>/brand/new", methods=["POST"])
@module_required(MODULE)
def brand_new(vaccine_id):
    vaccine = db.get_or_404(Vaccine, vaccine_id)
    name = (request.form.get("name") or "").strip()
    if not name:
        flash(t("common.required") + ": " + t("vaccinations.brand_name"), "danger")
        return redirect(url_for("vaccinations.manage"))
    brand = VaccineBrand(
        vaccine_id=vaccine.id, name=name,
        name_en=(request.form.get("name_en") or "").strip() or None,
        manufacturer=(request.form.get("manufacturer") or "").strip() or None,
        price=request.form.get("price", type=float),
        purchase_price=request.form.get("purchase_price", type=float),
        max_discount=request.form.get("max_discount", type=float),
        is_default=not vaccine.brands,
    )
    db.session.add(brand)
    db.session.flush()
    _set_brand_doses(brand, _parse_ages(request.form.get("dose_ages")))
    db.session.commit()
    flash(t("vaccinations.brand_added"), "success")
    return redirect(url_for("vaccinations.manage"))


@vaccinations_bp.route("/manage/brand/<int:brand_id>/edit", methods=["POST"])
@module_required(MODULE)
def brand_edit(brand_id):
    brand = db.get_or_404(VaccineBrand, brand_id)
    brand.name = (request.form.get("name") or brand.name).strip()
    brand.name_en = (request.form.get("name_en") or "").strip() or None
    brand.manufacturer = (request.form.get("manufacturer") or "").strip() or None
    brand.price = request.form.get("price", type=float)
    brand.purchase_price = request.form.get("purchase_price", type=float)
    brand.max_discount = request.form.get("max_discount", type=float)
    ages = _parse_ages(request.form.get("dose_ages"))
    if ages:
        _set_brand_doses(brand, ages)
    db.session.commit()
    flash(t("vaccinations.brand_updated"), "success")
    return redirect(url_for("vaccinations.manage"))


@vaccinations_bp.route("/manage/brand/<int:brand_id>/delete", methods=["POST"])
@module_required(MODULE)
def brand_delete(brand_id):
    brand = db.get_or_404(VaccineBrand, brand_id)
    if PatientVaccine.query.filter_by(brand_id=brand.id).first():
        flash(t("vaccinations.cannot_delete_used"), "warning")
        return redirect(url_for("vaccinations.manage"))
    vid = brand.vaccine_id
    db.session.delete(brand)
    db.session.commit()
    flash(t("vaccinations.brand_deleted"), "info")
    return redirect(url_for("vaccinations.manage"))


@vaccinations_bp.route("/<int:patient_id>/certificate")
@module_required(MODULE)
def certificate(patient_id):
    patient = db.get_or_404(Patient, patient_id)
    given = (
        PatientVaccine.query.filter_by(patient_id=patient.id)
        .order_by(PatientVaccine.given_date)
        .all()
    )
    return render_template(
        "vaccinations/certificate.html", patient=patient, given=given,
        now_date=datetime.utcnow().date().isoformat(),
    )
