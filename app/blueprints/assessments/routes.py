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

    patient = db.get_or_404(Patient, patient_id)
    return render_template("assessments/patient.html", patient=patient,
                           rows=asm.for_patient(patient.id), kinds=asm.kinds(_lang()),
                           may_write=asm.may_write(current_user), asm=asm)


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
                           may_edit_form=asm.may_edit_form(current_user), asm=asm)


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
                           printed_at=local_now(), asm=asm)


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
