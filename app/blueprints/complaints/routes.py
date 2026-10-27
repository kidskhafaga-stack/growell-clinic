"""The complaints book: register (anybody), handle (customer service).

``/complaints/new`` is open to everybody who works here — the receptionist
who hears it at the desk, the nurse told it on the ward — and ends on a
receipt with the number to hand the family. Everything after that, the
list, the case and every step on it, is ``complaints_manage``.
"""
from datetime import datetime, timedelta

from flask import (abort, flash, g, redirect, render_template, request,
                   url_for)
from flask_login import current_user, login_required

from app.blueprints.complaints import complaints_bp
from app.extensions import db
from app.i18n import t
from app.models import ActivityLog, Patient, Setting, User
from app.models.complaint import (BY_WHO, CATEGORIES, CHANNELS, DECISIONS,
                                  KINDS, OPEN_STATUSES, PHONE_NOTES,
                                  ROOT_CAUSES, SEVERITIES, SIDES, Complaint)
from app.utils import complaint_cases as cases
from app.utils.decorators import admin_required, capability_required
from app.utils.paging import paginate

MANAGE = cases.CAPABILITY


def _lang():
    return getattr(g, "lang", "ar")


def _centres():
    from app.utils import cost_centres
    cost_centres.ensure_all()
    return cost_centres.listing()


def _handlers():
    """Who a case can be handed to: the people who can handle one."""
    rows = User.query.filter_by(is_active=True).order_by(User.full_name).all()
    return [u for u in rows if u.can(MANAGE)]


def _patient_from(form_or_args):
    pid = form_or_args.get("patient_id", type=int)
    if pid:
        return db.session.get(Patient, pid)
    number = (form_or_args.get("patient_number") or "").strip()
    if number:
        return Patient.query.filter_by(patient_number=number).first()
    return None


def _thread_text(key):
    """The family's last words on a WhatsApp thread, to start the case from."""
    from app.models import MessageLog

    q = MessageLog.query.filter_by(direction="in")
    if key.startswith("p") and key[1:].isdigit():
        q = q.filter_by(patient_id=int(key[1:]))
    else:
        q = q.filter(MessageLog.patient_id.is_(None), MessageLog.to_phone == key)
    row = q.order_by(MessageLog.created_at.desc()).first()
    return (row.body or "") if row is not None else ""


def _thread_patient(key):
    if key.startswith("p") and key[1:].isdigit():
        return db.session.get(Patient, int(key[1:]))
    return None


def _staff_list():
    """Everybody who works here and is active — who a case can be about,
    and who can bring one."""
    return User.query.filter_by(is_active=True).order_by(User.full_name).all()


def _users(ids):
    ids = [i for i in ids if i]
    return User.query.filter(User.id.in_(ids)).all() if ids else []


def _phone_from(form, patient):
    """``(number, note)``: one of the file's numbers as it is, or another
    number with the reason it is not the file's (ش-١)."""
    picked = (form.get("phone_pick") or "").strip()
    on_file = {p["phone"] for p in cases.file_phones(patient)}
    if picked and picked != "other" and picked in on_file:
        return picked, None
    other = (form.get("contact_phone") or "").strip()
    if not other:
        return None, None
    if other in on_file:
        return other, None
    return other, form.get("phone_note")


# ------------------------------------------------------------ register ---
@complaints_bp.route("/patient-search")
@login_required
def patient_search():
    """JSON: the children a search matches — for the register form, which
    everybody who works here may use (the desk, the ward, the nurse). The
    same search as everywhere: name in either language, file number,
    guardian, phone, date of birth."""
    from flask import jsonify

    from app.utils.patients import apply_patient_search

    query = (request.args.get("q") or "").strip()
    if len(query) < 2:
        return jsonify([])
    rows = (apply_patient_search(Patient.query.filter(Patient.is_active.is_(True)), query)
            .order_by(Patient.full_name).limit(15).all())
    lang = _lang()
    return jsonify([{"id": p.id, "name": p.display_name(lang), "number": p.patient_number}
                    for p in rows])


@complaints_bp.route("/patient/<int:patient_id>/facts")
@login_required
def patient_facts(patient_id):
    """JSON: the numbers on the child's file and its last visits — what the
    register form offers once a child is chosen."""
    from flask import jsonify

    patient = db.get_or_404(Patient, patient_id)
    lang = _lang()
    return jsonify({
        "phones": [dict(p, label=t("cmp.rel_" + p["who"]) if p["who"] in
                        ("father", "mother", "guardian", "child") else p["who"])
                   for p in cases.file_phones(patient, lang)],
        "visits": [{"id": v.id, "date": v.visit_date.isoformat(),
                    "doctor": v.doctor.display_name(lang) if getattr(v, "doctor", None) else ""}
                   for v in cases.recent_visits(patient)],
    })


@complaints_bp.route("/new", methods=["GET", "POST"])
@login_required
def new():
    lang = _lang()
    if request.method == "POST":
        form = request.form
        patient = _patient_from(form)
        phone, note = _phone_from(form, patient)
        by_who = form.get("by_who")
        by_staff = (db.session.get(User, form.get("by_staff_id", type=int) or 0)
                    if by_who == "staff" else None)
        visit = None
        if form.get("visit_id", type=int):
            from app.models import Visit
            visit = db.session.get(Visit, form.get("visit_id", type=int))
        try:
            case = cases.open_case(
                form.get("description"), kind=form.get("kind"),
                channel=form.get("channel"), patient=patient,
                contact_name=form.get("contact_name"),
                contact_phone=phone,
                anonymous=bool(form.get("anonymous")), side=form.get("side"),
                severity=form.get("severity"),
                cost_centre_id=form.get("cost_centre_id", type=int),
                wanted=form.get("wanted"), user=current_user,
                thread_key=(form.get("thread") or "").strip()[:40] or None,
                notify=bool(form.get("notify")), lang=lang,
                by_who=by_who, by_staff=by_staff, phone_note=note, visit=visit,
                category=form.get("category"),
                staff=_users(form.getlist("staff_ids", type=int)))
        except ValueError:
            flash(t("cmp.need_description"), "danger")
            return redirect(request.referrer or url_for("complaints.new"))
        ActivityLog.record("complaint.open", user_id=current_user.id,
                           entity="complaint", entity_id=case.id,
                           detail=case.number)
        db.session.commit()
        flash(t("cmp.opened", number=case.number), "success")
        return redirect(url_for("complaints.receipt", case_id=case.id))

    thread = (request.args.get("thread") or "").strip()[:40]
    patient = _patient_from(request.args) or (_thread_patient(thread) if thread else None)
    kind = request.args.get("kind") if request.args.get("kind") in KINDS else "complaint"
    return render_template(
        "complaints/new.html", patient=patient, thread=thread, kind=kind,
        said=_thread_text(thread) if thread else "",
        channel=request.args.get("channel") or ("whatsapp" if thread else "desk"),
        kinds=KINDS, channels=CHANNELS, sides=SIDES, severities=SEVERITIES,
        categories=CATEGORIES, by_whos=BY_WHO, phone_notes=PHONE_NOTES,
        staff=_staff_list(), staff_names={u.id: u.display_name(lang) for u in _staff_list()},
        centres=_centres(), hours=cases.first_contact_hours(),
        days=cases.close_days())


def _may_see_receipt(case):
    return current_user.can(MANAGE) or case.created_by == current_user.id


@complaints_bp.route("/<int:case_id>/receipt")
@login_required
def receipt(case_id):
    case = db.get_or_404(Complaint, case_id)
    if not _may_see_receipt(case):
        abort(403)
    return render_template("complaints/receipt.html", case=case,
                           hours=cases.first_contact_hours(),
                           days=cases.close_days())


@complaints_bp.route("/blank")
@login_required
def blank():
    """The paper form, empty — for the counter, the ward, the waiting room."""
    return render_template("complaints/blank.html", centres=_centres(),
                           kinds=KINDS, sides=SIDES,
                           hours=cases.first_contact_hours(),
                           days=cases.close_days())


@complaints_bp.route("/invite/<int:patient_id>", methods=["POST"])
@login_required
def invite(patient_id):
    """Send the family a link to write it themselves."""
    from app.utils import whatsapp as wa

    patient = db.get_or_404(Patient, patient_id)
    if not patient.contact_phone:
        flash(t("cmp.no_phone"), "warning")
        return redirect(request.referrer or url_for("patients.view", patient_id=patient.id))
    lang = _lang()
    name = patient.display_name(lang)
    body = wa.render(wa.template_body("complaint_invite"), {
        "patient": name, "first_name": name.split()[0] if name else "",
        "clinic": Setting.get("clinic_name_ar") or Setting.get("clinic_name") or "",
        "link": cases.invite_link(patient),
    }).strip()
    log = wa.send(body, patient.contact_phone, patient_id=patient.id,
                  user_id=current_user.id, template_type="complaint_invite",
                  ignore_window=True)
    db.session.commit()
    # Manual mode: a click-to-send link, for the person standing here.
    if log.provider == "web" and log.link:
        return redirect(log.link)
    flash(t("cmp.invite_sent") if log.status not in ("failed", "skipped")
          else t("cmp.invite_failed"), "info")
    return redirect(request.referrer or url_for("patients.view", patient_id=patient.id))


# --------------------------------------------------------------- handle ---
VIEWS = ("open", "late", "mine", "closed", "all")


@complaints_bp.route("/")
@login_required
@capability_required(MANAGE)
def index():
    view = request.args.get("view") if request.args.get("view") in VIEWS else "open"
    kind = request.args.get("kind") if request.args.get("kind") in KINDS else None
    search = (request.args.get("q") or "").strip()
    q = Complaint.query
    if view in ("open", "late"):
        q = q.filter(Complaint.status.in_(OPEN_STATUSES))
    elif view == "mine":
        q = q.filter(Complaint.owner_id == current_user.id,
                     Complaint.status.in_(OPEN_STATUSES))
    elif view == "closed":
        q = q.filter(Complaint.status == "closed")
    if kind:
        q = q.filter(Complaint.kind == kind)
    # The board's numbers open here (ش-٥): each one narrows the list to the
    # cases behind it.
    narrowed = {}
    for key, column, allowed in (("category", Complaint.category, CATEGORIES),
                                 ("channel", Complaint.channel, CHANNELS),
                                 ("severity", Complaint.severity, SEVERITIES),
                                 ("side", Complaint.side, SIDES),
                                 ("cause", Complaint.root_cause, ROOT_CAUSES),
                                 ("decision", Complaint.decision, DECISIONS)):
        value = request.args.get(key)
        if value in allowed:
            q = q.filter(column == value)
            narrowed[key] = value
    for key, column in (("centre", Complaint.cost_centre_id), ("patient", Complaint.patient_id)):
        value = request.args.get(key, type=int)
        if value:
            q = q.filter(column == value)
            narrowed[key] = value
    staff_id = request.args.get("staff", type=int)
    if staff_id:
        from app.models.complaint import complaint_staff
        q = q.filter(Complaint.id.in_(db.session.query(complaint_staff.c.complaint_id)
                                      .filter(complaint_staff.c.user_id == staff_id)))
        narrowed["staff"] = staff_id
    if request.args.get("done") == "1":
        q = q.filter(Complaint.done_at.isnot(None))
        narrowed["done"] = "1"
    if request.args.get("from") or request.args.get("to"):
        from app.utils import cs_board
        start, end = cs_board.period(request.args.get("from"), request.args.get("to"))
        q = q.filter(Complaint.created_at >= start, Complaint.created_at < end)
        narrowed["from"], narrowed["to"] = [d.isoformat() for d in cs_board.dates(start, end)]
    if search:
        like = f"%{search}%"
        q = q.outerjoin(Patient, Complaint.patient_id == Patient.id).filter(
            db.or_(Complaint.number.ilike(like), Complaint.contact_name.ilike(like),
                   Complaint.contact_phone.ilike(like), Patient.full_name.ilike(like),
                   Complaint.description.ilike(like)))
    q = q.order_by(Complaint.created_at.asc() if view in ("open", "late", "mine")
                   else Complaint.created_at.desc())
    if view == "late":
        q = cases.late_cases(q)
    page = paginate(q)
    now = datetime.utcnow()
    hours, days = cases.first_contact_hours(), cases.close_days()
    return render_template(
        "complaints/index.html", page=page, view=view, kind=kind, search=search,
        narrowed=narrowed,
        counts=cases.open_counts(), kinds=KINDS,
        late={c.id for c in page.items if cases.is_late(c, now, hours, days)},
        month=cases.summary(now - timedelta(days=30), None),
        hours=hours, days=days)


@complaints_bp.route("/board")
@login_required
@capability_required(MANAGE)
def board():
    """The complaints and suggestions board for a period (ش-٥) — see
    ``utils/complaint_board``. Every number opens the cases behind it."""
    from app.utils import complaint_board, cs_board
    from app.utils.clock import local_today

    start, end = cs_board.period(request.args.get("from"), request.args.get("to"))
    first, last = cs_board.dates(start, end)
    today = local_today()
    presets = [(key, (today - timedelta(days=back)).isoformat(), today.isoformat())
               for key, back in (("today", 0), ("week", 6), ("month", 29),
                                 ("quarter", 89), ("year", 364))]
    return render_template(
        "complaints/board.html", d=complaint_board.board(start, end),
        start=first, last=last, prev=list(cs_board.dates(*cs_board.previous(start, end))),
        presets=presets, min_staff=complaint_board.MIN_FOR_STAFF,
        colour=cs_board.colour, hours=cases.first_contact_hours(), days=cases.close_days())


@complaints_bp.route("/<int:case_id>")
@login_required
@capability_required(MANAGE)
def view(case_id):
    case = db.get_or_404(Complaint, case_id)
    now = datetime.utcnow()
    hours, days = cases.first_contact_hours(), cases.close_days()
    return render_template(
        "complaints/case.html", case=case, handlers=_handlers(),
        centres=_centres(), sides=SIDES, severities=SEVERITIES,
        late_contact=cases.late_contact(case, now),
        late_close=cases.late_close(case, now), hours=hours, days=days,
        contact_due=case.contact_due(hours), close_due=case.close_due(days),
        verdict_link=cases.link(case), categories=CATEGORIES,
        root_causes=ROOT_CAUSES, decisions=DECISIONS, staff=_staff_list(),
        staff_names={u.id: u.display_name(_lang()) for u in _staff_list()},
        repeats=cases.repeats(case))


ACTS = ("assign", "contact", "note", "answer", "close", "reopen", "details",
        "decide", "done", "staff")


@complaints_bp.route("/<int:case_id>/act", methods=["POST"])
@login_required
@capability_required(MANAGE)
def act(case_id):
    case = db.get_or_404(Complaint, case_id)
    do = request.form.get("do")
    if do not in ACTS:
        abort(400)
    text = request.form.get("text")
    if do == "assign":
        owner = db.session.get(User, request.form.get("owner_id", type=int) or 0)
        if owner is None or not owner.can(MANAGE):
            flash(t("cmp.bad_owner"), "danger")
            return redirect(url_for("complaints.view", case_id=case.id))
        cases.assign(case, owner, current_user)
    elif do == "contact":
        if not (text or "").strip():
            flash(t("cmp.need_text"), "danger")
            return redirect(url_for("complaints.view", case_id=case.id))
        cases.contacted(case, text, current_user)
    elif do == "note":
        cases.note(case, text, current_user)
    elif do == "answer":
        try:
            cases.answer(case, request.form.get("finding"),
                         request.form.get("action"), request.form.get("answer"),
                         current_user, notify=bool(request.form.get("notify")),
                         lang=_lang())
        except ValueError:
            flash(t("cmp.need_answer"), "danger")
            return redirect(url_for("complaints.view", case_id=case.id))
        cause = request.form.get("root_cause")
        if cause in ROOT_CAUSES:
            case.root_cause = cause
    elif do == "decide":
        from datetime import date as _date
        try:
            target = _date.fromisoformat(request.form.get("target_date") or "")
        except ValueError:
            target = None
        try:
            cases.decide(case, request.form.get("decision"), request.form.get("plan"),
                         current_user, target_date=target,
                         notify=bool(request.form.get("notify")), lang=_lang())
        except ValueError:
            flash(t("cmp.need_decision"), "danger")
            return redirect(url_for("complaints.view", case_id=case.id))
    elif do == "done":
        try:
            cases.implemented(case, text, current_user)
        except ValueError:
            flash(t("cmp.need_done"), "danger")
            return redirect(url_for("complaints.view", case_id=case.id))
    elif do == "staff":
        cases.set_staff(case, _users(request.form.getlist("staff_ids", type=int)), current_user)
    elif do == "close":
        if case.status == "closed":
            return redirect(url_for("complaints.view", case_id=case.id))
        cases.close(case, text, current_user)
    elif do == "reopen":
        if case.status != "closed":
            return redirect(url_for("complaints.view", case_id=case.id))
        cases.reopen(case, text, current_user)
    elif do == "details":
        changed = []
        for field, allowed in (("side", SIDES), ("severity", SEVERITIES),
                               ("category", CATEGORIES), ("root_cause", ROOT_CAUSES)):
            value = request.form.get(field)
            if field in ("category", "root_cause") and value == "":
                value = None
                if getattr(case, field) is not None and field in request.form:
                    setattr(case, field, None)
                    changed.append(field)
                continue
            if value in allowed and getattr(case, field) != value:
                setattr(case, field, value)
                changed.append(field)
        centre = request.form.get("cost_centre_id", type=int)
        if centre != case.cost_centre_id:
            case.cost_centre_id = centre
            changed.append("cost_centre")
        if changed:
            cases.log(case, "edited", ",".join(changed), current_user)
    ActivityLog.record(f"complaint.{do}", user_id=current_user.id,
                       entity="complaint", entity_id=case.id, detail=case.number)
    db.session.commit()
    flash(t("cmp.done_" + do), "success")
    return redirect(url_for("complaints.view", case_id=case.id))


@complaints_bp.route("/<int:case_id>/print")
@login_required
@capability_required(MANAGE)
def print_case(case_id):
    case = db.get_or_404(Complaint, case_id)
    return render_template("complaints/print.html", case=case,
                           hours=cases.first_contact_hours(),
                           days=cases.close_days())


@complaints_bp.route("/settings", methods=["POST"])
@login_required
@admin_required
def settings():
    """The clinic's own timeframes (PCC.16 d) — its policy, not ours."""
    for key, lo, hi in (("complaint_contact_hours", 1, 720),
                        ("complaint_close_days", 1, 90)):
        value = request.form.get(key, type=int)
        if value is not None and lo <= value <= hi:
            Setting.set(key, str(value))
    db.session.commit()
    flash(t("cmp.settings_saved"), "success")
    return redirect(url_for("complaints.index"))
