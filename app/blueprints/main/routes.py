"""Main routes: landing redirect and the role-aware dashboard."""
from flask import redirect, render_template, url_for
from flask_login import current_user, login_required

from app.blueprints.main import main_bp


@main_bp.route("/")
def index():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))
    return redirect(url_for("auth.login"))


@main_bp.route("/dashboard")
@login_required
def dashboard():
    return render_template("main/dashboard.html")
