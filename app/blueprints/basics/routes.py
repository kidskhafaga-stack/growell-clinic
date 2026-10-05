"""The window that fills a quick registration's gaps before a second
service — ``utils/patient_basics`` (``needs_completion`` / ``complete``).

Reached from the desk's three doors — the booking, the till and a study —
so it answers to whoever stands at any of them, not to one module."""
from functools import wraps

from flask import (abort, current_app, flash, jsonify, redirect,
                   render_template, request, url_for)
from flask_login import current_user

from app.blueprints.basics import basics_bp
from app.extensions import db
from app.i18n import t
from app.models import Patient
from app.utils import patient_basics as basics


def _desk(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated:
            return current_app.login_manager.unauthorized()
        if not (current_user.can_collect or any(
                current_user.can_access(m)
                for m in ("patients", "appointments", "visits"))):
            abort(403, description=t("auth.no_permission"))
        return view(*args, **kwargs)
    return wrapped


def _safe_next(raw, patient):
    raw = (raw or "").strip()
    if raw.startswith("/") and not raw.startswith("//") and "\\" not in raw:
        return raw
    return url_for("patients.view", patient_id=patient.id)


def window(patient, next_url):
    """What a page passes its template to draw the window."""
    from app.models import BLOOD_TYPES

    return {"complete_patient": patient,
            "complete_gaps": basics.missing(patient),
            "complete_next": next_url,
            "complete_relations": basics.RELATIONS,
            "complete_blood_types": BLOOD_TYPES}


@basics_bp.route("/<int:patient_id>/complete")
@_desk
def window_page(patient_id):
    """The window on a page of its own — the door a study goes through."""
    patient = db.get_or_404(Patient, patient_id)
    next_url = _safe_next(request.args.get("next"), patient)
    if not basics.missing(patient):
        return redirect(next_url)
    return render_template("patients/complete_basics.html",
                           **window(patient, next_url))


@basics_bp.route("/<int:patient_id>/complete", methods=["POST"])
@_desk
def save(patient_id):
    from app.models import ActivityLog
    from app.utils.decorators import client_ip

    patient = db.get_or_404(Patient, patient_id)
    next_url = _safe_next(request.form.get("next"), patient)
    try:
        still = basics.complete(patient, request.form)
    except basics.BasicsError as err:
        db.session.rollback()
        flash(t(f"basics.err_{err}"), "error")
        return redirect(url_for("basics.window_page", patient_id=patient.id,
                                next=next_url))
    ActivityLog.record("patient.basics_completed", user_id=current_user.id,
                       entity="patient", entity_id=patient.id,
                       ip_address=client_ip())
    db.session.commit()
    if still:
        return redirect(url_for("basics.window_page", patient_id=patient.id,
                                next=next_url))
    flash(t("basics.completed"), "success")
    return redirect(next_url)


@basics_bp.route("/<int:patient_id>/complete.json", methods=["POST"])
@_desk
def save_json(patient_id):
    """The same, for the booking form's picker, which stays on its page."""
    from app.models import ActivityLog
    from app.utils.decorators import client_ip

    patient = db.get_or_404(Patient, patient_id)
    data = request.get_json(silent=True) or {}
    try:
        still = basics.complete(patient, data)
    except basics.BasicsError as err:
        db.session.rollback()
        return jsonify({"ok": False, "error": t(f"basics.err_{err}")}), 400
    ActivityLog.record("patient.basics_completed", user_id=current_user.id,
                       entity="patient", entity_id=patient.id,
                       ip_address=client_ip())
    db.session.commit()
    return jsonify({"ok": True, "missing": still})
