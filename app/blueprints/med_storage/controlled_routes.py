"""GAHAR MMS.09 ev. 4 — the controlled-drug register (``utils/controlled``):
one page per drug per place, kept by whoever keeps the cabinet."""
from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user

from app.blueprints.med_storage import med_storage_bp
from app.blueprints.med_storage.routes import _door
from app.extensions import db
from app.i18n import t
from app.models.controlled import ControlledItem
from app.models.med_storage import StorageArea
from app.utils import controlled
from app.utils import med_storage as ms


def _areas():
    return StorageArea.query.filter_by(is_active=True).order_by(StorageArea.name).all()


@med_storage_bp.route("/controlled")
@_door()
def controlled_book():
    return render_template(
        "med_storage/controlled.html", pages=controlled.pages(), areas=_areas(),
        items=ControlledItem.query.filter_by(is_active=True).order_by(ControlledItem.name).all(),
        may_manage=ms.may_manage(current_user))


@med_storage_bp.route("/controlled/items", methods=["POST"])
@_door(manage=True)
def controlled_item_save():
    try:
        controlled.save_item(request.form)
    except controlled.ControlledError as err:
        db.session.rollback()
        flash(t("ctrl.err_" + str(err)), "error")
        return redirect(url_for("med_storage.controlled_book"))
    db.session.commit()
    flash(t("ctrl.item_saved"), "success")
    return redirect(url_for("med_storage.controlled_book"))


@med_storage_bp.route("/controlled/open", methods=["POST"])
@_door()
def controlled_open():
    """Open a page: the drug and the place chosen on the book's front."""
    item = db.get_or_404(ControlledItem, request.form.get("item_id", type=int) or 0)
    area = db.get_or_404(StorageArea, request.form.get("area_id", type=int) or 0)
    return redirect(url_for("med_storage.controlled_page", item_id=item.id, area_id=area.id))


@med_storage_bp.route("/controlled/<int:item_id>/<int:area_id>")
@_door()
def controlled_page(item_id, area_id):
    from app.models import User
    from app.models.admission import Admission

    item = db.get_or_404(ControlledItem, item_id)
    area = db.get_or_404(StorageArea, area_id)
    stays = (Admission.query.filter(Admission.discharged_at.is_(None))
             .order_by(Admission.admitted_at.desc()).all())
    return render_template(
        "med_storage/controlled_page.html", item=item, area=area,
        rows=controlled.page(item.id, area.id), book=controlled.balance(item.id, area.id),
        areas=[a for a in _areas() if a.id != area.id], stays=stays,
        people=User.query.filter_by(is_active=True).order_by(User.id).all())


@med_storage_bp.route("/controlled/<int:item_id>/<int:area_id>/record", methods=["POST"])
@_door()
def controlled_record(item_id, area_id):
    item = db.get_or_404(ControlledItem, item_id)
    area = db.get_or_404(StorageArea, area_id)
    back = url_for("med_storage.controlled_page", item_id=item.id, area_id=area.id)
    try:
        row = controlled.record(item, area, request.form, current_user)
    except controlled.ControlledError as err:
        db.session.rollback()
        flash(t("ctrl.err_" + str(err)), "error")
        return redirect(back)
    db.session.commit()
    if row.kind == "count" and row.qty:
        flash(t("ctrl.count_differs"), "warning")
    else:
        flash(t("ctrl.recorded"), "success")
    return redirect(back)
