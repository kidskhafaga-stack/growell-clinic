"""GAHAR IPC.12 on the ward — the precautions in force on a stay, the sign
on the child's door, and the airborne isolation room (``utils/ipc``)."""
from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user

from app.blueprints.beds import beds_bp
from app.extensions import db
from app.i18n import t
from app.models.admission import Admission
from app.models.place import Space
from app.utils import ipc
from app.utils.decorators import module_required

MODULE = "beds"


@beds_bp.route("/admission/<int:admission_id>/precautions", methods=["POST"])
@module_required(MODULE)
def stay_precautions(admission_id):
    """Set or end the precautions on a stay — whoever cares for the child:
    empiric ones start at the bedside, before any result (IPC.12)."""
    row = db.get_or_404(Admission, admission_id)
    back = url_for("beds.admission", admission_id=row.id) + "#precautions"
    if not row.is_open:
        flash(t("stayprec.err_closed"), "error")
        return redirect(back)
    try:
        ipc.set_stay_precautions(row, request.form.getlist("precautions"),
                                 note=request.form.get("note"),
                                 empiric=request.form.get("empiric") == "1",
                                 user=current_user)
    except ipc.IpcError:
        db.session.rollback()
        flash(t("ipc.err_precautions"), "error")
        return redirect(back)
    db.session.commit()
    flash(t("stayprec.saved"), "success")
    return redirect(back)


@beds_bp.route("/admission/<int:admission_id>/isolation-sign")
@module_required(MODULE)
def isolation_sign(admission_id):
    """The sign for the door — the precaution, nothing of the diagnosis."""
    row = db.get_or_404(Admission, admission_id)
    if not row.precaution_list:
        abort(404)
    return render_template("beds/isolation_sign.html", admission=row)


@beds_bp.route("/space/<int:space_id>/aiir", methods=["POST"])
@module_required(MODULE)
def space_aiir(space_id):
    if not current_user.is_admin:
        abort(403, description=t("auth.no_permission"))
    space = db.get_or_404(Space, space_id)
    if not space.is_isolation:
        flash(t("stayprec.err_not_isolation"), "error")
        return redirect(url_for("beds.setup"))
    space.is_aiir = not space.is_aiir
    db.session.commit()
    return redirect(url_for("beds.setup"))


@beds_bp.route("/space/<int:space_id>/respiratory", methods=["POST"])
@module_required(MODULE)
def space_respiratory(space_id):
    """The space designated for suspected respiratory infections (IPC.07)."""
    if not current_user.is_admin:
        abort(403, description=t("auth.no_permission"))
    space = db.get_or_404(Space, space_id)
    space.is_respiratory = not space.is_respiratory
    db.session.commit()
    return redirect(url_for("beds.setup"))
