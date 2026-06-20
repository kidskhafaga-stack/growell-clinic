"""Messaging module (WhatsApp).

Prepares patient appointment confirmations (and logs them). Depending on the
configured provider the message is either sent through an API or surfaced as a
click-to-send wa.me link for the front desk.
"""
from datetime import datetime

from flask import flash, g, redirect, render_template, request, url_for
from flask_login import current_user

from app.blueprints.messages import messages_bp
from app.extensions import db
from app.i18n import t
from app.models import ACTIVE_STATUSES, Appointment, MessageLog, Setting, User
from app.utils import whatsapp as wa
from app.utils.decorators import module_required

MODULE = "messages"


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
    return wa.render(Setting.get("wa_tpl_appt_confirm", ""), {
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
    page = request.args.get("page", 1, type=int)
    pagination = (
        MessageLog.query.order_by(MessageLog.created_at.desc())
        .paginate(page=page, per_page=25, error_out=False)
    )
    return render_template("messages/index.html", pagination=pagination,
                           logs=pagination.items)


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
                  user_id=current_user.id)
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
    body = wa.render(Setting.get("wa_tpl_doctor_schedule", ""), {
        "doctor": doctor.display_name(lang),
        "date": on_date.strftime("%Y-%m-%d"),
        "count": len(appts),
        "list": lines,
    })
    log = wa.send(body, doctor.phone, user_id=current_user.id)
    db.session.commit()
    return render_template("messages/sent.html", log=log, appt=None)


@messages_bp.route("/roster/notify", methods=["POST"])
@module_required(MODULE)
def roster_notify():
    on_date = _parse_day()
    doctor = db.get_or_404(User, request.form.get("doctor_id", type=int))
    lang = getattr(g, "lang", "ar")

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
                      appointment_id=appt.id, user_id=current_user.id)
        results.append({"appt": appt, "log": log})
    db.session.commit()
    return render_template("messages/notify_result.html", results=results,
                           doctor=doctor, on_date=on_date)
