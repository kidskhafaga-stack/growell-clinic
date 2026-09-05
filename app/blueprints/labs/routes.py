"""The lab's own screens: the rack, one order, and the list of tests.

**The doctor already had a door and the lab had none.** Ordering has worked
from the visit screen for years, and reading a result has its own inbox. What
had no screen anywhere was the middle — the person who walks to the bed with a
tube, and the person who runs it — so a hospital's lab ran on a paper list
beside a program that already knew every order on it.

Three screens and no more:

* **the rack** — everything ordered and not answered, longest-waiting first,
  split into what needs drawing and what needs running, because those are two
  jobs done by two people;
* **one order** — draw it, or write the answer on it;
* **the tests** — the catalogue, with what each is charged as. Admin only,
  like every other list that decides what things cost.
"""
from datetime import datetime

from flask import (abort, flash, g, redirect, render_template, request,
                   url_for)
from flask_login import current_user

from app.blueprints.labs import labs_bp
from app.extensions import db
from app.i18n import t
from app.models import Investigation, VisitInvestigation
from app.models.prescription import INVESTIGATION_KINDS
from app.utils import labs as bench
from app.utils.decorators import module_required

MODULE = "labs"


@labs_bp.route("/")
@module_required(MODULE)
def index():
    """The rack."""
    kind = (request.args.get("kind") or "").strip() or None
    state = (request.args.get("state") or "").strip() or None
    if state not in bench.OPEN_STATES:
        state = None
    rows = bench.worklist(kind=kind, state=state)
    return render_template("labs/index.html",
                           rows=rows, kind=kind, state=state,
                           counts=bench.counts(), bench=bench,
                           kinds=INVESTIGATION_KINDS,
                           now=datetime.utcnow(),
                           may_build=current_user.is_admin)


@labs_bp.route("/order/<int:order_id>")
@module_required(MODULE)
def order(order_id):
    """One order: what was asked for, where it is, and the box for the answer."""
    row = db.get_or_404(VisitInvestigation, order_id)
    return render_template("labs/order.html", order=row, bench=bench,
                           waited=bench.waiting_minutes(row))


@labs_bp.route("/order/<int:order_id>/collect", methods=["POST"])
@module_required(MODULE)
def collect(order_id):
    """The sample was taken."""
    row = db.get_or_404(VisitInvestigation, order_id)
    try:
        bench.collect(row, user=current_user, code=request.form.get("code"))
    except ValueError:
        db.session.rollback()
        # Which refusal it was: an order that already has an answer is a
        # keystroke on the wrong row, and saying "no" without saying why sends
        # somebody to draw blood a second time to find out.
        flash(t("lab.already_resulted"), "error")
        return redirect(url_for("labs.order", order_id=row.id))
    db.session.commit()
    flash(t("lab.collected", code=row.sample_code), "success")
    return redirect(request.referrer or url_for("labs.index"))


@labs_bp.route("/order/<int:order_id>/result", methods=["POST"])
@module_required(MODULE)
def result(order_id):
    """The answer, written on the order it answers."""
    row = db.get_or_404(VisitInvestigation, order_id)
    bench.record(row,
                 value=_number(request.form.get("result_value")),
                 unit=request.form.get("result_unit"),
                 low=_number(request.form.get("result_low")),
                 high=_number(request.form.get("result_high")),
                 text=request.form.get("result_text") or "",
                 comment=None, user=current_user)
    db.session.commit()
    flash(t("lab.resulted") if row.status == bench.RESULTED
          else t("lab.result_cleared"), "success")
    return redirect(url_for("labs.order", order_id=row.id))


# ------------------------------------------------------------- the tests ---
@labs_bp.route("/tests")
@module_required(MODULE)
def tests():
    """The catalogue, and what each test is charged as."""
    _admin_only()
    from app.models.service import Service

    return render_template(
        "labs/tests.html",
        rows=(Investigation.query
              .order_by(Investigation.kind, Investigation.name_ar).all()),
        kinds=INVESTIGATION_KINDS,
        services=(Service.query.filter(Service.is_active.is_(True))
                  .order_by(Service.name).all()))


@labs_bp.route("/tests/add", methods=["POST"])
@module_required(MODULE)
def add_test():
    _admin_only()
    name = (request.form.get("name_ar") or "").strip()[:160]
    if not name:
        flash(t("lab.need_name"), "error")
        return redirect(url_for("labs.tests"))
    kind = request.form.get("kind")
    db.session.add(Investigation(
        name_ar=name,
        name_en=(request.form.get("name_en") or "").strip()[:160] or None,
        kind=kind if kind in INVESTIGATION_KINDS else "lab",
        unit=(request.form.get("unit") or "").strip()[:20] or None,
        sample_type=(request.form.get("sample_type") or "").strip()[:40] or None,
        service_id=request.form.get("service_id", type=int)))
    db.session.commit()
    flash(t("lab.test_added"), "success")
    return redirect(url_for("labs.tests"))


@labs_bp.route("/tests/<int:test_id>", methods=["POST"])
@module_required(MODULE)
def edit_test(test_id):
    """The unit, the sample, and the price. The name too — a clinic renames a
    test and every order already written keeps the name it was written with,
    because the order snapshots it."""
    _admin_only()
    row = db.get_or_404(Investigation, test_id)
    name = (request.form.get("name_ar") or "").strip()[:160]
    if name:
        row.name_ar = name
    row.name_en = (request.form.get("name_en") or "").strip()[:160] or None
    row.unit = (request.form.get("unit") or "").strip()[:20] or None
    row.sample_type = (request.form.get("sample_type") or "").strip()[:40] or None
    # Cleared on purpose when the box is empty: a clinic that stops charging
    # for a test has to be able to say so, and an empty select means nobody
    # rather than "leave it as it was".
    row.service_id = request.form.get("service_id", type=int)
    row.is_active = request.form.get("is_active") == "1"
    db.session.commit()
    flash(t("lab.test_saved"), "success")
    return redirect(url_for("labs.tests"))


def _admin_only():
    if not current_user.is_admin:
        abort(403, description=t("auth.no_permission"))


def _number(raw):
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None
