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
from app.models.user import clamp_print_scale
from app.utils.decorators import admin_required

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


def _clinic_now(user):
    """What the whole clinic is doing, for whoever runs it.

    **The gap this closes.** `_doctor_home` is pinned to
    ``doctor_id == user.id``, which is right for a doctor and wrong for the
    one who owns the place: a doctor holding full admin saw the same four
    numbers and the same single queue as the newest locum, and nothing on the
    dashboard said what the clinic was doing. The whole-clinic view already
    existed — it is what the board draws when no doctor is picked — so this
    reaches for that rather than growing a second version of it.

    Two audiences, and they are not the same person twice. A doctor who runs
    the clinic gets this **as well as** their own queue, because they are
    still seeing patients. An admin who is not a practitioner gets only this,
    and used to get nothing at all: the condition on the dashboard panel asked
    whether you were a doctor, so the manager of a four-doctor clinic opened
    the program to a screen that told them nothing about it.

    Returns ``None`` for anybody who is not an admin, so the caller does not
    have to know the rule twice.
    """
    from app.models import Appointment
    from app.utils.clinic_now import _clinics_now, _red_flags
    from app.utils.clock import local_today

    if not getattr(user, "is_admin", False):
        return None
    if not user.can_access("appointments"):
        return None

    today = local_today()
    appts = (Appointment.query
             .filter(Appointment.appt_date == today)
             .order_by(Appointment.appt_time).all())
    flags = _red_flags(appts)
    live = [a for a in appts if a.status not in ("cancelled", "no_show")]
    return {
        "clinics": _clinics_now(appts, today, flags),
        "counts": {
            "waiting": sum(1 for a in live if a.status in ("waiting", "scheduled")),
            "in_progress": sum(1 for a in live if a.status == "in_progress"),
            "completed": sum(1 for a in live if a.status == "completed"),
            "total": len(live),
            # Counted rather than inferred from the cards: a doctor with an
            # empty day has no card, and "how many doctors are in today" is
            # not the same question as "how many cards are on the screen".
            "doctors": len({a.doctor_id for a in live if a.doctor_id}),
        },
        # The children nobody should be leaving in a waiting room. Reception
        # watches this on the board; the person running the clinic has had no
        # way to see it without going and looking.
        "urgent": sum(1 for f in flags.values() if f.get("level") == "urgent"),
        "date": today,
    }


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
    # Doctors (and practitioners standing in as one) get a live home panel of
    # their own queue. Whoever runs the clinic also gets the clinic — the two
    # are separate questions and the same person often has both.
    if current_user.role == "doctor" or getattr(current_user, "is_practitioner", False):
        ctx["home"] = _doctor_home(current_user)
    ctx["clinic"] = _clinic_now(current_user)
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
    """The user guide, cut to what the signed-in user is allowed to do.

    It used to render the same page for everyone: admin, doctor and reception
    measured 4,193 / 4,114 / 4,075 characters — the difference was the name in
    the top bar. So a receptionist was taught the doctor's statement of account
    and how to write a prescription, neither of which opens for them, while the
    parts that *are* their job sat between the two.

    ``?all=1`` puts the rest back, clearly marked as outside your permissions,
    because "what would I be able to do as a doctor" is a fair question and
    hiding the answer only sends people to ask somebody.
    """
    from app.utils.facility import module_enabled
    from app.utils.handbook import CAPABILITY_LABELS, SECTIONS, sections_for

    from flask import g

    from app.models import Role

    show_all = request.args.get("all") == "1"
    role = Role.query.filter_by(name=current_user.role).first()
    lang = getattr(g, "lang", "ar")
    role_label = (role.label(lang) if role is not None
                  else t(f"roles.{current_user.role}"))
    mine = sections_for(current_user, module_enabled)
    mine_keys = {s["key"] for s in mine}
    sections = SECTIONS if show_all else mine
    return render_template(
        "main/guide.html",
        sections=sections,
        mine_keys=mine_keys,
        role_label=role_label,
        show_all=show_all,
        hidden_count=len(SECTIONS) - len(mine),
        my_modules=[m for m in current_user.modules if module_enabled(m)],
        my_capabilities=[(c, CAPABILITY_LABELS[c]) for c in CAPABILITY_LABELS
                         if current_user.can(c)],
    )


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


@main_bp.route("/doctor-search")
@login_required
def doctor_search():
    """JSON: the clinic's doctors, for every screen that has to pick one.

    The same list already existed behind ``prescriptions.doctor_search`` and
    exactly one screen used it — the prescription. Every other screen that
    asks "which doctor" (the schedules, the day board, the roster, the
    statements, the invoices, the discounts) still renders the whole list into
    a ``<select>``, which is fine at four doctors and is the screen at forty.

    It lives here rather than in ``prescriptions`` because reception needs it
    on the appointments board and has no prescriptions module — and a clinic
    can switch that module off entirely, which would take the doctor picker on
    unrelated screens with it.

    Nothing here is newly exposed: this is the same set of names those screens
    already render into their dropdowns for the same signed-in users. The
    screens keep their own module gates; this only answers the filter.

    An empty query returns everybody, because a clinic has a handful of
    doctors and making somebody guess the first two letters of a list that
    short is not searching, it is a hurdle.
    """
    from flask import g, jsonify

    from app.utils.appointments import list_doctors

    query = (request.args.get("q") or "").strip()
    lang = getattr(g, "lang", "ar")
    rows = list_doctors()
    if query:
        needle = query.lower()

        def matches(user):
            for field in (user.full_name, user.full_name_en,
                          user.rx_display_name, user.username, user.specialty):
                if field and needle in field.lower():
                    return True
            return False

        rows = [u for u in rows if matches(u)]
    return jsonify([
        {"id": u.id, "name": u.display_name(lang),
         "number": u.specialty or u.job_title or ""}
        for u in rows[:20]])


@main_bp.route("/about")
@login_required
def about():
    """What the program is, who made it, and what it does not do yet.

    It held three lines — name, version, licence. Everything else a person
    might reasonably ask lived in ``ROADMAP.md``, which nobody in a clinic is
    ever going to open.
    """
    from app.utils import project

    # Read once and handed to the template twice — the block a person copies
    # and the warning under it have to be talking about the same backup.
    support = project.support()

    return render_template(
        "main/about.html",
        summary=project.SUMMARY,
        principles=project.PRINCIPLES,
        people=project.people(),
        facts=project.facts(),
        support=support,
        staff=project.creditable_staff(),
        support_lines=project.support_lines(support),
        plan=[("done", "منجز وشغّال", "Done and running", project.DONE),
              ("building", "شغّال دلوقتي", "In progress", project.BUILDING),
              ("next", "الجاي", "Next", project.NEXT),
              ("deferred", "مؤجّل عن قصد", "Deliberately deferred",
               project.DEFERRED)],
    )


@main_bp.route("/about/people", methods=["POST"])
@login_required
def about_people():
    """Edit the credits from the page they appear on (admins only).

    The doctors a clinic credits are different in every installation, so the
    names are the clinic's to write — a real person's details do not belong
    compiled into the program. Four actions on one endpoint, the same shape
    the device-measurements screen uses: the developer block, and add / edit /
    delete for each credited person.
    """
    from app.utils import project

    if not current_user.is_admin:
        flash(t("auth.no_permission"), "danger")
        return redirect(url_for("main.about"))

    action = (request.form.get("action") or "developer").strip()
    if action == "add":
        if project.add_person(request.form, request.files) is None:
            flash(t("about.person_needs_name"), "warning")
            return redirect(url_for("main.about"))
    elif action == "edit":
        project.edit_person(request.form.get("id"), request.form, request.files)
    elif action == "delete":
        project.delete_person(request.form.get("id"))
    else:
        project.save_people(request.form, request.files)

    db.session.commit()
    flash(t("common.saved"), "success")
    return redirect(url_for("main.about"))


@main_bp.route("/set-sidebar", methods=["POST"])
@login_required
def set_sidebar():
    """Persist whether the sidebar is full-width or an icon rail."""
    mode = (request.form.get("sidebar") or "").strip()
    current_user.sidebar = "rail" if mode == "rail" else "full"
    db.session.commit()
    return {"sidebar": current_user.sidebar}


@main_bp.route("/update")
@admin_required
def update_available():
    """The old address, kept pointing at the screen that explains.

    ``/update`` and ``/settings/#update`` were two different screens wearing
    one word. The split they exist for — one says what the version is, the
    other installs it — was in the code and in the headings and nowhere in the
    address bar, so browser history, a typed URL and a bookmark could not tell
    them apart. Reported by somebody looking at two screenshots of them.

    Anybody arriving at the old name lands on the screen that answers, which
    is the same rule the bell already follows: know what it is before being
    asked to close the clinic.
    """
    return redirect(url_for("settings.index", _anchor="update"))


@main_bp.route("/update/install")
@admin_required
def update_install():
    """What the newer version is, and how to install it.

    The program does not install it. Not as a matter of taste: replacing the
    files a running process is executing, on the machine a clinic is seeing
    patients on, is the failure that cost a morning when `start.bat` used to
    run `git pull` on every launch. So this page ends at a sentence — close
    the program and run `update.bat` — and the update happens with nothing
    running, with a snapshot before it and a schema upgrade after it.

    A button that closed the program safely and handed the job to a separate
    updater would be a fair thing to build; it would still not be this page
    doing the updating, which is the part that matters.
    """
    from app.utils.updates import can_hand_off, remembered

    return render_template("main/update.html", update=remembered(),
                           can_hand_off=can_hand_off())


@main_bp.route("/update/start", methods=["POST"])
@admin_required
def update_start():
    """Close the clinic and let a separate program do the update.

    The distinction this route exists to keep: **the update does not happen
    here.** It starts an external script, hands it this process's id, and that
    script sits watching until this process is gone before it writes anything.
    Then the program closes itself.

    Replacing the files a running Python process is executing is not a
    theoretical problem — half the modules on disk are the new version while
    half of what is in memory is the old one, and nobody finds out until a
    request lands on the seam. So nothing is replaced while anybody could be
    served.

    The exit is deferred by a couple of seconds so this page can actually be
    delivered; a request that dies mid-response leaves the admin looking at a
    browser error and no idea whether anything started. The updater takes a
    full backup before it touches a file, which is the safety net under all
    of this.
    """
    from app.utils import updates
    from app.utils.updates import remembered

    if not remembered():
        flash(t("update.none"), "info")
        return redirect(url_for("main.update_install"))
    if not updates.can_hand_off() or not updates.hand_off():
        # Nothing was started, so nothing is closing. The clinic carries on
        # and the admin is told to do it the way that always works.
        flash(t("update.handoff_failed"), "danger")
        return redirect(url_for("main.update_install"))

    ActivityLog.record("app.update_started", user_id=current_user.id,
                       entity="app", entity_id=None)
    db.session.commit()

    updates.close_after()
    return render_template("main/update_started.html")


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

        # How big the two that print come out on paper. What is already
        # stored is the fallback, so a form that does not carry the slider —
        # and there are several that post to this route — cannot return a
        # doctor's stamp to the default by staying silent.
        for key in ("signature_scale", "stamp_scale"):
            if key in request.form:
                setattr(u, key, clamp_print_scale(request.form.get(key),
                                                  getattr(u, key) or 100))

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
