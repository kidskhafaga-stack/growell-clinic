"""The ambulance runs, the vehicles' readiness and drills, and the response
times (GAHAR ICD.02; ``utils/ambulance``)."""
from datetime import date, timedelta

from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user

from app.blueprints.ambulance import ambulance_bp
from app.extensions import db
from app.i18n import t
from app.models.ambulance import OUTCOMES, PROVIDERS, STEPS, AmbulanceCall
from app.utils import ambulance as amb
from app.utils.clock import local_today
from app.utils.decorators import module_required

MODULE = "ambulance"


def _done(where, err=None):
    if err is not None:
        db.session.rollback()
        flash(t("amb.err_" + str(err)), "error")
    else:
        db.session.commit()
        flash(t("amb.saved"), "success")
    return redirect(where)


@ambulance_bp.route("/", methods=["GET", "POST"])
@module_required(MODULE)
def index():
    if request.method == "POST":
        try:
            row = amb.receive(request.form, current_user)
        except amb.AmbulanceError as err:
            return _done(url_for("ambulance.index"), err)
        return _done(url_for("ambulance.call", call_id=row.id))
    return render_template("ambulance/index.html", data=amb.board(), fleet=amb.fleet())


@ambulance_bp.route("/call/<int:call_id>")
@module_required(MODULE)
def call(call_id):
    row = db.get_or_404(AmbulanceCall, call_id)
    return render_template("ambulance/call.html", call=row, steps=STEPS, outcomes=OUTCOMES,
                           fleet=amb.fleet(), over=amb.over_target(row))


@ambulance_bp.route("/call/<int:call_id>/<what>", methods=["POST"])
@module_required(MODULE)
def call_act(call_id, what):
    row = db.get_or_404(AmbulanceCall, call_id)
    back = url_for("ambulance.call", call_id=row.id)
    try:
        if what in STEPS:
            amb.stamp(row, what, request.form)
        elif what == "record":
            amb.record(row, request.form)
        elif what == "close":
            amb.close(row, request.form)
        else:
            abort(404)
    except amb.AmbulanceError as err:
        return _done(back, err)
    return _done(back)


@ambulance_bp.route("/fleet", methods=["GET", "POST"])
@module_required(MODULE)
def fleet():
    if request.method == "POST":
        what = request.form.get("what")
        try:
            if what == "vehicle":
                if not current_user.is_admin:
                    abort(403)
                amb.add_vehicle(request.form)
            elif what == "targets":
                if not current_user.is_admin:
                    abort(403)
                amb.set_targets(request.form)
            else:
                amb.readiness(request.form, current_user)
        except amb.AmbulanceError as err:
            return _done(url_for("ambulance.fleet"), err)
        return _done(url_for("ambulance.fleet"))
    return render_template("ambulance/fleet.html", fleet=amb.fleet(), providers=PROVIDERS,
                           targets=amb.targets(), today=local_today())


@ambulance_bp.route("/report")
@module_required(MODULE)
def report():
    today = local_today()
    try:
        start = date.fromisoformat(request.args.get("from") or "")
    except ValueError:
        start = today - timedelta(days=30)
    try:
        end = date.fromisoformat(request.args.get("to") or "")
    except ValueError:
        end = today
    return render_template("ambulance/report.html", data=amb.report(start, end), start=start, end=end,
                           outcomes=OUTCOMES)
