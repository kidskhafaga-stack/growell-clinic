"""Visit / examination module (Phase 4).

Vital signs, chief complaint, clinical exam, ICD-10/11 diagnoses (working /
secondary / final), and visit completion — which also closes a linked
appointment and mirrors growth measurements into growth_records.
"""
from datetime import datetime

from flask import (
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user

from app.blueprints.visits import visits_bp
from app.extensions import db
from app.i18n import t
from app.models import (
    ActivityLog,
    Appointment,
    Diagnosis,
    GrowthRecord,
    Patient,
    Visit,
    VitalSigns,
)
from app.utils.decorators import client_ip, module_required
from app.utils.icd import search_icd

MODULE = "visits"


def _float(name):
    raw = (request.form.get(name) or "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _int(name):
    raw = (request.form.get(name) or "").strip()
    if not raw:
        return None
    try:
        return int(float(raw))
    except ValueError:
        return None


# --------------------------------------------------------------- index -----
@visits_bp.route("/")
@module_required(MODULE)
def index():
    visits = Visit.query.order_by(Visit.created_at.desc()).limit(50).all()
    return render_template("visits/list.html", visits=visits)


# --------------------------------------------------------------- start -----
@visits_bp.route("/start/<int:patient_id>")
@module_required(MODULE)
def start(patient_id):
    """Create (or reopen) an open visit for a patient and go to the record."""
    patient = db.get_or_404(Patient, patient_id)
    appointment_id = request.args.get("appointment_id", type=int)

    visit = (
        Visit.query.filter_by(patient_id=patient.id, status="open")
        .order_by(Visit.created_at.desc())
        .first()
    )
    if visit is None:
        doctor_id = current_user.id
        if appointment_id:
            appt = db.session.get(Appointment, appointment_id)
            if appt:
                doctor_id = appt.doctor_id
        visit = Visit(
            patient_id=patient.id,
            doctor_id=doctor_id,
            appointment_id=appointment_id,
        )
        db.session.add(visit)
        ActivityLog.record(
            "visit.start", user_id=current_user.id, entity="visit",
            entity_id=None, detail=patient.patient_number, ip_address=client_ip(),
        )
        db.session.commit()
    return redirect(url_for("visits.record", visit_id=visit.id))


# -------------------------------------------------------------- record -----
@visits_bp.route("/<int:visit_id>/record", methods=["GET", "POST"])
@module_required(MODULE)
def record(visit_id):
    visit = db.get_or_404(Visit, visit_id)

    if request.method == "POST":
        visit.chief_complaint = (request.form.get("chief_complaint") or "").strip()
        visit.clinical_exam = (request.form.get("clinical_exam") or "").strip()
        visit.plan = (request.form.get("plan") or "").strip()
        visit.notes = (request.form.get("notes") or "").strip()

        _save_vitals(visit)
        ActivityLog.record(
            "visit.update", user_id=current_user.id, entity="visit",
            entity_id=visit.id, ip_address=client_ip(),
        )
        db.session.commit()
        flash(t("visits.saved"), "success")
        return redirect(url_for("visits.record", visit_id=visit.id))

    return render_template("visits/record.html", visit=visit)


def _save_vitals(visit):
    """Upsert the visit's vitals and mirror growth measurements."""
    vitals = visit.vitals or VitalSigns(visit_id=visit.id)
    vitals.weight_kg = _float("weight_kg")
    vitals.height_cm = _float("height_cm")
    vitals.head_circ_cm = _float("head_circ_cm")
    vitals.temperature_c = _float("temperature_c")
    vitals.pulse_bpm = _int("pulse_bpm")
    vitals.resp_rate = _int("resp_rate")
    vitals.spo2 = _int("spo2")
    if visit.vitals is None:
        db.session.add(vitals)
        visit.vitals = vitals

    # Mirror weight/height/head into a growth record for this visit.
    if vitals.has_growth:
        gr = GrowthRecord.query.filter_by(visit_id=visit.id).first()
        if gr is None:
            gr = GrowthRecord(patient_id=visit.patient_id, visit_id=visit.id,
                              source="visit")
            db.session.add(gr)
        gr.record_date = visit.visit_date
        gr.weight_kg = vitals.weight_kg
        gr.height_cm = vitals.height_cm
        gr.head_circ_cm = vitals.head_circ_cm
        gr.bmi = vitals.bmi


# ----------------------------------------------------------- diagnoses -----
@visits_bp.route("/<int:visit_id>/diagnoses", methods=["POST"])
@module_required(MODULE)
def add_diagnosis(visit_id):
    visit = db.get_or_404(Visit, visit_id)
    title = (request.form.get("title") or "").strip()
    if not title:
        flash(t("common.required") + ": " + t("visits.diagnosis"), "danger")
        return redirect(url_for("visits.record", visit_id=visit.id) + "#dx")

    dx_type = (request.form.get("dx_type") or "working").strip()
    version = (request.form.get("icd_version") or "10").strip()
    db.session.add(Diagnosis(
        visit_id=visit.id,
        code=(request.form.get("code") or "").strip() or None,
        title=title,
        icd_version=version if Diagnosis.valid_version(version) else "10",
        dx_type=dx_type if Diagnosis.valid_type(dx_type) else "working",
    ))
    db.session.commit()
    flash(t("visits.diagnosis_added"), "success")
    return redirect(url_for("visits.record", visit_id=visit.id) + "#dx")


@visits_bp.route("/diagnoses/<int:dx_id>/delete", methods=["POST"])
@module_required(MODULE)
def delete_diagnosis(dx_id):
    dx = db.get_or_404(Diagnosis, dx_id)
    visit_id = dx.visit_id
    db.session.delete(dx)
    db.session.commit()
    flash(t("visits.diagnosis_removed"), "info")
    return redirect(url_for("visits.record", visit_id=visit_id) + "#dx")


# ------------------------------------------------------------ complete -----
@visits_bp.route("/<int:visit_id>/complete", methods=["POST"])
@module_required(MODULE)
def complete(visit_id):
    visit = db.get_or_404(Visit, visit_id)
    visit.status = "completed"
    visit.completed_at = datetime.utcnow()

    # Close a linked, still-active appointment.
    if visit.appointment and visit.appointment.status in ("waiting", "in_progress", "scheduled"):
        visit.appointment.apply_status("completed")

    ActivityLog.record(
        "visit.complete", user_id=current_user.id, entity="visit",
        entity_id=visit.id, ip_address=client_ip(),
    )
    db.session.commit()
    flash(t("visits.completed"), "success")
    return redirect(url_for("visits.view", visit_id=visit.id))


# ---------------------------------------------------------------- view -----
@visits_bp.route("/<int:visit_id>")
@module_required(MODULE)
def view(visit_id):
    visit = db.get_or_404(Visit, visit_id)
    return render_template("visits/view.html", visit=visit)


# -------------------------------------------------------- icd search -------
@visits_bp.route("/icd")
@module_required(MODULE)
def icd():
    return jsonify({"results": search_icd(request.args.get("q", ""))})
