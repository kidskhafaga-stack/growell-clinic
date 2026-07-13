"""User management (admin only) — create, edit, enable/disable and delete."""
from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user

import re

from app.blueprints.users import users_bp
from app.extensions import db
from app.i18n import t
from app.models import ActivityLog, Role, User
from app.models.permissions import MODULES
from app.utils.decorators import admin_required, client_ip


def _roles():
    """Editable roles for dropdowns (ordered: system first, then custom)."""
    return Role.query.order_by(Role.is_system.desc(), Role.name).all()


@users_bp.route("/")
@admin_required
def index():
    users = User.query.order_by(User.created_at.desc()).all()
    return render_template("users/list.html", users=users, roles=_roles())


# ----------------------------------------------------------- roles ---------
@users_bp.route("/roles")
@admin_required
def roles():
    return render_template("users/roles.html", roles=_roles(), modules=MODULES)


@users_bp.route("/roles/new", methods=["POST"])
@admin_required
def role_new():
    name = re.sub(r"[^a-z0-9_]", "", (request.form.get("name") or "").strip().lower())
    if not name:
        flash(t("roles_mgmt.bad_name"), "danger")
        return redirect(url_for("users.roles"))
    if Role.query.filter_by(name=name).first():
        flash(t("roles_mgmt.exists"), "warning")
        return redirect(url_for("users.roles"))
    role = Role(
        name=name,
        label_ar=(request.form.get("label_ar") or name).strip(),
        label_en=(request.form.get("label_en") or "").strip() or None,
        is_system=False, is_admin=False,
    )
    role.set_modules(request.form.getlist("modules"))
    db.session.add(role)
    ActivityLog.record("role.create", user_id=current_user.id, entity="role",
                       detail=name, ip_address=client_ip())
    db.session.commit()
    flash(t("roles_mgmt.created"), "success")
    return redirect(url_for("users.roles"))


@users_bp.route("/roles/<int:role_id>/edit", methods=["POST"])
@admin_required
def role_edit(role_id):
    role = db.get_or_404(Role, role_id)
    role.label_ar = (request.form.get("label_ar") or role.label_ar).strip()
    role.label_en = (request.form.get("label_en") or "").strip() or None
    # The admin role keeps full access; everyone else is editable.
    if not role.is_admin:
        role.set_modules(request.form.getlist("modules"))
    db.session.commit()
    flash(t("roles_mgmt.updated"), "success")
    return redirect(url_for("users.roles"))


@users_bp.route("/roles/<int:role_id>/delete", methods=["POST"])
@admin_required
def role_delete(role_id):
    role = db.get_or_404(Role, role_id)
    if role.is_system:
        flash(t("roles_mgmt.system_locked"), "warning")
        return redirect(url_for("users.roles"))
    if User.query.filter_by(role=role.name).count():
        flash(t("roles_mgmt.in_use"), "warning")
        return redirect(url_for("users.roles"))
    db.session.delete(role)
    db.session.commit()
    flash(t("roles_mgmt.deleted"), "info")
    return redirect(url_for("users.roles"))


def _save_user_photo():
    """Persist an uploaded avatar (already circle-cropped client-side) into
    static/uploads/users; returns the stored filename or None."""
    import os
    import uuid

    from flask import current_app
    from werkzeug.utils import secure_filename

    file = request.files.get("photo")
    if not file or not file.filename:
        return None
    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in {"png", "jpg", "jpeg", "webp"}:
        return None
    path = os.path.join(current_app.static_folder, "uploads", "users")
    os.makedirs(path, exist_ok=True)
    name = f"{uuid.uuid4().hex}.{ext}"
    file.save(os.path.join(path, secure_filename(name)))
    return name


@users_bp.route("/new", methods=["GET", "POST"])
@admin_required
def create():
    if request.method == "POST":
        form = _read_form()
        error = _validate(form, existing=None)
        if error:
            flash(error, "danger")
            return render_template(
                "users/form.html", roles=_roles(), user=None, form=form
            )

        user = User(
            username=form["username"],
            full_name=form["full_name"],
            full_name_en=form["full_name_en"],
            role=form["role"],
            email=form["email"],
            phone=form["phone"],
            is_active=form["is_active"],
            is_practitioner=form["is_practitioner"],
            # Doctors default to an English UI; others follow the program default.
            language=form["language"] or ("en" if form["role"] == "doctor" else None),
        )
        user.set_password(form["password"])
        photo = _save_user_photo()
        if photo:
            user.photo = photo
        db.session.add(user)
        db.session.flush()
        ActivityLog.record(
            "user.create", user_id=current_user.id, entity="user",
            entity_id=user.id, detail=user.username, ip_address=client_ip(),
        )
        db.session.commit()
        flash(t("users.created"), "success")
        return redirect(url_for("users.index"))

    return render_template("users/form.html", roles=_roles(), user=None, form={})


@users_bp.route("/<int:user_id>/edit", methods=["GET", "POST"])
@admin_required
def edit(user_id):
    user = db.get_or_404(User, user_id)

    if request.method == "POST":
        form = _read_form()
        error = _validate(form, existing=user)
        if error:
            flash(error, "danger")
            return render_template(
                "users/form.html", roles=_roles(), user=user, form=form
            )

        user.username = form["username"]
        user.full_name = form["full_name"]
        user.full_name_en = form["full_name_en"]
        user.role = form["role"]
        user.email = form["email"]
        user.phone = form["phone"]
        user.is_active = form["is_active"]
        user.is_practitioner = form["is_practitioner"]
        user.language = form["language"] or None
        if form["password"]:
            user.set_password(form["password"])
        photo = _save_user_photo()
        if photo:
            user.photo = photo

        ActivityLog.record(
            "user.update", user_id=current_user.id, entity="user",
            entity_id=user.id, detail=user.username, ip_address=client_ip(),
        )
        db.session.commit()
        flash(t("users.updated"), "success")
        return redirect(url_for("users.index"))

    form = {
        "username": user.username,
        "full_name": user.full_name,
        "full_name_en": user.full_name_en or "",
        "role": user.role,
        "email": user.email or "",
        "phone": user.phone or "",
        "is_active": user.is_active,
        "is_practitioner": user.is_practitioner,
        "language": user.language or "",
        "password": "",
    }
    return render_template("users/form.html", roles=_roles(), user=user, form=form)


@users_bp.route("/<int:user_id>/delete", methods=["POST"])
@admin_required
def delete(user_id):
    user = db.get_or_404(User, user_id)
    if user.id == current_user.id:
        flash(t("users.cannot_delete_self"), "warning")
        return redirect(url_for("users.index"))

    username = user.username
    db.session.delete(user)
    ActivityLog.record(
        "user.delete", user_id=current_user.id, entity="user",
        entity_id=user_id, detail=username, ip_address=client_ip(),
    )
    db.session.commit()
    flash(t("users.deleted"), "info")
    return redirect(url_for("users.index"))


# --- doctors management ----------------------------------------------------
# One place per doctor: professional identity (titles / specialty / licence)
# plus their per-service pricing & commission — the doctor-centric inverse of
# the finance "per-service, all doctors" screen.
@users_bp.route("/doctors")
@admin_required
def doctors():
    from app.utils.feedback import doctor_ratings

    docs = User.query.filter_by(role="doctor").order_by(User.full_name).all()
    return render_template("users/doctors.html", doctors=docs,
                           ratings=doctor_ratings())


@users_bp.route("/doctors/<int:user_id>")
@admin_required
def doctor_manage(user_id):
    from app.blueprints.main.routes import PROFESSIONAL_TITLES
    from app.models import COMMISSION_TYPES, DoctorServiceCommission, Service

    doc = db.get_or_404(User, user_id)
    services = Service.query.filter_by(is_active=True).order_by(Service.name).all()
    overrides = {oc.service_id: oc
                 for oc in DoctorServiceCommission.query.filter_by(doctor_id=doc.id).all()}
    return render_template("users/doctor_manage.html", doc=doc, services=services,
                           overrides=overrides, titles=PROFESSIONAL_TITLES,
                           commission_types=COMMISSION_TYPES)


@users_bp.route("/doctors/<int:user_id>/professional", methods=["POST"])
@admin_required
def doctor_professional(user_id):
    from app.blueprints.main.routes import PROFESSIONAL_TITLES

    doc = db.get_or_404(User, user_id)
    f = request.form
    doc.rx_display_name = (f.get("rx_display_name") or "").strip() or None
    title = (f.get("professional_title") or "").strip()
    doc.professional_title = title if title in PROFESSIONAL_TITLES else None
    doc.specialty = (f.get("specialty") or "").strip() or None
    doc.sub_specialties = (f.get("sub_specialties") or "").strip() or None
    doc.license_no = (f.get("license_no") or "").strip() or None
    doc.print_title_ar = (f.get("print_title_ar") or "").strip() or None
    doc.print_title_en = (f.get("print_title_en") or "").strip() or None
    ActivityLog.record("doctor.professional", user_id=current_user.id, entity="user",
                       entity_id=doc.id, detail=doc.username, ip_address=client_ip())
    db.session.commit()
    flash(t("doctors.saved"), "success")
    return redirect(url_for("users.doctor_manage", user_id=doc.id))


@users_bp.route("/doctors/<int:user_id>/pricing", methods=["POST"])
@admin_required
def doctor_pricing(user_id):
    from app.models import COMMISSION_TYPES, DoctorServiceCommission, Service

    doc = db.get_or_404(User, user_id)
    existing = {oc.service_id: oc
                for oc in DoctorServiceCommission.query.filter_by(doctor_id=doc.id).all()}
    for svc in Service.query.filter_by(is_active=True).all():
        ctype = (request.form.get(f"type_{svc.id}") or "none").strip()
        if ctype not in COMMISSION_TYPES:
            ctype = "none"
        cval = request.form.get(f"value_{svc.id}", type=float) or 0
        # Blank price = no override (service default); "0" = free for this doctor.
        raw_price = (request.form.get(f"price_{svc.id}") or "").strip()
        price = request.form.get(f"price_{svc.id}", type=float) if raw_price != "" else None

        oc = existing.get(svc.id)
        if ctype == "none" and price is None:
            if oc:
                db.session.delete(oc)
            continue
        if oc is None:
            oc = DoctorServiceCommission(doctor_id=doc.id, service_id=svc.id)
            db.session.add(oc)
        oc.commission_type, oc.commission_value = ctype, cval
        oc.price_override = price
    ActivityLog.record("doctor.pricing", user_id=current_user.id, entity="user",
                       entity_id=doc.id, detail=doc.username, ip_address=client_ip())
    db.session.commit()
    flash(t("doctors.pricing_saved"), "success")
    return redirect(url_for("users.doctor_manage", user_id=doc.id))


# --- helpers ---------------------------------------------------------------
def _read_form():
    return {
        "username": (request.form.get("username") or "").strip(),
        "full_name": (request.form.get("full_name") or "").strip(),
        "full_name_en": (request.form.get("full_name_en") or "").strip(),
        "role": (request.form.get("role") or "").strip(),
        "email": (request.form.get("email") or "").strip(),
        "phone": (request.form.get("phone") or "").strip(),
        "password": request.form.get("password") or "",
        "is_active": bool(request.form.get("is_active")),
        "is_practitioner": bool(request.form.get("is_practitioner")),
        "language": (request.form.get("language") or "").strip(),
    }


def _validate(form, existing):
    """Return an error message string, or None when the form is valid."""
    if not form["username"]:
        return t("common.required") + ": " + t("auth.username")
    if not form["full_name"]:
        return t("common.required") + ": " + t("users.full_name")
    if not User.valid_role(form["role"]):
        return t("common.required") + ": " + t("users.role")
    if existing is None and not form["password"]:
        return t("common.required") + ": " + t("auth.password")

    query = User.query.filter_by(username=form["username"])
    if existing is not None:
        query = query.filter(User.id != existing.id)
    if query.first() is not None:
        return t("users.username_taken")
    return None
