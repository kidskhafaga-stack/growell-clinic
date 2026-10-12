"""GAHAR MMS.05 — emergency medication carts (``utils/emergency_cart``)."""
from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user

from app.blueprints.med_storage import med_storage_bp
from app.blueprints.med_storage.routes import _door
from app.extensions import db
from app.i18n import t
from app.models.emergency_cart import CartUse
from app.models.med_storage import StorageArea
from app.utils import emergency_cart as carts
from app.utils import med_storage as ms


def _back(err=None):
    if err is not None:
        db.session.rollback()
        flash(t("cart.err_" + str(err)), "error")
    return redirect(url_for("med_storage.carts_board"))


def _cart(area_id):
    area = db.get_or_404(StorageArea, area_id)
    if area.kind != "cart":
        abort(404)
    return area


@med_storage_bp.route("/carts")
@_door()
def carts_board():
    from app.models.admission import Admission

    stays = (Admission.query.filter(Admission.discharged_at.is_(None))
             .order_by(Admission.admitted_at.desc()).all())
    return render_template("med_storage/carts.html", data=carts.board(), items=carts.items(),
                           hours=carts.replace_hours(), stays=stays,
                           may_manage=ms.may_manage(current_user))


@med_storage_bp.route("/carts/<int:area_id>/check", methods=["POST"])
@_door()
def cart_check(area_id):
    try:
        carts.check(_cart(area_id), request.form, current_user)
    except carts.CartError as err:
        return _back(err)
    db.session.commit()
    flash(t("cart.saved"), "success")
    return _back()


@med_storage_bp.route("/carts/<int:area_id>/use", methods=["POST"])
@_door()
def cart_use(area_id):
    from app.models.admission import Admission

    form = request.form.to_dict()
    stay = db.session.get(Admission, request.form.get("admission_id", type=int) or 0)
    form["patient_id"] = stay.patient_id if stay else None
    try:
        carts.use(_cart(area_id), form, current_user)
    except carts.CartError as err:
        return _back(err)
    db.session.commit()
    flash(t("cart.saved"), "success")
    return _back()


@med_storage_bp.route("/carts/use/<int:use_id>/restock", methods=["POST"])
@_door()
def cart_restock(use_id):
    from app.utils import notifications

    try:
        carts.restock(db.get_or_404(CartUse, use_id), request.form, current_user)
    except carts.CartError as err:
        return _back(err)
    db.session.commit()
    notifications.invalidate()
    flash(t("cart.saved"), "success")
    return _back()


@med_storage_bp.route("/carts/setup", methods=["POST"])
@_door(manage=True)
def cart_setup():
    try:
        if request.form.get("what") == "hours":
            carts.set_hours(request.form.get("hours"))
        else:
            carts.add_item(request.form)
    except carts.CartError as err:
        return _back(err)
    db.session.commit()
    flash(t("cart.saved"), "success")
    return _back()
