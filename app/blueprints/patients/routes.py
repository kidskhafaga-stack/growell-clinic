"""Patients & Families module (Phase 2).

Covers patient CRUD with manual/auto file numbers, photo upload, medical
alerts, family grouping, parents/guardians and sibling linking.
"""
import os
from datetime import datetime

from flask import (
    Response,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from flask_login import current_user
from sqlalchemy import or_

from app.blueprints.patients import patients_bp
from app.extensions import db
from app.i18n import t
from app.models import (
    BLOOD_TYPES,
    CLIENT_CATEGORIES,
    Family,
    GENDERS,
    PARENT_RELATIONS,
    ActivityLog,
    Parent,
    Patient,
)
from app.utils.decorators import client_ip, module_required
from app.utils.imports import (
    allowed_import_file,
    build_template_csv,
    build_template_workbook,
    parse_date,
    parse_gender,
    read_rows,
)
from app.utils.patients import (
    delete_patient_photo,
    generate_patient_number,
    save_patient_photo,
)

MODULE = "patients"


def _upload_dir():
    return os.path.join(current_app.static_folder, "uploads", "patients")


# ---------------------------------------------------------------- list -----
@patients_bp.route("/")
@module_required(MODULE)
def index():
    q = (request.args.get("q") or "").strip()
    query = Patient.query
    if q:
        like = f"%{q}%"
        query = query.filter(
            or_(
                Patient.full_name.ilike(like),
                Patient.full_name_en.ilike(like),
                Patient.patient_number.ilike(like),
                Patient.reference_number.ilike(like),
                Patient.national_id.ilike(like),
            )
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
        q=q, stats=stats,
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
    patient = db.get_or_404(Patient, patient_id)
    return render_template(
        "patients/profile.html",
        patient=patient,
        relations=PARENT_RELATIONS,
        categories=CLIENT_CATEGORIES,
    )


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
        email=(request.form.get("email") or "").strip(),
        occupation=(request.form.get("occupation") or "").strip(),
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

        rows, error = read_rows(file)
        if error == "no_name_column":
            flash(t("import.no_name_column"), "danger")
            return redirect(url_for("patients.bulk_import"))
        if error or not rows:
            flash(t("import.empty"), "warning")
            return redirect(url_for("patients.bulk_import"))

        result = _process_import(rows)
        db.session.commit()
        ActivityLog.record(
            "patient.import", user_id=current_user.id, entity="patient",
            detail=f"created={result['created']} skipped={len(result['errors'])}",
            ip_address=client_ip(),
        )
        db.session.commit()
        return render_template("patients/import_result.html", result=result)

    return render_template("patients/import.html")


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
    family_cache = {}

    def resolve_family(name):
        if not name:
            return None
        key = name.strip()
        if key in family_cache:
            return family_cache[key]
        family = Family.query.filter_by(family_name=key).first()
        if family is None:
            family = Family(family_name=key)
            db.session.add(family)
            db.session.flush()
        family_cache[key] = family.id
        return family.id

    for offset, row in enumerate(rows):
        line = offset + 2  # account for the header row (1-based, human-friendly)
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

        family_id = resolve_family(row.get("family_name"))

        patient = Patient(
            patient_number=generate_patient_number(),
            reference_number=(str(row.get("reference_number")).strip()
                              if row.get("reference_number") not in (None, "") else None),
            family_id=family_id,
            full_name=name,
            full_name_en=(row.get("full_name_en") or "").strip() or None,
            date_of_birth=dob,
            gender=gender,
            national_id=(str(row.get("national_id")).strip()
                         if row.get("national_id") not in (None, "") else None),
            blood_type=(row.get("blood_type") or "").strip() or None,
            allergies=(row.get("allergies") or "").strip() or None,
            chronic_diseases=(row.get("chronic_diseases") or "").strip() or None,
            notes=(row.get("notes") or "").strip() or None,
            is_active=True,
        )
        db.session.add(patient)

        # Optional guardian on the family.
        parent_name = (row.get("parent_name") or "").strip()
        if parent_name and family_id:
            relation = (row.get("parent_relation") or "father").strip().lower()
            category = (row.get("client_category") or "normal").strip().lower()
            db.session.add(Parent(
                family_id=family_id,
                relation=relation if Parent.valid_relation(relation) else "father",
                full_name=parent_name,
                phone=(str(row.get("parent_phone")).strip()
                       if row.get("parent_phone") not in (None, "") else None),
                client_category=category if Parent.valid_category(category) else "normal",
            ))

        created += 1

    return {"created": created, "errors": errors, "total": len(rows)}
