"""Incident reports — GAHAR QPI.10, QPI.11, DAS.23 / GSR.13. The logic is in
``app/utils/incidents.py``.

Reporting is open to everybody signed in; the board and the review are
``incident_manage``."""
from datetime import timedelta
from functools import wraps

from flask import (abort, flash, redirect, render_template, request, url_for)
from flask_login import current_user, login_required

from app.blueprints.incidents import incidents_bp
from app.extensions import db
from app.i18n import t
from app.models.incident import (AFFECTED, CATEGORIES, CLASSES, STATUSES,
                                 Incident)
from app.utils import incidents as inc
from app.utils.clock import local_now, local_today


def _reviewer(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if not inc.may_review(current_user):
            abort(403, description=t("auth.no_permission"))
        return view(*args, **kwargs)
    return wrapped


def _units():
    from app.models.place import Unit

    return Unit.query.filter_by(is_active=True).order_by(Unit.sort_order, Unit.name).all()


def _lang():
    from app.i18n import get_locale

    return get_locale()


@incidents_bp.route("/report", methods=["GET", "POST"])
@login_required
def report():
    """«بلّغ عن حادثة» — anybody signed in, with or without their name."""
    if request.method == "POST":
        try:
            row = inc.report(current_user, request.form)
        except inc.IncidentError as err:
            db.session.rollback()
            flash(t(f"incident.err_{err}"), "error")
            return render_template("incidents/report.html", units=_units(),
                                   categories=CATEGORIES, affected=AFFECTED,
                                   form=request.form, now=local_now())
        db.session.commit()
        return render_template("incidents/thanks.html", row=row)
    return render_template("incidents/report.html", units=_units(), categories=CATEGORIES,
                           affected=AFFECTED, form={}, now=local_now())


@incidents_bp.route("/")
@_reviewer
def index():
    """The period's reports with the medication errors and equipment
    incidents beside them, and the period counted (QPI.10 e)."""
    from app.utils.appointments import parse_date_arg

    end = parse_date_arg(request.args.get("to"), local_today())
    raw = request.args.get("from")
    start = parse_date_arg(raw) if raw else end - timedelta(days=89)
    if start > end:
        start, end = end, start
    status = request.args.get("status") or None
    category = request.args.get("category") or None
    return render_template(
        "incidents/index.html", start=start, end=end, status=status, category=category,
        rows=inc.board(start, end, status, category, _lang()),
        data=inc.analysis(start, end), statuses=STATUSES, categories=CATEGORIES,
        classes=CLASSES)


@incidents_bp.route("/<int:incident_id>")
@_reviewer
def view(incident_id):
    row = db.get_or_404(Incident, incident_id)
    return render_template("incidents/view.html", row=row, classes=CLASSES,
                           missing=inc.still_missing(row))


@incidents_bp.route("/<int:incident_id>/review", methods=["POST"])
@_reviewer
def review(incident_id):
    from app.models import ActivityLog

    row = db.get_or_404(Incident, incident_id)
    try:
        missing = inc.review(row, current_user, request.form)
    except inc.IncidentError as err:
        db.session.rollback()
        flash(t(f"incident.err_{err}"), "error")
        return redirect(url_for("incidents.view", incident_id=row.id))
    ActivityLog.record("incident.review", user_id=current_user.id, entity="incident",
                       entity_id=row.id, detail=f"{row.status}:{row.classification}")
    db.session.commit()
    if missing:
        flash(t(f"incident.err_missing_{missing[0]}"), "error")
    else:
        flash(t("incident.closed_ok") if row.status == "closed" else t("incident.saved"),
              "success")
    return redirect(url_for("incidents.view", incident_id=row.id))
