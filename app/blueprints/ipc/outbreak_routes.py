"""Notifiable diseases and outbreaks — ``utils/ipc_outbreak``. The team's
(``infection_control``) screens, under the same bar as the alerts."""
from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user

from app.blueprints.ipc import ipc_bp
from app.blueprints.ipc.routes import _reviewer
from app.extensions import db
from app.i18n import t
from app.models.ipc_outbreak import STEPS, DiseaseReport, Outbreak
from app.utils import ipc_outbreak as ob
from app.utils.clock import local_today


def _refused(err):
    flash(t(f"ipco.err_{err}"), "error")


def _units():
    from app.models.place import Unit

    return Unit.query.filter_by(is_active=True).order_by(Unit.sort_order, Unit.name).all()


# --------------------------------------------------------------- reports ---
@ipc_bp.route("/reports")
@_reviewer
def disease_reports():
    pending, done = ob.reports()
    return render_template("ipc/reports.html", pending=pending, done=done, today=local_today())


@ipc_bp.route("/reports", methods=["POST"])
@_reviewer
def disease_report_add():
    try:
        ob.add_report(request.form, current_user)
    except ob.OutbreakError as err:
        db.session.rollback()
        _refused(err)
        return redirect(url_for("ipc.disease_reports"))
    db.session.commit()
    flash(t("ipco.report_added"), "success")
    return redirect(url_for("ipc.disease_reports"))


@ipc_bp.route("/reports/<int:report_id>", methods=["POST"])
@_reviewer
def disease_report_sent(report_id):
    row = db.get_or_404(DiseaseReport, report_id)
    try:
        ob.mark_reported(row, request.form, current_user)
    except ob.OutbreakError as err:
        db.session.rollback()
        _refused(err)
        return redirect(url_for("ipc.disease_reports"))
    db.session.commit()
    flash(t("ipco.reported"), "success")
    return redirect(url_for("ipc.disease_reports"))


# ------------------------------------------------------------- outbreaks ---
@ipc_bp.route("/outbreaks")
@_reviewer
def outbreaks():
    today = local_today()
    rows = Outbreak.query.order_by(Outbreak.closed_on.isnot(None), Outbreak.opened_on.desc()).all()
    return render_template("ipc/outbreaks.html", rows=rows, today=today, units=_units(),
                           clusters=ob.clusters(today), summary=ob.summary)


@ipc_bp.route("/outbreaks", methods=["POST"])
@_reviewer
def outbreak_open():
    try:
        row = ob.open_outbreak(request.form, current_user)
    except ob.OutbreakError as err:
        db.session.rollback()
        _refused(err)
        return redirect(url_for("ipc.outbreaks"))
    db.session.commit()
    return redirect(url_for("ipc.outbreak", outbreak_id=row.id))


@ipc_bp.route("/outbreak/<int:outbreak_id>")
@_reviewer
def outbreak(outbreak_id):
    row = db.get_or_404(Outbreak, outbreak_id)
    today = local_today()
    return render_template("ipc/outbreak.html", o=row, steps=STEPS, today=today,
                           done={s.step: s for s in row.steps}, stats=ob.summary(row, today))


@ipc_bp.route("/outbreak/<int:outbreak_id>/<what>", methods=["POST"])
@_reviewer
def outbreak_act(outbreak_id, what):
    row = db.get_or_404(Outbreak, outbreak_id)
    act = {"step": ob.record_step, "case": ob.add_case, "close": ob.close_outbreak}.get(what)
    if act is None:
        return redirect(url_for("ipc.outbreak", outbreak_id=row.id))
    try:
        act(row, request.form, current_user)
    except ob.OutbreakError as err:
        db.session.rollback()
        _refused(err)
        return redirect(url_for("ipc.outbreak", outbreak_id=row.id))
    db.session.commit()
    flash(t(f"ipco.saved_{what}"), "success")
    return redirect(url_for("ipc.outbreak", outbreak_id=row.id))
