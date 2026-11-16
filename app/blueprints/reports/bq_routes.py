"""The BigQuery export's screen (``REPORTS_PLAN.md`` ت-٥; ``utils/bq_export``).

``/reports/bigquery`` — shut until the administrator records the hospital's
decision and its legal opinion; then a period and one zip to download.
Administrator only, every step in the activity log.
"""
from datetime import date, timedelta

from flask import Response, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user

from app.blueprints.reports import reports_bp
from app.extensions import db
from app.i18n import t
from app.utils.clock import local_today
from app.utils.decorators import client_ip, module_required


def _admin_only():
    if not current_user.is_admin:
        abort(403)


def _log(action, detail=None):
    from app.models import ActivityLog

    ActivityLog.record(action, user_id=current_user.id, entity="bq_export",
                       detail=detail, ip_address=client_ip())


@reports_bp.route("/bigquery", methods=["GET", "POST"])
@module_required("reports")
def bq_export():
    from app.models import Setting, User
    from app.utils import bq_export as bq

    _admin_only()
    if request.method == "POST":
        action = request.form.get("action")
        if action == "decide":
            try:
                bq.decide(request.form, current_user)
            except ValueError as err:
                flash(t(str(err)), "danger")
                return redirect(url_for("reports.bq_export"))
            _log("bq_export.open", (request.form.get("hospital_ref") or "")[:200])
        elif action == "withdraw":
            bq.withdraw()
            _log("bq_export.close")
        elif action == "settings":
            raw = (request.form.get("min_cell") or "").strip()
            if raw:
                try:
                    if int(raw) < 1:
                        raise ValueError
                except ValueError:
                    flash(t("bqx.err_min_cell"), "danger")
                    return redirect(url_for("reports.bq_export"))
            Setting.set(bq.MIN_CELL_KEY, raw)
            Setting.set(bq.SITE_KEY, (request.form.get("site") or "").strip()[:60])
            _log("bq_export.settings", f"k={raw or bq.DEFAULT_MIN_CELL}")
        else:
            abort(400)
        db.session.commit()
        flash(t("bqx.saved"), "success")
        return redirect(url_for("reports.bq_export"))
    dec = bq.decision()
    by = db.session.get(User, dec["by"]) if dec and dec.get("by") else None
    today = local_today()
    return render_template("reports/bq_export.html", decision=dec, by=by,
                           k=bq.min_cell(), site=Setting.get(bq.SITE_KEY, "") or "",
                           start=today.replace(day=1) if today.day > 1
                           else (today - timedelta(days=1)).replace(day=1),
                           end=today, schema=bq.SCHEMA)


@reports_bp.route("/bigquery/export")
@module_required("reports")
def bq_export_file():
    from app.utils import bq_export as bq

    _admin_only()
    if not bq.is_open():
        abort(403)
    try:
        start = date.fromisoformat(request.args.get("start") or "")
        end = date.fromisoformat(request.args.get("end") or "")
        data, n = bq.bundle(start, end)
    except ValueError:
        flash(t("bqx.err_period"), "danger")
        return redirect(url_for("reports.bq_export"))
    _log("bq_export.download", f"{start}..{end} rows={n}")
    db.session.commit()
    return Response(data, mimetype="application/zip", headers={
        "Content-Disposition":
            f"attachment; filename=pediapro-counts-{start}-{end}.zip"})
