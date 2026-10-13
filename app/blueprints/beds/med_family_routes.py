"""GAHAR MMS.15 ev. 3 and 5, MMS.16 ev. 2 on the ward — the family told,
a medicine given by the child or the family, and the first dose watched
(``utils/med_family``)."""
from flask import flash, redirect, request, url_for
from flask_login import current_user

from app.blueprints.beds import beds_bp
from app.extensions import db
from app.i18n import t
from app.models import MedicationOrder
from app.models.admission import Admission
from app.utils import med_family as fam
from app.utils.decorators import module_required


def _back(stay_id, err=None):
    if err is not None:
        db.session.rollback()
        flash(t("fammed.err_" + str(err)), "error")
    else:
        flash(t("fammed.saved"), "success")
    return redirect(url_for("beds.admission", admission_id=stay_id) + "#family-meds")


@beds_bp.route("/admission/<int:admission_id>/meds-told", methods=["POST"])
@module_required("beds")
def meds_told(admission_id):
    stay = db.get_or_404(Admission, admission_id)
    try:
        fam.counsel(stay, request.form, current_user, "informed")
    except fam.FamilyMedError as err:
        return _back(stay.id, err)
    db.session.commit()
    return _back(stay.id)


@beds_bp.route("/medication/<int:order_id>/self-admin", methods=["POST"])
@module_required("beds")
def meds_self_admin(order_id):
    order = db.get_or_404(MedicationOrder, order_id)
    try:
        fam.self_admin(order, request.form, current_user)
    except fam.FamilyMedError as err:
        return _back(order.admission_id, err)
    db.session.commit()
    return _back(order.admission_id)


@beds_bp.route("/medication/<int:order_id>/first-dose", methods=["POST"])
@module_required("beds")
def meds_first_dose(order_id):
    order = db.get_or_404(MedicationOrder, order_id)
    try:
        fam.observe(order, request.form, current_user)
    except fam.FamilyMedError as err:
        return _back(order.admission_id, err)
    db.session.commit()
    if request.form.get("outcome") == "reaction":
        # A reaction is an adverse drug reaction to write (MMS.16 ev. 3).
        flash(t("fammed.write_adr"), "warning")
        return redirect(url_for("beds.admission", admission_id=order.admission_id) + "#adr")
    return _back(order.admission_id)
