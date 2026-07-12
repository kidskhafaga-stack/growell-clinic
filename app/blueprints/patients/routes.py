"""Patients & Families module (Phase 2).

Covers patient CRUD with manual/auto file numbers, photo upload, medical
alerts, family grouping, parents/guardians and sibling linking.
"""
import json
import os
import uuid
from datetime import date, datetime

from flask import (
    Response,
    current_app,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from flask_login import current_user

from app.blueprints.patients import patients_bp
from app.extensions import db
from app.i18n import t
from app.models import (
    BLOOD_TYPES,
    CLIENT_CATEGORIES,
    Family,
    GENDERS,
    CONSENT_TYPES,
    PARENT_RELATIONS,
    ActivityLog,
    Consent,
    Parent,
    Patient,
    PatientAttachment,
    PatientProblem,
)
from app.utils.uploads import ATTACHMENT_KINDS, remove_document, save_document
from app.utils.decorators import capability_required, client_ip, module_required
from app.utils.imports import (
    allowed_import_file,
    build_rows,
    build_template_csv,
    build_template_workbook,
    derive_guardian_name,
    guess_mapping,
    import_fields,
    normalize_phone,
    parse_date,
    parse_gender,
    read_matrix,
    REQUIRED_KEYS,
)
from app.utils.patients import (
    apply_patient_search,
    delete_patient_photo,
    generate_patient_number,
    patient_number_allocator,
    save_patient_photo,
)

MODULE = "patients"


def _upload_dir():
    return os.path.join(current_app.static_folder, "uploads", "patients")


@patients_bp.route("/<int:patient_id>/documents", methods=["POST"])
@module_required(MODULE)
@capability_required("patient_medical")
def upload_document(patient_id):
    """Upload a document (lab/imaging/report) straight to the patient file."""
    patient = db.get_or_404(Patient, patient_id)
    stored = save_document(request.files.get("file"))
    if not stored:
        flash(t("visits.att_bad_type"), "warning")
        return redirect(url_for("patients.view", patient_id=patient.id) + "#documents")
    kind = request.form.get("kind")
    db.session.add(PatientAttachment(
        patient_id=patient.id, filename=stored,
        original_name=request.files["file"].filename,
        kind=kind if kind in ATTACHMENT_KINDS else "report",
        label=(request.form.get("label") or "").strip() or None,
        uploaded_by=current_user.id,
    ))
    db.session.commit()
    flash(t("visits.att_uploaded"), "success")
    return redirect(url_for("patients.view", patient_id=patient.id) + "#documents")


@patients_bp.route("/documents/<int:att_id>/delete", methods=["POST"])
@module_required(MODULE)
@capability_required("patient_medical")
def delete_document(att_id):
    att = db.get_or_404(PatientAttachment, att_id)
    patient_id = att.patient_id
    remove_document(att.filename)
    db.session.delete(att)
    db.session.commit()
    flash(t("visits.att_removed"), "info")
    return redirect(url_for("patients.view", patient_id=patient_id) + "#documents")


# ---------------------------------------------------------------- list -----
@patients_bp.route("/")
@module_required(MODULE)
def index():
    q = (request.args.get("q") or "").strip()
    flag = (request.args.get("flag") or "").strip()
    query = apply_patient_search(Patient.query, q)
    if flag == "teen_no_phone":
        # Reception task: active teens (≥13) with no personal phone captured yet.
        from app.models.patient import own_phone_cutoff
        query = query.filter(
            Patient.is_active.is_(True),
            Patient.date_of_birth <= own_phone_cutoff(),
            db.or_(Patient.own_phone.is_(None), Patient.own_phone == ""),
        )
    pagination = query.order_by(Patient.created_at.desc()).paginate(
        page=request.args.get("page", 1, type=int), per_page=25, error_out=False
    )

    stats = {
        "total": Patient.query.count(),
        "active": Patient.query.filter_by(is_active=True).count(),
        "male": Patient.query.filter_by(gender="male").count(),
        "female": Patient.query.filter_by(gender="female").count(),
    }
    return render_template(
        "patients/list.html", patients=pagination.items, pagination=pagination,
        q=q, stats=stats, flag=flag,
    )


# ------------------------------------------------------------ analytics ----
@patients_bp.route("/analytics")
@module_required(MODULE)
def analytics():
    """Patient analytics: gender / age distribution + top diagnoses in a period."""
    from datetime import datetime, timedelta

    from sqlalchemy import func

    from app.blueprints.main.routes import AGE_GROUPS, _age_group
    from app.models import Diagnosis, Visit

    days = request.args.get("days", 90, type=int)
    if days not in (30, 90, 180, 365):
        days = 90
    start = datetime.utcnow().date() - timedelta(days=days)

    patients = Patient.query.filter_by(is_active=True).all()
    groups = {key: 0 for key, _ in AGE_GROUPS}
    male = female = 0
    for p in patients:
        if p.gender == "male":
            male += 1
        elif p.gender == "female":
            female += 1
        groups[_age_group(p.age_days)] += 1
    stats = {"total": len(patients), "male": male, "female": female, "groups": groups}

    # Top diagnoses recorded in visits within the period.
    top_dx = (
        db.session.query(Diagnosis.title, func.count().label("n"))
        .join(Visit, Diagnosis.visit_id == Visit.id)
        .filter(Visit.visit_date >= start, Diagnosis.title.isnot(None))
        .group_by(Diagnosis.title)
        .order_by(func.count().desc())
        .limit(10)
        .all()
    )
    period = {
        "days": days,
        "new_patients": Patient.query.filter(Patient.created_at >= start).count(),
        "visits": Visit.query.filter(Visit.visit_date >= start).count(),
    }
    return render_template(
        "patients/analytics.html", stats=stats,
        age_groups=[k for k, _ in AGE_GROUPS], top_dx=top_dx, period=period,
    )


# -------------------------------------------------------------- create -----
@patients_bp.route("/new", methods=["GET", "POST"])
@module_required(MODULE)
def create():
    families = Family.query.order_by(Family.family_name).all()
    prefill_family = request.args.get("family_id", type=int)

    if request.method == "POST":
        form = _read_patient_form()
        error = _validate_patient(form, existing=None)
        if error:
            flash(error, "danger")
            return render_template(
                "patients/form.html",
                patient=None, form=form, families=families,
                genders=GENDERS, blood_types=BLOOD_TYPES,
                suggested_number=form.get("patient_number"),
            )

        family_id = _resolve_family(form)

        patient = Patient(
            patient_number=form["patient_number"],
            reference_number=form["reference_number"] or None,
            family_id=family_id,
            full_name=form["full_name"],
            full_name_en=form["full_name_en"],
            date_of_birth=form["date_of_birth"],
            gender=form["gender"],
            national_id=form["national_id"],
            own_phone=form["own_phone"] or None,
            blood_type=form["blood_type"],
            allergies=form["allergies"],
            chronic_diseases=form["chronic_diseases"],
            notes=form["notes"],
            is_active=form["is_active"],
        )

        photo = save_patient_photo(request.files.get("photo"), _upload_dir())
        if photo:
            patient.photo = photo

        db.session.add(patient)
        db.session.flush()
        ActivityLog.record(
            "patient.create", user_id=current_user.id, entity="patient",
            entity_id=patient.id, detail=patient.patient_number,
            ip_address=client_ip(),
        )
        db.session.commit()
        flash(t("patients.created"), "success")
        return redirect(url_for("patients.view", patient_id=patient.id))

    return render_template(
        "patients/form.html",
        patient=None, form={"is_active": True}, families=families,
        genders=GENDERS, blood_types=BLOOD_TYPES,
        suggested_number=generate_patient_number(),
        prefill_family=prefill_family,
    )


# ---------------------------------------------------------------- view -----
@patients_bp.route("/<int:patient_id>")
@module_required(MODULE)
def view(patient_id):
    from app.models import Invoice, PayerEntity, Prescription
    from app.utils import ai as ai_utils

    patient = db.get_or_404(Patient, patient_id)
    ai_patient = (current_user.can_access("ai") and ai_utils.is_ready()
                  and ai_utils.patient_context_enabled())

    prescriptions = (Prescription.query.filter_by(patient_id=patient.id)
                     .order_by(Prescription.rx_date.desc(), Prescription.id.desc()).all())
    invoices = (Invoice.query.filter_by(patient_id=patient.id)
                .order_by(Invoice.invoice_date.desc(), Invoice.id.desc()).all())
    fin = {
        "total": round(sum(i.total for i in invoices), 2),
        "paid": round(sum(i.paid for i in invoices), 2),
        "balance": round(sum(i.balance for i in invoices), 2),
    }
    return render_template(
        "patients/profile.html",
        patient=patient,
        relations=PARENT_RELATIONS,
        consent_types=CONSENT_TYPES,
        categories=CLIENT_CATEGORIES,
        payers=PayerEntity.query.filter_by(is_active=True).order_by(PayerEntity.name).all(),
        ai_patient=ai_patient,
        prescriptions=prescriptions, invoices=invoices, fin=fin,
        growth_alert=_growth_concern(patient),
    )


@patients_bp.route("/<int:patient_id>/report")
@module_required(MODULE)
def report(patient_id):
    """Generate a comprehensive medical report for the case: demographics,
    problem list, growth, vaccination status, recent visits, current meds — all
    assembled from the record. The doctor can edit any section inline in the
    browser and print it (editing is browser-side; the record isn't changed)."""
    from app.models import GrowthRecord, Prescription, Visit
    from app.utils.vaccines import patient_plan, plan_summary

    patient = db.get_or_404(Patient, patient_id)

    problems = [p for p in getattr(patient, "problems", [])
                if p.status == "active"]
    visits = (Visit.query.filter_by(patient_id=patient.id)
              .order_by(Visit.visit_date.desc(), Visit.id.desc()).limit(10).all())
    latest_growth = (GrowthRecord.query.filter_by(patient_id=patient.id)
                     .order_by(GrowthRecord.record_date.desc(),
                               GrowthRecord.id.desc()).first())
    try:
        vac = plan_summary(patient_plan(patient, getattr(g, "lang", "ar")))
    except Exception:  # noqa: BLE001
        vac = None
    latest_rx = (Prescription.query.filter_by(patient_id=patient.id)
                 .order_by(Prescription.rx_date.desc(), Prescription.id.desc()).first())

    return render_template(
        "patients/report.html", patient=patient, problems=problems,
        visits=visits, latest_growth=latest_growth, vac=vac,
        latest_rx=latest_rx, growth_alert=_growth_concern(patient),
        generated_by=current_user, today=date.today(),
    )


def _growth_concern(patient):
    """If the patient's latest growth measurement falls in a caution/alert band
    (|z|>2), return a compact dict so the profile can flag it prominently."""
    from app.models import GrowthRecord
    from app.utils.growth import (
        INDICATORS, age_in_months, compute_point, status_for_z,
    )

    rec = (GrowthRecord.query.filter_by(patient_id=patient.id)
           .order_by(GrowthRecord.record_date.desc(), GrowthRecord.id.desc()).first())
    if rec is None:
        return None
    ref = "WHO" if patient.age_parts[0] < 5 else "CDC"
    worst = None
    for ind, meta in INDICATORS.items():
        value = getattr(rec, meta["field"], None)
        if not value:
            continue
        pt = compute_point(ref, ind, patient.gender,
                           patient.date_of_birth, rec.record_date, value)
        if not pt or pt.get("z") is None:
            continue
        status = status_for_z(pt["z"])
        if status in ("caution", "alert"):
            cand = {"indicator": ind, "z": pt["z"], "percentile": pt["percentile"],
                    "status": status, "date": rec.record_date.isoformat()}
            if worst is None or abs(pt["z"]) > abs(worst["z"]):
                worst = cand
    return worst


# ---------------------------------------------------------------- edit -----
@patients_bp.route("/<int:patient_id>/edit", methods=["GET", "POST"])
@module_required(MODULE)
def edit(patient_id):
    patient = db.get_or_404(Patient, patient_id)
    families = Family.query.order_by(Family.family_name).all()

    if request.method == "POST":
        form = _read_patient_form()
        error = _validate_patient(form, existing=patient)
        if error:
            flash(error, "danger")
            return render_template(
                "patients/form.html",
                patient=patient, form=form, families=families,
                genders=GENDERS, blood_types=BLOOD_TYPES,
                suggested_number=form.get("patient_number"),
            )

        patient.patient_number = form["patient_number"]
        patient.reference_number = form["reference_number"] or None
        patient.family_id = _resolve_family(form)
        patient.full_name = form["full_name"]
        patient.full_name_en = form["full_name_en"]
        patient.date_of_birth = form["date_of_birth"]
        patient.gender = form["gender"]
        patient.national_id = form["national_id"]
        patient.own_phone = form["own_phone"] or None
        patient.blood_type = form["blood_type"]
        patient.allergies = form["allergies"]
        patient.chronic_diseases = form["chronic_diseases"]
        patient.notes = form["notes"]
        patient.is_active = form["is_active"]

        new_photo = save_patient_photo(request.files.get("photo"), _upload_dir())
        if new_photo:
            delete_patient_photo(patient.photo, _upload_dir())
            patient.photo = new_photo

        ActivityLog.record(
            "patient.update", user_id=current_user.id, entity="patient",
            entity_id=patient.id, detail=patient.patient_number,
            ip_address=client_ip(),
        )
        db.session.commit()
        flash(t("patients.updated"), "success")
        return redirect(url_for("patients.view", patient_id=patient.id))

    form = {
        "patient_number": patient.patient_number,
        "reference_number": patient.reference_number or "",
        "family_id": patient.family_id,
        "full_name": patient.full_name,
        "full_name_en": patient.full_name_en or "",
        "date_of_birth": patient.date_of_birth.isoformat() if patient.date_of_birth else "",
        "gender": patient.gender,
        "national_id": patient.national_id or "",
        "own_phone": patient.own_phone or "",
        "blood_type": patient.blood_type or "",
        "allergies": patient.allergies or "",
        "chronic_diseases": patient.chronic_diseases or "",
        "notes": patient.notes or "",
        "is_active": patient.is_active,
    }
    return render_template(
        "patients/form.html",
        patient=patient, form=form, families=families,
        genders=GENDERS, blood_types=BLOOD_TYPES,
        suggested_number=patient.patient_number,
    )


# -------------------------------------------------------------- delete -----
@patients_bp.route("/<int:patient_id>/delete", methods=["POST"])
@module_required(MODULE)
def delete(patient_id):
    patient = db.get_or_404(Patient, patient_id)
    number = patient.patient_number
    delete_patient_photo(patient.photo, _upload_dir())
    db.session.delete(patient)
    ActivityLog.record(
        "patient.delete", user_id=current_user.id, entity="patient",
        entity_id=patient_id, detail=number, ip_address=client_ip(),
    )
    db.session.commit()
    flash(t("patients.deleted"), "info")
    return redirect(url_for("patients.index"))


# ----------------------------------------------- membership / coverage -----
@patients_bp.route("/<int:patient_id>/coverage/new", methods=["POST"])
@module_required(MODULE)
def add_coverage(patient_id):
    from datetime import datetime as _dt

    from app.models import PatientCoverage, PayerEntity

    patient = db.get_or_404(Patient, patient_id)
    payer = db.session.get(PayerEntity, request.form.get("payer_id", type=int))
    if payer is None:
        flash(t("coverage.need_payer"), "danger")
        return redirect(url_for("patients.view", patient_id=patient.id) + "#coverage")

    def _exp():
        raw = (request.form.get("expiry_date") or "").strip()
        try:
            return _dt.strptime(raw, "%Y-%m-%d").date() if raw else None
        except ValueError:
            return None

    card = (request.form.get("membership_number") or "").strip() or None
    expiry = _exp()
    targets = [patient]
    # Optionally apply the same entity to siblings (each keeps its own card).
    if request.form.get("apply_siblings"):
        targets += patient.siblings

    for tgt in targets:
        # Per-patient card number only for the main patient; siblings share the
        # entity but get their own (blank) card to fill later.
        db.session.add(PatientCoverage(
            patient_id=tgt.id, payer_id=payer.id,
            membership_number=card if tgt.id == patient.id else None,
            expiry_date=expiry, is_active=True,
        ))
    db.session.commit()
    flash(t("coverage.added"), "success")
    return redirect(url_for("patients.view", patient_id=patient.id) + "#coverage")


@patients_bp.route("/coverage/<int:coverage_id>/delete", methods=["POST"])
@module_required(MODULE)
def delete_coverage(coverage_id):
    from app.models import PatientCoverage

    cov = db.get_or_404(PatientCoverage, coverage_id)
    pid = cov.patient_id
    db.session.delete(cov)
    db.session.commit()
    flash(t("coverage.removed"), "info")
    return redirect(url_for("patients.view", patient_id=pid) + "#coverage")


# ------------------------------------------------------ parents (family) ---
@patients_bp.route("/<int:patient_id>/parents/new", methods=["POST"])
@module_required(MODULE)
def add_parent(patient_id):
    patient = db.get_or_404(Patient, patient_id)

    # Ensure the patient has a family to attach the parent to.
    if patient.family_id is None:
        family = Family(family_name=patient.full_name)
        db.session.add(family)
        db.session.flush()
        patient.family_id = family.id

    relation = (request.form.get("relation") or "father").strip()
    full_name = (request.form.get("full_name") or "").strip()
    category = (request.form.get("client_category") or "normal").strip()

    if not full_name:
        flash(t("common.required") + ": " + t("patients.parent_name"), "danger")
        return redirect(url_for("patients.view", patient_id=patient.id))

    parent = Parent(
        family_id=patient.family_id,
        relation=relation if Parent.valid_relation(relation) else "father",
        full_name=full_name,
        full_name_en=(request.form.get("full_name_en") or "").strip(),
        national_id=(request.form.get("national_id") or "").strip(),
        phone=(request.form.get("phone") or "").strip(),
        phone_alt=(request.form.get("phone_alt") or "").strip(),
        email=(request.form.get("email") or "").strip(),
        occupation=(request.form.get("occupation") or "").strip(),
        nationality=(request.form.get("nationality") or "").strip(),
        address=(request.form.get("address") or "").strip(),
        client_category=category if Parent.valid_category(category) else "normal",
        is_primary_contact=bool(request.form.get("is_primary_contact")),
    )
    db.session.add(parent)
    ActivityLog.record(
        "parent.create", user_id=current_user.id, entity="parent",
        entity_id=patient.family_id, detail=full_name, ip_address=client_ip(),
    )
    db.session.commit()
    flash(t("patients.parent_added"), "success")
    return redirect(url_for("patients.view", patient_id=patient.id) + "#family")


@patients_bp.route("/parents/<int:parent_id>/edit", methods=["POST"])
@module_required(MODULE)
def edit_parent(parent_id):
    parent = db.get_or_404(Parent, parent_id)
    patient_id = request.form.get("patient_id", type=int)

    full_name = (request.form.get("full_name") or "").strip()
    if not full_name:
        flash(t("common.required") + ": " + t("patients.parent_name"), "danger")
        return redirect(url_for("patients.view", patient_id=patient_id) + "#family")

    relation = (request.form.get("relation") or parent.relation).strip()
    category = (request.form.get("client_category") or parent.client_category).strip()
    parent.relation = relation if Parent.valid_relation(relation) else parent.relation
    parent.full_name = full_name
    parent.full_name_en = (request.form.get("full_name_en") or "").strip()
    parent.national_id = (request.form.get("national_id") or "").strip()
    parent.phone = (request.form.get("phone") or "").strip()
    parent.phone_alt = (request.form.get("phone_alt") or "").strip()
    parent.email = (request.form.get("email") or "").strip()
    parent.occupation = (request.form.get("occupation") or "").strip()
    parent.nationality = (request.form.get("nationality") or "").strip()
    parent.address = (request.form.get("address") or "").strip()
    parent.client_category = category if Parent.valid_category(category) else parent.client_category
    parent.is_primary_contact = bool(request.form.get("is_primary_contact"))

    ActivityLog.record(
        "parent.update", user_id=current_user.id, entity="parent",
        entity_id=parent.id, detail=full_name, ip_address=client_ip(),
    )
    db.session.commit()
    flash(t("patients.parent_updated"), "success")
    return redirect(url_for("patients.view", patient_id=patient_id) + "#family")


@patients_bp.route("/parents/<int:parent_id>/delete", methods=["POST"])
@module_required(MODULE)
def delete_parent(parent_id):
    parent = db.get_or_404(Parent, parent_id)
    patient_id = request.form.get("patient_id", type=int)
    db.session.delete(parent)
    db.session.commit()
    flash(t("patients.parent_removed"), "info")
    if patient_id:
        return redirect(url_for("patients.view", patient_id=patient_id) + "#family")
    return redirect(url_for("patients.index"))


# ------------------------------------------------------ problem list -------
def _parse_date(name):
    raw = (request.form.get(name) or "").strip()
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        return None


@patients_bp.route("/<int:patient_id>/problems", methods=["POST"])
@module_required(MODULE)
def add_problem(patient_id):
    patient = db.get_or_404(Patient, patient_id)
    title = (request.form.get("title") or "").strip()
    if not title:
        flash(t("common.required") + ": " + t("problems.title"), "danger")
        return redirect(url_for("patients.view", patient_id=patient.id) + "#problems")
    db.session.add(PatientProblem(
        patient_id=patient.id, title=title,
        title_en=(request.form.get("title_en") or "").strip() or None,
        icd_code=(request.form.get("icd_code") or "").strip() or None,
        onset_date=_parse_date("onset_date"),
        notes=(request.form.get("notes") or "").strip() or None,
    ))
    ActivityLog.record("problem.add", user_id=current_user.id, entity="patient",
                       entity_id=patient.id, detail=title, ip_address=client_ip())
    db.session.commit()
    flash(t("problems.added"), "success")
    return redirect(url_for("patients.view", patient_id=patient.id) + "#problems")


@patients_bp.route("/problems/<int:problem_id>/toggle", methods=["POST"])
@module_required(MODULE)
def toggle_problem(problem_id):
    prob = db.get_or_404(PatientProblem, problem_id)
    if prob.status == "active":
        prob.status = "resolved"
        prob.resolved_date = date.today()
    else:
        prob.status = "active"
        prob.resolved_date = None
    db.session.commit()
    flash(t("problems.updated"), "success")
    return redirect(url_for("patients.view", patient_id=prob.patient_id) + "#problems")


@patients_bp.route("/problems/<int:problem_id>/delete", methods=["POST"])
@module_required(MODULE)
def delete_problem(problem_id):
    prob = db.get_or_404(PatientProblem, problem_id)
    pid = prob.patient_id
    db.session.delete(prob)
    db.session.commit()
    flash(t("problems.deleted"), "info")
    return redirect(url_for("patients.view", patient_id=pid) + "#problems")


# --------------------------------------------------------- consent ---------
@patients_bp.route("/<int:patient_id>/consents", methods=["POST"])
@module_required(MODULE)
def add_consent(patient_id):
    patient = db.get_or_404(Patient, patient_id)
    guardian = (request.form.get("guardian_name") or "").strip()
    ctype = (request.form.get("consent_type") or "general").strip()
    if not guardian:
        flash(t("common.required") + ": " + t("consent.guardian_name"), "danger")
        return redirect(url_for("patients.view", patient_id=patient.id) + "#consent")
    db.session.add(Consent(
        patient_id=patient.id,
        consent_type=ctype if ctype in CONSENT_TYPES else "general",
        guardian_name=guardian,
        guardian_relation=(request.form.get("guardian_relation") or "").strip() or None,
        guardian_id_no=(request.form.get("guardian_id_no") or "").strip() or None,
        statement=(request.form.get("statement") or "").strip() or None,
        notes=(request.form.get("notes") or "").strip() or None,
        signed_date=_parse_date("signed_date") or date.today(),
        obtained_by=current_user.id,
    ))
    ActivityLog.record("consent.add", user_id=current_user.id, entity="patient",
                       entity_id=patient.id, detail=ctype, ip_address=client_ip())
    db.session.commit()
    flash(t("consent.added"), "success")
    return redirect(url_for("patients.view", patient_id=patient.id) + "#consent")


@patients_bp.route("/consents/<int:consent_id>/delete", methods=["POST"])
@module_required(MODULE)
def delete_consent(consent_id):
    c = db.get_or_404(Consent, consent_id)
    pid = c.patient_id
    db.session.delete(c)
    db.session.commit()
    flash(t("consent.deleted"), "info")
    return redirect(url_for("patients.view", patient_id=pid) + "#consent")


@patients_bp.route("/consents/<int:consent_id>/print")
@module_required(MODULE)
def print_consent(consent_id):
    c = db.get_or_404(Consent, consent_id)
    return render_template("patients/consent_print.html", c=c, patient=c.patient)


# ----------------------------------------------------------- families ------
@patients_bp.route("/families/search")
@module_required(MODULE)
def family_search():
    """Autocomplete for picking a family by name or number (booking/new patient)."""
    q = (request.args.get("q") or "").strip()
    if len(q) < 1:
        return jsonify({"families": []})
    like = f"%{q}%"
    rows = (
        Family.query.filter(db.or_(
            Family.family_name.ilike(like),
            Family.family_name_en.ilike(like),
            Family.family_number.ilike(like),
        )).order_by(Family.family_name).limit(15).all()
    )
    return jsonify({"families": [
        {"id": f.id, "name": f.display_name(),
         "number": f.family_number or "",
         "count": len(f.patients)} for f in rows
    ]})


@patients_bp.route("/families/<int:family_id>/edit", methods=["POST"])
@module_required(MODULE)
def family_update(family_id):
    """Rename / edit a family's details."""
    family = db.get_or_404(Family, family_id)
    name = (request.form.get("family_name") or "").strip()
    if not name:
        flash(t("common.required") + ": " + t("patients.family_name"), "danger")
    else:
        family.family_name = name
        family.family_name_en = (request.form.get("family_name_en") or "").strip() or None
        family.notes = (request.form.get("notes") or "").strip() or None
        db.session.commit()
        flash(t("patients.family_updated"), "success")
    patient_id = request.form.get("patient_id", type=int)
    if patient_id:
        return redirect(url_for("patients.view", patient_id=patient_id) + "#family")
    return redirect(url_for("patients.index"))


# --------------------------------------------------------------- helpers ---
def _read_patient_form():
    return {
        "patient_number": (request.form.get("patient_number") or "").strip(),
        "auto_number": bool(request.form.get("auto_number")),
        "reference_number": (request.form.get("reference_number") or "").strip(),
        "full_name": (request.form.get("full_name") or "").strip(),
        "full_name_en": (request.form.get("full_name_en") or "").strip(),
        "date_of_birth_raw": (request.form.get("date_of_birth") or "").strip(),
        "gender": (request.form.get("gender") or "").strip(),
        "national_id": (request.form.get("national_id") or "").strip(),
        "own_phone": (request.form.get("own_phone") or "").strip(),
        "blood_type": (request.form.get("blood_type") or "").strip(),
        "allergies": (request.form.get("allergies") or "").strip(),
        "chronic_diseases": (request.form.get("chronic_diseases") or "").strip(),
        "notes": (request.form.get("notes") or "").strip(),
        "is_active": bool(request.form.get("is_active")),
        # Family selection.
        "family_id": request.form.get("family_id", type=int),
        "new_family_name": (request.form.get("new_family_name") or "").strip(),
    }


def _validate_patient(form, existing):
    """Validate, parse the date, and assign the file number. Returns error str."""
    if not form["full_name"]:
        return t("common.required") + ": " + t("patients.full_name")
    if not Patient.valid_gender(form["gender"]):
        return t("common.required") + ": " + t("patients.gender")

    # Date of birth.
    if not form["date_of_birth_raw"]:
        return t("common.required") + ": " + t("patients.dob")
    try:
        form["date_of_birth"] = datetime.strptime(
            form["date_of_birth_raw"], "%Y-%m-%d"
        ).date()
    except ValueError:
        return t("patients.invalid_date")

    # File number: auto-generate or validate uniqueness of the manual one.
    if form["auto_number"] or not form["patient_number"]:
        if existing is not None:
            form["patient_number"] = existing.patient_number
        else:
            form["patient_number"] = generate_patient_number()
    else:
        dup = Patient.query.filter_by(patient_number=form["patient_number"])
        if existing is not None:
            dup = dup.filter(Patient.id != existing.id)
        if dup.first() is not None:
            return t("patients.number_taken")

    return None


def _resolve_family(form):
    """Return a family id based on the form: existing, new, or None."""
    if form.get("new_family_name"):
        family = Family(family_name=form["new_family_name"])
        db.session.add(family)
        db.session.flush()
        return family.id
    return form.get("family_id") or None


# ------------------------------------------------------- bulk import -------
MAX_PREVIEW_ROWS = 200


def _import_tmp_dir():
    path = os.path.join(current_app.instance_path, "import_tmp")
    os.makedirs(path, exist_ok=True)
    return path


def _analyze_rows(rows):
    """Validate parsed rows without writing anything (for the preview step).

    Returns (preview, valid_count) where preview is a per-row list with the
    resolved values and an ``ok``/``error`` status + reason.
    """
    preview = []
    valid = 0
    for offset, row in enumerate(rows):
        line = offset + 2  # +1 header, 1-based
        name = (str(row.get("full_name")).strip() if row.get("full_name") else "")
        gender = parse_gender(row.get("gender"))
        dob = parse_date(row.get("date_of_birth"))

        reason = None
        if not name:
            reason = t("import.err_name")
        elif gender is None:
            reason = t("import.err_gender")
        elif dob is None:
            reason = t("import.err_dob")

        if reason is None:
            valid += 1
        preview.append({
            "line": line,
            "name": name or "—",
            "name_en": (row.get("full_name_en") or "").strip() or None,
            "gender": gender,
            "dob": dob.isoformat() if dob else (row.get("date_of_birth") or "—"),
            "family": (row.get("family_name") or "").strip() or None,
            "parent": (row.get("parent_name") or "").strip() or None,
            "ok": reason is None,
            "reason": reason,
        })
    return preview, valid


@patients_bp.route("/import", methods=["GET", "POST"])
@module_required(MODULE)
def bulk_import():
    if request.method == "POST":
        file = request.files.get("file")
        if not file or not file.filename:
            flash(t("import.no_file"), "danger")
            return redirect(url_for("patients.bulk_import"))
        if not allowed_import_file(file.filename):
            flash(t("import.bad_format"), "danger")
            return redirect(url_for("patients.bulk_import"))

        headers, data_rows, error = read_matrix(file)
        if error == "unreadable":
            flash(t("import.unreadable"), "danger")
            return redirect(url_for("patients.bulk_import"))
        if error or not data_rows:
            flash(t("import.empty"), "warning")
            return redirect(url_for("patients.bulk_import"))

        # Stash the raw sheet (headers + rows) so the mapping step can rebuild
        # records however the user maps the columns. Dates -> ISO for JSON.
        token = uuid.uuid4().hex
        with open(os.path.join(_import_tmp_dir(), f"{token}.json"), "w",
                  encoding="utf-8") as fh:
            json.dump({"headers": headers, "rows": data_rows, "filename": file.filename},
                      fh, ensure_ascii=False, default=_json_cell)

        return render_template(
            "patients/import_map.html",
            token=token, headers=headers, filename=file.filename,
            fields=import_fields(), required_keys=REQUIRED_KEYS,
            guess=guess_mapping(headers),
            sample=data_rows[:5], total=len(data_rows),
        )

    return render_template("patients/import.html")


def _load_import_tmp(token):
    """Return (path, payload) for a stashed import, or (None, None) if missing."""
    if not token.isalnum():
        return None, None
    tmp_path = os.path.join(_import_tmp_dir(), f"{token}.json")
    if not os.path.isfile(tmp_path):
        return None, None
    with open(tmp_path, encoding="utf-8") as fh:
        return tmp_path, json.load(fh)


@patients_bp.route("/import/map", methods=["POST"])
@module_required(MODULE)
def import_map():
    token = (request.form.get("token") or "").strip()
    tmp_path, payload = _load_import_tmp(token)
    # A freshly-stashed upload is a dict; older canonical payloads are a list.
    if payload is None or not isinstance(payload, dict):
        flash(t("import.session_expired"), "warning")
        return redirect(url_for("patients.bulk_import"))

    headers = payload["headers"]
    data_rows = payload["rows"]

    # Read the user's column choices: each field maps to a column index or "".
    mapping = {}
    for key, _required, _sample in import_fields():
        raw = (request.form.get(f"map_{key}") or "").strip()
        if raw == "":
            continue
        try:
            idx = int(raw)
        except ValueError:
            continue
        if 0 <= idx < len(headers):
            mapping[key] = idx

    missing = [k for k in REQUIRED_KEYS if k not in mapping]
    if missing:
        flash(t("import.map_required"), "danger")
        return render_template(
            "patients/import_map.html",
            token=token, headers=headers, filename=payload.get("filename", ""),
            fields=import_fields(), required_keys=REQUIRED_KEYS,
            guess=mapping or guess_mapping(headers),
            sample=data_rows[:5], total=len(data_rows), missing=missing,
        )

    rows = build_rows(data_rows, mapping)
    # Overwrite the stash with canonical rows for the confirm step.
    with open(tmp_path, "w", encoding="utf-8") as fh:
        json.dump(rows, fh, ensure_ascii=False, default=_json_cell)

    preview, valid = _analyze_rows(rows)
    return render_template(
        "patients/import_preview.html",
        token=token, preview=preview[:MAX_PREVIEW_ROWS],
        total=len(rows), valid=valid, invalid=len(rows) - valid,
        shown=min(len(rows), MAX_PREVIEW_ROWS),
        filename=payload.get("filename", ""),
    )


def _json_cell(value):
    if isinstance(value, (date, datetime)):
        return value.strftime("%Y-%m-%d")
    return str(value)


@patients_bp.route("/import/confirm", methods=["POST"])
@module_required(MODULE)
def import_confirm():
    token = (request.form.get("token") or "").strip()
    tmp_path, rows = _load_import_tmp(token)
    # The confirm step expects canonical rows (a list) written by import_map.
    if rows is None or not isinstance(rows, list):
        flash(t("import.session_expired"), "warning")
        return redirect(url_for("patients.bulk_import"))

    result = _process_import(rows)
    db.session.commit()
    ActivityLog.record(
        "patient.import", user_id=current_user.id, entity="patient",
        detail=f"created={result['created']} skipped={len(result['errors'])}",
        ip_address=client_ip(),
    )
    db.session.commit()
    try:
        os.remove(tmp_path)
    except OSError:
        pass
    return render_template("patients/import_result.html", result=result)


@patients_bp.route("/import/template")
@module_required(MODULE)
def import_template():
    fmt = (request.args.get("fmt") or "xlsx").lower()
    if fmt == "csv":
        return Response(
            build_template_csv(),
            mimetype="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": "attachment; filename=patients_template.csv"
            },
        )
    return send_file(
        build_template_workbook(),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name="patients_template.xlsx",
    )


def _process_import(rows):
    """Create patients/families/parents from parsed rows.

    Families are de-duplicated by name within the import (and matched against
    existing families) so siblings land in the same family record.
    """
    created = 0
    errors = []
    # Prefetch every existing family once (one query) so sibling-linking is an
    # in-memory dict lookup instead of a query (and autoflush) per row.
    family_cache = {f.family_name: f for f in Family.query.all()}
    phone_family = {}        # guardian phone -> Family (siblings share a phone)
    family_has_parent = set()  # id(family) that already carries a guardian
    next_number = patient_number_allocator()

    def get_named_family(key):
        family = family_cache.get(key)
        if family is None:
            family = Family(family_name=key)
            db.session.add(family)
            family_cache[key] = family
        return family

    def cell(key):
        val = row.get(key)
        if val in (None, ""):
            return None
        return str(val).strip() or None

    # ``no_autoflush`` keeps SQLAlchemy from flushing the growing batch of
    # pending patients on every read, which is what made large imports crawl.
    with db.session.no_autoflush:
        for offset, row in enumerate(rows):
            line = offset + 2  # account for the header row (1-based)
            name = (row.get("full_name") or "").strip()
            if not name:
                errors.append({"line": line, "reason": t("import.err_name")})
                continue

            gender = parse_gender(row.get("gender"))
            if gender is None:
                errors.append({"line": line, "reason": t("import.err_gender")})
                continue

            dob = parse_date(row.get("date_of_birth"))
            if dob is None:
                errors.append({"line": line, "reason": t("import.err_dob")})
                continue

            # Guardian name: explicit, or derived from the child's name (father
            # = the name after the child's first name) and flagged for review.
            given_parent = (row.get("parent_name") or "").strip()
            derived_parent = derive_guardian_name(name)
            parent_name = given_parent or derived_parent
            phone = normalize_phone(row.get("parent_phone"))
            fam_name = (row.get("family_name") or "").strip()

            # Resolve family so siblings group: explicit family name → shared
            # guardian phone → the (given/derived) guardian name.
            if fam_name:
                family = get_named_family(fam_name)
            elif phone and phone in phone_family:
                family = phone_family[phone]
            elif phone:
                family = get_named_family(parent_name or name)
                phone_family[phone] = family
            elif parent_name:
                family = get_named_family(parent_name)
            else:
                family = None

            patient = Patient(
                patient_number=next_number(),
                reference_number=cell("reference_number"),
                family=family,
                full_name=name,
                full_name_en=cell("full_name_en"),
                date_of_birth=dob,
                gender=gender,
                national_id=cell("national_id"),
                blood_type=cell("blood_type"),
                allergies=cell("allergies"),
                chronic_diseases=cell("chronic_diseases"),
                notes=cell("notes"),
                is_active=True,
            )
            db.session.add(patient)

            # One guardian per family — skip if the family already has one
            # (existing record or an earlier sibling in this import).
            if (parent_name and family is not None
                    and id(family) not in family_has_parent and not family.parents):
                relation = (row.get("parent_relation") or "father").strip().lower()
                category = (row.get("client_category") or "normal").strip().lower()
                db.session.add(Parent(
                    family=family,
                    relation=relation if Parent.valid_relation(relation) else "father",
                    full_name=parent_name,
                    auto_named=not given_parent,
                    phone=cell("parent_phone"),
                    phone_alt=cell("parent_phone_alt"),
                    national_id=cell("parent_national_id"),
                    email=cell("parent_email"),
                    occupation=cell("parent_occupation"),
                    nationality=cell("parent_nationality"),
                    address=cell("parent_address"),
                    client_category=category if Parent.valid_category(category) else "normal",
                ))
                family_has_parent.add(id(family))

            created += 1

    return {"created": created, "errors": errors, "total": len(rows)}
