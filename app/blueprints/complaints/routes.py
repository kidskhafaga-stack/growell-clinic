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
from app.models.complaint import (CHANNELS, KINDS, OPEN_STATUSES, SEVERITIES,
                                  SIDES, Complaint)
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


# ------------------------------------------------------------ register ---
@complaints_bp.route("/new", methods=["GET", "POST"])
@login_required
def new():
    lang = _lang()
    if request.method == "POST":
        form = request.form
        patient = _patient_from(form)
        try:
            case = cases.open_case(
                form.get("description"), kind=form.get("kind"),
                channel=form.get("channel"), patient=patient,
                contact_name=form.get("contact_name"),
                contact_phone=form.get("contact_phone"),
                anonymous=bool(form.get("anonymous")), side=form.get("side"),
                severity=form.get("severity"),
                cost_centre_id=form.get("cost_centre_id", type=int),
                wanted=form.get("wanted"), user=current_user,
                thread_key=(form.get("thread") or "").strip()[:40] or None,
                notify=bool(form.get("notify")), lang=lang)
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
    return render_template(
        "complaints/new.html", patient=patient, thread=thread,
        said=_thread_text(thread) if thread else "",
        channel=request.args.get("channel") or ("whatsapp" if thread else "desk"),
        kinds=KINDS, channels=CHANNELS, sides=SIDES, severities=SEVERITIES,
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
        counts=cases.open_counts(), kinds=KINDS,
        late={c.id for c in page.items if cases.is_late(c, now, hours, days)},
        month=cases.summary(now - timedelta(days=30), None),
        hours=hours, days=days)


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
        verdict_link=cases.link(case))


ACTS = ("assign", "contact", "note", "answer", "close", "reopen", "details")


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
        for field, allowed in (("side", SIDES), ("severity", SEVERITIES)):
            value = request.form.get(field)
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
