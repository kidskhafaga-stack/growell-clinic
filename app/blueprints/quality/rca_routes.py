"""«تحليل الأسباب» — the fishbone and the Pareto (RCA_PLAN.md, ``utils/rca``).

For the quality team and the administration, and for each department's head
on their own department.
"""
from datetime import timedelta
from functools import wraps

from flask import abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user

from app.blueprints.quality import quality_bp
from app.extensions import db
from app.i18n import t
from app.models.rca import RcaCause, RcaProblem
from app.utils import rca


def _may_open(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated:
            return current_app.login_manager.unauthorized()
        if not rca.may_open(current_user):
            abort(403, description=t("auth.no_permission"))
        return view(*args, **kwargs)
    return wrapped


def _back(problem_id=None, **args):
    keep = {k: request.args.get(k) or request.form.get("_" + k) for k in ("from", "to", "only")}
    keep = {k: v for k, v in keep.items() if v}
    return redirect(url_for("quality.rca", p=problem_id, **keep, **args))


def _done(problem_id, err=None):
    if err is not None:
        db.session.rollback()
        flash(t("rca.err_" + str(err)), "error")
    else:
        db.session.commit()
        flash(t("rca.saved"), "success")
    return _back(problem_id)


def _problem_or_403(problem_id):
    row = db.get_or_404(RcaProblem, problem_id)
    if not rca.may_edit(current_user, row):
        abort(403, description=t("auth.no_permission"))
    return row


@quality_bp.route("/rca", endpoint="rca")
@_may_open
def rca_board():
    """The problems as cards, and the one chosen drawn: the fishbone, the
    Pareto with its 80% line, the bones as a strip, and every cause."""
    from app.utils import cs_board
    from app.utils.clock import local_today

    start, end = cs_board.period(request.args.get("from"), request.args.get("to"))
    first, last = cs_board.dates(start, end)
    p_start, p_end = cs_board.previous(start, end)
    only = request.args.get("only") if request.args.get("only") in ("system", "manual") else None
    problems = rca.visible(current_user)
    chosen = None
    wanted = request.args.get("p", type=int)
    for p in problems:
        if p.id == wanted:
            chosen = p
    if chosen is None and problems:
        chosen = next((p for p in problems if p.is_open), problems[0])

    cards = []
    for p in problems:
        if p.measure is not None:
            state = rca.measure_state(p.measure, p.baseline)
            cards.append({"p": p, "measure": state, "n": len(rca.causes(p, start, end))})
        elif p.source in ("complaints", "incidents"):
            now, before = rca.system_total(p, start, end), rca.system_total(p, p_start, p_end)
            change = round((now - before) * 100 / before) if before else None
            cards.append({"p": p, "count": now, "change": change,
                          "n": len(rca.causes(p, start, end))})
        else:
            cards.append({"p": p, "n": len(rca.causes(p, start, end))})

    view = None
    if chosen is not None:
        rows = rca.causes(chosen, start, end, only)
        par = rca.pareto(rows)
        view = {"p": chosen, "pareto": par, "chart": rca.pareto_chart(par["rows"]),
                "fish": rca.fishbone(par["rows"], title=chosen.title), "bones": rca.by_bone(par["rows"]),
                "may_edit": rca.may_edit(current_user, chosen),
                "measure": (rca.measure_state(chosen.measure, chosen.baseline)
                            if chosen.measure is not None else None)}

    from app.models import CostCentre, PerformanceMeasure

    team = rca.is_team(current_user)
    today = local_today()
    presets = [(key, (today - timedelta(days=back)).isoformat(), today.isoformat())
               for key, back in (("month", 29), ("quarter", 89), ("year", 364))]
    return render_template(
        "quality/rca.html", cards=cards, view=view, only=only, team=team,
        q={"from": first.isoformat(), "to": last.isoformat()}, presets=presets,
        suggested=rca.off_target_measures() if team else [],
        measures=PerformanceMeasure.query.filter_by(is_active=True)
        .order_by(PerformanceMeasure.name).all() if team else [],
        centres=(CostCentre.query.filter_by(is_active=True).order_by(CostCentre.sort_order).all()
                 if team else rca.headed(current_user)),
        bones=rca.BONES, all_bones=rca.ROOT_CAUSES, line=rca.PARETO_LINE)


@quality_bp.route("/rca/new", methods=["POST"])
@_may_open
def rca_new():
    try:
        row = rca.open_problem(request.form, current_user)
    except rca.RcaError as why:
        return _done(None, why)
    return _done(row.id)


@quality_bp.route("/rca/<int:problem_id>/cause", methods=["POST"])
@_may_open
def rca_cause(problem_id):
    row = _problem_or_403(problem_id)
    try:
        rca.add_cause(row, request.form, current_user)
    except rca.RcaError as why:
        return _done(row.id, why)
    return _done(row.id)


@quality_bp.route("/rca/cause/<int:cause_id>", methods=["POST"])
@_may_open
def rca_cause_edit(cause_id):
    cause = db.get_or_404(RcaCause, cause_id)
    _problem_or_403(cause.problem_id)
    try:
        rca.edit_cause(cause, request.form)
    except rca.RcaError as why:
        return _done(cause.problem_id, why)
    return _done(cause.problem_id)


@quality_bp.route("/rca/cause/<int:cause_id>/project", methods=["POST"])
@_may_open
def rca_cause_project(cause_id):
    """«ابدأ مشروع تحسين» from a cause — on the quality team's projects."""
    cause = db.get_or_404(RcaCause, cause_id)
    _problem_or_403(cause.problem_id)
    try:
        rca.to_project(cause, request.form)
    except rca.RcaError as why:
        return _done(cause.problem_id, why)
    db.session.commit()
    flash(t("rca.project_made"), "success")
    return _back(cause.problem_id)


@quality_bp.route("/rca/<int:problem_id>/close", methods=["POST"])
@_may_open
def rca_close(problem_id):
    row = _problem_or_403(problem_id)
    rca.close(row)
    return _done(row.id)
