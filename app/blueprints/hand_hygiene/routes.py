"""Hand hygiene — GAHAR IPC.04 / GSR.22. The logic is in
``app/utils/hand_hygiene.py``."""
from functools import wraps

from flask import (abort, current_app, flash, redirect, render_template,
                   request, url_for)
from flask_login import current_user

from app.blueprints.hand_hygiene import hand_hygiene_bp
from app.extensions import db
from app.i18n import t
from app.models.hand_hygiene import (ACTIONS, CATEGORIES, FACILITY_ITEMS,
                                     MOMENTS, HandHygieneSession)
from app.utils import hand_hygiene as hh
from app.utils.clock import local_today


def _door(manage=False):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not current_user.is_authenticated:
                return current_app.login_manager.unauthorized()
            allowed = hh.may_manage(current_user) if manage else hh.may_observe(current_user)
            if not allowed:
                abort(403, description=t("auth.no_permission"))
            return view(*args, **kwargs)
        return wrapped
    return decorator


def _refused(err):
    flash(t(f"hh.err_{err}"), "error")


def _units():
    from app.models.place import Unit

    return (Unit.query.filter_by(is_active=True)
            .order_by(Unit.sort_order, Unit.name).all())


def _lang():
    from app.i18n import get_locale

    return get_locale()


def _period():
    from app.utils.appointments import parse_date_arg

    today = local_today()
    end = parse_date_arg(request.args.get("to"), today)
    raw = request.args.get("from")
    start = parse_date_arg(raw) if raw else end.replace(day=1)
    if start > end:
        start, end = end, start
    return start, end


@hand_hygiene_bp.route("/")
@_door()
def index():
    """The period's compliance by area, staff category and moment; the
    year's trend; the stations; and what was decided."""
    start, end = _period()
    return render_template(
        "hand_hygiene/index.html", start=start, end=end,
        data=hh.compliance(start, end, _lang()), trend=hh.trend(),
        target=hh.target(), stations=hh.latest_facilities(_lang()),
        decisions=hh.actions(start, end), units=_units(),
        sessions=(HandHygieneSession.query
                  .filter(HandHygieneSession.observed_on >= start,
                          HandHygieneSession.observed_on <= end)
                  .order_by(HandHygieneSession.observed_on.desc(),
                            HandHygieneSession.id.desc()).limit(30).all()),
        categories=CATEGORIES, moments=MOMENTS, this_month=local_today().strftime("%Y-%m"),
        may_manage=hh.may_manage(current_user))


@hand_hygiene_bp.route("/observe")
@_door()
def observe():
    return render_template("hand_hygiene/observe.html", units=_units(),
                           categories=CATEGORIES, moments=MOMENTS, actions=ACTIONS,
                           rows=range(hh.MAX_ROWS), today=local_today())


@hand_hygiene_bp.route("/observe", methods=["POST"])
@_door()
def observe_save():
    try:
        session = hh.observe(current_user, request.form)
    except hh.HandHygieneError as err:
        db.session.rollback()
        _refused(err)
        return redirect(url_for("hand_hygiene.observe"))
    db.session.commit()
    flash(t("hh.saved"), "success")
    return redirect(url_for("hand_hygiene.session", session_id=session.id))


@hand_hygiene_bp.route("/session/<int:session_id>")
@_door()
def session(session_id):
    row = db.get_or_404(HandHygieneSession, session_id)
    done = sum(1 for o in row.opportunities if o.done)
    return render_template("hand_hygiene/session.html", row=row, done=done,
                           rate=hh._rate(done, len(row.opportunities)))


@hand_hygiene_bp.route("/stations")
@_door()
def stations():
    return render_template("hand_hygiene/stations.html", units=_units(),
                           items=FACILITY_ITEMS, today=local_today(),
                           stations=hh.latest_facilities(_lang()))


@hand_hygiene_bp.route("/stations", methods=["POST"])
@_door()
def stations_save():
    try:
        hh.check_facilities(current_user, request.form)
    except hh.HandHygieneError as err:
        db.session.rollback()
        _refused(err)
        return redirect(url_for("hand_hygiene.stations"))
    db.session.commit()
    flash(t("hh.saved"), "success")
    return redirect(url_for("hand_hygiene.stations"))


@hand_hygiene_bp.route("/action", methods=["POST"])
@_door(manage=True)
def action_save():
    try:
        hh.add_action(current_user, request.form)
    except hh.HandHygieneError as err:
        db.session.rollback()
        _refused(err)
        return redirect(url_for("hand_hygiene.index") + "#decide")
    db.session.commit()
    flash(t("hh.saved"), "success")
    return redirect(url_for("hand_hygiene.index") + "#decide")


@hand_hygiene_bp.route("/target", methods=["POST"])
@_door(manage=True)
def target_save():
    try:
        hh.set_target(request.form.get("target"))
    except hh.HandHygieneError as err:
        db.session.rollback()
        _refused(err)
        return redirect(url_for("hand_hygiene.index"))
    db.session.commit()
    flash(t("hh.saved"), "success")
    return redirect(url_for("hand_hygiene.index"))


@hand_hygiene_bp.route("/training")
@_door(manage=True)
def training():
    from app.models import User

    return render_template("hand_hygiene/training.html", rows=hh.training_board(),
                           today=local_today(),
                           staff=User.query.filter(User.is_active.is_(True))
                           .order_by(User.full_name).all())


@hand_hygiene_bp.route("/training", methods=["POST"])
@_door(manage=True)
def training_save():
    f = request.form
    try:
        hh.train(f.get("user_id"), f.get("trained_on"), trainer=f.get("trainer"),
                 valid_until=f.get("valid_until"), by=current_user)
    except hh.HandHygieneError as err:
        db.session.rollback()
        _refused(err)
        return redirect(url_for("hand_hygiene.training"))
    db.session.commit()
    flash(t("hh.training_saved"), "success")
    return redirect(url_for("hand_hygiene.training"))
