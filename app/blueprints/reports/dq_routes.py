"""The data-quality screen (SMART_PATTERNS_PLAN ج-١; ``utils/data_quality``).

``/reports/data-quality`` — the overall score, a card per department this
copy runs, every check with its score and its count, and the score's last
120 days. ``/reports/data-quality/<check>`` — the records behind one check,
each opening where it is fixed; ``…/sheet.csv`` the same list as a sheet.
The weights are the administrator's to change.
"""
import csv
import io

from flask import Response, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user

from app.blueprints.reports import reports_bp
from app.extensions import db
from app.i18n import t
from app.utils.decorators import client_ip, module_required


@reports_bp.route("/data-quality", methods=["GET", "POST"])
@module_required("reports")
def data_quality():
    from app.models import ActivityLog
    from app.utils import data_quality as dq

    if request.method == "POST":
        if not current_user.is_admin:
            abort(403)
        known = [c["key"] for s in dq.sections() for c in s["checks"]]
        dq.set_weights(request.form, known)
        ActivityLog.record("reports.dq_weights", user_id=current_user.id,
                           entity="settings", ip_address=client_ip())
        db.session.commit()
        flash(t("dq.weights_saved"), "success")
        return redirect(url_for("reports.data_quality"))
    data = dq.board()
    dq.record_today(data)
    db.session.commit()
    return render_template("reports/data_quality.html", data=data,
                           history=dq.history(), steep=dq.STEEP,
                           green=dq.GREEN, amber=dq.AMBER)


def _check_or_404(key):
    from app.utils import data_quality as dq

    sec, check = dq.check_by_key(key)
    if check is None:
        abort(404)
    return sec, dq.run_check(check)


@reports_bp.route("/data-quality/<key>")
@module_required("reports")
def data_quality_check(key):
    from app.utils import data_quality as dq

    sec, check = _check_or_404(key)
    return render_template("reports/dq_check.html", section=sec, check=check,
                           rows=dq.records(check), limit=dq.LIST_LIMIT)


@reports_bp.route("/data-quality/<key>/sheet.csv")
@module_required("reports")
def data_quality_sheet(key):
    from app.models import ActivityLog
    from app.utils import data_quality as dq

    _sec, check = _check_or_404(key)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([t("patients.file_number"), t("appointments.patient"),
                t("dq.when"), t("dq.detail"), t("dq.link")])
    for r in dq.records(check):
        p = r["patient"]
        w.writerow([p.patient_number if p else "", p.full_name if p else "",
                    str(r["when"] or "")[:16], r.get("detail") or "",
                    url_for(r["endpoint"], _external=True, **r["kwargs"]) + r["anchor"]])
    ActivityLog.record("reports.dq_sheet", user_id=current_user.id, entity="report",
                       detail=key, ip_address=client_ip())
    db.session.commit()
    # The byte-order mark makes Excel read the Arabic as Arabic.
    return Response("﻿" + buf.getvalue(), mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition":
                             f'attachment; filename="data-quality-{key}.csv"'})
