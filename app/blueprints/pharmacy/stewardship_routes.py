"""GAHAR MMS.02 — the antimicrobial stewardship board (``utils/stewardship``).

Seen by the pharmacy and the stewardship team; decided by the team."""
from functools import wraps

from flask import (abort, current_app, flash, redirect, render_template, request,
                   url_for)
from flask_login import current_user

from app.blueprints.pharmacy import pharmacy_bp
from app.extensions import db
from app.i18n import t
from app.models import MedicationOrder
from app.utils import stewardship as asp


def _door(decide=False):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not current_user.is_authenticated:
                return current_app.login_manager.unauthorized()
            ok = asp.may_decide(current_user) if decide else asp.may_see(current_user)
            if not ok:
                abort(403, description=t("auth.no_permission"))
            return view(*args, **kwargs)
        return wrapped
    return decorator


@pharmacy_bp.route("/stewardship")
@_door()
def stewardship():
    from app.models import DrugClass, GenericDrug
    from app.models.stewardship import RestrictedAntimicrobial
    from app.utils import ipc_program
    from app.utils.clock import local_today

    quarters, q = [], local_today()
    label = request.args.get("q") or ipc_program.quarter_of(q)
    bounds = ipc_program.quarter_bounds(label) or ipc_program.quarter_bounds(ipc_program.quarter_of(q))
    day = q.replace(day=1)
    for _ in range(4):
        quarters.append(ipc_program.quarter_of(day))
        month, year = day.month - 3, day.year
        if month < 1:
            month, year = month + 12, year - 1
        day = day.replace(year=year, month=month)
    return render_template(
        "pharmacy/stewardship.html", data=asp.board(), use=asp.consumption(*bounds),
        quarter=label, quarters=quarters, may_decide=asp.may_decide(current_user),
        restricted=RestrictedAntimicrobial.query.filter_by(is_active=True).all(),
        classes=DrugClass.query.filter_by(is_active=True).order_by(DrugClass.sort_order).all(),
        chosen=asp.class_ids(),
        generics=GenericDrug.query.filter_by(is_active=True).order_by(GenericDrug.name_en).all())


@pharmacy_bp.route("/stewardship/order/<int:order_id>", methods=["POST"])
@_door(decide=True)
def stewardship_decide(order_id):
    order = db.get_or_404(MedicationOrder, order_id)
    try:
        asp.decide(order, request.form, current_user)
    except asp.StewardshipError as err:
        db.session.rollback()
        flash(t("asp.err_" + str(err)), "error")
        return redirect(url_for("pharmacy.stewardship"))
    db.session.commit()
    flash(t("asp.decided"), "success")
    return redirect(url_for("pharmacy.stewardship"))


@pharmacy_bp.route("/stewardship/setup", methods=["POST"])
@_door(decide=True)
def stewardship_setup():
    try:
        if request.form.get("what") == "classes":
            asp.set_classes(int(x) for x in request.form.getlist("class_id") if x.isdigit())
        else:
            asp.add_restricted(request.form, current_user)
    except asp.StewardshipError as err:
        db.session.rollback()
        flash(t("asp.err_" + str(err)), "error")
        return redirect(url_for("pharmacy.stewardship"))
    db.session.commit()
    flash(t("asp.saved"), "success")
    return redirect(url_for("pharmacy.stewardship"))


@pharmacy_bp.route("/stewardship/restricted/<int:row_id>/off", methods=["POST"])
@_door(decide=True)
def stewardship_restricted_off(row_id):
    from app.models.stewardship import RestrictedAntimicrobial

    row = db.get_or_404(RestrictedAntimicrobial, row_id)
    row.is_active = False
    db.session.commit()
    return redirect(url_for("pharmacy.stewardship"))
