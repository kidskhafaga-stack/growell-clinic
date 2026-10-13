"""Remote encounters, the programme's settings and its periodic evaluation
(GAHAR ACT.16; ``utils/telemedicine``)."""
from datetime import date, timedelta

from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user

from app.blueprints.telemedicine import telemedicine_bp
from app.extensions import db
from app.i18n import t
from app.models.telemedicine import MODALITIES, OUTCOMES, TeleEncounter
from app.utils import telemedicine as tele
from app.utils.clock import local_today
from app.utils.decorators import module_required

MODULE = "telemedicine"


def _done(where, err=None):
    if err is not None:
        db.session.rollback()
        flash(t("tele.err_" + str(err)), "error")
    else:
        db.session.commit()
        flash(t("tele.saved"), "success")
    return redirect(where)


def _doctors():
    from app.models import User

    return (User.query.filter(User.is_active.is_(True),
                              db.or_(User.role == "doctor", User.is_practitioner.is_(True)))
            .order_by(User.full_name).all())


@telemedicine_bp.route("/", methods=["GET", "POST"])
@module_required(MODULE)
def index():
    if request.method == "POST":
        try:
            row = tele.request(request.form, current_user)
        except tele.TeleError as err:
            return _done(url_for("telemedicine.index"), err)
        return _done(url_for("telemedicine.encounter", enc_id=row.id))
    return render_template("telemedicine/index.html", data=tele.board(), program=tele.program(),
                           modalities=MODALITIES, doctors=_doctors())


@telemedicine_bp.route("/<int:enc_id>")
@module_required(MODULE)
def encounter(enc_id):
    row = db.get_or_404(TeleEncounter, enc_id)
    return render_template("telemedicine/encounter.html", enc=row, program=tele.program(), outcomes=OUTCOMES)


@telemedicine_bp.route("/<int:enc_id>/<what>", methods=["POST"])
@module_required(MODULE)
def act(enc_id, what):
    row = db.get_or_404(TeleEncounter, enc_id)
    back = url_for("telemedicine.encounter", enc_id=row.id)
    try:
        if what == "start":
            tele.start(row, request.form, current_user)
        elif what == "end":
            tele.end(row, request.form)
        elif what == "cancel":
            tele.cancel(row, request.form)
        else:
            abort(404)
    except tele.TeleError as err:
        return _done(back, err)
    return _done(back)


@telemedicine_bp.route("/programme", methods=["GET", "POST"])
@module_required(MODULE)
def programme():
    """The hospital's criteria (i), platforms (b) and the doctor who
    oversees the service (ev. 3); and the periodic evaluation (l)."""
    if request.method == "POST":
        try:
            if request.form.get("what") == "review":
                tele.add_review(request.form, current_user)
            else:
                if not current_user.is_admin:
                    abort(403)
                tele.save_program(request.form)
        except tele.TeleError as err:
            return _done(url_for("telemedicine.programme"), err)
        return _done(url_for("telemedicine.programme"))
    today = local_today()
    try:
        start = date.fromisoformat(request.args.get("from") or "")
    except ValueError:
        start = today - timedelta(days=90)
    try:
        end = date.fromisoformat(request.args.get("to") or "")
    except ValueError:
        end = today
    return render_template("telemedicine/programme.html", program=tele.program(), stats=tele.evaluation(start, end),
                           reviews=tele.reviews(), start=start, end=end, modalities=MODALITIES, outcomes=OUTCOMES)
