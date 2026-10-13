"""GAHAR MMS.08 — drug recalls by lot (``utils/drug_recall``)."""
from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user

from app.blueprints.med_storage import med_storage_bp
from app.blueprints.med_storage.routes import _door
from app.extensions import db
from app.i18n import t
from app.models.drug_recall import DrugRecall
from app.utils import drug_recall as rc
from app.utils import med_storage as ms


def _refused(err):
    db.session.rollback()
    flash(t("recall.err_" + str(err)), "error")


@med_storage_bp.route("/recalls")
@_door()
def recalls():
    from app.models import StoreItem

    return render_template("med_storage/recalls.html", rows=rc.board(),
                           items=StoreItem.query.filter_by(is_active=True).order_by(StoreItem.name).all(),
                           may_manage=ms.may_manage(current_user))


@med_storage_bp.route("/recalls/open", methods=["POST"])
@_door(manage=True)
def recall_open():
    from app.utils import notifications

    try:
        row = rc.open_recall(request.form, current_user)
    except rc.RecallError as err:
        _refused(err)
        return redirect(url_for("med_storage.recalls"))
    db.session.commit()
    notifications.invalidate()
    flash(t("recall.opened"), "success")
    return redirect(url_for("med_storage.recall", recall_id=row.id))


@med_storage_bp.route("/recall/<int:recall_id>")
@_door()
def recall(recall_id):
    row = db.get_or_404(DrugRecall, recall_id)
    return render_template("med_storage/recall.html", row=row, found=rc.trace(row),
                           may_manage=ms.may_manage(current_user))


@med_storage_bp.route("/recall/<int:recall_id>/act", methods=["POST"])
@_door(manage=True)
def recall_act(recall_id):
    from app.utils import notifications

    row = db.get_or_404(DrugRecall, recall_id)
    back = url_for("med_storage.recall", recall_id=row.id)
    try:
        if request.form.get("what") == "close":
            rc.close(row, current_user)
        else:
            rc.record_step(row, request.form.get("what"), request.form.get("note"), current_user)
    except rc.RecallError as err:
        _refused(err)
        return redirect(back)
    db.session.commit()
    notifications.invalidate()
    flash(t("recall.saved"), "success")
    return redirect(back)
