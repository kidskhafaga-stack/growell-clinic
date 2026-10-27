"""The assessments screens — ASSESSMENTS_PLAN.md ت-١.

A child's assessments; a new one from the form the clinic fills for its kind;
filling it (a draft, then sent to a doctor); the doctor's approval; the
printed report; the doctor's list of what waits for approval; and the screen
where the clinic edits a kind's form («عدّل الشكل»).
"""
from functools import wraps

from flask import abort, flash, g, redirect, render_template, request, url_for
from flask_login import current_user

from app.blueprints.assessments import assessments_bp
from app.extensions import db
from app.i18n import t
from app.utils import assessments as asm


def _door(view):
    """Who may, before whether it is on: a role with no business here is
    refused; then a clinic without the specialties module has no such page."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        from flask import current_app

        if not current_user.is_authenticated:
            return current_app.login_manager.unauthorized()
        if not asm.may_read(current_user):
            abort(403, description=t("auth.no_permission"))
        if not asm.on():
            abort(404)
        return view(*args, **kwargs)

    return wrapped


def _lang():
    return getattr(g, "lang", "ar")


def _refuse(err, back):
    db.session.rollback()
    flash(t(f"assessment.err_{err}"), "warning")
    return redirect(back)


@assessments_bp.route("/patient/<int:patient_id>")
@_door
def patient_list(patient_id):
    from app.models import Patient
    from app.utils.clock import local_today

    patient = db.get_or_404(Patient, patient_id)
    return render_template("assessments/patient.html", patient=patient,
                           rows=asm.for_patient(patient.id), kinds=asm.kinds(_lang()),
                           may_write=asm.may_write(current_user), asm=asm,
                           overview=asm.overview(patient),
                           age_months=asm.months_on(patient, local_today()))


@assessments_bp.route("/patient/<int:patient_id>/new", methods=["POST"])
@_door
def start(patient_id):
    from app.models import Patient, Visit

    patient = db.get_or_404(Patient, patient_id)
    visit = db.session.get(Visit, request.form.get("visit_id", type=int) or 0)
    if visit is not None and visit.patient_id != patient.id:
        visit = None
    try:
        row = asm.start(patient, request.form.get("kind"), current_user, visit=visit)
    except asm.AssessmentError as err:
        return _refuse(err, url_for("assessments.patient_list", patient_id=patient.id))
    db.session.commit()
    return redirect(url_for("assessments.view", assessment_id=row.id))


def _row(assessment_id):
    from app.models import Assessment

    return db.get_or_404(Assessment, assessment_id)


@assessments_bp.route("/<int:assessment_id>")
@_door
def view(assessment_id):
    row = _row(assessment_id)
    editing = row.status != "approved" and asm.may_write(current_user)
    return render_template("assessments/form.html", row=row, patient=row.patient,
                           form=row.form, answers=row.answers or {}, editing=editing,
                           history=asm.history(row), age=asm.age_on(row.patient, row.assessed_on),
                           may_approve=asm.may_approve(current_user) and row.status != "approved",
                           may_edit_form=asm.may_edit_form(current_user), asm=asm,
                           may_send=_may_send(current_user) and row.status == "approved",
                           shares=_shares(row), **_progress(row), **_questionnaires(row))


def _questionnaires(row):
    """The questionnaires this assessment can hand over, and those it did (ت-٤)."""
    from app.utils import lab_share
    from app.utils import questionnaires as qn

    offered = qn.offered(row) if row.status != "approved" else []
    return {"q_offered": [{"key": k, "shape": sh, "langs": qn.build_form(k)["langs"],
                           "age_outside": qn.age_outside(sh, row.patient, row.assessed_on)}
                          for k, sh in offered],
            "q_requests": qn.for_assessment(row), "q_online": lab_share.online(),
            "q_phone": row.patient.contact_phone if row.patient else ""}


def _progress(row):
    """How far along and which way (ت-٥), for every page that shows it."""
    return {"chrono": asm.months_on(row.patient, row.assessed_on),
            "development": asm.development(row), "progress": asm.progress(row),
            "trends": asm.trends(row)}


def _shares(row):
    from app.utils import assessment_share

    return assessment_share.sent(row) if row.status == "approved" else []


@assessments_bp.route("/<int:assessment_id>/save", methods=["POST"])
@_door
def save(assessment_id):
    row = _row(assessment_id)
    back = url_for("assessments.view", assessment_id=row.id)
    try:
        asm.save(row, request.form, current_user)
        if request.form.get("then") == "review":
            asm.send_for_review(row, current_user)
    except asm.AssessmentError as err:
        return _refuse(err, back)
    db.session.commit()
    flash(t("assessment.sent" if row.status == "review" else "assessment.saved"), "success")
    return redirect(back)


@assessments_bp.route("/<int:assessment_id>/approve", methods=["POST"])
@_door
def approve(assessment_id):
    row = _row(assessment_id)
    back = url_for("assessments.view", assessment_id=row.id)
    try:
        asm.approve(row, current_user, note=request.form.get("doctor_note"))
    except asm.AssessmentError as err:
        return _refuse(err, back)
    db.session.commit()
    flash(t("assessment.approved"), "success")
    return redirect(back)


@assessments_bp.route("/<int:assessment_id>/report")
@_door
def report(assessment_id):
    from app.utils.clock import local_now

    row = _row(assessment_id)
    return render_template("assessments/report.html", row=row, patient=row.patient,
                           form=row.form, answers=row.answers or {},
                           history=asm.history(row), age=asm.age_on(row.patient, row.assessed_on),
                           printed_at=local_now(), asm=asm, **_progress(row))


# ------------------------------------------------ to the family (ت-٣) ---
def _may_send(user):
    return asm.may_write(user) or asm.may_approve(user)


@assessments_bp.route("/<int:assessment_id>/send", methods=["POST"])
@_door
def send(assessment_id):
    """The approved report to the family on WhatsApp — a link, or the file
    when the clinic cannot be reached from outside (``utils/assessment_share``)."""
    from app.utils import assessment_share

    row = _row(assessment_id)
    back = url_for("assessments.view", assessment_id=row.id)
    if not _may_send(current_user):
        abort(403, description=t("auth.no_permission"))
    try:
        share, _log = assessment_share.send(row, current_user, _lang())
    except assessment_share.ShareError as err:
        db.session.rollback()
        flash(t(f"asm_share.err_{err.code}"), "warning")
        return redirect(back)
    db.session.commit()
    flash(t("asm_share.sent_link" if share.mode == "link" else "asm_share.sent_file"), "success")
    return redirect(back)


@assessments_bp.route("/<int:assessment_id>/sheet")
@_door
def sheet(assessment_id):
    """The family's page as a file, to send by hand or keep."""
    from flask import Response

    from app.utils import assessment_share

    row = _row(assessment_id)
    if not row.is_approved:
        abort(404)
    return Response(assessment_share.sheet(row, request.args.get("lang") or _lang()),
                    mimetype="text/html; charset=utf-8",
                    headers={"Content-Disposition":
                             f"attachment; filename={assessment_share.file_name(row)}"})


@assessments_bp.route("/r/<token>", methods=["GET", "POST"])
def shared(token):
    """What the family opens from the message: the child's date of birth
    first; the link ends after its days and five wrong answers lock it."""
    from app.utils import assessment_share, lab_share

    share = assessment_share.by_token(token)
    status = lab_share.state(share)
    if status == "ok" and not share.assessment.is_approved:
        status = "gone"
    if status != "ok":
        return render_template("assessments/shared_link.html", status=status), \
            404 if status == "gone" else 410
    wrong = False
    if request.method == "POST":
        if lab_share.check(share, request.form.get("born")):
            page = assessment_share.sheet(share.assessment, _lang())
            db.session.commit()
            return page
        db.session.commit()
        wrong = True
        if lab_share.state(share) == "locked":
            return render_template("assessments/shared_link.html", status="locked"), 410
    return render_template("assessments/shared_link.html", status="ask", wrong=wrong,
                           left=max(0, 5 - (share.failures or 0)))


@assessments_bp.route("/review")
@_door
def review():
    return render_template("assessments/review.html",
                           rows=asm.waiting_for(current_user),
                           may_approve=asm.may_approve(current_user))


# ------------------------------------------------- «عدّل الشكل» -----------
def _form_door(kind):
    if not asm.may_edit_form(current_user):
        abort(403, description=t("auth.no_permission"))
    if kind not in asm.default_kinds():
        abort(404)


@assessments_bp.route("/form/<kind>")
@_door
def form_edit(kind):
    _form_door(kind)
    return render_template("assessments/form_edit.html", kind=kind,
                           form=asm.form_for(kind), edited=asm.is_edited(kind),
                           all_tools=asm.default_tools(), asm=asm)


def _form_action(kind, call):
    _form_door(kind)
    back = url_for("assessments.form_edit", kind=kind)
    try:
        call()
    except asm.AssessmentError as err:
        return _refuse(err, back)
    db.session.commit()
    flash(t("assessment.form_saved"), "success")
    return redirect(back)


@assessments_bp.route("/form/<kind>/option-add", methods=["POST"])
@_door
def option_add(kind):
    return _form_action(kind, lambda: asm.add_option(
        kind, request.form.get("section"), request.form.get("label"), current_user))


@assessments_bp.route("/form/<kind>/option-remove", methods=["POST"])
@_door
def option_remove(kind):
    return _form_action(kind, lambda: asm.remove_option(
        kind, request.form.get("section"), request.form.get("option"), current_user))


@assessments_bp.route("/form/<kind>/tool-place", methods=["POST"])
@_door
def tool_place(kind):
    return _form_action(kind, lambda: asm.place_tool(
        kind, request.form.get("tool"), request.form.get("where"), current_user))


@assessments_bp.route("/form/<kind>/field", methods=["POST"])
@_door
def field_set(kind):
    return _form_action(kind, lambda: asm.set_field(
        kind, request.form.get("tool"), request.form.get("field"),
        request.form.get("label"), request.form.get("meets"), current_user))


@assessments_bp.route("/form/<kind>/tool-add", methods=["POST"])
@_door
def tool_add(kind):
    return _form_action(kind, lambda: asm.add_tool(
        kind, request.form.get("name"), request.form.get("fields"), current_user))


@assessments_bp.route("/form/<kind>/reset", methods=["POST"])
@_door
def form_reset(kind):
    return _form_action(kind, lambda: asm.reset(kind, current_user))


# ---------------------------------- questionnaires the family fills (ت-٤) --
def _q_refuse(err, back):
    db.session.rollback()
    flash(t(f"asm_q.err_{err}"), "warning")
    return redirect(back)


@assessments_bp.route("/questionnaires")
@_door
def questionnaires():
    """Every questionnaire the program has the shape of, and where each
    stands: no words yet, waiting for a doctor, open, or stopped."""
    from app.utils import questionnaires as qn

    rows = []
    for key, sh in qn.shapes().items():
        text = qn.text_for(key)
        rows.append({"key": key, "shape": sh, "text": text, "blockers": qn.blockers(key, text),
                     "langs": qn.ready_langs(sh, text), "items": len(qn.items_of(sh))})
    return render_template("assessments/questionnaires.html", rows=rows,
                           may_edit=asm.may_edit_form(current_user),
                           may_open=asm.may_approve(current_user))


@assessments_bp.route("/questionnaires/<key>", methods=["GET", "POST"])
@_door
def questionnaire_words(key):
    """The clinic types the questions and the choices from its licensed copy."""
    from app.utils import questionnaires as qn

    sh = qn.shape(key)
    if sh is None:
        abort(404)
    may_edit = asm.may_edit_form(current_user)
    problems = []
    if request.method == "POST":
        if not may_edit:
            abort(403, description=t("auth.no_permission"))
        problems = qn.save_text(key, request.form, current_user)
        if not problems:
            db.session.commit()
            flash(t("asm_q.saved"), "success")
            return redirect(url_for("assessments.questionnaire_words", key=key))
        db.session.rollback()
        flash(t("asm_q.err_lines"), "warning")
    text = qn.text_for(key)
    items = qn.items_of(sh)
    given = text.items if text and text.items else [{"ar": "", "en": ""}] * len(items)
    return render_template("assessments/questionnaire_words.html", key=key, sh=sh, text=text,
                           items=items, given=given, problems=problems,
                           posted=request.form if request.method == "POST" else None,
                           blockers=qn.blockers(key, text), langs=qn.ready_langs(sh, text),
                           may_edit=may_edit, may_open=asm.may_approve(current_user), qn=qn,
                           fields={f["key"]: f for f in asm.default_tools()[sh["tool"]]["fields"]})


@assessments_bp.route("/questionnaires/<key>/open", methods=["POST"])
@_door
def questionnaire_open(key):
    from app.utils import questionnaires as qn

    back = url_for("assessments.questionnaire_words", key=key)
    if qn.shape(key) is None:
        abort(404)
    try:
        qn.activate(key, current_user, request.form.get("note"))
    except qn.QuestionnaireError as err:
        return _q_refuse(err, back)
    db.session.commit()
    flash(t("asm_q.opened"), "success")
    return redirect(back)


@assessments_bp.route("/questionnaires/<key>/off", methods=["POST"])
@_door
def questionnaire_off(key):
    from app.utils import questionnaires as qn

    back = url_for("assessments.questionnaire_words", key=key)
    if qn.shape(key) is None:
        abort(404)
    if not (asm.may_edit_form(current_user) or asm.may_approve(current_user)):
        abort(403, description=t("auth.no_permission"))
    try:
        qn.switch_off(key, current_user)
    except qn.QuestionnaireError as err:
        return _q_refuse(err, back)
    db.session.commit()
    flash(t("asm_q.stopped"), "success")
    return redirect(back)


@assessments_bp.route("/<int:assessment_id>/questionnaire", methods=["POST"])
@_door
def questionnaire_new(assessment_id):
    """Hand a questionnaire over: the tablet page, a WhatsApp link, or paper."""
    from app.utils import questionnaires as qn

    row = _row(assessment_id)
    back = url_for("assessments.view", assessment_id=row.id) + "#questionnaires"
    try:
        req = qn.create(row, request.form.get("key"), current_user,
                        informant=request.form.get("informant") or "parent",
                        mode=request.form.get("mode") or "tablet",
                        respondent=request.form.get("respondent"),
                        phone=request.form.get("phone"), lang=request.form.get("lang") or _lang())
    except qn.QuestionnaireError as err:
        return _q_refuse(err, back)
    db.session.commit()
    if req.mode == "tablet":
        return redirect(url_for("assessments.questionnaire_fill", token=req.token))
    if req.mode == "paper":
        return redirect(url_for("assessments.questionnaire_paper", request_id=req.id))
    flash(t("asm_q.sent_link"), "success")
    return redirect(back)


def _request(request_id):
    from app.models import QuestionnaireRequest

    return db.get_or_404(QuestionnaireRequest, request_id)


@assessments_bp.route("/questionnaire/<int:request_id>/paper")
@_door
def questionnaire_paper(request_id):
    """The questionnaire on paper, to fill by hand and type in afterwards."""
    req = _request(request_id)
    L = request.args.get("lang") or req.lang
    L = L if L in req.form["langs"] else req.lang
    # The paper's own words (the labels around the questions) in the paper's
    # language, whatever the screen is set to.
    from app.i18n import get_direction

    g.lang, g.direction = L, get_direction(L)
    return render_template("assessments/questionnaire_paper.html", req=req, form=req.form, L=L)


@assessments_bp.route("/questionnaire/<int:request_id>/enter", methods=["GET", "POST"])
@_door
def questionnaire_enter(request_id):
    """A paper questionnaire, typed in by the specialist."""
    from app.utils import questionnaires as qn

    req = _request(request_id)
    back = url_for("assessments.view", assessment_id=req.assessment_id) + "#questionnaires"
    if not asm.may_write(current_user):
        abort(403, description=t("auth.no_permission"))
    if request.method == "POST":
        try:
            qn.answer(req, request.form, current_user)
        except qn.QuestionnaireError as err:
            return _q_refuse(err, back)
        db.session.commit()
        flash(t("asm_q.entered"), "success")
        return redirect(back)
    if not req.answerable:
        return _q_refuse("closed", back)
    return render_template("assessments/questionnaire_enter.html", req=req, form=req.form,
                           L=req.lang)


@assessments_bp.route("/questionnaire/<int:request_id>/use", methods=["POST"])
@_door
def questionnaire_use(request_id):
    """The specialist puts the scores into the assessment."""
    from app.utils import questionnaires as qn

    req = _request(request_id)
    back = url_for("assessments.view", assessment_id=req.assessment_id)
    try:
        qn.use(req, current_user)
    except qn.QuestionnaireError as err:
        return _q_refuse(err, back + "#questionnaires")
    db.session.commit()
    flash(t("asm_q.used"), "success")
    return redirect(back)


@assessments_bp.route("/questionnaire/<int:request_id>/cancel", methods=["POST"])
@_door
def questionnaire_cancel(request_id):
    from app.utils import questionnaires as qn

    req = _request(request_id)
    back = url_for("assessments.view", assessment_id=req.assessment_id) + "#questionnaires"
    try:
        qn.cancel(req, current_user)
    except qn.QuestionnaireError as err:
        return _q_refuse(err, back)
    db.session.commit()
    flash(t("asm_q.cancelled"), "success")
    return redirect(back)


@assessments_bp.route("/q/<token>", methods=["GET", "POST"])
def questionnaire_fill(token):
    """What the parent, the teacher or the child opens — on the clinic's
    tablet or from the message. The questions only: no score, no record.
    Answered once; then it says thank you and closes."""
    from datetime import datetime

    from app.utils import questionnaires as qn

    if not asm.on():
        abort(404)
    req = qn.by_token(token)
    if req is None or req.mode == "paper":
        return render_template("assessments/questionnaire_fill.html", status="gone"), 404
    L = request.args.get("lang") or req.lang
    L = L if L in req.form["langs"] else req.lang
    from app.i18n import get_direction

    g.lang, g.direction = L, get_direction(L)
    if req.status in ("done", "used"):
        return render_template("assessments/questionnaire_fill.html", status="thanks", req=req,
                               form=req.form, L=L)
    if not req.answerable:
        return render_template("assessments/questionnaire_fill.html", status="closed"), 410
    if request.method == "POST":
        try:
            qn.answer(req, request.form)
        except qn.QuestionnaireError:
            db.session.rollback()
            return render_template("assessments/questionnaire_fill.html", status="closed"), 410
        db.session.commit()
        return render_template("assessments/questionnaire_fill.html", status="thanks", req=req,
                               form=req.form, L=L)
    if req.opened_at is None:
        req.opened_at = datetime.utcnow()
        db.session.commit()
    return render_template("assessments/questionnaire_fill.html", status="ask", req=req,
                           form=req.form, L=L)
