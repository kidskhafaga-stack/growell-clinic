"""Where medicines are kept — GAHAR MMS.04 / GSR.19.

The storage places with their monthly inspection and today's temperatures,
the expiry list, and power outages. The logic is in
``app/utils/med_storage.py``.

**Not behind the pharmacy module alone.** A fridge on a ward is read by the
ward's nurse and a store by its keeper; whoever can reach the pharmacy, the
store or the beds can write a reading or an inspection. Setting the places
up and deciding on an outage is the pharmacy's.
"""
from datetime import timedelta
from functools import wraps

from flask import (abort, current_app, flash, redirect, render_template,
                   request, url_for)
from flask_login import current_user

from app.blueprints.med_storage import med_storage_bp
from app.extensions import db
from app.i18n import t
from app.models.med_storage import (ANSWERS, AREA_KINDS, INSPECTION_ITEMS,
                                    OUTAGE_DECISIONS, PowerOutage, StorageArea)
from app.utils import med_storage as ms
from app.utils.clock import local_today


def _door(manage=False):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not current_user.is_authenticated:
                return current_app.login_manager.unauthorized()
            from app.utils.facility import module_enabled

            if not (module_enabled("pharmacy") or module_enabled("inventory")):
                abort(404)
            allowed = ms.may_manage(current_user) if manage else ms.may_record(current_user)
            if not allowed:
                abort(403, description=t("auth.no_permission"))
            return view(*args, **kwargs)
        return wrapped
    return decorator


def _refused(err):
    flash(t(f"med_store.err_{err}"), "error")


@med_storage_bp.route("/")
@_door()
def storage():
    """Every place medicines are kept: its last inspection, today's
    temperatures against the hospital's range, the open outages, and how
    many lots are expired or near."""
    from app.models import Warehouse

    return render_template("med_storage/storage.html", data=ms.board(),
                           kinds=AREA_KINDS, may_manage=ms.may_manage(current_user),
                           warehouses=Warehouse.query.filter_by(is_active=True).all())


@med_storage_bp.route("/areas", methods=["POST"])
@med_storage_bp.route("/area/<int:area_id>/save", methods=["POST"])
@_door(manage=True)
def storage_area_save(area_id=None):
    row = db.get_or_404(StorageArea, area_id) if area_id else None
    try:
        row = ms.save_area(request.form, row)
    except ms.StorageError as err:
        db.session.rollback()
        _refused(err)
        return redirect(url_for("med_storage.storage_area", area_id=area_id)
                        if area_id else url_for("med_storage.storage"))
    db.session.commit()
    flash(t("med_store.area_saved"), "success")
    return redirect(url_for("med_storage.storage_area", area_id=row.id))


@med_storage_bp.route("/area/<int:area_id>/retire", methods=["POST"])
@_door(manage=True)
def storage_area_retire(area_id):
    row = db.get_or_404(StorageArea, area_id)
    row.is_active = not row.is_active
    db.session.commit()
    return redirect(url_for("med_storage.storage_area", area_id=row.id))


@med_storage_bp.route("/area/<int:area_id>")
@_door()
def storage_area(area_id):
    """One place: its range, its readings of the last fortnight, and its
    inspections."""
    from app.models import StorageInspection, Warehouse

    row = db.get_or_404(StorageArea, area_id)
    today = local_today()
    return render_template(
        "med_storage/storage_area.html", area=row, today=today,
        readings=ms.readings(row.id, today - timedelta(days=13), today),
        state=ms.today_state(row, today), due=ms.inspection_due(row, today),
        inspections=(StorageInspection.query.filter_by(area_id=row.id)
                     .order_by(StorageInspection.inspected_on.desc()).limit(24).all()),
        items=INSPECTION_ITEMS, answers=ANSWERS, kinds=AREA_KINDS,
        warehouses=Warehouse.query.filter_by(is_active=True).all(),
        may_manage=ms.may_manage(current_user))


@med_storage_bp.route("/area/<int:area_id>/temp", methods=["POST"])
@_door()
def storage_temp(area_id):
    row = db.get_or_404(StorageArea, area_id)
    try:
        reading = ms.read_temp(row, current_user, request.form.get("temp_c"),
                               humidity=request.form.get("humidity"),
                               action=request.form.get("action"))
    except ms.StorageError as err:
        db.session.rollback()
        _refused(err)
        return redirect(url_for("med_storage.storage_area", area_id=row.id) + "#temp")
    db.session.commit()
    flash(t("med_store.temp_out" if reading.out_of_range else "med_store.temp_saved"),
          "warning" if reading.out_of_range else "success")
    return redirect(url_for("med_storage.storage_area", area_id=row.id) + "#temp")


@med_storage_bp.route("/area/<int:area_id>/inspect", methods=["POST"])
@_door()
def storage_inspect(area_id):
    row = db.get_or_404(StorageArea, area_id)
    try:
        ms.inspect(row, current_user, request.form)
    except ms.StorageError as err:
        db.session.rollback()
        _refused(err)
        return redirect(url_for("med_storage.storage_area", area_id=row.id) + "#inspect")
    db.session.commit()
    flash(t("med_store.inspection_saved"), "success")
    return redirect(url_for("med_storage.storage_area", area_id=row.id))


@med_storage_bp.route("/expiry")
@_door()
def storage_expiry():
    """Every lot with something left that is expired or near — store items
    and vaccine batches on one list, expired first."""
    return render_template("med_storage/storage_expiry.html", rows=ms.expiry_list(),
                           near_days=ms.NEAR_EXPIRY_DAYS)


@med_storage_bp.route("/outages")
@_door()
def storage_outages():
    rows = PowerOutage.query.order_by(PowerOutage.started_at.desc()).limit(50).all()
    return render_template("med_storage/storage_outages.html", rows=rows,
                           areas=ms.areas(active_only=False),
                           may_manage=ms.may_manage(current_user))


@med_storage_bp.route("/outages", methods=["POST"])
@_door()
def storage_outage_new():
    try:
        row = ms.open_outage(current_user, request.form)
    except ms.StorageError as err:
        db.session.rollback()
        _refused(err)
        return redirect(url_for("med_storage.storage_outages"))
    db.session.commit()
    flash(t("med_store.outage_saved"), "warning")
    return redirect(url_for("med_storage.storage_outage", outage_id=row.id))


@med_storage_bp.route("/outage/<int:outage_id>")
@_door()
def storage_outage(outage_id):
    from app.models import StoreItem

    row = db.get_or_404(PowerOutage, outage_id)
    names = {a.id: a for a in ms.areas(active_only=False)}
    return render_template(
        "med_storage/storage_outage.html", row=row, decisions=OUTAGE_DECISIONS,
        affected=[names[a] for a in row.area_list if a in names],
        items=StoreItem.query.filter_by(is_active=True).order_by(StoreItem.name).all(),
        may_manage=ms.may_manage(current_user))


def _outage_back(row):
    return redirect(url_for("med_storage.storage_outage", outage_id=row.id))


@med_storage_bp.route("/outage/<int:outage_id>/end", methods=["POST"])
@_door()
def storage_outage_end(outage_id):
    row = db.get_or_404(PowerOutage, outage_id)
    try:
        ms.end_outage(row, request.form)
    except ms.StorageError as err:
        db.session.rollback()
        _refused(err)
        return _outage_back(row)
    db.session.commit()
    flash(t("med_store.outage_ended"), "success")
    return _outage_back(row)


@med_storage_bp.route("/outage/<int:outage_id>/decide", methods=["POST"])
@_door(manage=True)
def storage_outage_decide(outage_id):
    row = db.get_or_404(PowerOutage, outage_id)
    try:
        ms.decide(row, current_user, request.form)
    except ms.StorageError as err:
        db.session.rollback()
        _refused(err)
        return _outage_back(row)
    db.session.commit()
    flash(t("med_store.decision_saved"), "success")
    return _outage_back(row)


@med_storage_bp.route("/outage/<int:outage_id>/close", methods=["POST"])
@_door(manage=True)
def storage_outage_close(outage_id):
    row = db.get_or_404(PowerOutage, outage_id)
    try:
        ms.close_outage(row, current_user)
    except ms.StorageError as err:
        db.session.rollback()
        _refused(err)
        return _outage_back(row)
    db.session.commit()
    flash(t("med_store.outage_closed"), "success")
    return _outage_back(row)
