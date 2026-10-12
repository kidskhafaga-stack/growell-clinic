"""GAHAR MMS.09 ev. 5 on the ward — medicines a child brought in from home:
received, identified, labelled, and handed back (``utils/own_medicine``)."""
from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user

from app.blueprints.beds import beds_bp
from app.extensions import db
from app.i18n import t
from app.models.admission import Admission
from app.models.own_medicine import OwnMedicine
from app.utils import own_medicine as own
from app.utils.decorators import module_required

MODULE = "beds"


def _back(stay_id):
    return redirect(url_for("beds.admission", admission_id=stay_id) + "#own-meds")


def _refused(err, stay_id):
    db.session.rollback()
    flash(t("ownmed.err_" + str(err)), "error")
    return _back(stay_id)


@beds_bp.route("/admission/<int:admission_id>/own-meds", methods=["POST"])
@module_required(MODULE)
def own_med_receive(admission_id):
    stay = db.get_or_404(Admission, admission_id)
    if not stay.is_open:
        return _refused("closed", stay.id)
    try:
        row = own.receive(stay, request.form, current_user)
    except own.OwnMedicineError as err:
        return _refused(err, stay.id)
    db.session.commit()
    flash(t("ownmed.received"), "success")
    return redirect(url_for("beds.own_med_label", row_id=row.id))


@beds_bp.route("/own-meds/<int:row_id>/identify", methods=["POST"])
@module_required(MODULE)
def own_med_identify(row_id):
    row = db.get_or_404(OwnMedicine, row_id)
    try:
        own.identify(row, request.form, current_user)
    except own.OwnMedicineError as err:
        return _refused(err, row.admission_id)
    db.session.commit()
    flash(t("ownmed.identified"), "success")
    return _back(row.admission_id)


@beds_bp.route("/own-meds/<int:row_id>/out", methods=["POST"])
@module_required(MODULE)
def own_med_out(row_id):
    row = db.get_or_404(OwnMedicine, row_id)
    try:
        own.hand_out(row, request.form, current_user)
    except own.OwnMedicineError as err:
        return _refused(err, row.admission_id)
    db.session.commit()
    flash(t("ownmed.out_done"), "success")
    return _back(row.admission_id)


@beds_bp.route("/own-meds/<int:row_id>/label")
@module_required(MODULE)
def own_med_label(row_id):
    return render_template("beds/own_med_label.html", row=db.get_or_404(OwnMedicine, row_id))
