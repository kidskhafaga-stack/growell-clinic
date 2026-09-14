"""The scans' own screen — because a scan is not a sample.

> «ليه ركويست الايكو موجود فى المعمل ؟»

Imaging and the lab share one order table, and for as long as they have, they
shared one screen too: `/labs/` defaulted to «every kind», so the bench's own
rack listed every echocardiogram in the building, counted them under «to
collect», and offered a «sample taken» button that would have written a sample
code and a collection time onto a study that has neither.

Filtering them out of the lab and stopping there would have been worse: an
order nobody can see is an order nobody does. So they get this.

**It rides the `labs` module rather than bringing its own.**

That is deliberate and it is the safer of the two. A new module is *off* until
somebody switches it on — that is what `OPT_IN_MODULES` is for — so shipping
one here would have turned imaging off for every clinic already running, and
their outstanding scans would have vanished from the program on upgrade. Which
is the exact failure this screen exists to undo. The module is «this place
handles investigations»; the screens are two because the **jobs** are two.
"""
from datetime import datetime

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user

from app.blueprints.imaging import imaging_bp
from app.extensions import db
from app.i18n import t
from app.models import VisitInvestigation
from app.utils import labs as bench
from app.utils.decorators import module_required

#: The same module as the lab. See the note at the top of this file.
MODULE = "labs"


@imaging_bp.route("/")
@module_required(MODULE)
def index():
    """Everything scanned or waiting to be, longest-waiting first."""
    state = (request.args.get("state") or "").strip() or None
    if state not in bench.OPEN_STATES:
        state = None
    return render_template(
        "imaging/index.html",
        rows=bench.worklist(kind=bench.IMAGING, state=state),
        state=state, counts=bench.counts(bench.IMAGING), bench=bench,
        now=datetime.utcnow())


@imaging_bp.route("/order/<int:order_id>/performed", methods=["POST"])
@module_required(MODULE)
def performed(order_id):
    """The scan was done. The imaging half of «the sample was taken».

    It writes `performed_at`, never `collected_at` — the whole point of the
    column. See :func:`app.utils.labs.perform`.
    """
    row = db.get_or_404(VisitInvestigation, order_id)
    try:
        bench.perform(row, user=current_user)
    except ValueError:
        db.session.rollback()
        # Named rather than a bare «no»: the two refusals are different
        # mistakes. A lab order here is somebody on the wrong screen; an
        # order that already has a report is a keystroke on the wrong row.
        flash(t("imaging.not_a_scan") if row.kind != bench.IMAGING
              else t("imaging.already_reported"), "warning")
        return redirect(url_for("imaging.index"))
    db.session.commit()
    flash(t("imaging.marked_done"), "success")
    return redirect(url_for("imaging.index"))
