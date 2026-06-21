"""Main routes: landing redirect, dashboard, in-app guide and user profile."""
import os
import uuid

from flask import (
    current_app, flash, redirect, render_template, request, url_for,
)
from flask_login import current_user, login_required
from werkzeug.utils import secure_filename

from app.blueprints.main import main_bp
from app.extensions import db
from app.i18n import t
from app.models import ActivityLog

ALLOWED_IMG = {"png", "jpg", "jpeg", "webp", "svg", "gif"}
PROFESSIONAL_TITLES = ["Professor", "Consultant", "Specialist", "Lecturer",
                       "Resident", "GP"]
IMAGE_FIELDS = {"photo", "signature_file", "stamp_file", "personal_logo"}


@main_bp.route("/")
def index():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))
    return redirect(url_for("auth.login"))


# Age groups (upper bound in days, 365-day years) — see clinical reference.
AGE_GROUPS = [
    ("newborn", 30),       # 1st month of life: 0–30 days
    ("infant", 730),       # infant: 1 month – 2 years
    ("toddler", 1825),     # toddler: 2–5 years
    ("school", 4380),      # school age: 5–12 years
    ("adolescent", 6570),  # adolescent: 12–18 years
    ("over", None),        # over age: > 18 years
]


def _age_group(days):
    if days is None:
        return "over"
    for key, upper in AGE_GROUPS:
        if upper is None or days <= upper:
            return key
    return "over"


@main_bp.route("/dashboard")
@login_required
def dashboard():
    from app.models import Patient

    stats = None
    if current_user.can_access("patients"):
        patients = Patient.query.filter_by(is_active=True).all()
        groups = {key: 0 for key, _ in AGE_GROUPS}
        male = female = 0
        for p in patients:
            if p.gender == "male":
                male += 1
            elif p.gender == "female":
                female += 1
            groups[_age_group(p.age_days)] += 1
        stats = {"total": len(patients), "male": male, "female": female,
                 "groups": groups}
    return render_template("main/dashboard.html", stats=stats,
                           age_groups=[k for k, _ in AGE_GROUPS])


@main_bp.route("/guide")
@login_required
def guide():
    """In-app user guide (available to every signed-in user)."""
    return render_template("main/guide.html")


def _users_dir():
    path = os.path.join(current_app.static_folder, "uploads", "users")
    os.makedirs(path, exist_ok=True)
    return path


def _save_image(field):
    file = request.files.get(field)
    if not file or not file.filename:
        return None
    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in ALLOWED_IMG:
        return None
    name = f"{uuid.uuid4().hex}.{ext}"
    file.save(os.path.join(_users_dir(), secure_filename(name)))
    return name


def _remove_image(name):
    if not name:
        return
    path = os.path.join(_users_dir(), name)
    if os.path.isfile(path):
        try:
            os.remove(path)
        except OSError:
            pass


@main_bp.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    u = current_user
    if request.method == "POST":
        u.full_name = (request.form.get("full_name") or u.full_name).strip()
        u.full_name_en = (request.form.get("full_name_en") or "").strip() or None
        u.phone = (request.form.get("phone") or "").strip() or None
        u.email = (request.form.get("email") or "").strip() or None
        u.job_title = (request.form.get("job_title") or "").strip() or None
        u.branch = (request.form.get("branch") or "").strip() or None
        u.accent_color = (request.form.get("accent_color") or "").strip() or None

        # UI personalization.
        u.theme = "dark" if request.form.get("theme") == "dark" else "light"
        scale = (request.form.get("font_scale") or "md").strip()
        u.font_scale = scale if scale in ("sm", "md", "lg") else "md"
        landing = (request.form.get("default_landing") or "").strip()
        u.default_landing = landing if landing and u.can_access(landing) else None

        if u.role == "doctor":
            u.rx_display_name = (request.form.get("rx_display_name") or "").strip() or None
            title = (request.form.get("professional_title") or "").strip()
            u.professional_title = title if title in PROFESSIONAL_TITLES else None
            u.specialty = (request.form.get("specialty") or "").strip() or None
            u.sub_specialties = (request.form.get("sub_specialties") or "").strip() or None
            u.license_no = (request.form.get("license_no") or "").strip() or None
            u.rx_template_id = request.form.get("rx_template_id", type=int) or None

        for field in IMAGE_FIELDS:
            saved = _save_image(field)
            if saved:
                _remove_image(getattr(u, field))
                setattr(u, field, saved)

        new_pw = request.form.get("password") or ""
        if new_pw:
            u.set_password(new_pw)

        ActivityLog.record("profile.update", user_id=u.id, entity="user",
                           entity_id=u.id, detail=u.username)
        db.session.commit()
        flash(t("profile.saved"), "success")
        return redirect(url_for("main.profile"))

    from app.models import RxPrintTemplate
    templates = (RxPrintTemplate.query.order_by(RxPrintTemplate.name).all()
                 if u.role == "doctor" else [])
    return render_template("main/profile.html", titles=PROFESSIONAL_TITLES,
                           rx_templates=templates)


@main_bp.route("/profile/image/<field>/delete", methods=["POST"])
@login_required
def profile_image_delete(field):
    if field in IMAGE_FIELDS:
        _remove_image(getattr(current_user, field))
        setattr(current_user, field, None)
        db.session.commit()
        flash(t("profile.image_removed"), "info")
    return redirect(url_for("main.profile"))
