"""Appointments & smart scheduling (Phase 3).

Includes the doctor's "Today's Appointments" board, conflict-free booking,
the appointment status lifecycle, and per-doctor working-hours schedules.
"""
from datetime import datetime, timedelta

from flask import (
    flash,
    g,
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
from app.utils import appt_reminder as reminders
from app.utils import no_show
from app.utils import patient_flags as flags
from app.utils.clock import local_today
from app.utils.decorators import client_ip, module_required

MODULE = "appointments"


def _appt_type(value):
    """Validate a posted appointment-type key, falling back to the default."""
    from app.utils.visit_types import valid_key
    return value if valid_key(value) else DEFAULT_APPT_TYPE


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
    # With the privacy policy on, a doctor is locked to it (no switching).
    from app.utils.privacy import doctor_locked_id
    locked = doctor_locked_id()
    doctor_id = locked or request.args.get("doctor_id", type=int)
    if doctor_id is None and current_user.role == "doctor":
        doctor_id = current_user.id

    # The board shows each child's name and their guardian's phone, so the
    # patient (and their family) come along rather than one query per row.
    from sqlalchemy.orm import selectinload

    query = (Appointment.query
             .options(selectinload(Appointment.patient)
                      .selectinload(Patient.family))
             .filter(Appointment.appt_date == on_date))
    if doctor_id:
        query = query.filter(Appointment.doctor_id == doctor_id)
    appointments = query.order_by(Appointment.appt_time).all()

    # Stat cards (per the reference design): total / done / waiting / no-show.
    stats = {
        "total": len(appointments),
        "completed": sum(1 for a in appointments if a.status == "completed"),
        "in_progress": sum(1 for a in appointments if a.status == "in_progress"),
        "waiting": sum(1 for a in appointments if a.status in ("waiting", "scheduled")),
        "no_show": sum(1 for a in appointments if a.status == "no_show"),
    }
    # What the nurse measured, read before the child's turn comes round.
    # The station already flags it; this is the same judgement on the screen
    # the *doctor* is looking at, because the nurse cannot always tell how
    # serious a number is and the doctor is the one who decides.
    flags = _red_flags(appointments)

    # Payment snapshot per appointment, so the doctor sees who paid / who's
    # still owing while the clinic is running.
    pay = _payment_status(appointments, on_date)
    stats["paid"] = sum(1 for a in appointments if pay.get(a.id, {}).get("state") == "paid")
    stats["unpaid"] = sum(
        1 for a in appointments if pay.get(a.id, {}).get("state") in ("unpaid", "partial")
    )
    # With one doctor in view, "the current patient" is a question with one
    # answer and the big card below is right. Looking at the whole clinic it
    # is not: ten doctors are examining ten children, and picking the first
    # row that happens to say `in_progress` puts somebody else's patient under
    # a heading that reads "المريض الحالي". So the clinic view gets a card per
    # عيادة instead, and the big card is kept for the doctor's own board.
    current = current_summary = None
    clinics = None
    if doctor_id:
        current = next((a for a in appointments if a.status == "in_progress"), None)
        current_summary = _current_summary(current.patient) if current else None
    else:
        clinics = _clinics_now(appointments, on_date, flags)

    # Collection + the doctor's own share, today and this month (invoice-based,
    # consistent with the doctor statement screen).
    fin = _finance_summary(doctor_id, on_date)

    # Visit-type breakdown (كشف/متابعة/تطعيم…) + new vs returning, day & month.
    breakdown = _visit_breakdown(doctor_id, on_date)

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
        today=local_today().isoformat(),
        stats=stats,
        current=current,
        current_summary=current_summary,
        clinics=clinics,
        waitlist=waitlist,
        appt_types=APPOINTMENT_TYPES,
        pay=pay,
        flags=flags,
        fin=fin,
        breakdown=breakdown,
        bookable_services=_bookable_services(),
        doctor_marks=_doctor_marks(),
        doctor_locked=bool(locked),
    )


def _finance_summary(doctor_id, on_date):
    """Collection + doctor share for a doctor (or the whole clinic) — today and
    month-to-date. Invoice-date based, matching the doctor statement screen."""
    from sqlalchemy.orm import selectinload

    from app.models import Invoice

    month_start = on_date.replace(day=1)
    # The totals below are summed in Python from the lines and the payments,
    # so without loading them up front this is two queries per invoice — and
    # month-to-date on a working clinic is thousands of invoices.
    base = Invoice.query.options(selectinload(Invoice.items),
                                 selectinload(Invoice.payments))
    if doctor_id:
        base = base.filter(Invoice.doctor_id == doctor_id)

    def agg(invoices):
        return {
            "collection": round(sum(i.paid for i in invoices), 2),
            "share": round(sum(i.doctor_share_total for i in invoices), 2),
        }

    return {
        "today": agg(base.filter(Invoice.invoice_date == on_date).all()),
        "month": agg(base.filter(Invoice.invoice_date >= month_start,
                                 Invoice.invoice_date <= on_date).all()),
    }


def _visit_breakdown(doctor_id, on_date):
    """Visit-type breakdown for the board (doctor + reception): how many of each
    visit type (كشف / متابعة / تطعيم …) and how many new vs returning patients —
    today and month-to-date. Whole panel and its month/new-old parts are each
    show/hide-able from settings so the board never gets crowded."""
    if Setting.get("board_show_breakdown", "1") == "0":
        return {"enabled": False}

    from collections import Counter
    from flask import g
    from app.utils.visit_types import active_types, label as vt_label

    lang = getattr(g, "lang", "ar")
    show_month = Setting.get("board_breakdown_month", "1") != "0"
    show_newold = Setting.get("board_breakdown_newold", "1") != "0"
    month_start = on_date.replace(day=1)

    # Real visits only — a cancelled or no-show slot is not a patient seen.
    base = Appointment.query.filter(
        Appointment.status.notin_(("cancelled", "no_show")))
    if doctor_id:
        base = base.filter(Appointment.doctor_id == doctor_id)
    day_appts = base.filter(Appointment.appt_date == on_date).all()
    month_appts = base.filter(Appointment.appt_date >= month_start,
                              Appointment.appt_date <= on_date).all()

    day_c = Counter(a.appt_type for a in day_appts)
    month_c = Counter(a.appt_type for a in month_appts)
    rows, seen = [], set()
    for vt in active_types():
        rows.append({"key": vt.key, "label": vt.display_name(lang),
                     "color": vt.color, "day": day_c.get(vt.key, 0),
                     "month": month_c.get(vt.key, 0)})
        seen.add(vt.key)
    for k in set(day_c) | set(month_c):
        if k not in seen:
            rows.append({"key": k, "label": vt_label(k, lang), "color": "blue",
                         "day": day_c.get(k, 0), "month": month_c.get(k, 0)})

    def _newold(appts, start):
        """New = the patient's first-ever real visit (any doctor) falls inside
        the window; otherwise they are a returning patient."""
        pids = {a.patient_id for a in appts}
        if not pids:
            return {"new": 0, "old": 0, "total": 0}
        firsts = dict(
            db.session.query(Appointment.patient_id,
                             db.func.min(Appointment.appt_date))
            .filter(Appointment.patient_id.in_(pids),
                    Appointment.status.notin_(("cancelled", "no_show")))
            .group_by(Appointment.patient_id).all())
        new = sum(1 for p in pids
                  if firsts.get(p) and start <= firsts[p] <= on_date)
        return {"new": new, "old": len(pids) - new, "total": len(pids)}

    return {
        "enabled": True,
        "show_month": show_month,
        "show_newold": show_newold,
        "rows": rows,
        "total": {"day": len(day_appts), "month": len(month_appts)},
        "newold": {"day": _newold(day_appts, on_date),
                   "month": _newold(month_appts, month_start)},
    }


def _payment_status(appointments, on_date):
    """Map appointment.id -> payment snapshot from that patient's invoices on
    the date. State is one of: ``paid`` / ``partial`` / ``unpaid`` / ``none``
    (no invoice raised yet)."""
    from app.models import Invoice

    if not appointments:
        return {}
    patient_ids = {a.patient_id for a in appointments}
    # Today's invoices, plus any still-outstanding balance from any date — so a
    # charge the doctor added after the patient paid (or a lingering due) shows
    # up for the cashier instead of silently disappearing.
    from sqlalchemy.orm import selectinload

    invoices = (
        Invoice.query
        .options(selectinload(Invoice.items), selectinload(Invoice.payments))
        .filter(
            Invoice.patient_id.in_(patient_ids),
            db.or_(Invoice.invoice_date == on_date,
                   Invoice.status.in_(["unpaid", "partial"])),
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


def _red_flags(appointments):
    """``{appointment_id: flag}`` for the children who have vitals recorded.

    Only the ones still waiting or in the room: a completed visit's flag is
    history, and history on a live board is noise that teaches people to stop
    reading the colour.
    """
    from app.models import Visit
    from app.utils.red_flags import assess

    live = [a for a in appointments if a.status in ("waiting", "in_progress")]
    if not live:
        return {}
    # Newest first, so a child with more than one open visit is judged on the
    # one the nurse just filled rather than on whichever row the database
    # happened to return — which is an older, empty visit as often as not, and
    # produces a board that is silently blank about a feverish infant.
    visits = {}
    for visit in (Visit.query
                  .filter(Visit.patient_id.in_([a.patient_id for a in live]),
                          Visit.status == "open")
                  .order_by(Visit.created_at.desc(), Visit.id.desc()).all()):
        visits.setdefault(visit.patient_id, visit)

    out = {}
    for appt in live:
        visit = visits.get(appt.patient_id)
        flag = assess(appt.patient, getattr(visit, "vitals", None),
                      " ".join(filter(None, [
                          appt.reason, getattr(visit, "chief_complaint", "")])))
        if flag["level"]:
            out[appt.id] = flag
    return out


def _clinics_now(appointments, on_date, flags=None):
    """One card per عيادة that is running today — the whole-clinic view.

    Reception's question is never "who is the current patient"; there is no
    such person once two doctors are working. Their question is "what is the
    state of every عيادة right now", and the part of the answer nobody has
    today is the second line: how many are waiting for each doctor and **how
    long the worst of them has been sitting there**. That is the number that
    turns a complaint at the desk into something the clinic saw coming.

    Doctors with nothing booked today are left out — an empty card for a
    doctor who is off is noise on a screen that has to be read at a glance.
    """
    rooms = _rooms_on(on_date)
    by_doctor = {}
    for appt in appointments:
        by_doctor.setdefault(appt.doctor_id, []).append(appt)

    out = []
    for doctor_id, rows in by_doctor.items():
        waiting = [a for a in rows if a.status in ("waiting", "scheduled")]
        current = next((a for a in rows if a.status == "in_progress"), None)
        # The earliest check-in still waiting *is* the longest wait — handing
        # the screen that moment rather than a number of minutes lets the
        # counter keep ticking instead of freezing at whatever it said when
        # the page was drawn.
        checked_in = [a.checked_in_at for a in waiting if a.checked_in_at]
        out.append({
            "doctor": rows[0].doctor,
            "room": rooms.get(doctor_id),
            "current": current,
            "waiting": len(waiting),
            "longest_since": min(checked_in) if checked_in else None,
            # How many in this عيادة's queue should not be waiting. Reception
            # watches the whole clinic and is the one who can go and knock.
            "urgent": sum(1 for a in rows
                          if (flags or {}).get(a.id, {}).get("level") == "urgent"),
            "done": sum(1 for a in rows if a.status == "completed"),
        })
    # Busy عيادات first — the ones with somebody inside, then by queue length,
    # so the screen puts what needs attention where the eye lands.
    out.sort(key=lambda c: (c["current"] is None, -c["waiting"],
                            c["doctor"].display_name() if c["doctor"] else ""))
    return out


def _rooms_on(on_date):
    """``{doctor_id: ClinicRoom}`` for one day, from the daily assignments."""
    from app.models import RoomAssignment

    rows = (RoomAssignment.query.filter(RoomAssignment.on_date == on_date)
            .join(RoomAssignment.room).all())
    return {row.doctor_id: row.room for row in rows}


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
def booking_open():
    """Whether the clinic is accepting new bookings right now."""
    return Setting.get("clinic_booking_open", "1") != "0"


def _booking_blocked():
    """Whether *this* user may not create an appointment right now.

    One helper because the gate has to hold on **every** way in. It used to be
    written inline in ``create`` and nowhere else, so a paused clinic still took
    walk-ins: the doctor saw "booking paused" on their screen, reception carried
    on registering patients, and the setting was decoration. A guard that covers
    one of two doors is worse than none — it tells the person who flipped it
    that something is being enforced.

    An admin still gets through: the emergency in front of reception is real
    whatever the setting says, and the override is logged.
    """
    if booking_open() or current_user.is_admin:
        return False
    flash(t("appointments.booking_closed_msg"), "warning")
    return True


@appointments_bp.route("/toggle-booking", methods=["POST"])
@module_required(MODULE)
def toggle_booking():
    """Pause / resume accepting new bookings from the clinic (doctor's home).

    A simple clinic-wide gate the doctor flips when the day is full or they're
    stepping out; reception sees a clear banner and can't create appointments
    while it's paused (an admin can still override in an emergency)."""
    now_open = booking_open()
    Setting.set("clinic_booking_open", "0" if now_open else "1")
    ActivityLog.record(
        "appointment.booking_toggle", user_id=current_user.id,
        entity="setting", detail=("closed" if now_open else "open"),
        ip_address=client_ip(),
    )
    db.session.commit()
    flash(t("appointments.booking_paused" if now_open else "appointments.booking_resumed"),
          "info" if now_open else "success")
    return redirect(request.referrer or url_for("main.dashboard"))


@appointments_bp.route("/new", methods=["GET", "POST"])
@module_required(MODULE)
def create():
    doctors = list_doctors()
    is_open = booking_open()

    if request.method == "POST":
        if _booking_blocked():
            return redirect(url_for("appointments.create"))
        patient_id = request.form.get("patient_id", type=int)
        doctor_id = request.form.get("doctor_id", type=int)
        on_date = parse_date_arg(request.form.get("appt_date"), default=None)
        slot = (request.form.get("appt_time") or "").strip()
        reason = (request.form.get("reason") or "").strip()
        appt_type = _appt_type((request.form.get("appt_type") or "").strip())

        error = _validate_booking(patient_id, doctor_id, on_date, slot)
        # A payment block stops the booking unless somebody with financial
        # authority says otherwise on this booking, and that override is
        # recorded with their name — the point of the block is that a decision
        # gets made by a person who can make it, not that the family is turned
        # away by a screen.
        if not error and flags.blocks_booking(patient_id):
            override = request.form.get("flag_override") == "1"
            if not (override and flags.can_clear(current_user)):
                error = t("flags.blocked_booking")
            else:
                ActivityLog.record(
                    "appointment.flag_override", user_id=current_user.id,
                    entity="patient", entity_id=patient_id,
                    ip_address=client_ip())
        if error:
            flash(error, "danger")
            chosen = db.session.get(Patient, patient_id) if patient_id else None
            return render_template(
                "appointments/form.html", doctors=doctors, form=request.form,
                selected_patient=_patient_brief(chosen) if chosen else None,
                appt_types=APPOINTMENT_TYPES, vaccine_brands=_vaccine_brands(),
                doctor_options=_doctor_options(doctors),
                services=_bookable_services(),
                doctor_marks=_doctor_marks(),
                vaccination_service_id=_vaccination_service_id(),
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
        appt.extra_service_ids = _extra_services_arg() or None
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
        # Queue the day-before reminder. Declines quietly for every ordinary
        # reason (manual mode, type off, no phone, booked for later today) —
        # the reminder's settings card is where those are explained, not a
        # flash message on the booking screen.
        reminders.schedule(appt, user_id=current_user.id,
                           lang=getattr(g, "lang", "ar"))
        # They have rebooked, so the "we missed you — shall we book you in?"
        # waiting in the queue would now be asking for something already done.
        no_show.cancel_for_patient(appt.patient_id)
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
        doctor_options=_doctor_options(doctors),
        services=_bookable_services(),
        doctor_marks=_doctor_marks(),
        vaccination_service_id=_vaccination_service_id(),
        booking_open=is_open,
    )


def _doctor_options(doctors):
    """Doctors as plain dicts for the searchable picker on the booking form."""
    lang = getattr(g, "lang", "ar")
    return [{"id": d.id, "name": d.display_name(lang)} for d in doctors]


def _bookable_services():
    """Active services offered as optional extras at booking time."""
    from app.models import Service

    return Service.query.filter_by(is_active=True).order_by(Service.name).all()


def _doctor_marks():
    """Which services each doctor is marked as performing, for the browser.

    The doctor is chosen in the same form as the services here, so the list
    has to reorder as that choice changes — which a server-side split cannot
    do. A doctor with no marks is absent from the map, and the screen then
    behaves exactly as it did before.
    """
    from app.utils.doctor_services import marks_map

    return marks_map()


def _vaccination_service_id():
    """The (free) vaccination service id, so ticking it at booking opens the
    vaccine picker: the service itself costs nothing — the vaccine is what the
    parent pays for."""
    from app.blueprints.finance.routes import _vaccine_service

    try:
        svc = _vaccine_service()
        return svc.id if svc is not None else None
    except Exception:                                   # pragma: no cover
        return None


def _extra_services_arg():
    """Sanitise the extra_services[] checkboxes into a comma-separated id list."""
    ids = [s for s in request.form.getlist("extra_services") if s.strip().isdigit()]
    return ",".join(ids[:20])


@appointments_bp.route("/poll")
@module_required(MODULE)
def poll():
    """Cheap change fingerprint for the board's live refresh.

    Covers what the board actually shows: the queue, whether each patient has
    been billed, and what has been collected. Column-only queries over
    indexed columns; the page reloads only when the answer differs, so idle
    polling costs almost nothing and the screen stays current by itself.
    """
    from app.utils.live import board_fingerprint
    from app.utils.privacy import doctor_locked_id

    on_date = parse_date_arg(request.args.get("date"))
    doctor_id = doctor_locked_id() or request.args.get("doctor_id", type=int)
    return jsonify({"fp": board_fingerprint(on_date, doctor_id)})


@appointments_bp.route("/consult-check")
@module_required(MODULE)
def consult_check():
    """JSON: classify a consultation booking against the follow-up window so the
    booking form can warn reception before saving."""
    info = consultation_window(
        request.args.get("patient_id", type=int),
        request.args.get("doctor_id", type=int),
        parse_date_arg(request.args.get("date"), default=None),
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
    reminders.resync(appt, user_id=current_user.id,
                     lang=getattr(g, "lang", "ar"))
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
    # A walk-in is a new appointment, so the pause applies to it. This is the
    # door the gate was missing, and the one reception actually uses.
    if _booking_blocked():
        return redirect(url_for("appointments.index"))
    patient_id = request.form.get("patient_id", type=int)
    doctor_id = request.form.get("doctor_id", type=int)
    reason = (request.form.get("reason") or "").strip()
    appt_type = _appt_type((request.form.get("appt_type") or "").strip())

    if not patient_id or not db.session.get(Patient, patient_id) or not doctor_id:
        flash(t("appointments.walk_in_need"), "danger")
        return redirect(url_for("appointments.index"))

    # The clinic's day, not the server's: a walk-in taken after midnight
    # local time was being stamped with yesterday and never reached the
    # doctor's station, which asks for local_today().
    today = local_today()
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
        extra_service_ids=_extra_services_arg() or None,
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
    from app.utils.patients import apply_patient_search
    rows = (
        apply_patient_search(Patient.query.filter(Patient.is_active.is_(True)), q)
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
        "phone": p.contact_phone or "",
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
    # A reminder for a cancelled visit is the clinic telling a family to come
    # to something that is not happening.
    reminders.resync(appt, user_id=current_user.id,
                     lang=getattr(g, "lang", "ar"))
    if new_status == "no_show":
        # The most important patient of the day, and the one the program used
        # to do nothing at all about.
        no_show.schedule(appt, user_id=current_user.id,
                         lang=getattr(g, "lang", "ar"))
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
    # Before the row goes: a queued reminder outlives the appointment it points
    # at, and would still go out — to a family whose booking no longer exists.
    reminders.cancel(appt.id)
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

        def _opt_date(name):
            raw = (request.form.get(name) or "").strip()
            try:
                return datetime.strptime(raw, "%Y-%m-%d").date() if raw else None
            except ValueError:
                return None

        db.session.add(DoctorSchedule(
            doctor_id=doctor_id,
            weekday=weekday,
            start_time=datetime.strptime(start_raw, "%H:%M").time(),
            end_time=datetime.strptime(end_raw, "%H:%M").time(),
            slot_minutes=slot_minutes,
            max_patients=max_patients,
            start_date=_opt_date("start_date"),
            end_date=_opt_date("end_date"),
            season_label=(request.form.get("season_label") or "").strip() or None,
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
            .filter(ScheduleException.exc_date >= local_today())
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
    """Register a doctor's time off: a full day, a date *range* (vacation from
    date X to date Y — one row per day), or a timed break within one day."""
    from datetime import timedelta

    doctor_id = request.form.get("doctor_id", type=int)
    exc_date = parse_date_arg(request.form.get("exc_date"), default=None)
    exc_date_to = parse_date_arg(request.form.get("exc_date_to"), default=None)
    full_day = bool(request.form.get("is_full_day"))
    if not doctor_id or exc_date is None:
        flash(t("appointments.exc_need"), "danger")
        return redirect(url_for("appointments.schedules", doctor_id=doctor_id))

    start_t = end_t = None
    if not full_day:
        exc_date_to = None  # a timed break applies to a single day
        try:
            start_t = datetime.strptime(request.form.get("start_time") or "", "%H:%M").time()
            end_t = datetime.strptime(request.form.get("end_time") or "", "%H:%M").time()
        except ValueError:
            flash(t("appointments.invalid_time"), "danger")
            return redirect(url_for("appointments.schedules", doctor_id=doctor_id))
        if start_t >= end_t:
            flash(t("appointments.bad_window"), "danger")
            return redirect(url_for("appointments.schedules", doctor_id=doctor_id))

    # Expand a vacation range into one row per day (capped at 60 days),
    # skipping days that already have a full-day exception.
    last = exc_date_to if (exc_date_to and exc_date_to > exc_date) else exc_date
    if (last - exc_date).days > 60:
        last = exc_date + timedelta(days=60)
    reason = (request.form.get("reason") or "").strip() or None
    existing = {e.exc_date for e in ScheduleException.query.filter(
        ScheduleException.doctor_id == doctor_id,
        ScheduleException.exc_date >= exc_date,
        ScheduleException.exc_date <= last,
        ScheduleException.is_full_day.is_(True)).all()}
    added = 0
    day = exc_date
    while day <= last:
        if not (full_day and day in existing):
            db.session.add(ScheduleException(
                doctor_id=doctor_id, exc_date=day, is_full_day=full_day,
                start_time=start_t, end_time=end_t, reason=reason))
            added += 1
        day += timedelta(days=1)
    db.session.commit()
    flash(t("appointments.exc_added_n").replace("{n}", str(added))
          if added > 1 else t("appointments.exc_added"), "success")
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


# --------------------------------------------------------- عيادات ----------
@appointments_bp.route("/clinics")
@module_required(MODULE)
def clinics():
    """The عيادات, and who is working in each one on a chosen day.

    Deliberately a *daily* screen rather than a settings page. A doctor is not
    in the same عيادة every day — shifts swap, somebody is on leave, one
    عيادة has the nebuliser this week — so the thing reception actually does
    is set today's arrangement each morning, and the thing a manager actually
    asks is who was where last Tuesday. Both are the same screen with a
    different date.
    """
    from app.models import ClinicRoom, RoomAssignment

    on_date = parse_date_arg(request.args.get("date"))
    rooms = (ClinicRoom.query.order_by(ClinicRoom.sort_order, ClinicRoom.code)
             .all())
    assigned = {row.doctor_id: row for row in
                RoomAssignment.query.filter_by(on_date=on_date).all()}
    # Yesterday's arrangement, offered as the starting point — most days are
    # the same as the day before, and retyping the whole clinic every morning
    # is how a feature stops being used by the second week.
    previous = _previous_assignment(on_date)
    return render_template(
        "appointments/clinics.html", rooms=rooms, doctors=list_doctors(),
        assigned=assigned, previous=previous, on_date=on_date,
        today=local_today().isoformat(),
        prev_date=(on_date - timedelta(days=1)).isoformat(),
        next_date=(on_date + timedelta(days=1)).isoformat(),
    )


def _previous_assignment(on_date):
    """``{doctor_id: room_id}`` from the most recent day that had any."""
    from app.models import RoomAssignment

    last = (RoomAssignment.query.filter(RoomAssignment.on_date < on_date)
            .order_by(RoomAssignment.on_date.desc()).first())
    if last is None:
        return {}
    rows = RoomAssignment.query.filter_by(on_date=last.on_date).all()
    return {row.doctor_id: row.room_id for row in rows}


@appointments_bp.route("/clinics/add", methods=["POST"])
@module_required(MODULE)
def clinic_add():
    """Add a عيادة. The number generates itself — the clinic's own rule for
    everything the program creates."""
    from app.models import ClinicRoom

    room = ClinicRoom(
        code=ClinicRoom.next_code(),
        name_ar=(request.form.get("name_ar") or "").strip() or None,
        name_en=(request.form.get("name_en") or "").strip() or None,
    )
    db.session.add(room)
    ActivityLog.record("clinic_room.create", user_id=current_user.id,
                       entity="clinic_room", detail=str(room.code),
                       ip_address=client_ip())
    db.session.commit()
    flash(t("rooms.added"), "success")
    return redirect(url_for("appointments.clinics",
                            date=request.form.get("date") or None))


@appointments_bp.route("/clinics/<int:room_id>/edit", methods=["POST"])
@module_required(MODULE)
def clinic_edit(room_id):
    from app.models import ClinicRoom

    room = db.get_or_404(ClinicRoom, room_id)
    room.name_ar = (request.form.get("name_ar") or "").strip() or None
    room.name_en = (request.form.get("name_en") or "").strip() or None
    room.is_active = bool(request.form.get("is_active"))
    ActivityLog.record("clinic_room.update", user_id=current_user.id,
                       entity="clinic_room", entity_id=room.id,
                       ip_address=client_ip())
    db.session.commit()
    flash(t("rooms.saved"), "success")
    return redirect(url_for("appointments.clinics",
                            date=request.form.get("date") or None))


@appointments_bp.route("/clinics/<int:room_id>/delete", methods=["POST"])
@module_required(MODULE)
def clinic_delete(room_id):
    """Remove a عيادة — but never one that days of history point at.

    Deleting it would take its assignments with it (cascade), and "who was in
    عيادة ٢ that Tuesday" would quietly become unanswerable. A عيادة that has
    been used gets switched off instead, which keeps the past readable and
    still takes it off tomorrow's list.
    """
    from app.models import ClinicRoom

    room = db.get_or_404(ClinicRoom, room_id)
    if room.assignments:
        room.is_active = False
        flash(t("rooms.deactivated_instead"), "warning")
    else:
        db.session.delete(room)
        flash(t("rooms.deleted"), "success")
    ActivityLog.record("clinic_room.delete", user_id=current_user.id,
                       entity="clinic_room", entity_id=room_id,
                       ip_address=client_ip())
    db.session.commit()
    return redirect(url_for("appointments.clinics",
                            date=request.form.get("date") or None))


@appointments_bp.route("/clinics/assign", methods=["POST"])
@module_required(MODULE)
def clinic_assign():
    """Set (or clear) which عيادة each doctor is in on one day."""
    from app.models import ClinicRoom, RoomAssignment

    on_date = parse_date_arg(request.form.get("date"))
    valid = {r.id for r in ClinicRoom.query.all()}
    existing = {row.doctor_id: row for row in
                RoomAssignment.query.filter_by(on_date=on_date).all()}

    for doctor in list_doctors():
        room_id = request.form.get(f"room_{doctor.id}", type=int)
        row = existing.get(doctor.id)
        if room_id in valid:
            if row is None:
                db.session.add(RoomAssignment(on_date=on_date,
                                              doctor_id=doctor.id,
                                              room_id=room_id))
            else:
                row.room_id = room_id
        elif row is not None:
            db.session.delete(row)      # "— " means not working here today

    ActivityLog.record("clinic_room.assign", user_id=current_user.id,
                       entity="clinic_room", detail=on_date.isoformat(),
                       ip_address=client_ip())
    db.session.commit()
    flash(t("rooms.assigned"), "success")
    return redirect(url_for("appointments.clinics", date=on_date.isoformat()))
