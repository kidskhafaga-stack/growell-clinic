"""Authentication routes: login, logout and language switching."""
from datetime import datetime, timedelta

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
from app.models import ActivityLog, Setting, User
from app.utils.decorators import client_ip
from app.utils.rate_limit import LOGIN_PER_MINUTE, limit


def _is_safe_next(target):
    """Only allow same-app relative redirects after login."""
    return bool(target) and target.startswith("/") and not target.startswith("//")


def _lockout_config():
    """(max_attempts, window_minutes) for the failed-login lockout; 0 attempts
    disables it. Defaults: 5 attempts / 15 minutes."""
    def _int(key, default):
        try:
            return max(0, int(Setting.get(key, str(default)) or default))
        except (TypeError, ValueError):
            return default
    return _int("login_max_attempts", 5), _int("login_lockout_minutes", 15)


def _recent_failures(username, minutes):
    """How many failed sign-ins this username has had within the window."""
    since = datetime.utcnow() - timedelta(minutes=minutes)
    return (ActivityLog.query
            .filter(ActivityLog.action == "login_failed",
                    ActivityLog.detail == username[:80],
                    ActivityLog.created_at >= since).count())


@auth_bp.route("/login", methods=["GET", "POST"])
# The lockout below counts failures per *username*, which does nothing about
# one machine trying a thousand different names — every one of them is on its
# first attempt. This counts the caller instead.
@limit("login", LOGIN_PER_MINUTE)
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        remember = bool(request.form.get("remember_me"))

        # Brute-force guard: after N failed attempts within the window, refuse
        # further tries (without touching the password) until it elapses.
        max_attempts, window = _lockout_config()
        if username and max_attempts and _recent_failures(username, window) >= max_attempts:
            ActivityLog.record(
                "login_locked", user_id=None, entity="user",
                detail=username[:80], ip_address=client_ip())
            db.session.commit()
            flash(t("auth.too_many_attempts").replace("{n}", str(window)), "danger")
            return render_template("auth/login.html"), 429

        user = User.query.filter_by(username=username).first()

        if user is None or not user.check_password(password):
            # Audit failed sign-ins (wrong user or password) so brute-force
            # attempts are visible — the username tried is kept, never the
            # password. Attributed to the user id when the name matched.
            ActivityLog.record(
                "login_failed", user_id=(user.id if user else None),
                entity="user", detail=username[:80], ip_address=client_ip(),
            )
            db.session.commit()
            flash(t("auth.invalid_credentials"), "danger")
            return render_template("auth/login.html"), 401

        if not user.is_active:
            ActivityLog.record(
                "login_disabled", user_id=user.id, entity="user",
                entity_id=user.id, detail=username[:80], ip_address=client_ip(),
            )
            db.session.commit()
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
