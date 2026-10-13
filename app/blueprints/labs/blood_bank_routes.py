"""The blood store, supplied from a contracted blood bank — GAHAR DAS.28,
DAS.29, DAS.30 (``utils/blood_bank``)."""
from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user

from app.blueprints.labs import labs_bp
from app.extensions import db
from app.i18n import t
from app.models.blood import PRODUCTS
from app.models.blood_bank import ABO, CROSSMATCHED, RH, BloodSupplier, BloodUnit
from app.utils import blood_bank as bb
from app.utils.clock import local_today
from app.utils.decorators import module_required

MODULE = "labs"


def _done(where, err=None):
    if err is not None:
        db.session.rollback()
        flash(t("bbank.err_" + str(err)), "error")
    else:
        db.session.commit()
        flash(t("bbank.saved"), "success")
    return redirect(where)


@labs_bp.route("/blood-bank", methods=["GET", "POST"])
@module_required(MODULE)
def blood_bank():
    if request.method == "POST":
        try:
            row = bb.receive(request.form, current_user, local_today())
        except bb.BloodBankError as err:
            return _done(url_for("labs.blood_bank"), err)
        return _done(url_for("labs.blood_unit", unit_id=row.id))
    return render_template("labs/blood_bank.html", data=bb.board(local_today()), suppliers=bb.suppliers(),
                           products=PRODUCTS, abo=ABO, rh=RH, crossmatched=CROSSMATCHED)


@labs_bp.route("/blood-bank/unit/<int:unit_id>")
@module_required(MODULE)
def blood_unit(unit_id):
    unit = db.get_or_404(BloodUnit, unit_id)
    return render_template("labs/blood_unit.html", unit=unit, trace=bb.trace(unit), requests=bb.open_requests(),
                           crossmatched=CROSSMATCHED, today=local_today())


@labs_bp.route("/blood-bank/unit/<int:unit_id>/<what>", methods=["POST"])
@module_required(MODULE)
def blood_unit_act(unit_id, what):
    unit = db.get_or_404(BloodUnit, unit_id)
    back = url_for("labs.blood_unit", unit_id=unit.id)
    try:
        if what == "issue":
            bb.issue(unit, request.form, current_user, local_today())
        elif what == "return":
            bb.give_back(unit, request.form)
        elif what == "discard":
            bb.discard(unit, request.form)
        else:
            abort(404)
    except bb.BloodBankError as err:
        return _done(back, err)
    return _done(back)


@labs_bp.route("/blood-bank/suppliers", methods=["GET", "POST"])
@module_required(MODULE)
def blood_suppliers():
    if request.method == "POST":
        if not current_user.is_admin:
            abort(403)
        try:
            if request.form.get("what") == "evaluate":
                bb.evaluate_supplier(db.get_or_404(BloodSupplier, request.form.get("supplier_id", type=int) or 0),
                                     request.form)
            else:
                bb.save_supplier(request.form)
        except bb.BloodBankError as err:
            return _done(url_for("labs.blood_suppliers"), err)
        return _done(url_for("labs.blood_suppliers"))
    return render_template("labs/blood_suppliers.html", rows=bb.suppliers(), today=local_today())
