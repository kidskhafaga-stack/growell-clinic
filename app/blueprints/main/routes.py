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


@main_bp.route("/healthz")
def healthz():
    """Is this program actually answering? — for the watchdog on the server.

    Restarting a crashed process is the easy half. A program that is *running*
    and not answering — a locked database, a thread pool with nothing left —
    looks identical to a healthy one from outside, and it is the half a clinic
    actually meets: the server is up, the icon is there, and nobody can book a
    patient.

    So this touches the database. A route that only proves Python is alive
    would answer happily through exactly the failure it exists to catch.

    Deliberately open, and deliberately dull: a status, a version, and nothing
    that names the clinic or counts its patients. A watchdog cannot log in,
    and a health check that needs a session is one that reports "unhealthy"
    every time somebody's cookie expires.
    """
    from flask import jsonify

    from app.utils.version import APP_VERSION

    try:
        db.session.execute(db.text("SELECT 1")).scalar()
    except Exception as exc:  # noqa: BLE001 — any failure here is the answer
        current_app.logger.warning("health check failed: %s", exc)
        return jsonify({"status": "error", "database": False}), 503
    return jsonify({"status": "ok", "database": True, "version": APP_VERSION})


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


def _greeting_key(hour):
    """Time-of-day greeting bucket (local server time)."""
    if hour < 12:
        return "morning"
    if hour < 17:
        return "afternoon"
    return "evening"


def _doctor_home(user):
    """Live queue snapshot for a doctor's personalised home panel: today's
    waiting / in-progress / scheduled patients for this doctor, ordered by time,
    plus counts and the patient currently in the room. Cheap — one indexed query
    over today's appointments for this doctor."""
    from datetime import datetime as _dt

    from app.models import Appointment

    today = _dt.now().date()
    appts = (Appointment.query
             .filter(Appointment.appt_date == today,
                     Appointment.doctor_id == user.id)
             .order_by(Appointment.appt_time)
             .all())
    counts = {
        "waiting": sum(1 for a in appts if a.status == "waiting"),
        "scheduled": sum(1 for a in appts if a.status == "scheduled"),
        "in_progress": sum(1 for a in appts if a.status == "in_progress"),
        "completed": sum(1 for a in appts if a.status == "completed"),
        "total": len(appts),
    }
    current = next((a for a in appts if a.status == "in_progress"), None)
    # The live queue: who is checked in and who is still expected (not the ones
    # already seen / cancelled / no-show), most-imminent first.
    queue = [a for a in appts if a.status in ("waiting", "scheduled")]
    return {"queue": queue, "current": current, "counts": counts, "date": today}


@main_bp.route("/dashboard")
@login_required
def dashboard():
    # Patient classification now lives on the dedicated analytics page
    # (patients.analytics), linked from here.
    from datetime import datetime as _dt

    from app.models import Setting

    ctx = {"greeting": _greeting_key(_dt.now().hour)}
    # A half-configured clinic should learn it here, not on the first busy
    # morning with a family at the desk. Admins only — a receptionist can do
    # nothing about a missing till, and a banner nobody can act on is noise.
    ctx["setup"] = None
    if current_user.is_admin:
        from app.utils.readiness import dismissed, summary

        state = summary()
        if not state["ready"] and not dismissed():
            ctx["setup"] = state
    # Whether bookings are paused is read for **everyone**, not only the doctor
    # who can flip it. It used to be set inside the doctor-home branch, so the
    # banner lived inside a card reception never sees: the doctor paused
    # booking, watched their own screen say so, and reception carried on with no
    # idea. The person the pause is aimed at was the one person not told.
    ctx["booking_open"] = Setting.get("clinic_booking_open", "1") != "0"
    # Doctors (and practitioners standing in as one) get a live home panel.
    if current_user.role == "doctor" or getattr(current_user, "is_practitioner", False):
        ctx["home"] = _doctor_home(current_user)
    return render_template("main/dashboard.html", **ctx)


@main_bp.route("/live/<kind>/<int:ident>")
@login_required
def live_fingerprint(kind, ident):
    """A short answer to "has this screen's data changed since I loaded it?".

    One endpoint for every screen that wants to know, because the alternative
    is a poll route per blueprint and a fingerprint that drifts out of step
    with what its screen actually shows.

    The kinds come from a fixed map, not from the URL: a name arriving here is
    looked up, never called. And it is behind the ordinary login — the answer
    is a hash, but *whether it changed* still tells you something about a
    patient, so it is not public.
    """
    from flask import abort, jsonify

    from app.utils.live import FINGERPRINTS

    build = FINGERPRINTS.get(kind)
    if build is None:
        abort(404)
    return jsonify({"fp": build(ident)})


@main_bp.route("/guide")
@login_required
def guide():
    """In-app user guide (available to every signed-in user)."""
    return render_template("main/guide.html")


@main_bp.route("/set-theme", methods=["POST"])
@login_required
def set_theme():
    """Persist the user's appearance preference: light / dark / system."""
    theme = (request.form.get("theme") or "").strip()
    if theme not in ("light", "dark", "system"):
        theme = "light"
    current_user.theme = theme
    db.session.commit()
    return {"theme": theme}


@main_bp.route("/about")
@login_required
def about():
    """Version, licence and credits — the detail that used to be printed in
    0.64rem type down the side of every screen."""
    return render_template("main/about.html")


@main_bp.route("/set-sidebar", methods=["POST"])
@login_required
def set_sidebar():
    """Persist whether the sidebar is full-width or an icon rail."""
    mode = (request.form.get("sidebar") or "").strip()
    current_user.sidebar = "rail" if mode == "rail" else "full"
    db.session.commit()
    return {"sidebar": current_user.sidebar}


@main_bp.route("/notifications/dismiss", methods=["POST"])
@login_required
def notif_dismiss():
    """Mark a bell alert as seen so it drops from the count (click-to-dismiss)."""
    from app.utils import notifications

    key = (request.form.get("key") or "").strip()
    if key:
        notifications.dismiss(current_user, key)
    return {"ok": True, "key": key}


@main_bp.route("/notifications/dismiss-all", methods=["POST"])
@login_required
def notif_dismiss_all():
    """Mark every current bell alert as seen so the bell clears."""
    from app.utils import notifications

    notifications.dismiss_all(current_user)
    return {"ok": True}


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
            u.print_title_ar = (request.form.get("print_title_ar") or "").strip() or None
            u.print_title_en = (request.form.get("print_title_en") or "").strip() or None
            u.license_no = (request.form.get("license_no") or "").strip() or None
            u.rx_template_id = request.form.get("rx_template_id", type=int) or None
            # Their own quick phrases are edited on their own screen
            # (``visits.phrases_screen``) and deliberately not written here:
            # this form does not post them, and a blank read as "clear it"
            # would wipe a doctor's list every time they changed their photo.

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
