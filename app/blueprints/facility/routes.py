"""The building's safety records — GAHAR EFS.03 / GSR.23, EFS.04 / GSR.24,
EFS.11 / GSR.28. The logic is in ``app/utils/facility_safety.py``."""
from functools import wraps

from flask import (abort, current_app, flash, redirect, render_template,
                   request, url_for)
from flask_login import current_user

from app.blueprints.facility import facility_bp
from app.extensions import db
from app.i18n import t
from app.models.facility_safety import (FIRE_SYSTEMS, RESULTS, SHIFTS,
                                        UTILITY_CHECKS, UTILITY_KINDS,
                                        FireTraining, UtilitySystem)
from app.utils import facility_safety as fs
from app.utils.clock import local_today


def _door(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated:
            return current_app.login_manager.unauthorized()
        if not fs.may_manage(current_user):
            abort(403, description=t("auth.no_permission"))
        return view(*args, **kwargs)
    return wrapped


def _staff():
    from app.models import User

    return User.query.filter(User.is_active.is_(True)).order_by(User.full_name).all()


def _do(fn, anchor):
    try:
        fn()
    except fs.FacilityError as err:
        db.session.rollback()
        flash(t(f"facility.err_{err}"), "error")
        return redirect(url_for("facility.index") + anchor)
    db.session.commit()
    flash(t("facility.saved"), "success")
    return redirect(url_for("facility.index") + anchor)


@facility_bp.route("/")
@_door
def index():
    """The year's drills against the standard's figures, the fire systems,
    who is untrained, and the utilities."""
    year = request.args.get("year", type=int) or local_today().year
    return render_template(
        "facility/index.html", today=local_today(), year=fs.year_of_drills(year),
        fire=fs.fire_systems_now(), untrained=fs.untrained_this_year(),
        utilities=fs.utilities_now(), staff=_staff(),
        trainings=(FireTraining.query.order_by(FireTraining.trained_on.desc(),
                                               FireTraining.id.desc()).limit(20).all()),
        shifts=SHIFTS, fire_systems=FIRE_SYSTEMS, results=RESULTS,
        utility_kinds=UTILITY_KINDS, utility_checks=UTILITY_CHECKS)


@facility_bp.route("/drill", methods=["POST"])
@_door
def drill():
    return _do(lambda: fs.drill(current_user, request.form), "#drills")


@facility_bp.route("/fire-check", methods=["POST"])
@_door
def fire_check():
    return _do(lambda: fs.fire_check(current_user, request.form), "#fire")


@facility_bp.route("/training", methods=["POST"])
@_door
def training():
    return _do(lambda: fs.train(current_user, request.form), "#training")


@facility_bp.route("/utility", methods=["POST"])
@_door
def utility_new():
    return _do(lambda: fs.save_utility(request.form), "#utilities")


@facility_bp.route("/utility/<int:system_id>/check", methods=["POST"])
@_door
def utility_check(system_id):
    system = db.get_or_404(UtilitySystem, system_id)
    return _do(lambda: fs.utility_check(system, current_user, request.form), "#utilities")
