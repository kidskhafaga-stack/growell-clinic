"""Calling for help for a child getting worse — GAHAR ICD.22 / GSR.10.

Beside the observation chart, because that is where the red reading is seen:
the call is opened from it, the responder marks arrival on it, and what was
done is written on it. The logic is in ``app/utils/deterioration.py``.
"""
from datetime import timedelta

from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user

from app.blueprints.observations import observations_bp
from app.extensions import db
from app.i18n import t
from app.models import Patient
from app.models.deterioration import OUTCOMES, DeteriorationCall
from app.utils import deterioration as det
from app.utils.clock import local_today
from app.utils.decorators import module_required

MODULE = "observations"


def _refused(error):
    flash(t(f"deterioration.err_{error}"), "error")


@observations_bp.route("/patient/<int:patient_id>/call", methods=["POST"])
@module_required(MODULE)
def call_for_help(patient_id):
    """Noticed and called, in one press — the reading filled from the chart."""
    from app.models import Observation

    patient = db.get_or_404(Patient, patient_id)
    obs_id = request.form.get("observation_id", type=int)
    observation = db.session.get(Observation, obs_id) if obs_id else None
    if observation is not None and observation.patient_id != patient.id:
        observation = None
    try:
        row = det.open_call(patient, current_user, observation=observation,
                            concern=request.form.get("concern"),
                            code_key=request.form.get("code_key"),
                            called_whom=request.form.get("called_whom"))
    except det.CallError as err:
        db.session.rollback()
        _refused(err)
        return redirect(url_for("observations.chart", patient_id=patient.id))
    db.session.commit()
    flash(t("deterioration.called"), "warning")
    return redirect(url_for("observations.call_view", call_id=row.id))


@observations_bp.route("/call/<int:call_id>")
@module_required(MODULE)
def call_view(call_id):
    from app.models import Resuscitation

    row = db.get_or_404(DeteriorationCall, call_id)
    arrests = (Resuscitation.query.filter_by(patient_id=row.patient_id)
               .order_by(Resuscitation.recognised_at.desc()).limit(10).all())
    return render_template("observations/call.html", row=row, outcomes=OUTCOMES,
                           arrests=arrests, late=det.late(row),
                           limit=det.response_minutes(),
                           code_label=det.code_label)


@observations_bp.route("/call/<int:call_id>/arrive", methods=["POST"])
@module_required(MODULE)
def call_arrive(call_id):
    row = db.get_or_404(DeteriorationCall, call_id)
    try:
        det.arrive(row, current_user)
    except det.CallError as err:
        db.session.rollback()
        _refused(err)
    else:
        db.session.commit()
        flash(t("deterioration.arrived"), "success")
    return redirect(url_for("observations.call_view", call_id=row.id))


@observations_bp.route("/call/<int:call_id>/close", methods=["POST"])
@module_required(MODULE)
def call_close(call_id):
    row = db.get_or_404(DeteriorationCall, call_id)
    try:
        det.close(row, current_user, request.form.get("actions"),
                  request.form.get("outcome"),
                  resuscitation_id=request.form.get("resuscitation_id", type=int))
    except det.CallError as err:
        db.session.rollback()
        _refused(err)
    else:
        db.session.commit()
        flash(t("deterioration.closed"), "success")
    return redirect(url_for("observations.call_view", call_id=row.id))


@observations_bp.route("/calls")
@module_required(MODULE)
def calls():
    """Open calls first, then the last week's — and the hospital's codes and
    time frame, for whoever builds the lists."""
    from datetime import datetime

    week = datetime.utcnow() - timedelta(days=7)
    recent = (DeteriorationCall.query
              .filter(DeteriorationCall.closed_at.isnot(None),
                      DeteriorationCall.called_at >= week)
              .order_by(DeteriorationCall.called_at.desc()).all())
    return render_template("observations/calls.html", open_rows=det.open_calls(),
                           recent=recent, codes=det.codes(),
                           limit=det.response_minutes(), late=det.late,
                           code_label=det.code_label)


@observations_bp.route("/calls/settings", methods=["POST"])
@module_required(MODULE)
def calls_settings():
    if not current_user.is_admin:
        abort(403)
    det.set_response_minutes(request.form.get("minutes"))
    name = (request.form.get("code") or "").strip()
    if name:
        det.add_code(name)
    db.session.commit()
    flash(t("deterioration.settings_saved"), "success")
    return redirect(url_for("observations.calls") + "#call-settings")


@observations_bp.route("/calls/codes/<int:code_id>/retire", methods=["POST"])
@module_required(MODULE)
def calls_code_retire(code_id):
    from app.models import Lookup

    if not current_user.is_admin:
        abort(403)
    try:
        det.retire_code(db.session.get(Lookup, code_id))
    except det.CallError:
        abort(404)
    db.session.commit()
    return redirect(url_for("observations.calls") + "#call-settings")


@observations_bp.route("/calls/report")
@module_required(MODULE)
def calls_report():
    """Evidence 4 and (و) — the calls of a period, the time to the bed, and
    the same figures by weekday and by time of day."""
    from app.utils.appointments import parse_date_arg

    end = parse_date_arg(request.args.get("to"), local_today())
    raw = request.args.get("from")
    start = parse_date_arg(raw) if raw else end - timedelta(days=29)
    if start > end:
        start, end = end, start
    return render_template("observations/calls_report.html", start=start,
                           end=end, data=det.report(start, end))
