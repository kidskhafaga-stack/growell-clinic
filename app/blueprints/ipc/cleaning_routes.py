"""Environmental cleaning — ``utils/cleaning``. The schedule is infection
control's; a task done is recorded by whoever cleans or supervises it."""
from functools import wraps

from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.blueprints.ipc import ipc_bp
from app.blueprints.ipc.routes import _reviewer
from app.extensions import db
from app.i18n import t
from app.models.cleaning import FREQUENCIES, RISKS, CleaningArea, CleaningTask
from app.utils import cleaning as cl
from app.utils import ipc as ipc_utils
from app.utils.clock import local_today


def _recorder(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if not cl.may_record(current_user):
            abort(403, description=t("auth.no_permission"))
        return view(*args, **kwargs)
    return wrapped


def _refused(err):
    flash(t(f"clean.err_{err}"), "error")


@ipc_bp.route("/cleaning")
@_recorder
def cleaning():
    from app.models.place import Unit

    return render_template("ipc/cleaning.html", data=cl.board(local_today()), today=local_today(),
                           risks=RISKS, frequencies=FREQUENCIES,
                           units=Unit.query.filter_by(is_active=True).order_by(Unit.sort_order).all(),
                           areas=CleaningArea.query.order_by(CleaningArea.name).all(),
                           may_setup=ipc_utils.may_review(current_user))


@ipc_bp.route("/cleaning/area", methods=["POST"])
@_reviewer
def cleaning_area():
    try:
        cl.add_area(request.form)
    except cl.CleaningError as err:
        db.session.rollback()
        _refused(err)
        return redirect(url_for("ipc.cleaning") + "#setup")
    db.session.commit()
    return redirect(url_for("ipc.cleaning") + "#setup")


@ipc_bp.route("/cleaning/area/<int:area_id>/task", methods=["POST"])
@_reviewer
def cleaning_task_add(area_id):
    area = db.get_or_404(CleaningArea, area_id)
    try:
        cl.add_task(area, request.form)
    except cl.CleaningError as err:
        db.session.rollback()
        _refused(err)
        return redirect(url_for("ipc.cleaning") + "#setup")
    db.session.commit()
    return redirect(url_for("ipc.cleaning") + "#setup")


@ipc_bp.route("/cleaning/task/<int:task_id>/stop", methods=["POST"])
@_reviewer
def cleaning_task_stop(task_id):
    row = db.get_or_404(CleaningTask, task_id)
    row.is_active = not row.is_active
    db.session.commit()
    return redirect(url_for("ipc.cleaning") + "#setup")


@ipc_bp.route("/cleaning/task/<int:task_id>/done", methods=["POST"])
@_recorder
def cleaning_done(task_id):
    row = db.get_or_404(CleaningTask, task_id)
    try:
        cl.record(row, request.form, current_user)
    except cl.CleaningError as err:
        db.session.rollback()
        _refused(err)
        return redirect(url_for("ipc.cleaning"))
    db.session.commit()
    flash(t("clean.recorded"), "success")
    return redirect(url_for("ipc.cleaning") + f"#area-{row.area_id}")
