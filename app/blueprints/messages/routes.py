"""Messaging module (WhatsApp).

Prepares patient appointment confirmations (and logs them). Depending on the
configured provider the message is either sent through an API or surfaced as a
click-to-send wa.me link for the front desk.
"""
import os
import uuid
from datetime import date, datetime

from flask import current_app, flash, g, redirect, render_template, request, url_for
from flask_login import current_user
from werkzeug.utils import secure_filename

from app.blueprints.messages import messages_bp
from app.extensions import db
from app.i18n import t
from app.models import (
    ACTIVE_STATUSES,
    AUTOMATION_TYPES,
    MESSAGE_STATUSES,
    OCCASION_TYPES,
    SEND_MODES,
    TEMPLATE_VARIABLES,
    Appointment,
    MessageLog,
    MessageTemplate,
    Patient,
    Setting,
    User,
)
from app.utils import whatsapp as wa
from app.utils.decorators import admin_required, module_required

MODULE = "messages"
ALLOWED_IMG = {"png", "jpg", "jpeg", "webp", "gif"}
WA_CONFIG_KEYS = [
    "crm_mode", "wa_provider", "wa_country_code", "queue_mode",
    "wa_cloud_token", "wa_cloud_phone_id",
    "wa_wapilot_key", "wa_wapilot_instance", "wa_wapilot_endpoint",
    "wa_public_base_url", "wa_send_from", "wa_send_to", "wa_daily_cap",
    "wa_meta_verify_token",
]
WA_TOGGLE_KEYS = ["wa_inbound_enabled"]


def _crm_img_dir():
    return os.path.join(current_app.static_folder, "uploads", "crm")


def _save_crm_image(file):
    """Store an uploaded template image, returning its static-relative path."""
    if not file or not file.filename:
        return None
    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in ALLOWED_IMG:
        flash(t("crm.bad_image"), "warning")
        return None
    name = f"{uuid.uuid4().hex}.{ext}"
    os.makedirs(_crm_img_dir(), exist_ok=True)
    file.save(os.path.join(_crm_img_dir(), secure_filename(name)))
    return f"static/uploads/crm/{name}"


def _remove_crm_image(rel_path):
    if not rel_path or not rel_path.startswith("static/uploads/crm/"):
        return
    path = os.path.join(current_app.static_folder, rel_path.split("static/", 1)[1])
    if os.path.isfile(path):
        try:
            os.remove(path)
        except OSError:
            pass


def _day_appointments(doctor_id, on_date):
    """A doctor's active bookings for a day, ordered by time (queue order)."""
    return (
        Appointment.query
        .filter(Appointment.doctor_id == doctor_id)
        .filter(Appointment.appt_date == on_date)
        .filter(Appointment.status.in_(ACTIVE_STATUSES))
        .order_by(Appointment.appt_time, Appointment.id)
        .all()
    )


def queue_position(appointment):
    """1-based position among the doctor's same-day active bookings."""
    day = _day_appointments(appointment.doctor_id, appointment.appt_date)
    for idx, appt in enumerate(day, start=1):
        if appt.id == appointment.id:
            return idx
    return len(day) + 1


def _appt_confirm_body(appt, lang, queue=None):
    """Render the patient appointment-confirmation message."""
    if queue is None:
        mode = Setting.get("queue_mode", "number")
        queue = queue_position(appt) if mode == "number" else appt.time_label
    return wa.render(wa.template_body("appointment_confirm"), {
        "patient": appt.patient.display_name(lang) if appt.patient else "",
        "clinic": Setting.get("clinic_name_ar") or Setting.get("clinic_name") or "",
        "date": appt.appt_date.strftime("%Y-%m-%d"),
        "time": appt.time_label,
        "doctor": appt.doctor.display_name(lang) if appt.doctor else "",
        "queue": queue,
    })


@messages_bp.route("/")
@module_required(MODULE)
def index():
    """Send dashboard: delivery stats, status filter, scheduled queue, log."""
    page = request.args.get("page", 1, type=int)
    status = (request.args.get("status") or "").strip()

    q = MessageLog.query
    if status in MESSAGE_STATUSES:
        q = q.filter(MessageLog.status == status)
    pagination = (q.order_by(MessageLog.created_at.desc())
                  .paginate(page=page, per_page=25, error_out=False))

    counts = {s: 0 for s in MESSAGE_STATUSES}
    for st, n in (db.session.query(MessageLog.status, db.func.count())
                  .group_by(MessageLog.status).all()):
        counts[st] = n
    today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    sent_today = (MessageLog.query
                  .filter(MessageLog.status == "sent",
                          MessageLog.sent_at >= today).count())
    due_now = (MessageLog.query
               .filter(MessageLog.status == "scheduled",
                       MessageLog.scheduled_at <= datetime.utcnow()).count())
    return render_template(
        "messages/index.html", pagination=pagination, logs=pagination.items,
        counts=counts, status=status, statuses=MESSAGE_STATUSES,
        sent_today=sent_today, due_now=due_now,
        daily_cap=Setting.get("wa_daily_cap", "") or "0",
    )


@messages_bp.route("/satisfaction")
@module_required(MODULE)
def satisfaction():
    """Patient-satisfaction analytics: CSAT/NPS, distribution, doctor board."""
    from app.utils.feedback import clinic_summary, doctor_ratings

    summary = clinic_summary()
    ratings = doctor_ratings()
    docs = ({u.id: u for u in User.query.filter(User.id.in_(ratings.keys())).all()}
            if ratings else {})
    leaderboard = sorted(
        ({"doctor": docs[d], "avg": v["avg"], "count": v["count"]}
         for d, v in ratings.items() if d in docs),
        key=lambda x: (-x["avg"], -x["count"]))
    return render_template("messages/satisfaction.html", s=summary,
                           leaderboard=leaderboard)


@messages_bp.route("/send-due", methods=["POST"])
@module_required(MODULE)
def send_due():
    """Dispatch every scheduled message whose time has come."""
    res = wa.dispatch_due()
    if res["sent"] or res["skipped"]:
        flash(t("crm.dispatched", n=res["sent"], skipped=res["skipped"]), "success")
    else:
        flash(t("crm.nothing_due"), "info")
    return redirect(request.referrer or url_for("messages.index"))


@messages_bp.route("/patient/<int:patient_id>/opt-toggle", methods=["POST"])
@module_required(MODULE)
def opt_toggle(patient_id):
    """Flip a patient's WhatsApp opt-out preference."""
    patient = db.get_or_404(Patient, patient_id)
    patient.wa_opt_out = not patient.wa_opt_out
    db.session.commit()
    flash(t("crm.opted_out") if patient.wa_opt_out else t("crm.opted_in"), "info")
    return redirect(request.referrer or url_for("messages.index"))


@messages_bp.route("/appointment/<int:appt_id>/confirm")
@module_required(MODULE)
def confirm_appointment(appt_id):
    appt = db.get_or_404(Appointment, appt_id)
    patient = appt.patient
    phone = patient.contact_phone if patient else None
    if not phone:
        flash(t("messages_mod.no_phone"), "warning")
        return redirect(request.referrer or url_for("appointments.index"))

    lang = getattr(g, "lang", "ar")
    body = _appt_confirm_body(appt, lang)
    log = wa.send(body, phone, patient_id=patient.id, appointment_id=appt.id,
                  user_id=current_user.id, template_type="appointment_confirm",
                  image_url=wa.template_image("appointment_confirm"))
    db.session.commit()
    return render_template("messages/sent.html", log=log, appt=appt)


def _parse_day():
    raw = (request.args.get("date") or request.form.get("date") or "").strip()
    if raw:
        try:
            return datetime.strptime(raw, "%Y-%m-%d").date()
        except ValueError:
            pass
    return datetime.utcnow().date()


@messages_bp.route("/roster")
@module_required(MODULE)
def roster():
    on_date = _parse_day()
    doctor_id = request.args.get("doctor_id", type=int)
    doctors = User.query.filter_by(role="doctor", is_active=True).order_by(User.full_name).all()
    doctor = db.session.get(User, doctor_id) if doctor_id else None

    rows = []
    if doctor is not None:
        for idx, appt in enumerate(_day_appointments(doctor.id, on_date), start=1):
            rows.append({"appt": appt, "queue": idx,
                         "phone": appt.patient.contact_phone if appt.patient else None})
    return render_template(
        "messages/roster.html", doctors=doctors, doctor=doctor,
        on_date=on_date, rows=rows,
        queue_mode=Setting.get("queue_mode", "number"),
    )


@messages_bp.route("/roster/doctor", methods=["POST"])
@module_required(MODULE)
def roster_doctor():
    on_date = _parse_day()
    doctor = db.get_or_404(User, request.form.get("doctor_id", type=int))
    if not doctor.phone:
        flash(t("messages_mod.no_doctor_phone"), "warning")
        return redirect(url_for("messages.roster", doctor_id=doctor.id, date=on_date))

    lang = getattr(g, "lang", "ar")
    appts = _day_appointments(doctor.id, on_date)
    lines = "\n".join(
        f"{i}) {a.time_label} - {a.patient.display_name(lang) if a.patient else ''}"
        for i, a in enumerate(appts, start=1)
    )
    body = wa.render(wa.template_body("doctor_schedule"), {
        "doctor": doctor.display_name(lang),
        "date": on_date.strftime("%Y-%m-%d"),
        "count": len(appts),
        "list": lines,
    })
    log = wa.send(body, doctor.phone, user_id=current_user.id,
                  template_type="doctor_schedule",
                  image_url=wa.template_image("doctor_schedule"))
    db.session.commit()
    return render_template("messages/sent.html", log=log, appt=None)


def _parse_schedule():
    """Optional ``schedule_at`` datetime-local from the form (future only)."""
    raw = (request.form.get("schedule_at") or "").strip()
    if not raw:
        return None
    for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M"):
        try:
            when = datetime.strptime(raw, fmt)
            return when if when > datetime.utcnow() else None
        except ValueError:
            continue
    return None


@messages_bp.route("/roster/notify", methods=["POST"])
@module_required(MODULE)
def roster_notify():
    on_date = _parse_day()
    doctor = db.get_or_404(User, request.form.get("doctor_id", type=int))
    lang = getattr(g, "lang", "ar")
    schedule_at = _parse_schedule()

    results = []
    for idx, appt in enumerate(_day_appointments(doctor.id, on_date), start=1):
        phone = appt.patient.contact_phone if appt.patient else None
        if not phone:
            results.append({"appt": appt, "log": None})
            continue
        mode = Setting.get("queue_mode", "number")
        queue = idx if mode == "number" else appt.time_label
        body = _appt_confirm_body(appt, lang, queue=queue)
        log = wa.send(body, phone, patient_id=appt.patient_id,
                      appointment_id=appt.id, user_id=current_user.id,
                      template_type="appointment_confirm",
                      image_url=wa.template_image("appointment_confirm"),
                      scheduled_at=schedule_at)
        results.append({"appt": appt, "log": log})
    db.session.commit()
    return render_template("messages/notify_result.html", results=results,
                           doctor=doctor, on_date=on_date, scheduled=schedule_at)


# =======================================================================
# CRM — occasions & birthdays
# =======================================================================
def _upcoming_birthdays(days=7):
    """Active patients whose birthday falls within the next ``days`` days."""
    today = date.today()
    rows = []
    for p in Patient.query.filter_by(is_active=True).all():
        if not p.date_of_birth:
            continue
        dob = p.date_of_birth
        # This year's birthday (handle Feb 29 -> Feb 28).
        try:
            nb = dob.replace(year=today.year)
        except ValueError:
            nb = dob.replace(year=today.year, day=28)
        if nb < today:
            try:
                nb = dob.replace(year=today.year + 1)
            except ValueError:
                nb = dob.replace(year=today.year + 1, day=28)
        delta = (nb - today).days
        if 0 <= delta <= days:
            rows.append({"patient": p, "in_days": delta, "date": nb,
                         "turning": nb.year - dob.year,
                         "phone": p.contact_phone})
    return sorted(rows, key=lambda r: r["in_days"])


@messages_bp.route("/occasions")
@module_required(MODULE)
def occasions():
    """The unified Patient Customer Service (CRM) hub.

    One place for: the WhatsApp connection, the canonical per-type
    notification templates (body + image + auto/manual), free-form occasion
    templates, and upcoming birthdays.
    """
    # Make sure the canonical rows exist even before an upgrade-db has run.
    wa.seed_system_templates()

    system_rows = {
        r.occasion: r for r in
        MessageTemplate.query.filter_by(is_system=True).all()
    }
    system_templates = [system_rows[tp] for tp in AUTOMATION_TYPES
                        if tp in system_rows]
    custom_templates = (MessageTemplate.query
                        .filter_by(is_system=False)
                        .order_by(MessageTemplate.occasion, MessageTemplate.name)
                        .all())
    values = {row.key: row.value for row in Setting.query.all()}
    return render_template(
        "messages/occasions.html",
        birthdays=_upcoming_birthdays(),
        system_templates=system_templates,
        custom_templates=custom_templates,
        occasion_types=OCCASION_TYPES,
        template_variables=TEMPLATE_VARIABLES,
        send_modes=SEND_MODES,
        values=values,
        crm_mode=values.get("crm_mode", "manual"),
    )


@messages_bp.route("/connection", methods=["POST"])
@admin_required
def connection_save():
    """Save the WhatsApp connection / delivery configuration from the hub."""
    import secrets

    for key in WA_CONFIG_KEYS:
        Setting.set(key, (request.form.get(key) or "").strip())
    for key in WA_TOGGLE_KEYS:
        Setting.set(key, "1" if request.form.get(key) else "0")
    # Regenerate or first-time-create the inbound webhook secret on demand.
    if request.form.get("regen_secret") or not Setting.get("wa_webhook_secret", ""):
        Setting.set("wa_webhook_secret", secrets.token_urlsafe(24))
    db.session.commit()
    flash(t("settings.saved"), "success")
    return redirect(url_for("messages.occasions") + "#connection")


@messages_bp.route("/type/<int:tpl_id>/save", methods=["POST"])
@module_required(MODULE)
def system_template_save(tpl_id):
    """Edit a canonical notification type: body, image, auto/manual, on/off."""
    tpl = db.get_or_404(MessageTemplate, tpl_id)
    tpl.body = (request.form.get("body") or "").strip()
    mode = (request.form.get("send_mode") or tpl.send_mode).strip()
    tpl.send_mode = mode if mode in SEND_MODES else tpl.send_mode
    tpl.is_active = bool(request.form.get("is_active"))
    # Per-template scheduling: delay after the trigger + fixed hour of day.
    tpl.delay_days = max(0, request.form.get("delay_days", type=int) or 0)
    tpl.delay_hours = max(0, request.form.get("delay_hours", type=int) or 0)
    sh = request.form.get("send_hour", type=int)
    tpl.send_hour = max(0, min(23, sh)) if sh is not None else None

    if request.form.get("remove_image"):
        _remove_crm_image(tpl.image_url)
        tpl.image_url = None
    new_img = _save_crm_image(request.files.get("image"))
    if new_img:
        _remove_crm_image(tpl.image_url)
        tpl.image_url = new_img

    db.session.commit()
    flash(t("crm.type_saved"), "success")
    return redirect(url_for("messages.occasions") + "#types")


@messages_bp.route("/occasions/birthday/<int:patient_id>")
@module_required(MODULE)
def send_birthday(patient_id):
    patient = db.get_or_404(Patient, patient_id)
    phone = patient.contact_phone
    if not phone:
        flash(t("messages_mod.no_phone"), "warning")
        return redirect(url_for("messages.occasions"))

    lang = getattr(g, "lang", "ar")
    body = wa.render(wa.template_body("birthday"), {
        "patient": patient.display_name(lang),
        "clinic": Setting.get("clinic_name_ar") or Setting.get("clinic_name") or "",
    })
    from app.models.message import _template_schedule
    btpl = wa.template_for("birthday")
    schedule_at = _template_schedule(btpl) if btpl is not None else None
    log = wa.send(body, phone, patient_id=patient.id, user_id=current_user.id,
                  template_type="birthday", scheduled_at=schedule_at,
                  image_url=wa.template_image("birthday"))
    db.session.commit()
    return render_template("messages/sent.html", log=log, appt=None)


@messages_bp.route("/occasions/template/new", methods=["POST"])
@module_required(MODULE)
def occasion_template_new():
    name = (request.form.get("name") or "").strip()
    body = (request.form.get("body") or "").strip()
    if not name or not body:
        flash(t("common.required") + ": " + t("occasions.name"), "danger")
        return redirect(url_for("messages.occasions"))
    occ = (request.form.get("occasion") or "custom").strip()
    db.session.add(MessageTemplate(
        name=name, body=body,
        occasion=occ if occ in OCCASION_TYPES else "custom",
        image_url=_save_crm_image(request.files.get("image")),
    ))
    db.session.commit()
    flash(t("occasions.tpl_added"), "success")
    return redirect(url_for("messages.occasions") + "#custom")


@messages_bp.route("/occasions/template/<int:tpl_id>/edit", methods=["POST"])
@module_required(MODULE)
def occasion_template_edit(tpl_id):
    tpl = db.get_or_404(MessageTemplate, tpl_id)
    tpl.name = (request.form.get("name") or tpl.name).strip()
    tpl.body = (request.form.get("body") or tpl.body).strip()
    occ = (request.form.get("occasion") or tpl.occasion).strip()
    tpl.occasion = occ if occ in OCCASION_TYPES else tpl.occasion
    tpl.is_active = bool(request.form.get("is_active"))
    if request.form.get("remove_image"):
        _remove_crm_image(tpl.image_url)
        tpl.image_url = None
    new_img = _save_crm_image(request.files.get("image"))
    if new_img:
        _remove_crm_image(tpl.image_url)
        tpl.image_url = new_img
    db.session.commit()
    flash(t("occasions.tpl_updated"), "success")
    return redirect(url_for("messages.occasions") + "#custom")


@messages_bp.route("/occasions/template/<int:tpl_id>/delete", methods=["POST"])
@module_required(MODULE)
def occasion_template_delete(tpl_id):
    tpl = db.get_or_404(MessageTemplate, tpl_id)
    if tpl.is_system:  # canonical rows are managed, never deleted
        flash(t("crm.cant_delete_system"), "warning")
        return redirect(url_for("messages.occasions") + "#types")
    _remove_crm_image(tpl.image_url)
    db.session.delete(tpl)
    db.session.commit()
    flash(t("occasions.tpl_deleted"), "info")
    return redirect(url_for("messages.occasions") + "#custom")
