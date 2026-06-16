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
from app.models import ActivityLog, Patient, PatientVaccine, Vaccine
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
    patients = Patient.query.filter_by(is_active=True).order_by(Patient.full_name).all()
    return render_template("vaccinations/index.html", patients=patients)


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

    db.session.add(PatientVaccine(
        patient_id=patient.id, vaccine_id=vaccine.id, brand_id=brand.id,
        dose_number=dose_number, given_date=given_date,
        lot_number=(request.form.get("lot_number") or "").strip() or None,
        notes=(request.form.get("notes") or "").strip() or None,
    ))
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


@vaccinations_bp.route("/<int:patient_id>/certificate")
@module_required(MODULE)
def certificate(patient_id):
    patient = db.get_or_404(Patient, patient_id)
    given = (
        PatientVaccine.query.filter_by(patient_id=patient.id)
        .order_by(PatientVaccine.given_date)
        .all()
    )
    return render_template("vaccinations/certificate.html", patient=patient, given=given)
