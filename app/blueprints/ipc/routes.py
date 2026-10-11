"""Infection control's alerts — the logic is in ``app/utils/ipc.py``.

Every route is ``infection_control`` (or the admin)."""
from datetime import date, timedelta
from functools import wraps

from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.blueprints.ipc import ipc_bp
from app.extensions import db
from app.i18n import t
from app.models.micro import ISOLATION, IpcAlert, MicroOrganism
from app.utils import hand_hygiene as hh
from app.utils import ipc
from app.utils.clock import local_today


def _reviewer(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if not ipc.may_review(current_user):
            abort(403, description=t("auth.no_permission"))
        return view(*args, **kwargs)
    return wrapped


def _day(key, default):
    try:
        return date.fromisoformat(request.args.get(key) or "")
    except ValueError:
        return default


@ipc_bp.route("/")
@_reviewer
def index():
    from app.models.theatre import EXTRA_PRECAUTIONS, PRECAUTIONS

    today = local_today()
    end = _day("to", today)
    start = _day("from", end - timedelta(days=30))
    if start > end:
        start, end = end, start
    return render_template("ipc/index.html", data=ipc.board(start, end),
                           start=start, end=end, precautions=PRECAUTIONS,
                           extra=EXTRA_PRECAUTIONS, isolation=ISOLATION,
                           hand_hygiene=hh.may_manage(current_user))


@ipc_bp.route("/alert/<int:alert_id>", methods=["POST"])
@_reviewer
def review(alert_id):
    row = db.get_or_404(IpcAlert, alert_id)
    try:
        ipc.review(row, request.form, current_user)
    except ipc.IpcError as err:
        db.session.rollback()
        flash(t(f"ipc.err_{err}"), "error")
        return redirect(url_for("ipc.index") + f"#alert-{alert_id}")
    db.session.commit()
    flash(t("ipc.reviewed"), "success")
    return redirect(url_for("ipc.index"))


@ipc_bp.route("/organism/<int:organism_id>", methods=["POST"])
@_reviewer
def organism_precaution(organism_id):
    row = db.get_or_404(MicroOrganism, organism_id)
    try:
        ipc.set_precaution(row, request.form.get("precaution"))
    except ipc.IpcError as err:
        db.session.rollback()
        flash(t(f"ipc.err_{err}"), "error")
        return redirect(url_for("ipc.index") + "#organisms")
    db.session.commit()
    return redirect(url_for("ipc.index") + "#organisms")
