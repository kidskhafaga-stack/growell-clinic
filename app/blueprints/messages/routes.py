"""Messaging module (WhatsApp).

Prepares patient appointment confirmations (and logs them). Depending on the
configured provider the message is either sent through an API or surfaced as a
click-to-send wa.me link for the front desk.
"""
from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user

from app.blueprints.messages import messages_bp
from app.extensions import db
from app.i18n import t
from app.models import ACTIVE_STATUSES, Appointment, MessageLog, Setting
from app.utils import whatsapp as wa
from app.utils.decorators import module_required

MODULE = "messages"


def queue_position(appointment):
    """1-based position of an appointment among its doctor's active bookings
    on the same day, ordered by time."""
    day = (
        Appointment.query
        .filter(Appointment.doctor_id == appointment.doctor_id)
        .filter(Appointment.appt_date == appointment.appt_date)
        .filter(Appointment.status.in_(ACTIVE_STATUSES))
        .order_by(Appointment.appt_time, Appointment.id)
        .all()
    )
    for idx, appt in enumerate(day, start=1):
        if appt.id == appointment.id:
            return idx
    return len(day) + 1


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

    from flask import g
    lang = getattr(g, "lang", "ar")
    queue_mode = Setting.get("queue_mode", "number")
    queue = queue_position(appt) if queue_mode == "number" else appt.time_label

    body = wa.render(Setting.get("wa_tpl_appt_confirm", ""), {
        "patient": patient.display_name(lang),
        "clinic": Setting.get("clinic_name_ar") or Setting.get("clinic_name") or "",
        "date": appt.appt_date.strftime("%Y-%m-%d"),
        "time": appt.time_label,
        "doctor": appt.doctor.display_name(lang) if appt.doctor else "",
        "queue": queue,
    })

    log = wa.send(body, phone, patient_id=patient.id, appointment_id=appt.id,
                  user_id=current_user.id)
    db.session.commit()
    return render_template("messages/sent.html", log=log, appt=appt)
