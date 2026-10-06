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
    if request.form.get("back") == "order" and row.kind == bench.IMAGING:
        return redirect(url_for("imaging.order", order_id=row.id))
    return redirect(url_for(_back_to(row)))


def _back_to(row):
    """The room this order belongs to, so «done» lands where it was pressed."""
    return ("visits.device_board" if row.kind == bench.DIAGNOSTIC
            else "imaging.index")


# ---------------------------------------------------------------------------
# One scan: the report, the dose and the contrast — radiology's own page
# ---------------------------------------------------------------------------
def _scan(order_id):
    row = db.get_or_404(VisitInvestigation, order_id)
    if row.kind != bench.IMAGING:
        from flask import abort

        abort(404)
    return row


@imaging_bp.route("/order/<int:order_id>")
@module_required(MODULE)
def order(order_id):
    """One scan: what was asked, the child's earlier doses and contrast —
    before this one is done — and the boxes for the report and for what this
    one gave (`utils/radiation`)."""
    from app.utils import radiation

    row = _scan(order_id)
    from app.utils import lab_critical, lab_results
    from app.utils import radiation_safety as rs

    is_mri = rs.is_mri(row)
    screening = rs.last_screening(row) if is_mri else None
    return render_template(
        "imaging/order.html", order=row, bench=bench, radiation=radiation,
        # GAHAR DAS.09 (f) — the hospital's MRI screening questions, only on an
        # MRI and only where the hospital wrote them.
        is_mri=is_mri, mri_questions=rs.mri_questions() if is_mri else [],
        mri_screening=screening,
        mri_answers=rs.answers_of(screening) if screening else [],
        before=radiation.summary(row.patient_id, exclude_id=row.id),
        over=radiation.over_reference(row), ionising=radiation.ionising(row),
        # The critical box (`labs/_critical_box.html`).
        may_read=lab_results.reads_results(current_user),
        doctors=lab_critical.doctor_names(),
        critical_late=lab_critical.late_call(row))


@imaging_bp.route("/order/<int:order_id>/report", methods=["POST"])
@module_required(MODULE)
def report(order_id):
    """The report: what was seen, and the impression."""
    row = _scan(order_id)
    bench.record(row, text=request.form.get("result_text") or "",
                 comment=request.form.get("result_comment") or "",
                 user=current_user)
    db.session.commit()
    flash(t("imaging.reported") if row.status == bench.RESULTED
          else t("lab.result_cleared"), "success")
    return redirect(url_for("imaging.order", order_id=row.id))


@imaging_bp.route("/order/<int:order_id>/exposure", methods=["POST"])
@module_required(MODULE)
def exposure(order_id):
    """What this scan gave the child: the dose the machine reported, and the
    contrast — agent, route, amount, and how the child took it."""
    from app.models import ActivityLog
    from app.utils import radiation

    row = _scan(order_id)
    try:
        radiation.save(row, request.form, current_user)
    except radiation.ExposureError as err:
        db.session.rollback()
        flash(t(f"radiation.err_{err}"), "error")
        return redirect(url_for("imaging.order", order_id=row.id))
    ActivityLog.record("imaging.exposure", user_id=current_user.id,
                       entity="visit_investigation", entity_id=row.id,
                       detail=f"{row.dose_kind}:{row.dose_value}/{row.contrast_agent or ''}")
    db.session.commit()
    flash(t("radiation.saved"), "success")
    if radiation.over_reference(row):
        flash(t("radiation.over_reference"), "warning")
    return redirect(url_for("imaging.order", order_id=row.id))


@imaging_bp.route("/doses")
@module_required(MODULE)
def doses():
    """What the children received in a period — scans above the hospital's
    reference level and contrast reactions first: where a review starts."""
    from datetime import timedelta

    from app.utils import radiation
    from app.utils.clock import local_today
    from app.utils.appointments import parse_date_arg

    today = local_today()
    date_to = parse_date_arg(request.args.get("to"), default=today)
    date_from = parse_date_arg(request.args.get("from"), default=date_to - timedelta(days=30))
    rows = radiation.report(date_from, date_to)
    return render_template("imaging/doses.html", rows=rows, radiation=radiation,
                           date_from=date_from, date_to=date_to,
                           over=sum(1 for r in rows if radiation.over_reference(r)),
                           reactions=sum(1 for r in rows if r.contrast_reaction
                                         in ("mild", "moderate", "severe")))


@imaging_bp.route("/dose-units", methods=["POST"])
@module_required(MODULE)
def dose_units():
    """The units this hospital's machines print each measure in."""
    from flask import abort

    from app.models import Setting
    from app.utils import radiation

    if not current_user.is_admin:
        abort(403)
    for kind, units in radiation.MEASURES.items():
        unit = (request.form.get(f"unit_{kind}") or "").strip()
        if unit in units:
            Setting.set(f"dose_unit:{kind}", unit)
    db.session.commit()
    flash(t("radiation.units_saved"), "success")
    return redirect(url_for("imaging.doses"))
