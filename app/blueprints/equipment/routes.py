"""The medical equipment register — GAHAR EFS.10 / GSR.27 and CSS.02 /
GSR.08. The logic is in ``app/utils/equipment.py``."""
from datetime import timedelta
from functools import wraps

from flask import (abort, current_app, flash, redirect, render_template,
                   request, url_for)
from flask_login import current_user

from app.blueprints.equipment import equipment_bp
from app.extensions import db
from app.i18n import t
from app.models.equipment import (EVENT_KINDS, RESULTS, SCHEDULED, Equipment)
from app.utils import equipment as eq
from app.utils.clock import local_today


def _door(manage=False):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not current_user.is_authenticated:
                return current_app.login_manager.unauthorized()
            allowed = eq.may_manage(current_user) if manage else eq.may_report(current_user)
            if not allowed:
                abort(403, description=t("auth.no_permission"))
            return view(*args, **kwargs)
        return wrapped
    return decorator


def _refused(err):
    flash(t(f"equip.err_{err}"), "error")


def _devices():
    from app.models import MedicalDevice

    return (MedicalDevice.query.filter_by(is_active=True)
            .order_by(MedicalDevice.name).all())


@equipment_bp.route("/")
@_door()
def index():
    """Every piece of equipment: out of service or overdue first, then the
    critical ones."""
    show_retired = request.args.get("retired") == "1"
    return render_template("equipment/index.html",
                           rows=eq.board(include_retired=show_retired),
                           show_retired=show_retired, devices=_devices(),
                           may_manage=eq.may_manage(current_user))


@equipment_bp.route("/new", methods=["POST"])
@equipment_bp.route("/<int:equipment_id>/save", methods=["POST"])
@_door(manage=True)
def save(equipment_id=None):
    row = db.get_or_404(Equipment, equipment_id) if equipment_id else None
    try:
        row = eq.save(request.form, row)
    except eq.EquipmentError as err:
        db.session.rollback()
        _refused(err)
        return redirect(url_for("equipment.view", equipment_id=equipment_id)
                        if equipment_id else url_for("equipment.index"))
    db.session.commit()
    flash(t("equip.saved"), "success")
    return redirect(url_for("equipment.view", equipment_id=row.id))


@equipment_bp.route("/<int:equipment_id>")
@_door()
def view(equipment_id):
    from app.models import User

    row = db.get_or_404(Equipment, equipment_id)
    today = local_today()
    return render_template(
        "equipment/view.html", row=row, today=today,
        checks={k: eq.due(row, k, today) for k in SCHEDULED},
        broken=eq.open_malfunction(row), trained=eq.trained_now(row, today),
        kinds=[k for k in EVENT_KINDS if eq.may_manage(current_user) or k in eq.REPORTABLE],
        scheduled=SCHEDULED, results=RESULTS, devices=_devices(),
        staff=User.query.filter(User.is_active.is_(True)).order_by(User.full_name).all(),
        may_manage=eq.may_manage(current_user))


@equipment_bp.route("/<int:equipment_id>/event", methods=["POST"])
@_door()
def event(equipment_id):
    row = db.get_or_404(Equipment, equipment_id)
    try:
        eq.record(row, current_user, request.form)
    except eq.EquipmentError as err:
        db.session.rollback()
        _refused(err)
        return redirect(url_for("equipment.view", equipment_id=row.id) + "#event")
    db.session.commit()
    flash(t("equip.event_saved"), "success")
    return redirect(url_for("equipment.view", equipment_id=row.id))


@equipment_bp.route("/<int:equipment_id>/train", methods=["POST"])
@_door(manage=True)
def train(equipment_id):
    row = db.get_or_404(Equipment, equipment_id)
    f = request.form
    try:
        eq.train(row, f.get("user_id"), f.get("trained_on"), trainer=f.get("trainer"),
                 valid_until=f.get("valid_until"), by=current_user)
    except eq.EquipmentError as err:
        db.session.rollback()
        _refused(err)
        return redirect(url_for("equipment.view", equipment_id=row.id) + "#training")
    db.session.commit()
    flash(t("equip.training_saved"), "success")
    return redirect(url_for("equipment.view", equipment_id=row.id) + "#training")


@equipment_bp.route("/<int:equipment_id>/retire", methods=["POST"])
@_door(manage=True)
def retire(equipment_id):
    row = db.get_or_404(Equipment, equipment_id)
    try:
        eq.retire(row, request.form.get("reason"))
    except eq.EquipmentError as err:
        db.session.rollback()
        _refused(err)
        return redirect(url_for("equipment.view", equipment_id=row.id))
    db.session.commit()
    flash(t("equip.retired_ok"), "success")
    return redirect(url_for("equipment.view", equipment_id=row.id))


@equipment_bp.route("/incidents")
@_door()
def incidents():
    """Malfunctions, adverse incidents and alarm events over a period."""
    from app.utils.appointments import parse_date_arg

    end = parse_date_arg(request.args.get("to"), local_today())
    raw = request.args.get("from")
    start = parse_date_arg(raw) if raw else end - timedelta(days=89)
    if start > end:
        start, end = end, start
    return render_template("equipment/incidents.html", start=start, end=end,
                           rows=eq.incidents(start, end))
