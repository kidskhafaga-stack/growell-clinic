"""GAHAR IPC.20 (h) on the ward — expressed breast milk: received into the
fridge or freezer with a label, given only to its own baby before it
expires, and the board of every bag kept (``utils/breast_milk``)."""
from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user

from app.blueprints.beds import beds_bp
from app.extensions import db
from app.i18n import t
from app.models.admission import Admission
from app.models.breast_milk import MilkBag
from app.utils import breast_milk as milk
from app.utils.decorators import module_required

MODULE = "beds"


def _refused(err, back):
    db.session.rollback()
    flash(t("milk.err_" + str(err)), "error")
    return redirect(back)


@beds_bp.route("/admission/<int:admission_id>/milk", methods=["POST"])
@module_required(MODULE)
def milk_receive(admission_id):
    row = db.get_or_404(Admission, admission_id)
    back = url_for("beds.admission", admission_id=row.id) + "#milk"
    if not row.is_open:
        return _refused("closed", back)
    try:
        bag = milk.receive(row, request.form, current_user)
    except milk.MilkError as err:
        return _refused(err, back)
    db.session.commit()
    flash(t("milk.received", code=bag.code), "success")
    return redirect(url_for("beds.milk_label", bag_id=bag.id))


@beds_bp.route("/admission/<int:admission_id>/milk/give", methods=["POST"])
@module_required(MODULE)
def milk_give(admission_id):
    """The bag scanned or typed on the baby's own page — another baby's bag
    is refused before anything is written."""
    row = db.get_or_404(Admission, admission_id)
    back = url_for("beds.admission", admission_id=row.id) + "#milk"
    if not row.is_open:
        return _refused("closed", back)
    try:
        bag = milk.give(row, request.form, current_user)
    except milk.MilkError as err:
        return _refused(err, back)
    db.session.commit()
    flash(t("milk.given", code=bag.code), "success")
    return redirect(back)


@beds_bp.route("/milk/<int:bag_id>/label")
@module_required(MODULE)
def milk_label(bag_id):
    return render_template("beds/milk_label.html", bag=db.get_or_404(MilkBag, bag_id))


@beds_bp.route("/milk")
@module_required(MODULE)
def milk_board():
    from datetime import datetime

    return render_template("beds/milk.html", bags=milk.board(), now=datetime.utcnow(),
                           hours={s: milk.hours_for(s) for s in milk.HOURS_SETTINGS})


@beds_bp.route("/milk/<int:bag_id>/thaw", methods=["POST"])
@module_required(MODULE)
def milk_thaw(bag_id):
    bag = db.get_or_404(MilkBag, bag_id)
    try:
        milk.thaw(bag, current_user)
    except milk.MilkError as err:
        return _refused(err, url_for("beds.milk_board"))
    db.session.commit()
    flash(t("milk.thawed", code=bag.code), "success")
    return redirect(url_for("beds.milk_board"))


@beds_bp.route("/milk/<int:bag_id>/discard", methods=["POST"])
@module_required(MODULE)
def milk_discard(bag_id):
    bag = db.get_or_404(MilkBag, bag_id)
    try:
        milk.discard(bag, request.form.get("reason"))
    except milk.MilkError as err:
        return _refused(err, url_for("beds.milk_board"))
    db.session.commit()
    flash(t("milk.discarded", code=bag.code), "success")
    return redirect(url_for("beds.milk_board"))


@beds_bp.route("/milk/hours", methods=["POST"])
@module_required(MODULE)
def milk_hours():
    """The hospital's keeping times — the admin writes them from policy."""
    if not current_user.is_admin:
        abort(403, description=t("auth.no_permission"))
    try:
        milk.set_hours(request.form)
    except milk.MilkError as err:
        return _refused(err, url_for("beds.milk_board"))
    db.session.commit()
    flash(t("milk.hours_saved"), "success")
    return redirect(url_for("beds.milk_board"))
