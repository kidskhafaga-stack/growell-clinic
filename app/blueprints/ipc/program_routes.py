"""Surveillance, care bundles and the committee — ``utils/ipc_program``.

Surveillance and the committee are infection control's (``infection_control``);
a bundle check is the ward's too — whoever works the beds files it."""
from datetime import timedelta
from functools import wraps

from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.blueprints.ipc import ipc_bp
from app.blueprints.ipc.routes import _reviewer
from app.extensions import db
from app.i18n import t
from app.models.ipc_program import (ANSWERS, BUNDLE_SCOPES, HAI_KINDS, BundleElement,
                                    CareBundle, HaiCase, IpcDecision, IpcMeeting)
from app.utils import ipc as ipc_utils
from app.utils import ipc_program as prog
from app.utils.clock import local_today


def _checker(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if not prog.may_check(current_user):
            abort(403, description=t("auth.no_permission"))
        return view(*args, **kwargs)
    return wrapped


def _refused(err):
    flash(t(f"ipcp.err_{err}"), "error")


# ---------------------------------------------------------- surveillance ---
@ipc_bp.route("/surveillance")
@_reviewer
def surveillance():
    today = local_today()
    quarter = request.args.get("q") or prog.quarter_of(today)
    bounds = prog.quarter_bounds(quarter) or prog.quarter_bounds(prog.quarter_of(today))
    start, end = bounds
    quarters = []
    day = today
    for _ in range(6):
        q = prog.quarter_of(day)
        quarters.append(q)
        day = prog.quarter_bounds(q)[0] - timedelta(days=1)
    return render_template("ipc/surveillance.html", quarter=prog.quarter_of(start),
                           quarters=quarters, data=prog.rates(start, end),
                           rows=prog.cases(start, end), kinds=HAI_KINDS, today=today,
                           open_rows=HaiCase.query.filter_by(status="suspected")
                           .order_by(HaiCase.onset_on).all())


@ipc_bp.route("/surveillance", methods=["POST"])
@_reviewer
def surveillance_report():
    try:
        row = prog.report_case(request.form, current_user)
    except prog.ProgramError as err:
        db.session.rollback()
        _refused(err)
        return redirect(url_for("ipc.surveillance"))
    db.session.commit()
    flash(t("ipcp.case_reported"), "success")
    return redirect(url_for("ipc.surveillance", q=prog.quarter_of(row.onset_on)))


@ipc_bp.route("/surveillance/<int:case_id>", methods=["POST"])
@_reviewer
def surveillance_decide(case_id):
    row = db.get_or_404(HaiCase, case_id)
    try:
        prog.decide_case(row, request.form, current_user)
    except prog.ProgramError as err:
        db.session.rollback()
        _refused(err)
        return redirect(url_for("ipc.surveillance"))
    db.session.commit()
    flash(t("ipcp.case_decided"), "success")
    return redirect(url_for("ipc.surveillance", q=prog.quarter_of(row.onset_on)))


# --------------------------------------------------------------- bundles ---
@ipc_bp.route("/bundles")
@_checker
def bundles():
    from app.models.line import KINDS as LINE_KINDS

    today = local_today()
    month_start = today.replace(day=1)
    return render_template("ipc/bundles.html", due=prog.due_today(today), today=today,
                           compliance=prog.compliance(month_start, today + timedelta(days=1)),
                           bundles=CareBundle.query.order_by(CareBundle.name).all(),
                           kinds=HAI_KINDS, scopes=BUNDLE_SCOPES, line_kinds=LINE_KINDS,
                           answers=ANSWERS, may_setup=ipc_utils.may_review(current_user))


@ipc_bp.route("/bundles", methods=["POST"])
@_reviewer
def bundle_add():
    try:
        prog.save_bundle(request.form)
    except prog.ProgramError as err:
        db.session.rollback()
        _refused(err)
        return redirect(url_for("ipc.bundles") + "#setup")
    db.session.commit()
    flash(t("ipcp.bundle_saved"), "success")
    return redirect(url_for("ipc.bundles") + "#setup")


@ipc_bp.route("/bundles/element/<int:element_id>", methods=["POST"])
@_reviewer
def bundle_element(element_id):
    row = db.get_or_404(BundleElement, element_id)
    row.is_active = not row.is_active
    db.session.commit()
    return redirect(url_for("ipc.bundles") + "#setup")


@ipc_bp.route("/bundles/<int:bundle_id>/check", methods=["POST"])
@_checker
def bundle_check(bundle_id):
    bundle = db.get_or_404(CareBundle, bundle_id)
    try:
        row = prog.record_check(bundle, request.form, current_user, local_today())
    except prog.ProgramError as err:
        db.session.rollback()
        _refused(err)
        return redirect(url_for("ipc.bundles"))
    db.session.commit()
    flash(t("ipcp.check_met" if row.all_met else "ipcp.check_not_met"),
          "success" if row.all_met else "warning")
    return redirect(url_for("ipc.bundles"))


# -------------------------------------------------------------- committee ---
@ipc_bp.route("/committee")
@_reviewer
def committee():
    today = local_today()
    return render_template("ipc/committee.html", today=today,
                           meetings=IpcMeeting.query.order_by(IpcMeeting.held_on.desc())
                           .limit(24).all(),
                           open_decisions=prog.open_decisions(),
                           no_meeting=prog.months_without_meeting(today),
                           unreviewed=prog.unreviewed_quarters(today),
                           last_quarter=prog.quarter_of(
                               prog.quarter_bounds(prog.quarter_of(today))[0] - timedelta(days=1)))


@ipc_bp.route("/committee", methods=["POST"])
@_reviewer
def committee_save():
    try:
        prog.save_meeting(request.form, current_user)
    except prog.ProgramError as err:
        db.session.rollback()
        _refused(err)
        return redirect(url_for("ipc.committee"))
    db.session.commit()
    flash(t("ipcp.meeting_saved"), "success")
    return redirect(url_for("ipc.committee"))


@ipc_bp.route("/decision/<int:decision_id>", methods=["POST"])
@_reviewer
def decision_close(decision_id):
    row = db.get_or_404(IpcDecision, decision_id)
    try:
        prog.close_decision(row, request.form, current_user)
    except prog.ProgramError as err:
        db.session.rollback()
        _refused(err)
        return redirect(url_for("ipc.committee"))
    db.session.commit()
    flash(t("ipcp.decision_closed"), "success")
    return redirect(url_for("ipc.committee"))
