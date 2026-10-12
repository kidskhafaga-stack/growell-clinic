"""The sterilization logbook — ``utils/sterilization``. Whoever runs the
sterilizer records; infection control sets the sterilizers and the
hospital's limits, and signs the month."""
from functools import wraps

from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.blueprints.ipc import ipc_bp
from app.blueprints.ipc.routes import _reviewer
from app.extensions import db
from app.i18n import t
from app.models.sterilization import (BI_RESULTS, CYCLE_KINDS, RESULTS, Sterilizer,
                                      SterilizerCycle)
from app.utils import ipc as ipc_utils
from app.utils import sterilization as st
from app.utils.clock import local_today


def _recorder(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if not st.may_record(current_user):
            abort(403, description=t("auth.no_permission"))
        return view(*args, **kwargs)
    return wrapped


def _back(err=None, anchor=""):
    if err is not None:
        flash(t(f"steril.err_{err}"), "error")
    return redirect(url_for("ipc.sterilization") + anchor)


@ipc_bp.route("/sterilization")
@_recorder
def sterilization():
    from app.models import HldTest

    return render_template("ipc/sterilization.html", data=st.board(local_today()),
                           kinds=CYCLE_KINDS, results=RESULTS, bi_results=BI_RESULTS,
                           hld=HldTest.query.order_by(HldTest.tested_at.desc()).limit(20).all(),
                           months=st.months(), every=st.BI_EVERY_DAYS,
                           sterilizers=Sterilizer.query.order_by(Sterilizer.name).all(),
                           may_setup=ipc_utils.may_review(current_user))


@ipc_bp.route("/sterilization/sterilizer", methods=["POST"])
@_reviewer
def sterilizer_save():
    row = db.session.get(Sterilizer, request.form.get("id", type=int) or 0)
    try:
        st.save_sterilizer(request.form, row)
    except st.SterilizationError as err:
        db.session.rollback()
        return _back(err, "#setup")
    db.session.commit()
    return _back(anchor="#setup")


@ipc_bp.route("/sterilization/<int:sterilizer_id>/cycle", methods=["POST"])
@_recorder
def sterilizer_cycle(sterilizer_id):
    row = db.get_or_404(Sterilizer, sterilizer_id)
    try:
        cycle = st.record_cycle(row, request.form, current_user)
    except st.SterilizationError as err:
        db.session.rollback()
        return _back(err, f"#st-{row.id}")
    db.session.commit()
    flash(t("steril.cycle_failed" if cycle.failed else "steril.cycle_ok"),
          "warning" if cycle.failed else "success")
    return _back(anchor=f"#st-{row.id}")


@ipc_bp.route("/sterilization/cycle/<int:cycle_id>/bi", methods=["POST"])
@_recorder
def sterilizer_bi(cycle_id):
    row = db.get_or_404(SterilizerCycle, cycle_id)
    try:
        st.read_bi(row, request.form, current_user)
    except st.SterilizationError as err:
        db.session.rollback()
        return _back(err, f"#st-{row.sterilizer_id}")
    db.session.commit()
    return _back(anchor=f"#st-{row.sterilizer_id}")


@ipc_bp.route("/sterilization/hld", methods=["POST"])
@_recorder
def hld_test():
    try:
        st.record_hld(request.form, current_user)
    except st.SterilizationError as err:
        db.session.rollback()
        return _back(err, "#hld")
    db.session.commit()
    return _back(anchor="#hld")


@ipc_bp.route("/sterilization/review", methods=["POST"])
@_reviewer
def sterilization_review():
    try:
        st.review(request.form.get("month"), request.form.get("note"), current_user)
    except st.SterilizationError as err:
        db.session.rollback()
        return _back(err, "#review")
    db.session.commit()
    return _back(anchor="#review")
