"""Appointments & smart scheduling (Phase 3).

Includes the doctor's "Today's Appointments" board, conflict-free booking,
the appointment status lifecycle, and per-doctor working-hours schedules.
"""
from datetime import datetime, timedelta

from flask import (
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user

from app.blueprints.appointments import appointments_bp
from app.extensions import db
from app.i18n import t
from app.models import (
    ActivityLog,
    Appointment,
    DoctorSchedule,
    Patient,
)
from app.models.appointment import ACTIVE_STATUSES
from app.models.doctor_schedule import WEEKDAY_ORDER
from app.utils.appointments import (
    available_slots,
    list_doctors,
    parse_date_arg,
    slot_duration,
)
from app.utils.decorators import client_ip, module_required

MODULE = "appointments"


# ----------------------------------------------- board (Today's screen) ----
@appointments_bp.route("/")
@module_required(MODULE)
def index():
    on_date = parse_date_arg(request.args.get("date"))
    doctors = list_doctors()

    # Default the doctor filter: the logged-in doctor sees their own board.
    doctor_id = request.args.get("doctor_id", type=int)
    if doctor_id is None and current_user.role == "doctor":
        doctor_id = current_user.id

    query = Appointment.query.filter(Appointment.appt_date == on_date)
    if doctor_id:
        query = query.filter(Appointment.doctor_id == doctor_id)
    appointments = query.order_by(Appointment.appt_time).all()

    # Stat cards (per the reference design): total / done / waiting / no-show.
    stats = {
        "total": len(appointments),
        "completed": sum(1 for a in appointments if a.status == "completed"),
        "waiting": sum(1 for a in appointments if a.status in ("waiting", "scheduled")),
        "no_show": sum(1 for a in appointments if a.status == "no_show"),
    }
    current = next((a for a in appointments if a.status == "in_progress"), None)

    return render_template(
        "appointments/board.html",
        appointments=appointments,
        doctors=doctors,
        doctor_id=doctor_id,
        on_date=on_date,
        prev_date=(on_date - timedelta(days=1)).isoformat(),
        next_date=(on_date + timedelta(days=1)).isoformat(),
        today=datetime.today().date().isoformat(),
        stats=stats,
        current=current,
    )


# -------------------------------------------------------- booking ----------
@appointments_bp.route("/new", methods=["GET", "POST"])
@module_required(MODULE)
def create():
    doctors = list_doctors()
    patients = Patient.query.filter_by(is_active=True).order_by(Patient.full_name).all()

    if request.method == "POST":
        patient_id = request.form.get("patient_id", type=int)
        doctor_id = request.form.get("doctor_id", type=int)
        on_date = parse_date_arg(request.form.get("appt_date"), default=None)
        slot = (request.form.get("appt_time") or "").strip()
        reason = (request.form.get("reason") or "").strip()

        error = _validate_booking(patient_id, doctor_id, on_date, slot)
        if error:
            flash(error, "danger")
            return render_template(
                "appointments/form.html", doctors=doctors, patients=patients,
                form=request.form,
            )

        appt = Appointment(
            patient_id=patient_id,
            doctor_id=doctor_id,
            appt_date=on_date,
            appt_time=datetime.strptime(slot, "%H:%M").time(),
            duration_minutes=slot_duration(doctor_id, on_date),
            reason=reason,
            status="scheduled",
        )
        db.session.add(appt)
        db.session.flush()
        ActivityLog.record(
            "appointment.create", user_id=current_user.id, entity="appointment",
            entity_id=appt.id, ip_address=client_ip(),
        )
        db.session.commit()
        flash(t("appointments.created"), "success")
        return redirect(url_for("appointments.index", date=on_date.isoformat(),
                                doctor_id=doctor_id))

    return render_template(
        "appointments/form.html", doctors=doctors, patients=patients, form={}
    )


@appointments_bp.route("/slots")
@module_required(MODULE)
def slots():
    """JSON: available slots for a doctor on a date (drives the booking form)."""
    doctor_id = request.args.get("doctor_id", type=int)
    on_date = parse_date_arg(request.args.get("date"), default=None)
    exclude_id = request.args.get("exclude_id", type=int)
    if not doctor_id or not on_date:
        return jsonify({"slots": []})
    return jsonify({"slots": available_slots(doctor_id, on_date, exclude_id=exclude_id)})


# -------------------------------------------------- status lifecycle -------
@appointments_bp.route("/<int:appt_id>/status", methods=["POST"])
@module_required(MODULE)
def change_status(appt_id):
    appt = db.get_or_404(Appointment, appt_id)
    new_status = (request.form.get("status") or "").strip()

    if not Appointment.valid_status(new_status) or not appt.can_transition_to(new_status):
        flash(t("appointments.invalid_transition"), "warning")
        return _back_to_board(appt)

    appt.apply_status(new_status)
    ActivityLog.record(
        "appointment.status", user_id=current_user.id, entity="appointment",
        entity_id=appt.id, detail=new_status, ip_address=client_ip(),
    )
    db.session.commit()
    flash(t("appointments.status_changed", status=t("statuses." + new_status)), "success")
    return _back_to_board(appt)


@appointments_bp.route("/<int:appt_id>/delete", methods=["POST"])
@module_required(MODULE)
def delete(appt_id):
    appt = db.get_or_404(Appointment, appt_id)
    target = _back_to_board(appt)
    db.session.delete(appt)
    ActivityLog.record(
        "appointment.delete", user_id=current_user.id, entity="appointment",
        entity_id=appt_id, ip_address=client_ip(),
    )
    db.session.commit()
    flash(t("appointments.deleted"), "info")
    return target


# ----------------------------------------------- doctor schedules ----------
@appointments_bp.route("/schedules", methods=["GET", "POST"])
@module_required(MODULE)
def schedules():
    doctors = list_doctors()
    selected = request.args.get("doctor_id", type=int)
    if selected is None and current_user.role == "doctor":
        selected = current_user.id
    elif selected is None and doctors:
        selected = doctors[0].id

    if request.method == "POST":
        doctor_id = request.form.get("doctor_id", type=int)
        weekday = request.form.get("weekday", type=int)
        start_raw = request.form.get("start_time") or ""
        end_raw = request.form.get("end_time") or ""
        slot_minutes = request.form.get("slot_minutes", type=int) or 15
        max_patients = request.form.get("max_patients", type=int)

        error = _validate_schedule(doctor_id, weekday, start_raw, end_raw)
        if error:
            flash(error, "danger")
            return redirect(url_for("appointments.schedules", doctor_id=doctor_id or selected))

        db.session.add(DoctorSchedule(
            doctor_id=doctor_id,
            weekday=weekday,
            start_time=datetime.strptime(start_raw, "%H:%M").time(),
            end_time=datetime.strptime(end_raw, "%H:%M").time(),
            slot_minutes=slot_minutes,
            max_patients=max_patients,
        ))
        db.session.commit()
        flash(t("appointments.schedule_added"), "success")
        return redirect(url_for("appointments.schedules", doctor_id=doctor_id))

    schedule_rows = []
    if selected:
        rows = DoctorSchedule.query.filter_by(doctor_id=selected).all()
        by_day = {wd: [] for wd in WEEKDAY_ORDER}
        for r in rows:
            by_day.setdefault(r.weekday, []).append(r)
        for wd in WEEKDAY_ORDER:
            schedule_rows.append((wd, sorted(by_day.get(wd, []), key=lambda s: s.start_time)))

    return render_template(
        "appointments/schedules.html",
        doctors=doctors, selected=selected, schedule_rows=schedule_rows,
        weekday_order=WEEKDAY_ORDER,
    )


@appointments_bp.route("/schedules/<int:schedule_id>/delete", methods=["POST"])
@module_required(MODULE)
def delete_schedule(schedule_id):
    sched = db.get_or_404(DoctorSchedule, schedule_id)
    doctor_id = sched.doctor_id
    db.session.delete(sched)
    db.session.commit()
    flash(t("appointments.schedule_removed"), "info")
    return redirect(url_for("appointments.schedules", doctor_id=doctor_id))


# --------------------------------------------------------------- helpers ---
def _back_to_board(appt):
    return redirect(url_for("appointments.index", date=appt.appt_date.isoformat(),
                            doctor_id=appt.doctor_id))


def _validate_booking(patient_id, doctor_id, on_date, slot):
    if not patient_id or not db.session.get(Patient, patient_id):
        return t("common.required") + ": " + t("appointments.patient")
    if not doctor_id:
        return t("common.required") + ": " + t("appointments.doctor")
    if on_date is None:
        return t("common.required") + ": " + t("appointments.date")
    if not slot:
        return t("common.required") + ": " + t("appointments.time")
    try:
        slot_time = datetime.strptime(slot, "%H:%M").time()
    except ValueError:
        return t("appointments.invalid_time")
    # Conflict prevention: re-check the slot is genuinely free server-side.
    if slot not in available_slots(doctor_id, on_date):
        return t("appointments.slot_taken")
    return None


def _validate_schedule(doctor_id, weekday, start_raw, end_raw):
    if not doctor_id:
        return t("common.required") + ": " + t("appointments.doctor")
    if weekday is None or weekday < 0 or weekday > 6:
        return t("common.required") + ": " + t("appointments.weekday")
    try:
        start = datetime.strptime(start_raw, "%H:%M").time()
        end = datetime.strptime(end_raw, "%H:%M").time()
    except ValueError:
        return t("appointments.invalid_time")
    if start >= end:
        return t("appointments.bad_window")
    return None
