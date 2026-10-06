"""The radiation safety program's screens — GAHAR DAS.09 / GSR.12. The logic
is in ``app/utils/radiation_safety.py``."""
from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user

from app.blueprints.imaging import imaging_bp
from app.blueprints.imaging.routes import MODULE, _scan
from app.extensions import db
from app.i18n import t
from app.models.radiation_safety import (APRON_RESULTS, CBC_RESULTS,
                                         ApronCheck,
                                         AreaMeasurement, DoseBadgeReading,
                                         RadiationWorker, StaffBloodCount)
from app.utils import radiation_safety as rs
from app.utils.clock import local_today
from app.utils.decorators import module_required


def _refused(err):
    flash(t(f"radsafe.err_{err}"), "error")


def _saved(anchor):
    db.session.commit()
    flash(t("radsafe.saved"), "success")
    return redirect(url_for("imaging.safety") + anchor)


@imaging_bp.route("/safety")
@module_required(MODULE)
def safety():
    """Who is monitored and where each stands — the badge, the six-monthly
    blood count — and the areas, the aprons and the program's settings."""
    from app.models import User

    workers = {w.user_id for w in RadiationWorker.query.filter_by(is_active=True)}
    return render_template(
        "imaging/safety.html", rows=rs.board(), today=local_today(),
        level=rs.badge_level(), questions=rs.mri_questions(),
        badges=rs.recent(DoseBadgeReading, "period_to"),
        counts=rs.recent(StaffBloodCount, "done_on"),
        areas=rs.recent(AreaMeasurement, "measured_on"),
        aprons=rs.recent(ApronCheck, "checked_on"),
        staff=User.query.filter(User.is_active.is_(True)).order_by(User.full_name).all(),
        workers=workers, cbc_results=CBC_RESULTS, apron_results=APRON_RESULTS)


def _post(fn, anchor):
    try:
        fn(current_user, request.form)
    except rs.SafetyError as err:
        db.session.rollback()
        _refused(err)
        return redirect(url_for("imaging.safety") + anchor)
    return _saved(anchor)


@imaging_bp.route("/safety/worker", methods=["POST"])
@module_required(MODULE)
def safety_worker():
    return _post(lambda _u, f: rs.add_worker(f), "#workers")


@imaging_bp.route("/safety/worker/<int:worker_id>/stop", methods=["POST"])
@module_required(MODULE)
def safety_worker_stop(worker_id):
    rs.stop_worker(db.get_or_404(RadiationWorker, worker_id))
    return _saved("#workers")


@imaging_bp.route("/safety/badge", methods=["POST"])
@module_required(MODULE)
def safety_badge():
    return _post(rs.badge, "#badges")


@imaging_bp.route("/safety/cbc", methods=["POST"])
@module_required(MODULE)
def safety_cbc():
    return _post(rs.blood_count, "#counts")


@imaging_bp.route("/safety/area", methods=["POST"])
@module_required(MODULE)
def safety_area():
    return _post(rs.area, "#areas")


@imaging_bp.route("/safety/apron", methods=["POST"])
@module_required(MODULE)
def safety_apron():
    return _post(rs.apron, "#aprons")


@imaging_bp.route("/safety/settings", methods=["POST"])
@module_required(MODULE)
def safety_settings():
    return _post(lambda _u, f: rs.save_settings(f), "#program")


@imaging_bp.route("/order/<int:order_id>/mri-screening", methods=["POST"])
@module_required(MODULE)
def mri_screening(order_id):
    """(f) — the metals, implants and devices screening before the MRI."""
    row = _scan(order_id)
    try:
        rs.screen_mri(row, current_user, request.form)
    except rs.SafetyError as err:
        db.session.rollback()
        _refused(err)
        return redirect(url_for("imaging.order", order_id=row.id) + "#mri")
    db.session.commit()
    flash(t("radsafe.screened"), "success")
    return redirect(url_for("imaging.order", order_id=row.id) + "#mri")
