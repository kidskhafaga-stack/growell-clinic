"""GAHAR MMS.16 on the ward — an adverse drug reaction written on the
child's stay (``utils/adverse_reaction``)."""
from flask import flash, redirect, request, url_for
from flask_login import current_user

from app.blueprints.beds import beds_bp
from app.extensions import db
from app.i18n import t
from app.models.admission import Admission
from app.utils import adverse_reaction as adr
from app.utils.decorators import module_required


@beds_bp.route("/admission/<int:admission_id>/adr", methods=["POST"])
@module_required("beds")
def adr_record(admission_id):
    from app.utils import notifications

    stay = db.get_or_404(Admission, admission_id)
    back = url_for("beds.admission", admission_id=stay.id) + "#adr"
    try:
        adr.record(stay, request.form, current_user)
    except adr.ReactionError as err:
        db.session.rollback()
        flash(t("adr.err_" + str(err)), "error")
        return redirect(back)
    db.session.commit()
    notifications.invalidate()
    flash(t("adr.recorded"), "success")
    return redirect(back)
