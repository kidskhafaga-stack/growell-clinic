"""User management (admin only) — create, edit, enable/disable and delete."""
from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user

from app.blueprints.users import users_bp
from app.extensions import db
from app.i18n import t
from app.models import ActivityLog, User
from app.models.permissions import ROLES
from app.utils.decorators import admin_required, client_ip


@users_bp.route("/")
@admin_required
def index():
    users = User.query.order_by(User.created_at.desc()).all()
    return render_template("users/list.html", users=users, roles=ROLES)


@users_bp.route("/new", methods=["GET", "POST"])
@admin_required
def create():
    if request.method == "POST":
        form = _read_form()
        error = _validate(form, existing=None)
        if error:
            flash(error, "danger")
            return render_template(
                "users/form.html", roles=ROLES, user=None, form=form
            )

        user = User(
            username=form["username"],
            full_name=form["full_name"],
            full_name_en=form["full_name_en"],
            role=form["role"],
            email=form["email"],
            phone=form["phone"],
            is_active=form["is_active"],
        )
        user.set_password(form["password"])
        db.session.add(user)
        db.session.flush()
        ActivityLog.record(
            "user.create", user_id=current_user.id, entity="user",
            entity_id=user.id, detail=user.username, ip_address=client_ip(),
        )
        db.session.commit()
        flash(t("users.created"), "success")
        return redirect(url_for("users.index"))

    return render_template("users/form.html", roles=ROLES, user=None, form={})


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
                "users/form.html", roles=ROLES, user=user, form=form
            )

        user.username = form["username"]
        user.full_name = form["full_name"]
        user.full_name_en = form["full_name_en"]
        user.role = form["role"]
        user.email = form["email"]
        user.phone = form["phone"]
        user.is_active = form["is_active"]
        if form["password"]:
            user.set_password(form["password"])

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
        "password": "",
    }
    return render_template("users/form.html", roles=ROLES, user=user, form=form)


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
