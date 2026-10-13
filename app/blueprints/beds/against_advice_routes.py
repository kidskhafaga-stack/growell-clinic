"""Leaving against medical advice — the form that closes the episode, the
signature or the witnessed refusal to sign, the hospital's policy, and the
report (``utils/against_advice``).

Reached from three places — a stay's discharge, an emergency bed's
decision, and an emergency attendance's departure — whenever the way out is
``self_discharge``; each sends the clinician here instead of closing the
episode with one tap.
"""
from datetime import date, timedelta
from functools import wraps

from flask import abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user

from app.blueprints.beds import beds_bp
from app.extensions import db
from app.i18n import t
from app.models.refusal import Refusal
from app.utils import against_advice as ama
from app.utils.clock import local_today


def _reachable(view):
    """The wards or the emergency department — whichever the hospital runs
    and the user holds. Writing the form is a clinical act: it needs the
    clinical file (``patient_medical``), which the desk does not hold."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        from app.utils.facility import module_enabled

        if not current_user.is_authenticated:
            return current_app.login_manager.unauthorized()
        held = [m for m in ("beds", "emergency")
                if module_enabled(m) and (current_user.is_admin or current_user.can_access(m))]
        if not held:
            abort(403, description=t("auth.no_permission"))
        if request.method == "POST" and not (current_user.is_admin or current_user.can("patient_medical")):
            abort(403, description=t("auth.no_permission"))
        return view(*args, **kwargs)
    return wrapped


def _back(kind, episode_id):
    return redirect(url_for("beds.against_advice", kind=kind, episode_id=episode_id))


@beds_bp.route("/against-advice/<kind>/<int:episode_id>", methods=["GET", "POST"])
@_reachable
def against_advice(kind, episode_id):
    row, patient, refusal_kind = ama.episode(kind, episode_id)
    if row is None:
        abort(404)
    if request.method == "POST":
        def finish():
            if kind == "stay":
                from app.blueprints.beds.routes import finish_stay

                finish_stay(row, ama.AGAINST_ADVICE, request.form.get("note"),
                            request.form.get("leave_reason"), request.form.get("leave_note"))
            else:
                from app.blueprints.beds.routes import _survey_after
                from app.utils import emergency as er
                from app.utils import leave_reasons

                er.depart(row, ama.AGAINST_ADVICE, condition=request.form.get("condition_now"),
                          followup=request.form.get("followup_plan"), user=current_user)
                leave_reasons.record(row, row.disposition, request.form.get("leave_reason"),
                                     request.form.get("leave_note"))
                db.session.flush()
                _survey_after(row.patient, row.disposition, centre_key="emergency", emergency_visit=row)
        try:
            record, gaps = ama.close(kind, row, patient, request.form, current_user, finish)
        except ama.AgainstAdviceError as err:
            db.session.rollback()
            flash(t("ama.err_incomplete", items="، ".join(t("ama.need_" + g) for g in err.missing)), "error")
            return _back(kind, episode_id)
        db.session.commit()
        if gaps:
            flash(t("ama.saved_with_gaps", items="، ".join(t("ama.need_" + g) for g in gaps)), "warning")
        else:
            flash(t("ama.saved"), "success")
        return _back(kind, episode_id)
    from app.utils import leave_reasons

    record = ama.refusal_for(kind, row)
    return render_template("beds/against_advice.html", kind=kind, row=row, patient=patient,
                           refusal_kind=refusal_kind, record=record, missing=ama.missing(record),
                           open=ama.is_open(kind, row), policy=ama.policy(), doctors=ama.doctors(),
                           leave_reasons=leave_reasons.options())


@beds_bp.route("/against-advice/form/<int:refusal_id>/signature", methods=["POST"])
@_reachable
def against_advice_signature(refusal_id):
    """The guardian's signature on the printed form, scanned, or drawn on
    the screen — the same evidence a consent carries."""
    from app.blueprints.patients.routes import _a_signature
    from app.models import ActivityLog
    from app.utils.clock import local_now

    record = db.get_or_404(Refusal, refusal_id)
    kind, episode_id = ("stay", record.admission_id) if record.admission_id else ("er", record.emergency_visit_id)
    stored, how = _a_signature()
    if stored is None:
        flash(t("visits.att_bad_type"), "warning")
        return _back(kind, episode_id)
    record.signature_file, record.signature_kind = stored, how
    record.signature_at = local_now().replace(tzinfo=None)
    record.signature_refused = False
    ActivityLog.record(f"refusal.signature.{how}", user_id=current_user.id, entity="refusal",
                       entity_id=record.id)
    db.session.commit()
    flash(t("ama.signature_saved"), "success")
    return _back(kind, episode_id)


@beds_bp.route("/against-advice/report")
@_reachable
def against_advice_report():
    today = local_today()
    try:
        start = date.fromisoformat(request.args.get("from") or "")
    except ValueError:
        start = today - timedelta(days=30)
    try:
        end = date.fromisoformat(request.args.get("to") or "")
    except ValueError:
        end = today
    return render_template("beds/against_advice_report.html", data=ama.report(start, end), start=start, end=end,
                           policy=ama.policy())


@beds_bp.route("/against-advice/policy", methods=["POST"])
@_reachable
def against_advice_policy():
    if not current_user.is_admin:
        abort(403)
    try:
        ama.set_policy(request.form.get("policy"))
    except ama.AgainstAdviceError:
        abort(400)
    from app.models import ActivityLog

    ActivityLog.record("settings.ama_policy", user_id=current_user.id, detail=request.form.get("policy"))
    db.session.commit()
    flash(t("ama.saved"), "success")
    return redirect(url_for("beds.against_advice_report"))
