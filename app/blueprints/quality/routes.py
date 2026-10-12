"""The quality programme — performance measures, the risk register,
improvement projects and the quality committee (GAHAR QPI.01, QPI.05–09,
QPI.12; ``utils/quality``)."""
from functools import wraps

from flask import abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user

from app.blueprints.quality import quality_bp
from app.extensions import db
from app.i18n import t
from app.models.quality import (CLINICAL_AREAS, MANAGERIAL_AREAS, RISK_CATEGORIES, ImprovementProject,
                                PerformanceMeasure, QualityDecision, RiskItem)
from app.utils import incidents as inc
from app.utils import quality as q
from app.utils.clock import local_today


def _team(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated:
            return current_app.login_manager.unauthorized()
        if not (current_user.is_admin or inc.may_review(current_user)):
            abort(403, description=t("auth.no_permission"))
        return view(*args, **kwargs)
    return wrapped


def _done(where, err=None):
    if err is not None:
        db.session.rollback()
        flash(t("qual.err_" + str(err)), "error")
    else:
        db.session.commit()
        flash(t("qual.saved"), "success")
    return redirect(where)


@quality_bp.route("/")
@_team
def index():
    return redirect(url_for("quality.measures"))


@quality_bp.route("/measures", methods=["GET", "POST"])
@_team
def measures():
    if request.method == "POST":
        try:
            q.save_measure(request.form)
        except q.QualityError as err:
            return _done(url_for("quality.measures"), err)
        return _done(url_for("quality.measures"))
    rows = PerformanceMeasure.query.filter_by(is_active=True).order_by(PerformanceMeasure.kind,
                                                                       PerformanceMeasure.name).all()
    return render_template("quality/measures.html", rows=rows, q=q, clinical=CLINICAL_AREAS,
                           managerial=MANAGERIAL_AREAS)


@quality_bp.route("/measure/<int:measure_id>", methods=["GET", "POST"])
@_team
def measure(measure_id):
    row = db.get_or_404(PerformanceMeasure, measure_id)
    if request.method == "POST":
        try:
            q.add_value(row, request.form, current_user)
        except q.QualityError as err:
            return _done(url_for("quality.measure", measure_id=row.id), err)
        return _done(url_for("quality.measure", measure_id=row.id))
    return render_template("quality/measure.html", m=row, q=q, chart=q.trend(row))


@quality_bp.route("/risks", methods=["GET", "POST"])
@_team
def risks():
    if request.method == "POST":
        what = request.form.get("what")
        try:
            if what == "proactive":
                q.add_proactive(request.form, current_user)
            elif what == "report":
                q.add_risk_report(request.form)
            else:
                q.save_risk(request.form)
        except q.QualityError as err:
            return _done(url_for("quality.risks"), err)
        return _done(url_for("quality.risks"))
    return render_template("quality/risks.html", data=q.risk_board(local_today()), categories=RISK_CATEGORIES)


@quality_bp.route("/risk/<int:risk_id>/close", methods=["POST"])
@_team
def risk_close(risk_id):
    q.close_risk(db.get_or_404(RiskItem, risk_id))
    return _done(url_for("quality.risks"))


@quality_bp.route("/projects", methods=["GET", "POST"])
@_team
def projects():
    if request.method == "POST":
        try:
            q.save_project(request.form)
        except q.QualityError as err:
            return _done(url_for("quality.projects"), err)
        return _done(url_for("quality.projects"))
    return render_template("quality/projects.html", data=q.projects_board(local_today()),
                           measures=PerformanceMeasure.query.filter_by(is_active=True).all())


@quality_bp.route("/project/<int:project_id>", methods=["POST"])
@_team
def project_update(project_id):
    try:
        q.update_project(db.get_or_404(ImprovementProject, project_id), request.form)
    except q.QualityError as err:
        return _done(url_for("quality.projects") + f"#p-{project_id}", err)
    return _done(url_for("quality.projects") + f"#p-{project_id}")


@quality_bp.route("/committee", methods=["GET", "POST"])
@_team
def committee():
    from app.utils.incidents import WEEKEND_SETTING

    if request.method == "POST":
        try:
            q.save_meeting(request.form, current_user)
        except q.QualityError as err:
            return _done(url_for("quality.committee"), err)
        return _done(url_for("quality.committee"))
    from app.models import Setting

    year = request.args.get("year", type=int) or local_today().year
    return render_template("quality/committee.html", data=q.committee_board(), year=year,
                           today=local_today(), weekend=Setting.get(WEEKEND_SETTING) or "")


@quality_bp.route("/decision/<int:row_id>/done", methods=["POST"])
@_team
def decision_done(row_id):
    try:
        q.close_decision(db.get_or_404(QualityDecision, row_id), request.form.get("note"))
    except q.QualityError as err:
        return _done(url_for("quality.committee"), err)
    return _done(url_for("quality.committee"))


@quality_bp.route("/evaluation/<int:year>", methods=["POST"])
@_team
def evaluation(year):
    try:
        q.save_evaluation(year, request.form.get("text"), current_user)
    except q.QualityError as err:
        return _done(url_for("quality.committee", year=year), err)
    return _done(url_for("quality.committee", year=year))


@quality_bp.route("/weekend", methods=["POST"])
@_team
def weekend():
    """The hospital's non-working weekdays — for counting "working days" in
    the sentinel-event clock (QPI.11)."""
    from app.models import Setting
    from app.utils.incidents import WEEKEND_SETTING

    days = [d for d in request.form.getlist("day") if d.isdigit() and 0 <= int(d) <= 6]
    Setting.set(WEEKEND_SETTING, ",".join(days))
    return _done(url_for("quality.committee"))
