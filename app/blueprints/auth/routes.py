"""Authentication routes: login, logout and language switching."""
from datetime import datetime

from flask import (
    flash,
    redirect,
    request,
    render_template,
    session,
    url_for,
)
from werkzeug.routing import BuildError
from flask_login import current_user, login_required, login_user, logout_user

from app.blueprints.auth import auth_bp
from app.extensions import db
from app.i18n import set_locale, t
from app.models import ActivityLog, User
from app.utils.decorators import client_ip


def _is_safe_next(target):
    """Only allow same-app relative redirects after login."""
    return bool(target) and target.startswith("/") and not target.startswith("//")


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        remember = bool(request.form.get("remember_me"))

        user = User.query.filter_by(username=username).first()

        if user is None or not user.check_password(password):
            flash(t("auth.invalid_credentials"), "danger")
            return render_template("auth/login.html"), 401

        if not user.is_active:
            flash(t("auth.account_disabled"), "warning")
            return render_template("auth/login.html"), 403

        login_user(user, remember=remember)
        # Apply the user's preferred UI language (doctors default to English).
        if user.language:
            set_locale(user.language)
        user.last_login_at = datetime.utcnow()
        ActivityLog.record(
            "login", user_id=user.id, entity="user", entity_id=user.id,
            ip_address=client_ip(),
        )
        db.session.commit()

        flash(t("auth.welcome_back", name=user.display_name(session.get("lang", "ar"))), "success")

        next_page = request.args.get("next")
        if _is_safe_next(next_page):
            return redirect(next_page)
        # Honour the user's preferred landing page, if set and accessible.
        landing = user.default_landing
        if landing and user.can_access(landing):
            try:
                ep = "main.dashboard" if landing == "dashboard" else f"{landing}.index"
                return redirect(url_for(ep))
            except BuildError:
                pass
        return redirect(url_for("main.dashboard"))

    return render_template("auth/login.html")


@auth_bp.route("/logout")
@login_required
def logout():
    ActivityLog.record(
        "logout", user_id=current_user.id, entity="user",
        entity_id=current_user.id, ip_address=client_ip(),
    )
    db.session.commit()
    logout_user()
    flash(t("auth.logged_out"), "info")
    return redirect(url_for("auth.login"))


@auth_bp.route("/lang/<lang>")
def set_language(lang):
    """Switch UI language and return to the referring page."""
    set_locale(lang)
    target = request.referrer
    if target and target.startswith(request.host_url):
        return redirect(target)
    return redirect(url_for("main.dashboard"))
