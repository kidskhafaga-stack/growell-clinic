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
from app.utils.paging import paginate


def _titles():
    from app.blueprints.main.routes import PROFESSIONAL_TITLES

    return PROFESSIONAL_TITLES


def _roles():
    """Editable roles for dropdowns (ordered: system first, then custom)."""
    return Role.query.order_by(Role.is_system.desc(), Role.name).all()


def _owner_count(exclude=None):
    """How many institution owners exist (optionally excluding one user)."""
    q = User.query.filter_by(is_super_admin=True)
    if exclude is not None:
        q = q.filter(User.id != exclude)
    return q.count()


def _last_login_ip_map(user_ids):
    """{user_id: last login IP} from the audit log (one query, no N+1)."""
    if not user_ids:
        return {}
    rows = (db.session.query(
                ActivityLog.user_id, ActivityLog.ip_address,
                db.func.max(ActivityLog.created_at))
            .filter(ActivityLog.action == "login",
                    ActivityLog.user_id.in_(user_ids))
            .group_by(ActivityLog.user_id).all())
    return {uid: ip for uid, ip, _ in rows}


@users_bp.route("/")
@admin_required
def index():
    users = User.query.order_by(User.created_at.desc()).all()
    last_ip = _last_login_ip_map([u.id for u in users])
    return render_template("users/list.html", users=users, roles=_roles(),
                           last_ip=last_ip)


# ----------------------------------------------------------- audit ---------
# Security-relevant actions worth surfacing as their own filter in the log.
AUDIT_ACTIONS = ["login", "login_failed", "login_disabled", "logout",
                 "user.create", "user.update", "user.delete",
                 "role.create", "role.update", "role.delete",
                 "user.capability_grant", "user.capability_revoke",
                 "patient.archive", "patient.restore", "patient.delete",
                 "appointment.booking_toggle"]


@users_bp.route("/audit")
@admin_required
def audit():
    """Security & activity audit trail: who did what, when and from where.
    Filterable by user and action; failed sign-ins are highlighted."""
    action = (request.args.get("action") or "").strip()
    user_id = request.args.get("user_id", type=int)
    q = ActivityLog.query
    if action:
        q = q.filter(ActivityLog.action == action)
    if user_id:
        q = q.filter(ActivityLog.user_id == user_id)
    pagination = paginate(q.order_by(ActivityLog.created_at.desc()), default=50)
    # Failed sign-ins in the last 24h — a quick brute-force signal.
    from datetime import datetime, timedelta
    since = datetime.utcnow() - timedelta(hours=24)
    failed_24h = (ActivityLog.query
                  .filter(ActivityLog.action == "login_failed",
                          ActivityLog.created_at >= since).count())
    return render_template(
        "users/audit.html", entries=pagination.items, pagination=pagination,
        users=User.query.order_by(User.full_name).all(),
        actions=AUDIT_ACTIONS, action=action, user_id=user_id,
        failed_24h=failed_24h)


# ----------------------------------------------------------- roles ---------
@users_bp.route("/roles")
@admin_required
def roles():
    return render_template("users/roles.html", roles=_roles(), modules=MODULES)


@users_bp.route("/permissions")
@admin_required
def permissions():
    """Every role against every module and sensitive capability, on one screen.

    It was read-only, and told the reader to go to role management to change
    anything — a screen showing somebody exactly what they want to change and
    sending them somewhere else to change it. The module grid is editable here
    now; role management keeps what only it can do (creating, naming and
    deleting roles), so "who reaches what" still has exactly one editor.
    """
    from app.models.permissions import (
        CAPABILITIES, MODULE_ICONS, role_capabilities,
    )

    roles = _roles()
    access = {m: {r.id: (m in r.module_list) for r in roles} for m in MODULES}
    caps = {c: {r.id: (r.is_admin or c in role_capabilities(r.name)) for r in roles}
            for c in CAPABILITIES}
    counts = dict(db.session.query(User.role, db.func.count())
                  .group_by(User.role).all())
    return render_template(
        "users/permissions.html", roles=roles, modules=MODULES,
        module_icons=MODULE_ICONS, access=access,
        capabilities=CAPABILITIES, caps=caps, user_counts=counts)


@users_bp.route("/permissions", methods=["POST"])
@admin_required
def permissions_save():
    """Save the whole matrix in one press.

    Read as "every box that is ticked", not as a diff: a checkbox that is off
    sends nothing at all, so anything absent from the form is absent from the
    role. That is only safe because the form draws every module for every
    role — which it does, and the test below holds it, since a partially
    rendered form would silently strip access nobody chose to remove.

    Admin roles are skipped rather than read. Their boxes are not rendered, so
    reading them would strip every module from the one role that must keep
    them, on the first save.
    """
    changed = 0
    for role in _roles():
        if role.is_admin:
            continue
        # Only roles this form actually drew. An unchecked box sends nothing,
        # so without the marker a POST that omitted a role would read as
        # "this role now reaches nothing" and empty it — found by a test that
        # posted one role's boxes and watched another role lose everything.
        if not request.form.get(f"role_present_{role.id}"):
            continue
        wanted = [m for m in MODULES if request.form.get(f"mod_{role.id}_{m}")]
        if sorted(wanted) != sorted(role.module_list):
            role.set_modules(wanted)
            changed += 1
            ActivityLog.record("role.update", user_id=current_user.id,
                               entity="role", entity_id=role.id,
                               detail=role.name, ip_address=client_ip())
    db.session.commit()
    flash(t("perms.saved", n=changed) if changed else t("perms.no_change"),
          "success" if changed else "info")
    return redirect(url_for("users.permissions"))


@users_bp.route("/<int:user_id>/capabilities", methods=["POST"])
@admin_required
def capability_grant(user_id):
    """Allow one person one thing their role is not.

    Admin only. A capability that can be handed out by anybody who already has
    it spreads until the matrix on the permissions screen stops describing the
    clinic.
    """
    from app.models import UserCapability
    from app.models.permissions import CAPABILITIES

    user = db.get_or_404(User, user_id)
    capability = (request.form.get("capability") or "").strip()
    if capability not in CAPABILITIES:
        flash(t("perms.unknown_capability"), "danger")
        return redirect(url_for("users.edit", user_id=user.id) + "#caps")

    existing = UserCapability.query.filter_by(
        user_id=user.id, capability=capability).first()
    if existing is None:
        db.session.add(UserCapability(
            user_id=user.id, capability=capability,
            reason=(request.form.get("reason") or "").strip() or None,
            granted_by=current_user.id))
        ActivityLog.record("user.capability_grant", user_id=current_user.id,
                           entity="user", entity_id=user.id,
                           detail=capability, ip_address=client_ip())
        db.session.commit()
        flash(t("perms.granted"), "success")
    return redirect(url_for("users.edit", user_id=user.id) + "#caps")


@users_bp.route("/capabilities/<int:grant_id>/revoke", methods=["POST"])
@admin_required
def capability_revoke(grant_id):
    """Take the exception back. The role underneath is untouched."""
    from app.models import UserCapability

    row = db.get_or_404(UserCapability, grant_id)
    user_id, capability = row.user_id, row.capability
    db.session.delete(row)
    ActivityLog.record("user.capability_revoke", user_id=current_user.id,
                       entity="user", entity_id=user_id,
                       detail=capability, ip_address=client_ip())
    db.session.commit()
    flash(t("perms.revoked"), "info")
    return redirect(url_for("users.edit", user_id=user_id) + "#caps")


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
            return render_template("users/form.html", roles=_roles(),
                                   user=None, form=form, titles=_titles())

        user = User(
            username=form["username"],
            full_name=form["full_name"],
            full_name_en=form["full_name_en"],
            role=form["role"],
            email=form["email"],
            phone=form["phone"],
            is_active=form["is_active"],
            is_practitioner=form["is_practitioner"],
            # Only an existing owner may mint another owner (super-admin).
            is_super_admin=form["is_super_admin"] and current_user.is_owner,
            # Doctors default to an English UI; others follow the program default.
            # No language forced on anybody. A doctor used to be created as
            # "en" whatever the clinic runs in, so they signed in to an
            # English interface wrapped around Arabic names, Arabic
            # complaints and Arabic drug notes — "عربي على إنجليزي". The
            # field is still theirs to set, here or from their own profile.
            language=form["language"] or None,
        )
        user.set_password(form["password"])
        _apply_profile(user, form)
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

    return render_template("users/form.html", roles=_roles(), user=None,
                           form={}, titles=_titles())


@users_bp.route("/<int:user_id>/edit", methods=["GET", "POST"])
@admin_required
def edit(user_id):
    user = db.get_or_404(User, user_id)

    if request.method == "POST":
        form = _read_form()
        error = _validate(form, existing=user)
        if error:
            flash(error, "danger")
            return render_template("users/form.html", roles=_roles(),
                                   user=user, form=form, titles=_titles())

        user.username = form["username"]
        user.full_name = form["full_name"]
        user.full_name_en = form["full_name_en"]
        user.role = form["role"]
        user.email = form["email"]
        user.phone = form["phone"]
        user.is_active = form["is_active"]
        user.is_practitioner = form["is_practitioner"]
        user.language = form["language"] or None
        # Only owners may change owner status, and never remove the last owner.
        if current_user.is_owner:
            new_owner = form["is_super_admin"]
            if user.is_super_admin and not new_owner and _owner_count(exclude=user.id) == 0:
                flash(t("owner.last_owner"), "warning")
            else:
                user.is_super_admin = new_owner
        if form["password"]:
            user.set_password(form["password"])
        _apply_profile(user, form)
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
        "is_super_admin": user.is_super_admin,
        "language": user.language or "",
        "password": "",
    }
    for field in PROFILE_FIELDS + PRACTITIONER_FIELDS:
        form[field] = getattr(user, field, None) or ""
    from app.models import UserCapability
    from app.models.permissions import CAPABILITIES, role_capabilities

    grants = UserCapability.query.filter_by(user_id=user.id).all()
    # Only capabilities the role does not already carry are offered. Granting
    # somebody something they already have would read as a decision on the
    # screen forever, and mean nothing.
    from_role = set(role_capabilities(user.role))
    return render_template("users/form.html", roles=_roles(), user=user,
                           form=form, titles=_titles(),
                           grants=grants, role_capabilities=from_role,
                           grantable=[c for c in CAPABILITIES
                                      if c not in from_role
                                      and c not in {g.capability for g in grants}])


@users_bp.route("/<int:user_id>/delete", methods=["POST"])
@admin_required
def delete(user_id):
    user = db.get_or_404(User, user_id)
    if user.id == current_user.id:
        flash(t("users.cannot_delete_self"), "warning")
        return redirect(url_for("users.index"))
    # Owners are protected: only another owner may remove one, and never the
    # last one standing.
    if user.is_super_admin:
        if not current_user.is_owner:
            flash(t("owner.only_owner_removes"), "warning")
            return redirect(url_for("users.index"))
        if _owner_count(exclude=user.id) == 0:
            flash(t("owner.last_owner"), "warning")
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
    from datetime import date, timedelta

    from app.utils.feedback import doctor_ratings
    from app.utils.waiting import clinic_start, doctor_timings

    docs = User.query.filter_by(role="doctor").order_by(User.full_name).all()
    # A month, because a week of a paediatric clinic is mostly whichever virus
    # was going round — and the numbers below are medians, which need enough
    # consultations under them to mean anything.
    until = date.today()
    since = until - timedelta(days=30)
    return render_template("users/doctors.html", doctors=docs,
                           ratings=doctor_ratings(),
                           timings=doctor_timings(since, until),
                           starts=clinic_start(since, until),
                           since=since, until=until)


@users_bp.route("/doctors/<int:user_id>")
@admin_required
def doctor_manage(user_id):
    from app.blueprints.main.routes import PROFESSIONAL_TITLES
    from app.models import COMMISSION_TYPES, DoctorServiceCommission, Service

    from app.models import RxPrintTemplate

    doc = db.get_or_404(User, user_id)
    services = Service.query.filter_by(is_active=True).order_by(Service.name).all()
    overrides = {oc.service_id: oc
                 for oc in DoctorServiceCommission.query.filter_by(doctor_id=doc.id).all()}
    return render_template("users/doctor_manage.html", doc=doc, services=services,
                           overrides=overrides, titles=PROFESSIONAL_TITLES,
                           commission_types=COMMISSION_TYPES,
                           rx_templates=(RxPrintTemplate.query
                                         .order_by(RxPrintTemplate.name).all()))


@users_bp.route("/doctors/<int:user_id>/rx", methods=["POST"])
@admin_required
def doctor_rx(user_id):
    """The paper this doctor's prescriptions come out on.

    It was already a per-doctor setting in the database and already had a
    picker — on the doctor's *own* profile page, which only the doctor can
    reach. So the person who sets the clinic up could enter a doctor's name,
    licence and stamp and then not say which layout to print them with; that
    last step needed the doctor's password. The layouts themselves are drawn
    on the templates screen, which stays one screen for the whole clinic
    because a layout is a piece of paper and clinics buy one kind.
    """
    from app.models import RxPrintTemplate

    doc = db.get_or_404(User, user_id)
    chosen = request.form.get("rx_template_id", type=int)
    # A template id from a stale form (someone deleted the layout meanwhile)
    # must not become a dangling reference that prints nothing.
    doc.rx_template_id = (chosen if chosen
                          and db.session.get(RxPrintTemplate, chosen) else None)
    from app.blueprints.main.routes import _save_image
    for field in RX_IMAGE_FIELDS:
        saved = _save_image(field)
        if saved:
            setattr(doc, field, saved)
    ActivityLog.record("doctor.rx_setup", user_id=current_user.id, entity="user",
                       entity_id=doc.id, detail=doc.username, ip_address=client_ip())
    db.session.commit()
    flash(t("doctors.saved"), "success")
    return redirect(url_for("users.doctor_manage", user_id=doc.id))


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

        provides = bool(request.form.get(f"provides_{svc.id}"))

        oc = existing.get(svc.id)
        # The row is deleted only when it would say nothing at all. Ticking
        # "performs this" at the clinic's own price sets no commission and no
        # price override, so the old condition threw the tick away on save and
        # the mark would never have survived the redirect.
        if ctype == "none" and price is None and not provides:
            if oc:
                db.session.delete(oc)
            continue
        if oc is None:
            oc = DoctorServiceCommission(doctor_id=doc.id, service_id=svc.id)
            db.session.add(oc)
        oc.commission_type, oc.commission_value = ctype, cval
        oc.price_override = price
        oc.provides = provides
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
        "is_super_admin": bool(request.form.get("is_super_admin")),
        "language": (request.form.get("language") or "").strip(),
        # Profile fields. These used to exist only on the person's own profile
        # page, so an admin could create a doctor and the clinic still knew
        # nothing about them until that doctor logged in and filled it in
        # themselves — which nobody does before their first shift.
        "job_title": (request.form.get("job_title") or "").strip(),
        "branch": (request.form.get("branch") or "").strip(),
        "rx_display_name": (request.form.get("rx_display_name") or "").strip(),
        "professional_title": (request.form.get("professional_title") or "").strip(),
        "specialty": (request.form.get("specialty") or "").strip(),
        "sub_specialties": (request.form.get("sub_specialties") or "").strip(),
        "license_no": (request.form.get("license_no") or "").strip(),
    }


# The profile fields an admin can now fill in from the user screen. Doctor
# identity (what gets printed on a prescription) only applies to someone who
# actually sees patients.
PROFILE_FIELDS = ["job_title", "branch"]
PRACTITIONER_FIELDS = ["rx_display_name", "professional_title", "specialty",
                       "sub_specialties", "license_no"]


# Signature, stamp and personal logo: the pictures a prescription prints. The
# admin has them in hand when the doctor joins — waiting for the doctor to
# upload their own stamp is how a clinic ends up printing without one.
RX_IMAGE_FIELDS = ["signature_file", "stamp_file", "personal_logo"]


def _apply_profile(user, form):
    """Copy the profile part of the form onto the user."""
    from app.blueprints.main.routes import PROFESSIONAL_TITLES, _save_image

    for field in PROFILE_FIELDS:
        setattr(user, field, form.get(field) or None)
    sees_patients = user.role == "doctor" or user.is_practitioner
    for field in PRACTITIONER_FIELDS:
        if not sees_patients:
            continue
        value = form.get(field) or None
        if field == "professional_title" and value not in PROFESSIONAL_TITLES:
            value = None
        setattr(user, field, value)
    if sees_patients:
        for field in RX_IMAGE_FIELDS:
            saved = _save_image(field)
            if saved:
                setattr(user, field, saved)


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
