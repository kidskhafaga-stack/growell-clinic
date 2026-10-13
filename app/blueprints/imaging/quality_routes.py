"""Radiology's own quality: report turnaround (GAHAR DAS.07), the printed
report (DAS.08), a substituted examination (DAS.04 e), staff competency
(DAS.02), quality control and the yearly review (DAS.05, DAS.01 ev. 4)."""
from datetime import datetime, timedelta

from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user

from app.blueprints.imaging import imaging_bp
from app.extensions import db
from app.i18n import t
from app.models import VisitInvestigation
from app.utils import imaging_quality as iq
from app.utils import lab_tat
from app.utils.clock import local_today
from app.utils.decorators import module_required

MODULE = "imaging"


def _scan(order_id):
    row = db.get_or_404(VisitInvestigation, order_id)
    if row.kind != "imaging":
        abort(404)
    return row


def _day(raw):
    from datetime import date

    try:
        return date.fromisoformat((raw or "").strip())
    except ValueError:
        return None


# ================================================================ DAS.07 ==
@imaging_bp.route("/turnaround")
@module_required(MODULE)
def turnaround():
    end = _day(request.args.get("to")) or local_today()
    start = _day(request.args.get("from")) or (end - timedelta(days=30))
    if start > end:
        start, end = end, start
    per_test, late_rows = lab_tat.report(start, end, kind="imaging")
    return render_template("labs/turnaround.html", area="imaging", per_test=per_test, late_rows=late_rows,
                           start=start, end=end, stat=lab_tat.stat_list("imaging"), minutes=lab_tat.minutes)


@imaging_bp.route("/order/<int:order_id>/delay", methods=["POST"])
@module_required(MODULE)
def tell_delay(order_id):
    """DAS.07 ev. 5 — *"Delays in reporting medical imaging studies are
    notified to referrers"*."""
    row = _scan(order_id)
    try:
        lab_tat.tell_delay(row, request.form.get("told_to"), reason=request.form.get("reason"), user=current_user)
    except lab_tat.DelayError as err:
        db.session.rollback()
        flash(t(f"lab_tat.err_{err}"), "error")
        return redirect(url_for("imaging.order", order_id=row.id))
    db.session.commit()
    flash(t("lab_tat.told"), "success")
    return redirect(url_for("imaging.order", order_id=row.id))


@imaging_bp.route("/order/<int:order_id>/late-reason", methods=["POST"])
@module_required(MODULE)
def late_reason(order_id):
    row = _scan(order_id)
    back = (url_for("imaging.turnaround") if request.form.get("back") == "report"
            else url_for("imaging.order", order_id=row.id))
    try:
        lab_tat.explain(row, request.form.get("reason"))
    except lab_tat.DelayError as err:
        db.session.rollback()
        flash(t(f"lab_tat.err_{err}"), "error")
        return redirect(back)
    db.session.commit()
    flash(t("lab_tat.reason_saved"), "success")
    return redirect(back)


# ================================================================ DAS.08 ==
@imaging_bp.route("/order/<int:order_id>/print")
@module_required(MODULE)
def print_report(order_id):
    """The report as it goes into the file: the hospital's name, the child's
    identifiers on the page, the study, the findings, when it was reported
    and by whom (a–f)."""
    row = _scan(order_id)
    if row.status != "resulted":
        flash(t("img_qc.not_reported"), "warning")
        return redirect(url_for("imaging.order", order_id=row.id))
    return render_template("imaging/report_print.html", order=row)


# ================================================================ DAS.04 ==
@imaging_bp.route("/order/<int:order_id>/substitute", methods=["POST"])
@module_required(MODULE)
def substitute(order_id):
    """(e) — an additional or substituted examination, and who was told."""
    row = _scan(order_id)
    what = (request.form.get("substituted_with") or "").strip()[:160]
    told = (request.form.get("substitution_told") or "").strip()[:160]
    if not what or not told:
        flash(t("img_qc.err_substitute"), "error")
    else:
        row.substituted_with, row.substitution_told, row.substituted_at = what, told, datetime.utcnow()
        db.session.commit()
        flash(t("img_qc.saved"), "success")
    return redirect(url_for("imaging.order", order_id=row.id))


# ================================================================ DAS.02 ==
@imaging_bp.route("/staff")
@module_required(MODULE)
def staff():
    from app.utils import lab_competency as comp

    return render_template("labs/staff.html", area="imaging", lines=comp.overview(kind="imaging"),
                           checking=False, may_write=comp.may_write(current_user))


@imaging_bp.route("/staff/<int:user_id>")
@module_required(MODULE)
def staff_file(user_id):
    from app.models import User
    from app.models.lab_quality import COMPETENCY_METHODS, COMPETENCY_RESULTS
    from app.utils import lab_competency as comp

    person = db.get_or_404(User, user_id)
    today = local_today()
    mine = set(comp.sections("imaging")) | {comp.IMAGING_WHOLE}
    return render_template("labs/staff_file.html", area="imaging", person=person,
                           rows=[r for r in comp.file_of(person.id) if r.section in mine], today=today,
                           state=comp.state, sections=comp.sections("imaging"), methods=COMPETENCY_METHODS,
                           results=COMPETENCY_RESULTS, assessors=comp.staff("imaging"),
                           suggested_due=comp.suggested_due(today), may_write=comp.may_write(current_user))


@imaging_bp.route("/staff/<int:user_id>/assess", methods=["POST"])
@module_required(MODULE)
def staff_assess(user_id):
    from app.utils import lab_competency as comp

    if not comp.may_write(current_user):
        abort(403)
    f = request.form
    section = f.get("section") or comp.IMAGING_WHOLE
    if section != comp.IMAGING_WHOLE and section not in comp.sections("imaging"):
        abort(400)
    try:
        comp.record(user_id, section, f.get("assessed_on"), f.getlist("methods"), f.get("result"),
                    assessor_id=f.get("assessor_id", type=int), due_on=f.get("due_on"), note=f.get("note"),
                    by=current_user)
    except comp.CompetencyError as err:
        db.session.rollback()
        flash(t(f"lab_comp.err_{err}"), "error")
        return redirect(url_for("imaging.staff_file", user_id=user_id))
    db.session.commit()
    flash(t("lab_comp.saved"), "success")
    return redirect(url_for("imaging.staff_file", user_id=user_id))


# ======================================================== DAS.05, DAS.01 ==
@imaging_bp.route("/qc", methods=["GET", "POST"])
@module_required(MODULE)
def qc():
    month = request.args.get("month") or local_today().strftime("%Y-%m")
    if request.method == "POST":
        what = request.form.get("what")
        try:
            if what == "review":
                iq.review_month(request.form.get("month"), request.form.get("note"), current_user)
            elif what == "service":
                iq.save_service_review("imaging", request.form.get("year", type=int),
                                       request.form.get("text"), current_user)
            else:
                iq.add_qc(request.form, current_user)
        except iq.ImagingQualityError as err:
            db.session.rollback()
            flash(t("img_qc.err_" + str(err)), "error")
            return redirect(url_for("imaging.qc", month=month))
        db.session.commit()
        flash(t("img_qc.saved"), "success")
        return redirect(url_for("imaging.qc", month=request.form.get("month") or month))
    try:
        data = iq.board(month)
    except ValueError:
        abort(404)
    return render_template("imaging/qc.html", data=data, machines=iq.machines(),
                           reviews=iq.service_reviews("imaging"), today=local_today())
