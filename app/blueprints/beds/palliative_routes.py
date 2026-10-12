"""GAHAR CSS.04 on the stay — the goals of care decided with the family, and
the symptoms reviewed (``utils/palliative``)."""
from flask import flash, redirect, request, url_for
from flask_login import current_user

from app.blueprints.beds import beds_bp
from app.extensions import db
from app.i18n import t
from app.models.admission import Admission
from app.utils import palliative as pall
from app.utils.decorators import module_required


def _back(stay_id, err=None):
    if err is not None:
        db.session.rollback()
        flash(t("pall.err_" + str(err)), "error")
    else:
        flash(t("pall.saved"), "success")
    return redirect(url_for("beds.admission", admission_id=stay_id) + "#palliative")


@beds_bp.route("/admission/<int:admission_id>/palliative/plan", methods=["POST"])
@module_required("beds")
def palliative_plan(admission_id):
    stay = db.get_or_404(Admission, admission_id)
    try:
        pall.save_plan(stay, request.form, current_user)
    except pall.PalliativeError as err:
        return _back(stay.id, err)
    db.session.commit()
    return _back(stay.id)


@beds_bp.route("/admission/<int:admission_id>/palliative/review", methods=["POST"])
@module_required("beds")
def palliative_review(admission_id):
    stay = db.get_or_404(Admission, admission_id)
    try:
        pall.review(stay, request.form, current_user)
    except pall.PalliativeError as err:
        return _back(stay.id, err)
    db.session.commit()
    return _back(stay.id)
