"""Appointments & smart scheduling (Phase 3).

Includes the doctor's "Today's Appointments" board, conflict-free booking,
the appointment status lifecycle, and per-doctor working-hours schedules.
"""
from datetime import date, datetime, timedelta

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
    ScheduleException,
    Setting,
    VaccineBrand,
    WaitlistEntry,
)
from app.models.appointment import (
    ACTIVE_STATUSES,
    APPOINTMENT_TYPES,
    DEFAULT_APPT_TYPE,
    type_minutes,
)
from app.models.doctor_schedule import WEEKDAY_ORDER
from app.utils.appointments import (
    available_slots,
    consult_window_days,
    consultation_window,
    first_available_doctor,
    list_doctors,
    next_available,
    parse_date_arg,
    slot_duration,
)
from app.utils.decorators import client_ip, module_required

MODULE = "appointments"


def _appt_type(value):
    """Validate a posted appointment-type key, falling back to the default."""
    return value if value in APPOINTMENT_TYPES else DEFAULT_APPT_TYPE


def _vaccine_brands():
    """Active, in-production vaccine brands for the booking picker."""
    return (VaccineBrand.query
            .filter(VaccineBrand.is_discontinued.is_(False))
            .join(VaccineBrand.vaccine)
            .order_by(VaccineBrand.name).all())


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
    # Payment snapshot per appointment, so the doctor sees who paid / who's
    # still owing while the clinic is running.
    pay = _payment_status(appointments, on_date)
    stats["paid"] = sum(1 for a in appointments if pay.get(a.id, {}).get("state") == "paid")
    stats["unpaid"] = sum(
        1 for a in appointments if pay.get(a.id, {}).get("state") in ("unpaid", "partial")
    )
    current = next((a for a in appointments if a.status == "in_progress"), None)
    current_summary = _current_summary(current.patient) if current else None

    # Active waiting-list entries (optionally filtered to the selected doctor).
    wl_query = WaitlistEntry.query.filter_by(status="active")
    if doctor_id:
        wl_query = wl_query.filter(
            db.or_(WaitlistEntry.doctor_id == doctor_id,
                   WaitlistEntry.doctor_id.is_(None))
        )
    waitlist = wl_query.order_by(WaitlistEntry.created_at).all()

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
        current_summary=current_summary,
        waitlist=waitlist,
        appt_types=APPOINTMENT_TYPES,
        pay=pay,
    )


def _payment_status(appointments, on_date):
    """Map appointment.id -> payment snapshot from that patient's invoices on
    the date. State is one of: ``paid`` / ``partial`` / ``unpaid`` / ``none``
    (no invoice raised yet)."""
    from app.models import Invoice

    if not appointments:
        return {}
    patient_ids = {a.patient_id for a in appointments}
    invoices = (
        Invoice.query.filter(
            Invoice.patient_id.in_(patient_ids), Invoice.invoice_date == on_date
        ).all()
    )
    by_patient = {}
    for inv in invoices:
        by_patient.setdefault(inv.patient_id, []).append(inv)

    out = {}
    for a in appointments:
        ivs = by_patient.get(a.patient_id)
        if not ivs:
            out[a.id] = {"state": "none"}
            continue
        total = round(sum(i.total for i in ivs), 2)
        balance = round(sum(i.balance for i in ivs), 2)
        if total > 0 and balance <= 0:
            state = "paid"
        elif balance < total:
            state = "partial"
        else:
            state = "unpaid"
        out[a.id] = {
            "state": state, "total": total, "balance": balance,
            "invoice_id": ivs[0].id if len(ivs) == 1 else None,
        }
    return out


def _current_summary(patient):
    """Growth (latest measurement) + vaccination status for the live patient."""
    from app.models import GrowthRecord
    from app.utils.vaccines import patient_plan, plan_summary

    growth = (GrowthRecord.query.filter_by(patient_id=patient.id)
              .order_by(GrowthRecord.record_date.desc(), GrowthRecord.id.desc()).first())
    try:
        vac = plan_summary(patient_plan(patient))
    except Exception:  # noqa: BLE001
        vac = None
    return {"growth": growth, "vac": vac}


# -------------------------------------------------------- booking ----------
@appointments_bp.route("/new", methods=["GET", "POST"])
@module_required(MODULE)
def create():
    doctors = list_doctors()

    if request.method == "POST":
        patient_id = request.form.get("patient_id", type=int)
        doctor_id = request.form.get("doctor_id", type=int)
        on_date = parse_date_arg(request.form.get("appt_date"), default=None)
        slot = (request.form.get("appt_time") or "").strip()
        reason = (request.form.get("reason") or "").strip()
        appt_type = _appt_type((request.form.get("appt_type") or "").strip())

        error = _validate_booking(patient_id, doctor_id, on_date, slot)
        if error:
            flash(error, "danger")
            chosen = db.session.get(Patient, patient_id) if patient_id else None
            return render_template(
                "appointments/form.html", doctors=doctors, form=request.form,
                selected_patient=_patient_brief(chosen) if chosen else None,
                appt_types=APPOINTMENT_TYPES, vaccine_brands=_vaccine_brands(),
            )

        appt = Appointment(
            patient_id=patient_id,
            doctor_id=doctor_id,
            appt_date=on_date,
            appt_time=datetime.strptime(slot, "%H:%M").time(),
            duration_minutes=type_minutes(appt_type, slot_duration(doctor_id, on_date)),
            reason=reason,
            appt_type=appt_type,
            status="scheduled",
        )
        # Vaccination booking: remember the chosen vaccine + dose.
        if appt_type == "vaccination":
            appt.vaccine_brand_id = request.form.get("vaccine_brand_id", type=int) or None
            appt.vaccine_dose = request.form.get("vaccine_dose", type=int) or None
        db.session.add(appt)
        db.session.flush()
        ActivityLog.record(
            "appointment.create", user_id=current_user.id, entity="appointment",
            entity_id=appt.id, ip_address=client_ip(),
        )
        # If this booking came from a waiting-list entry, close it out.
        wl_id = request.form.get("from_waitlist", type=int)
        if wl_id:
            entry = db.session.get(WaitlistEntry, wl_id)
            if entry and entry.status == "active":
                entry.status = "booked"
                entry.appointment_id = appt.id
        db.session.commit()
        flash(t("appointments.created"), "success")
        # Consultation follow-up window: warn reception if it's late / overdue.
        if appt_type == "consultation":
            info = consultation_window(patient_id, doctor_id, on_date)
            if info["status"] == "warn":
                flash(t("appointments.consult_warn",
                        days=info["days"], free=info["free_days"]), "warning")
            elif info["status"] == "exceeded":
                flash(t("appointments.consult_exceeded",
                        days=info["days"], max=info["max_days"]), "warning")
        return redirect(url_for("appointments.index", date=on_date.isoformat(),
                                doctor_id=doctor_id))

    # Prefill from query params (patient profile or a waiting-list promotion).
    prefill = request.args.get("patient_id", type=int)
    chosen = db.session.get(Patient, prefill) if prefill else None
    form = {
        "doctor_id": request.args.get("doctor_id", ""),
        "appt_type": _appt_type(request.args.get("appt_type", "")),
        "from_waitlist": request.args.get("from_waitlist", ""),
    }
    return render_template(
        "appointments/form.html", doctors=doctors, form=form,
        selected_patient=_patient_brief(chosen) if chosen else None,
        appt_types=APPOINTMENT_TYPES, vaccine_brands=_vaccine_brands(),
    )


@appointments_bp.route("/consult-check")
@module_required(MODULE)
def consult_check():
    """JSON: classify a consultation booking against the follow-up window so the
    booking form can warn reception before saving."""
    info = consultation_window(
        request.args.get("patient_id", type=int),
        request.args.get("doctor_id", type=int),
        parse_date_arg(request.args.get("date"), default=None) or date.today(),
    )
    msgs = {
        "no_exam": t("appointments.consult_no_exam"),
        "ok": t("appointments.consult_ok", days=info["days"] or 0),
        "warn": t("appointments.consult_warn",
                  days=info["days"] or 0, free=info["free_days"]),
        "exceeded": t("appointments.consult_exceeded",
                     days=info["days"] or 0, max=info["max_days"]),
    }
    info["message"] = msgs.get(info["status"], "")
    return jsonify(info)


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


@appointments_bp.route("/next-available")
@module_required(MODULE)
def next_available_slot():
    """JSON: the soonest free slot for a doctor (from a date forward)."""
    doctor_id = request.args.get("doctor_id", type=int)
    from_date = parse_date_arg(request.args.get("date"))
    if not doctor_id:
        return jsonify({"found": False})
    result = next_available(doctor_id, from_date)
    return jsonify({"found": bool(result), **(result or {})})


@appointments_bp.route("/first-available")
@module_required(MODULE)
def first_available():
    """JSON: the soonest free slot across all doctors (from a date forward)."""
    from_date = parse_date_arg(request.args.get("date"))
    result = first_available_doctor(from_date)
    return jsonify({"found": bool(result), **(result or {})})


# -------------------------------------------------- reschedule / walk-in ---
@appointments_bp.route("/<int:appt_id>/reschedule", methods=["POST"])
@module_required(MODULE)
def reschedule(appt_id):
    """Move an appointment to a new date/time (and optionally doctor)."""
    appt = db.get_or_404(Appointment, appt_id)
    new_doctor = request.form.get("doctor_id", type=int) or appt.doctor_id
    new_date = parse_date_arg(request.form.get("appt_date"), default=None)
    new_slot = (request.form.get("appt_time") or "").strip()

    if new_date is None or not new_slot:
        flash(t("appointments.reschedule_need_slot"), "danger")
        return _back_to_board(appt)
    # The slot must be free (ignoring this appointment itself).
    if new_slot not in available_slots(new_doctor, new_date, exclude_id=appt.id):
        flash(t("appointments.slot_taken"), "danger")
        return _back_to_board(appt)

    appt.rescheduled_from = f"{appt.appt_date.isoformat()} {appt.time_label}"
    appt.doctor_id = new_doctor
    appt.appt_date = new_date
    appt.appt_time = datetime.strptime(new_slot, "%H:%M").time()
    if appt.status in ("no_show", "cancelled"):
        appt.status = "scheduled"
    ActivityLog.record(
        "appointment.reschedule", user_id=current_user.id, entity="appointment",
        entity_id=appt.id, detail=appt.rescheduled_from, ip_address=client_ip(),
    )
    db.session.commit()
    flash(t("appointments.rescheduled"), "success")
    return redirect(url_for("appointments.index", date=new_date.isoformat(),
                            doctor_id=new_doctor))


@appointments_bp.route("/walk-in", methods=["POST"])
@module_required(MODULE)
def walk_in():
    """Register a walk-in: book the next free slot today (overbook if full)."""
    patient_id = request.form.get("patient_id", type=int)
    doctor_id = request.form.get("doctor_id", type=int)
    reason = (request.form.get("reason") or "").strip()
    appt_type = _appt_type((request.form.get("appt_type") or "").strip())

    if not patient_id or not db.session.get(Patient, patient_id) or not doctor_id:
        flash(t("appointments.walk_in_need"), "danger")
        return redirect(url_for("appointments.index"))

    today = datetime.today().date()
    spot = next_available(doctor_id, today, days=1)
    if spot:
        appt_time = datetime.strptime(spot["time"], "%H:%M").time()
    else:
        # Clinic full / outside hours: overbook at the current time.
        appt_time = datetime.now().time().replace(second=0, microsecond=0)

    appt = Appointment(
        patient_id=patient_id, doctor_id=doctor_id, appt_date=today,
        appt_time=appt_time, duration_minutes=type_minutes(appt_type),
        reason=reason or t("appointments.walk_in"), appt_type=appt_type,
        is_walk_in=True, status="waiting",
    )
    appt.apply_status("waiting")  # stamp check-in time
    db.session.add(appt)
    db.session.flush()
    ActivityLog.record(
        "appointment.walk_in", user_id=current_user.id, entity="appointment",
        entity_id=appt.id, ip_address=client_ip(),
    )
    db.session.commit()
    flash(t("appointments.walk_in_added"), "success")
    return redirect(url_for("appointments.index", date=today.isoformat(),
                            doctor_id=doctor_id))


# ------------------------------------------------------------- waitlist ----
@appointments_bp.route("/waitlist", methods=["POST"])
@module_required(MODULE)
def waitlist_add():
    """Add a patient to the waiting list (used when no slot suits them)."""
    patient_id = request.form.get("patient_id", type=int)
    if not patient_id or not db.session.get(Patient, patient_id):
        flash(t("appointments.qc_need_name"), "danger")
        return redirect(url_for("appointments.index"))

    entry = WaitlistEntry(
        patient_id=patient_id,
        doctor_id=request.form.get("doctor_id", type=int) or None,
        preferred_from=parse_date_arg(request.form.get("preferred_from"), default=None),
        preferred_to=parse_date_arg(request.form.get("preferred_to"), default=None),
        appt_type=_appt_type((request.form.get("appt_type") or "").strip()),
        reason=(request.form.get("reason") or "").strip() or None,
        note=(request.form.get("note") or "").strip() or None,
    )
    db.session.add(entry)
    db.session.commit()
    flash(t("appointments.waitlist_added"), "success")
    return redirect(request.referrer or url_for("appointments.index"))


@appointments_bp.route("/waitlist/<int:entry_id>/cancel", methods=["POST"])
@module_required(MODULE)
def waitlist_cancel(entry_id):
    entry = db.get_or_404(WaitlistEntry, entry_id)
    entry.status = "cancelled"
    db.session.commit()
    flash(t("appointments.waitlist_removed"), "info")
    return redirect(request.referrer or url_for("appointments.index"))


@appointments_bp.route("/waitlist/<int:entry_id>/book")
@module_required(MODULE)
def waitlist_book(entry_id):
    """Promote a waiting-list entry: open the booking form pre-filled."""
    entry = db.get_or_404(WaitlistEntry, entry_id)
    return redirect(url_for(
        "appointments.create", patient_id=entry.patient_id,
        doctor_id=entry.doctor_id or "", appt_type=entry.appt_type or "",
        from_waitlist=entry.id,
    ))


@appointments_bp.route("/patient-search")
@module_required(MODULE)
def patient_search():
    """JSON: matching active patients for the booking search box (name/number)."""
    q = (request.args.get("q") or "").strip()
    if len(q) < 2:
        return jsonify({"patients": []})
    like = f"%{q}%"
    rows = (
        Patient.query.filter(Patient.is_active.is_(True))
        .filter(
            db.or_(
                Patient.full_name.ilike(like),
                Patient.full_name_en.ilike(like),
                Patient.patient_number.ilike(like),
            )
        )
        .order_by(Patient.full_name)
        .limit(15)
        .all()
    )
    return jsonify({"patients": [_patient_brief(p) for p in rows]})


@appointments_bp.route("/patient-quick", methods=["POST"])
@module_required(MODULE)
def patient_quick():
    """Create a minimal patient inline during booking and return it as JSON."""
    from app.models import GENDERS
    from app.utils.patients import generate_patient_number

    data = request.get_json(silent=True) or {}
    name = (data.get("full_name") or "").strip()
    gender = (data.get("gender") or "").strip()
    dob_raw = (data.get("date_of_birth") or "").strip()

    if not name:
        return jsonify({"ok": False, "error": t("appointments.qc_need_name")}), 400
    if gender not in GENDERS:
        return jsonify({"ok": False, "error": t("appointments.qc_need_gender")}), 400
    try:
        dob = datetime.strptime(dob_raw, "%Y-%m-%d").date()
    except ValueError:
        return jsonify({"ok": False, "error": t("appointments.qc_need_dob")}), 400

    patient = Patient(
        patient_number=generate_patient_number(),
        full_name=name,
        gender=gender,
        date_of_birth=dob,
        is_active=True,
    )
    db.session.add(patient)
    db.session.flush()
    ActivityLog.record(
        "patient.create", user_id=current_user.id, entity="patient",
        entity_id=patient.id, detail=patient.patient_number, ip_address=client_ip(),
    )
    db.session.commit()
    return jsonify({"ok": True, "patient": _patient_brief(patient)})


def _patient_brief(p):
    """Compact patient dict for the booking search/quick-create widgets."""
    years, months = p.age_parts
    return {
        "id": p.id,
        "name": p.display_name(),
        "number": p.patient_number,
        "age": f"{years}y {months}m" if years else f"{months}m",
    }


# -------------------------------------------------- status lifecycle -------
@appointments_bp.route("/<int:appt_id>/status", methods=["POST"])
@module_required(MODULE)
def change_status(appt_id):
    appt = db.get_or_404(Appointment, appt_id)
    new_status = (request.form.get("status") or "").strip()

    if not Appointment.valid_status(new_status) or not appt.can_transition_to(new_status):
        flash(t("appointments.invalid_transition"), "warning")
        return _back_to_board(appt)

    # Capture an optional reason when cancelling or marking a no-show.
    if new_status in ("cancelled", "no_show"):
        reason = (request.form.get("cancel_reason") or "").strip()
        if reason:
            appt.cancel_reason = reason

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
    exceptions = []
    if selected:
        rows = DoctorSchedule.query.filter_by(doctor_id=selected).all()
        by_day = {wd: [] for wd in WEEKDAY_ORDER}
        for r in rows:
            by_day.setdefault(r.weekday, []).append(r)
        for wd in WEEKDAY_ORDER:
            schedule_rows.append((wd, sorted(by_day.get(wd, []), key=lambda s: s.start_time)))
        # Upcoming time off / breaks only (past ones are irrelevant).
        exceptions = (
            ScheduleException.query.filter_by(doctor_id=selected)
            .filter(ScheduleException.exc_date >= datetime.today().date())
            .order_by(ScheduleException.exc_date)
            .all()
        )

    free_days, max_days = consult_window_days()
    return render_template(
        "appointments/schedules.html",
        doctors=doctors, selected=selected, schedule_rows=schedule_rows,
        weekday_order=WEEKDAY_ORDER, exceptions=exceptions,
        consult_free_days=free_days, consult_max_days=max_days,
    )


@appointments_bp.route("/consult-settings", methods=["POST"])
@module_required(MODULE)
def consult_settings():
    """Save the consultation follow-up window (free / max days)."""
    free = max(request.form.get("consult_free_days", type=int) or 0, 0)
    mx = max(request.form.get("consult_max_days", type=int) or 0, free)
    Setting.set("consult_free_days", str(free))
    Setting.set("consult_max_days", str(mx))
    db.session.commit()
    flash(t("appointments.consult_window_saved"), "success")
    return redirect(url_for("appointments.schedules"))


@appointments_bp.route("/schedules/<int:schedule_id>/delete", methods=["POST"])
@module_required(MODULE)
def delete_schedule(schedule_id):
    sched = db.get_or_404(DoctorSchedule, schedule_id)
    doctor_id = sched.doctor_id
    db.session.delete(sched)
    db.session.commit()
    flash(t("appointments.schedule_removed"), "info")
    return redirect(url_for("appointments.schedules", doctor_id=doctor_id))


@appointments_bp.route("/schedules/exception", methods=["POST"])
@module_required(MODULE)
def add_exception():
    """Register a doctor's time off: a full day, or a timed break."""
    doctor_id = request.form.get("doctor_id", type=int)
    exc_date = parse_date_arg(request.form.get("exc_date"), default=None)
    full_day = bool(request.form.get("is_full_day"))
    if not doctor_id or exc_date is None:
        flash(t("appointments.exc_need"), "danger")
        return redirect(url_for("appointments.schedules", doctor_id=doctor_id))

    start_t = end_t = None
    if not full_day:
        try:
            start_t = datetime.strptime(request.form.get("start_time") or "", "%H:%M").time()
            end_t = datetime.strptime(request.form.get("end_time") or "", "%H:%M").time()
        except ValueError:
            flash(t("appointments.invalid_time"), "danger")
            return redirect(url_for("appointments.schedules", doctor_id=doctor_id))
        if start_t >= end_t:
            flash(t("appointments.bad_window"), "danger")
            return redirect(url_for("appointments.schedules", doctor_id=doctor_id))

    db.session.add(ScheduleException(
        doctor_id=doctor_id, exc_date=exc_date, is_full_day=full_day,
        start_time=start_t, end_time=end_t,
        reason=(request.form.get("reason") or "").strip() or None,
    ))
    db.session.commit()
    flash(t("appointments.exc_added"), "success")
    return redirect(url_for("appointments.schedules", doctor_id=doctor_id))


@appointments_bp.route("/schedules/exception/<int:exc_id>/delete", methods=["POST"])
@module_required(MODULE)
def delete_exception(exc_id):
    exc = db.get_or_404(ScheduleException, exc_id)
    doctor_id = exc.doctor_id
    db.session.delete(exc)
    db.session.commit()
    flash(t("appointments.exc_removed"), "info")
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
