"""Which extra questions each specialty asks, and who is being asked them.

A module rather than a setting because of what "off" has to mean: a clinic
that does not work specialties should not have the section on its
consultation screen at all — not an empty picker, not a disabled control,
absent. A setting hides a control; a module removes the ground it stood on.

Admin-only, because nobody else ever opens it. A doctor meets the panels on
the visit screen, which is where the work is; this is where somebody decides
which panels exist for this clinic and who works them.

The screen is not a shell to satisfy the landing-page guard. It answers three
questions a person actually asks: what does each panel ask for, which doctors
are on it, and is anybody filling it in.
"""
from flask import render_template
from flask_login import login_required

from app.blueprints.panels import panels_bp
from app.extensions import db
from app.utils.decorators import admin_required, module_required

MODULE = "panels"


@panels_bp.route("/")
@login_required
@module_required(MODULE)
@admin_required
def index():
    """The panels this clinic has, with their doctors and their use.

    Usage is counted from `Measurement.panel` rather than
    `Visit.specialty_panel`: the measurement row is stamped with the panel it
    was entered from at the moment it was saved, so it stays true for a visit
    whose doctor later changes specialty. It is also the only one that can
    count a visit that recorded under two.
    """
    from app.models import Measurement, User
    from app.utils import panels as catalogue

    counts = dict(
        db.session.query(Measurement.panel, db.func.count(
            db.func.distinct(Measurement.visit_id)))
        .filter(Measurement.panel.isnot(None))
        .group_by(Measurement.panel).all())

    doctors = [u for u in User.query.filter_by(is_active=True).all()
               if User.sees_patients(u.role, u.is_practitioner)]

    rows = []
    for key, meta in catalogue.all_panels().items():
        rows.append({
            "key": key,
            "meta": meta,
            "fields": len(meta.get("fields") or []),
            "reads": meta.get("reads") or [],
            "visits": counts.get(key, 0),
            "doctors": [d for d in doctors if key in catalogue.for_doctor(d)],
        })

    # Panels nobody is on come last: the useful half of this screen is what is
    # in use, and a clinic that has enabled the module has usually enabled it
    # for one or two.
    rows.sort(key=lambda r: (not r["doctors"], -r["visits"], r["key"]))
    return render_template("panels/index.html", rows=rows,
                           doctors=doctors, orphans=sorted(
                               set(counts) - set(catalogue.all_panels())))


@panels_bp.route("/alerts")
@login_required
@module_required(MODULE)
@admin_required
def alerts():
    """The numbers this clinic wants to be warned at.

    **The door that was missing.** The survey asked every specialty *"متى
    ينبّهك البرنامج من نفسه؟"* and a hundred and three alerts came back; the
    ones that are a threshold were declared as *"a figure the clinic sets"* —
    and there was nowhere in the program to set one. A feature built with no
    way in, which is the failure this codebase keeps finding in itself.

    Only the alerts the program can actually answer get a box. An alert whose
    reading we do not hold would collect a number and change nothing, which is
    worse than saying plainly that it is waiting on something else.
    """
    from app.utils import panel_alerts, panels as catalogue

    known = panel_alerts.rules()
    rows = []
    for key, meta in catalogue.all_panels().items():
        answerable = panel_alerts.watchable(key)
        if not answerable:
            continue
        rows.append({
            "key": key, "meta": meta,
            "alerts": [{"alert": a, "rule": known.get((key, a["code"]))}
                       for a in answerable],
            # What this specialty asked for that nothing can answer yet. Said
            # on the same screen, because a clinic filling in four numbers
            # should be told the other nine are not a setting they are missing.
            "waiting": panel_alerts.waiting([key]),
        })
    rows.sort(key=lambda r: r["key"])
    return render_template("panels/alerts.html", rows=rows)


@panels_bp.route("/alerts/set", methods=["POST"])
@login_required
@module_required(MODULE)
@admin_required
def set_alert():
    """Write one number down — or clear it, which disarms the alert."""
    from flask import flash, redirect, request, url_for
    from flask_login import current_user

    from app.i18n import t
    from app.models import PanelAlertRule
    from app.utils import panel_alerts

    key = (request.form.get("panel_key") or "").strip()[:40]
    code = (request.form.get("alert_code") or "").strip()[:40]
    # Checked against the catalogue, never trusted: a posted pair that names
    # no real alert would sit in the table for ever, arming nothing and
    # showing up on no screen.
    if not any(a["code"] == code for a in panel_alerts.watchable(key)):
        flash(t("panel_alerts.unknown"), "error")
        return redirect(url_for("panels.alerts"))

    row = PanelAlertRule.query.filter_by(panel_key=key,
                                         alert_code=code).first()
    if row is None:
        row = PanelAlertRule(panel_key=key, alert_code=code)
        db.session.add(row)
    raw = (request.form.get("threshold") or "").strip()
    try:
        row.threshold = float(raw) if raw else None
    except ValueError:
        row.threshold = None
    row.is_active = request.form.get("is_active") == "1"
    row.note = (request.form.get("note") or "").strip()[:160] or None
    row.set_by = current_user.id
    db.session.commit()
    flash(t("panel_alerts.saved") if row.is_armed
          else t("panel_alerts.disarmed"), "success")
    return redirect(url_for("panels.alerts"))
