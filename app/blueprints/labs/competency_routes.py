"""Who in the laboratory is competent for what — GAHAR DAS.11.

The staff list, each person's file, the assessment form, the switch that
makes the order page say so, and the report of work done outside an
assessed competency. The logic is in ``app/utils/lab_competency.py``.
"""
from datetime import timedelta

from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user

from app.blueprints.labs import labs_bp
from app.extensions import db
from app.i18n import t
from app.models.lab_quality import COMPETENCY_METHODS, COMPETENCY_RESULTS
from app.utils import lab_competency as comp
from app.utils.clock import local_today
from app.utils.decorators import module_required

MODULE = "labs"


@labs_bp.route("/staff")
@module_required(MODULE)
def staff():
    """Everybody in the laboratory and where their file stands — nobody
    assessed yet first, then whoever is past the date or not competent."""
    return render_template("labs/staff.html", lines=comp.overview(),
                           checking=comp.checking(),
                           may_write=comp.may_write(current_user))


@labs_bp.route("/staff/<int:user_id>")
@module_required(MODULE)
def staff_file(user_id):
    from app.models import User

    person = db.get_or_404(User, user_id)
    today = local_today()
    return render_template("labs/staff_file.html", person=person,
                           rows=comp.file_of(person.id), today=today,
                           state=comp.state, sections=comp.sections(),
                           methods=COMPETENCY_METHODS,
                           results=COMPETENCY_RESULTS,
                           assessors=comp.staff(),
                           suggested_due=comp.suggested_due(today),
                           may_write=comp.may_write(current_user))


@labs_bp.route("/staff/<int:user_id>/assess", methods=["POST"])
@module_required(MODULE)
def staff_assess(user_id):
    if not comp.may_write(current_user):
        abort(403)
    f = request.form
    try:
        comp.record(user_id, f.get("section"), f.get("assessed_on"),
                    f.getlist("methods"), f.get("result"),
                    assessor_id=f.get("assessor_id", type=int),
                    due_on=f.get("due_on"), note=f.get("note"),
                    by=current_user)
    except comp.CompetencyError as err:
        db.session.rollback()
        flash(t(f"lab_comp.err_{err}"), "error")
        return redirect(url_for("labs.staff_file", user_id=user_id))
    db.session.commit()
    flash(t("lab_comp.saved"), "success")
    return redirect(url_for("labs.staff_file", user_id=user_id))


@labs_bp.route("/staff/check", methods=["POST"])
@module_required(MODULE)
def staff_check():
    if not comp.may_write(current_user):
        abort(403)
    comp.set_checking(request.form.get("on") == "1")
    db.session.commit()
    flash(t("lab_comp.check_saved"), "success")
    return redirect(url_for("labs.staff"))


@labs_bp.route("/staff/outside")
@module_required(MODULE)
def staff_outside():
    """Evidence 3 — results written or released by somebody with no
    standing assessment for the section that day."""
    from app.utils.appointments import parse_date_arg

    end = parse_date_arg(request.args.get("to"), local_today())
    raw = request.args.get("from")
    start = parse_date_arg(raw) if raw else end - timedelta(days=29)
    if start > end:
        start, end = end, start
    return render_template("labs/staff_outside.html", start=start, end=end,
                           rows=comp.outside(start, end))
