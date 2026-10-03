"""The scans' own screen — because a scan is not a sample.

> «ليه ركويست الايكو موجود فى المعمل ؟»

Imaging and the lab share one order table, and for as long as they have, they
shared one screen too: `/labs/` defaulted to «every kind», so the bench's own
rack listed every echocardiogram in the building, counted them under «to
collect», and offered a «sample taken» button that would have written a sample
code and a collection time onto a study that has neither.

Filtering them out of the lab and stopping there would have been worse: an
order nobody can see is an order nobody does. So they get this.

**Radiology is a module of its own** — «المعمل مديول لواحده والاشعة مديول».
It rode `labs` for a while, so that no clinic lost its outstanding scans on
the day it appeared; it is split out now, and the upgrade switches it on
wherever the lab was on and gives it to every role that held the lab
(`schema.split_imaging_from_labs`), so nothing goes quiet.

**And the echo, the sonar, the ECG and the EEG are not here.** They are device
studies, done in any clinic room and at any bedside, and they have their own
board beside the visit (`visits.device_board`).
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

#: Radiology's own module. See the note at the top of this file.
MODULE = "imaging"


def _room(kind, endpoint):
    """One worklist, drawn for whichever room asked for it.

    Two routes and one template because it is one job — done, then reported —
    in two places. What the screens do **not** share is a list: the person on
    the X-ray machine and the person doing echoes are not each other's cover,
    and a single list would make each of them read the other's work. That is
    the same sentence the lab's own stylesheet has carried for years.
    """
    state = (request.args.get("state") or "").strip() or None
    if state not in bench.OPEN_STATES:
        state = None
    other = (bench.DIAGNOSTIC if kind == bench.IMAGING else bench.IMAGING)
    return render_template(
        "imaging/index.html",
        rows=bench.worklist(kind=kind, state=state),
        state=state, counts=bench.counts(kind), bench=bench,
        kind=kind, endpoint=endpoint,
        # The door to the other room, with its count on it — nothing is
        # allowed to go quiet just because it moved screens.
        other_kind=other, other_open=sum(bench.counts(other).values()),
        now=datetime.utcnow())


@imaging_bp.route("/")
@module_required(MODULE)
def index():
    """Radiology: films, CT and MRI — taken and reported by the X-ray room."""
    return _room(bench.IMAGING, "imaging.index")


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
        flash(t("imaging.not_a_scan") if row.kind not in bench.ROOMS
              else t("imaging.already_reported"), "warning")
        return redirect(url_for(_back_to(row)))
    db.session.commit()
    flash(t("imaging.marked_done"), "success")
    return redirect(url_for(_back_to(row)))


def _back_to(row):
    """The room this order belongs to, so «done» lands where it was pressed."""
    return ("visits.device_board" if row.kind == bench.DIAGNOSTIC
            else "imaging.index")
