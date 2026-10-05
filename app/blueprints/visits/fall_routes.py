"""Fall screening in the clinic — GAHAR ICD.10 / GSR.05 evidence 4. The
logic is in ``app/utils/fall_screen.py``."""
from datetime import timedelta

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user

from app.blueprints.visits import visits_bp
from app.extensions import db
from app.i18n import t
from app.models import Visit
from app.utils import fall_screen
from app.utils.clock import local_today
from app.utils.decorators import module_required

MODULE = "visits"


@visits_bp.route("/<int:visit_id>/fall-screen", methods=["POST"])
@module_required(MODULE)
def fall_screen_save(visit_id):
    visit = db.get_or_404(Visit, visit_id)
    try:
        fall_screen.screen(visit, current_user, request.form.getlist("criteria"),
                           family_told=bool(request.form.get("family_told")),
                           note=request.form.get("note"))
    except fall_screen.ScreenError as err:
        db.session.rollback()
        flash(t(f"fall_screen.err_{err}"), "error")
    else:
        db.session.commit()
        flash(t("fall_screen.saved"), "success")
    return redirect(url_for("visits.record", visit_id=visit.id) + "#fall-screen")


@visits_bp.route("/fall-screening")
@module_required(MODULE)
def fall_screening():
    """Evidence 4–5 over a period: screened, positive, families told, and
    which of the hospital's criteria applied."""
    from app.utils.appointments import parse_date_arg

    end = parse_date_arg(request.args.get("to"), local_today())
    raw = request.args.get("from")
    start = parse_date_arg(raw) if raw else end - timedelta(days=29)
    if start > end:
        start, end = end, start
    return render_template("visits/fall_screening.html", start=start, end=end,
                           data=fall_screen.report(start, end),
                           on=fall_screen.on())
