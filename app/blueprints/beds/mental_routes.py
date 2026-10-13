"""GAHAR CSS.11 on the stay — the risk of harm screened, and rapid
tranquilization recorded (``utils/mental_health``)."""
from flask import abort, flash, redirect, request, url_for
from flask_login import current_user

from app.blueprints.beds import beds_bp
from app.extensions import db
from app.i18n import t
from app.models.admission import Admission
from app.utils import mental_health as mh
from app.utils.decorators import module_required


def _back(stay_id, err=None):
    if err is not None:
        db.session.rollback()
        flash(t("mental.err_" + str(err)), "error")
    else:
        flash(t("mental.saved"), "success")
    return redirect(url_for("beds.admission", admission_id=stay_id) + "#mental")


@beds_bp.route("/admission/<int:admission_id>/harm-screen", methods=["POST"])
@module_required("beds")
def harm_screen(admission_id):
    stay = db.get_or_404(Admission, admission_id)
    try:
        mh.screen(stay, request.form, current_user)
    except mh.MentalHealthError as err:
        return _back(stay.id, err)
    db.session.commit()
    return _back(stay.id)


@beds_bp.route("/admission/<int:admission_id>/tranquilization", methods=["POST"])
@module_required("beds")
def tranquilization(admission_id):
    stay = db.get_or_404(Admission, admission_id)
    try:
        mh.tranquilize(stay, request.form, current_user)
    except mh.MentalHealthError as err:
        return _back(stay.id, err)
    db.session.commit()
    return _back(stay.id)


@beds_bp.route("/harm-screen/tool", methods=["POST"])
@module_required("beds")
def harm_screen_tool():
    """The hospital's screening tool's name — the admin writes it."""
    from app.models import Setting

    if not current_user.is_admin:
        abort(403, description=t("auth.no_permission"))
    Setting.set(mh.TOOL_SETTING, (request.form.get("tool") or "").strip()[:120])
    db.session.commit()
    flash(t("mental.saved"), "success")
    return redirect(request.referrer or url_for("beds.index"))
