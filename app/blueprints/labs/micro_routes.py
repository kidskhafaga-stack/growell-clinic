"""Microbiology on the bench: the laboratory's lists, a culture answered in
its parts, and the antibiogram (`utils/micro`, `models/micro`)."""
from datetime import timedelta

from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user

from app.blueprints.labs import labs_bp
from app.blueprints.labs.routes import MODULE, _admin_only
from app.extensions import db
from app.i18n import t
from app.models import (CultureIsolate, MicroAntibiotic, MicroOrganism,
                        VisitInvestigation)
from app.utils import micro
from app.utils.clock import local_today
from app.utils.decorators import module_required


# ------------------------------------------------------------ the lists ---
@labs_bp.route("/micro")
@module_required(MODULE)
def micro_lists():
    _admin_only()
    return render_template(
        "labs/micro.html",
        organisms=MicroOrganism.query.order_by(MicroOrganism.is_active.desc(),
                                               MicroOrganism.name).all(),
        antibiotics=MicroAntibiotic.query.order_by(MicroAntibiotic.is_active.desc(),
                                                   MicroAntibiotic.sort_order,
                                                   MicroAntibiotic.name).all())


@labs_bp.route("/micro/<kind>", methods=["POST"])
@module_required(MODULE)
def micro_add(kind):
    _admin_only()
    model = {"organisms": MicroOrganism, "antibiotics": MicroAntibiotic}.get(kind)
    if model is None:
        abort(404)
    n = micro.add_names(model, request.form.get("names"))
    db.session.commit()
    flash(t("micro.added", n=n), "success")
    return redirect(url_for("labs.micro_lists") + f"#{kind}")


@labs_bp.route("/micro/<kind>/<int:item_id>", methods=["POST"])
@module_required(MODULE)
def micro_item(kind, item_id):
    """An organism marked alert or not; either list's item stopped or back."""
    _admin_only()
    model = {"organisms": MicroOrganism, "antibiotics": MicroAntibiotic}.get(kind)
    if model is None:
        abort(404)
    row = db.get_or_404(model, item_id)
    action = request.form.get("action")
    if action == "alert" and model is MicroOrganism:
        row.alert = not row.alert
    elif action == "toggle":
        row.is_active = not row.is_active
    db.session.commit()
    return redirect(url_for("labs.micro_lists") + f"#{kind}")


# ------------------------------------------------------------ a culture ---
def _culture_order(order_id):
    row = db.get_or_404(VisitInvestigation, order_id)
    if not micro.is_culture(row):
        abort(404)
    return row


def _back(row):
    return redirect(url_for("labs.order", order_id=row.id) + "#culture")


@labs_bp.route("/order/<int:order_id>/culture", methods=["POST"])
@module_required(MODULE)
def culture_outcome(order_id):
    row = _culture_order(order_id)
    try:
        micro.set_outcome(row, request.form, current_user)
    except micro.MicroError as why:
        db.session.rollback()
        flash(t(f"micro.err_{why}"), "error")
        return _back(row)
    db.session.commit()
    flash(t("micro.saved"), "success")
    return _back(row)


@labs_bp.route("/order/<int:order_id>/culture/isolate", methods=["POST"])
@module_required(MODULE)
def culture_add_isolate(order_id):
    row = _culture_order(order_id)
    try:
        micro.add_isolate(row, request.form, current_user)
    except micro.MicroError as why:
        db.session.rollback()
        flash(t(f"micro.err_{why}"), "error")
        return _back(row)
    db.session.commit()
    flash(t("micro.isolate_added"), "success")
    return _back(row)


@labs_bp.route("/order/<int:order_id>/culture/isolate/<int:isolate_id>", methods=["POST"])
@module_required(MODULE)
def culture_isolate(order_id, isolate_id):
    row = _culture_order(order_id)
    isolate = db.get_or_404(CultureIsolate, isolate_id)
    try:
        micro.save_isolate(row, isolate, request.form, current_user)
    except micro.MicroError as why:
        db.session.rollback()
        flash(t(f"micro.err_{why}"), "error")
        return _back(row)
    db.session.commit()
    flash(t("micro.saved"), "success")
    return _back(row)


# ---------------------------------------------------------- antibiogram ---
@labs_bp.route("/antibiogram")
@module_required(MODULE)
def antibiogram():
    """A period's first isolates and how often each antibiotic still works."""
    from datetime import date

    today = local_today()

    def day(key, default):
        try:
            return date.fromisoformat(request.args.get(key) or "")
        except ValueError:
            return default

    start = day("start", today.replace(month=1, day=1))
    end = day("end", today)
    if end < start:
        start, end = end, start
    return render_template("labs/antibiogram.html", start=start, end=end,
                           table=micro.antibiogram(start, end),
                           last_year=(today.replace(month=1, day=1) - timedelta(days=1)))
