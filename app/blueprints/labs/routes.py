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
import json
from datetime import datetime

from flask import (abort, flash, g, redirect, render_template, request,
                   url_for)
from flask_login import current_user

from app.blueprints.labs import catalogue, labs_bp
from app.extensions import db
from app.i18n import t
from app.models import Investigation, VisitInvestigation
# Still both kinds here, and rightly: the **catalogue** screen lists
# every investigation the clinic offers and `add_test` creates either.
# What stopped being two kinds is the *rack* — see `index`.
from app.models.prescription import INVESTIGATION_KINDS
from app.utils import lab_results
from app.utils import labs as bench
from app.utils.decorators import module_required

MODULE = "labs"


def _critical_door(view):
    """Critical results belong to the rooms that answer an order — the lab,
    radiology and the device studies — and to the doctors they are for
    (GAHAR ICD.19). So the critical screens open, wherever the lab or the
    radiology module is on, for whoever works in either and for any doctor.
    With neither on they are not there at all, as before."""
    from functools import wraps

    @wraps(view)
    def wrapped(*args, **kwargs):
        from flask import current_app

        if not current_user.is_authenticated:
            return current_app.login_manager.unauthorized()
        from app.utils import lab_critical

        rooms = lab_critical.rooms_on()
        if not rooms:
            abort(404)
        if not (any(current_user.can_access(m) for m in rooms)
                or lab_results.reads_results(current_user)):
            abort(403, description=t("auth.no_permission"))
        return view(*args, **kwargs)

    return wrapped


def _critical_back(row):
    """Back to the page the critical box was on: the list, a film's page,
    a device study's page, or the lab order."""
    back = request.form.get("back") or ""
    if back == "list":
        return url_for("labs.critical")
    if back == "imaging":
        return url_for("imaging.order", order_id=row.id)
    if back.startswith("study:") and back[6:].isdigit():
        return url_for("visits.study_view", study_id=int(back[6:]))
    return url_for("labs.order", order_id=row.id)


@labs_bp.route("/")
@module_required(MODULE)
def index():
    """The rack — **the lab's, and only the lab's**.

    It used to read a `kind` off the query string and default it to `None`,
    which is «every kind»: the bench's own screen listed every echocardiogram
    in the building beside the blood counts, counted them under «to collect»,
    and offered a «sample taken» button on them. Reported as «ليه ركويست
    الايكو موجود فى المعمل؟».

    There is no kind here now, because this screen is one of them. Scans have
    their own screen, with their own verb — see `app/blueprints/imaging`.
    """
    state = (request.args.get("state") or "").strip() or None
    if state not in bench.OPEN_STATES:
        state = None
    from app.utils import lab_reception

    rows = bench.worklist(kind=bench.LAB, state=state)
    return render_template("labs/index.html",
                           rows=rows, state=state,
                           refused=lab_reception.last_rejections(rows),
                           reason_label=lab_reception.reason_label,
                           urgent_open=bench.urgent_count(bench.LAB),
                           to_release=_release().waiting_count(),
                           sent_labs=bool(_sendout().laboratories()),
                           expired_lots=_reagents().expired_on_shelf(),
                           qc_failures=_quality().failed_without_action(),
                           poct_attention=_poct_util().needing_attention(),
                           staff_attention=_competency().attention(),
                           at_door=request.args.get("receive") == "1",
                           # Where the child is, when they are in a bed: the
                           # sample is drawn at the bed, not at the desk.
                           beds=bench.beds_of(rows),
                           counts=bench.counts(bench.LAB), bench=bench,
                           now=datetime.utcnow(),
                           late=lab_results.late,
                           critical_open=len(lab_results.all_waiting()),
                           may_build=current_user.is_admin)


@labs_bp.route("/order/<int:order_id>")
@module_required(MODULE)
def order(order_id):
    """One order: what was asked for, where it is, and the box for the answer."""
    row = db.get_or_404(VisitInvestigation, order_id)
    # A scan is radiology's: its report, its dose and its contrast are written
    # on radiology's own page, not on the lab's.
    if row.kind == bench.IMAGING:
        from app.utils.facility import module_enabled

        if module_enabled("imaging") and current_user.can_access("imaging"):
            return redirect(url_for("imaging.order", order_id=row.id))
    # A test the laboratory has broken into what it measures is answered
    # line by line, each against this child's range; one it has not is
    # answered the way it always was.
    lines = lab_results.sheet(row) if lab_results.measured(row) else None
    from app.utils import lab_reception

    return render_template("labs/order.html", order=row, bench=bench,
                           reasons=lab_reception.reasons(),
                           release_required=_release().required(),
                           may_release=_release().may_release(current_user),
                           referral_labs=_sendout().laboratories(),
                           sent_late=_sendout().late(row),
                           was_late=_tat().was_late(row), took=_tat().minutes(row),
                           critical_late=_critical().late_call(row),
                           reason_label=lab_reception.reason_label,
                           lines=lines, late=lab_results.late(row),
                           age_days=lab_results.age_days(
                               row.patient, row.collected_at or row.created_at),
                           may_read=lab_results.reads_results(current_user),
                           waited=bench.waiting_minutes(row),
                           doctors=_doctor_names(),
                           # GAHAR DAS.11 — the person writing has no
                           # standing assessment for this section.
                           competency_warning=_competency().warning_for(
                               row, current_user),
                           # GAHAR DAS.20 — where this tube is kept.
                           papers=_papers(row), ai_reads_papers=_ai_reads(),
                           **_storage_for(row))


def _papers(row):
    from app.utils import lab_read

    return lab_read.papers(row)


def _ai_reads():
    from app.utils import ai

    try:
        return bool(ai.get_config().get("enabled") and ai.patient_context_enabled())
    except Exception:          # noqa: BLE001 - a settings read never breaks the bench
        return False


def _storage_for(row):
    from app.utils import lab_storage

    kept = lab_storage.current(row.sample_code) if row.sample_code else None
    return {"kept": kept, "kept_place": lab_storage.place_label(kept),
            "store_places": lab_storage.places()}


def _doctor_names():
    """Who a critical value is telephoned to — for the box's suggestions."""
    from app.models import User

    rows = (User.query.filter(User.is_active.is_(True),
                              db.or_(User.role == "doctor", User.is_practitioner.is_(True)))
            .order_by(User.full_name).all())
    return [u.full_name for u in rows if u.full_name]


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


@labs_bp.route("/order/<int:order_id>/label", methods=["POST"])
@module_required(MODULE)
def label(order_id):
    """Write the tube's number (if it has none) and open its label to print.

    A POST because it writes the number; the label page itself only reads.
    """
    row = db.get_or_404(VisitInvestigation, order_id)
    try:
        bench.label_code(row)
    except ValueError:
        db.session.rollback()
        flash(t("lab.no_tube"), "warning")
        return redirect(request.referrer or url_for("labs.index"))
    db.session.commit()
    return redirect(url_for("labs.labels", ids=str(row.id)))


@labs_bp.route("/patient/<int:patient_id>/labels", methods=["POST"])
@module_required(MODULE)
def patient_labels(patient_id):
    """Every tube this child is waiting to have drawn, on one sheet — the
    nurse walks to the bed once, not once per test."""
    rows = [r for r in bench.worklist(kind=bench.LAB, state=bench.REQUESTED)
            if r.patient_id == patient_id]
    if not rows:
        flash(t("lab.nothing_to_draw"), "info")
        return redirect(request.referrer or url_for("labs.index"))
    for r in rows:
        bench.label_code(r)
    db.session.commit()
    return redirect(url_for("labs.labels", ids=",".join(str(r.id) for r in rows)))


@labs_bp.route("/labels")
@module_required(MODULE)
def labels():
    """The tube labels, sized for a 50×30 mm label printer. Read only: an
    order with no number yet is left off rather than numbered by a GET."""
    from app.utils.barcode39 import svg

    ids = [int(x) for x in (request.args.get("ids") or "").split(",")
           if x.strip().isdigit()][:60]
    rows = (VisitInvestigation.query
            .filter(VisitInvestigation.id.in_(ids),
                    VisitInvestigation.kind == bench.LAB,
                    VisitInvestigation.sample_code.isnot(None))
            .order_by(VisitInvestigation.id).all()) if ids else []
    if not rows:
        abort(404)
    return render_template("labs/labels.html", rows=rows,
                           bars={r.id: svg(r.sample_code) for r in rows})


@labs_bp.route("/scan")
@module_required(MODULE)
def scan():
    """A barcode reader's input: the tube's code, then Enter. Opens the order
    it belongs to — to mark it drawn, or to write its result.

    **At the door** (``receive=1``) it receives the tube instead and comes
    straight back to the box, so a tray of tubes is received by scanning
    them one after another (GAHAR DAS.15 ب-١)."""
    from app.utils import lab_reception

    code = (request.args.get("code") or "").strip()
    at_door = request.args.get("receive") == "1"
    row = bench.by_code(code)
    if row is None:
        flash(t("lab.scan_unknown", code=code[:24]), "warning")
        return redirect(url_for("labs.index", receive=1 if at_door else None))
    if at_door:
        try:
            lab_reception.receive(row, user=current_user)
        except lab_reception.ReceptionError as err:
            db.session.rollback()
            flash(t(f"lab_reception.err_{err}"), "warning")
            return redirect(url_for("labs.index", receive=1))
        db.session.commit()
        flash(t("lab_reception.received_code", code=row.sample_code,
                name=row.name), "success")
        return redirect(url_for("labs.index", receive=1))
    return redirect(url_for("labs.order", order_id=row.id))


@labs_bp.route("/order/<int:order_id>/receive", methods=["POST"])
@module_required(MODULE)
def receive(order_id):
    """The tube reached the lab and was accepted — with a note when it was
    accepted although not as it should be (GAHAR DAS.15 ب)."""
    from app.utils import lab_reception

    row = db.get_or_404(VisitInvestigation, order_id)
    try:
        lab_reception.receive(row, user=current_user,
                              note=request.form.get("note"))
    except lab_reception.ReceptionError as err:
        db.session.rollback()
        flash(t(f"lab_reception.err_{err}"), "error")
        return redirect(url_for("labs.order", order_id=row.id))
    db.session.commit()
    flash(t("lab_reception.received"), "success")
    if request.form.get("back") == "rack":
        return redirect(url_for("labs.index"))
    return redirect(url_for("labs.order", order_id=row.id))


@labs_bp.route("/order/<int:order_id>/reject", methods=["POST"])
@module_required(MODULE)
def reject(order_id):
    """The tube is refused: why, and who was told to draw it again. The
    order goes back to be drawn (GAHAR DAS.15 ب-٢)."""
    from app.models import ActivityLog
    from app.utils import lab_reception

    row = db.get_or_404(VisitInvestigation, order_id)
    try:
        refused = lab_reception.reject(
            row, reason_key=request.form.get("reason_key"),
            reason_text=request.form.get("reason_text"),
            told_to=request.form.get("told_to"), user=current_user)
    except lab_reception.ReceptionError as err:
        db.session.rollback()
        flash(t(f"lab_reception.err_{err}"), "error")
        return redirect(url_for("labs.order", order_id=row.id))
    ActivityLog.record("lab.sample_rejected", user_id=current_user.id,
                       entity="visit_investigation", entity_id=row.id,
                       detail=f"{refused.sample_code}: "
                              f"{lab_reception.reason_label(refused)}"[:250])
    db.session.commit()
    flash(t("lab_reception.rejected"), "warning")
    return redirect(url_for("labs.order", order_id=row.id))


@labs_bp.route("/order/<int:order_id>/verify", methods=["POST"])
@module_required(MODULE)
def verify(order_id):
    """Release a result — by whoever the hospital authorized (GAHAR DAS.20 ب)."""
    from app.models import ActivityLog
    from app.utils import lab_release

    row = db.get_or_404(VisitInvestigation, order_id)
    back = (url_for("labs.to_verify") if request.form.get("back") == "list"
            else url_for("labs.order", order_id=row.id))
    try:
        lab_release.verify(row, current_user)
    except lab_release.ReleaseError as err:
        db.session.rollback()
        flash(t(f"lab_release.err_{err}"), "error")
        return redirect(back)
    ActivityLog.record("lab.verified", user_id=current_user.id,
                       entity="visit_investigation", entity_id=row.id)
    db.session.commit()
    flash(t("lab_release.verified"), "success")
    return redirect(back)


@labs_bp.route("/verify")
@module_required(MODULE)
def to_verify():
    """Results written and waiting for release, oldest first."""
    from app.utils import lab_release

    return render_template("labs/verify.html", rows=lab_release.waiting(),
                           required=lab_release.required(),
                           may_release=lab_release.may_release(current_user),
                           beds=bench.beds_of(lab_release.waiting()))


@labs_bp.route("/verify-setting", methods=["POST"])
@module_required(MODULE)
def verify_setting():
    """Switch result release on or off — the laboratory's policy."""
    from app.models import ActivityLog, Setting
    from app.utils import lab_release

    if not current_user.is_admin:
        abort(403)
    on = request.form.get("required") == "1"
    Setting.set(lab_release.SETTING, "1" if on else "0")
    ActivityLog.record("lab.verify_setting", user_id=current_user.id,
                       detail="on" if on else "off")
    db.session.commit()
    flash(t("lab_release.setting_saved"), "success")
    return redirect(url_for("labs.tests") + "#verify-setting")


@labs_bp.route("/report")
def report():
    """The laboratory's final report for one child — GAHAR DAS.20 (أ):
    the laboratory, the child, each test with its specimen, collection and
    reporting times, the values against their reference, the ordering
    doctor, the person who released it, and the comment.

    Read by the lab and by whoever treats the child, so it asks for either
    the lab module or the medical record, not the lab alone."""
    from app.utils import lab_release
    from app.utils.clock import local_now
    from app.utils.privacy import can_see_visit

    if not current_user.is_authenticated:
        from flask import current_app
        return current_app.login_manager.unauthorized()
    if not (current_user.can_access(MODULE) or current_user.can("patient_medical")):
        abort(403, description=t("auth.no_permission"))
    ids = [int(x) for x in (request.args.get("ids") or "").split(",")
           if x.strip().isdigit()]
    patient, rows = lab_release.report_rows(ids)
    rows = [r for r in rows if r.visit is None or can_see_visit(r.visit)]
    if not rows:
        abort(404)
    return render_template("labs/report.html", patient=patient, rows=rows,
                           required=lab_release.required(),
                           printed_at=local_now())


# ------------------------------------------- sent to a referral laboratory --
@labs_bp.route("/send-out")
@module_required(MODULE)
def send_out():
    """Samples to send, and samples out — GAHAR DAS.13 / DAS.15 (د)."""
    from app.utils import lab_sendout

    rows = lab_sendout.to_send()
    out = lab_sendout.out_now()
    return render_template("labs/send_out.html", rows=rows, out=out,
                           labs=lab_sendout.laboratories(),
                           late=lab_sendout.late, now=datetime.utcnow(),
                           beds=bench.beds_of(rows + out))


@labs_bp.route("/send-out", methods=["POST"])
@module_required(MODULE)
def send_out_post():
    """Send the ticked samples to one laboratory, on one numbered batch."""
    from app.models import ActivityLog, ReferralLab
    from app.utils import lab_sendout

    ids = [int(x) for x in request.form.getlist("order_id") if x.isdigit()]
    orders = [db.session.get(VisitInvestigation, i) for i in ids]
    lab = db.session.get(ReferralLab, request.form.get("lab_id", type=int) or 0)
    try:
        code = lab_sendout.send(orders, lab, user=current_user)
    except lab_sendout.SendError as err:
        db.session.rollback()
        flash(t(f"lab_sendout.err_{err}"), "error")
        back = request.form.get("back_order", type=int)
        return redirect(url_for("labs.order", order_id=back) if back
                        else url_for("labs.send_out"))
    ActivityLog.record("lab.sent_out", user_id=current_user.id,
                       detail=f"{code} → {lab.name} ({len(orders)})"[:250])
    db.session.commit()
    flash(t("lab_sendout.sent", code=code, n=len(orders)), "success")
    return redirect(url_for("labs.send_batch", code=code))


@labs_bp.route("/send-out/batch/<code>")
@module_required(MODULE)
def send_batch(code):
    """The batch's manifest — what goes in the box, to print and sign."""
    from app.utils import lab_sendout
    from app.utils.clock import local_now

    rows = lab_sendout.batch(code)
    if not rows:
        abort(404)
    return render_template("labs/send_batch.html", rows=rows, code=code,
                           lab=rows[0].sent_lab, printed_at=local_now())


@labs_bp.route("/order/<int:order_id>/recall", methods=["POST"])
@module_required(MODULE)
def recall(order_id):
    """Marked sent by mistake — taken back before its result came."""
    from app.utils import lab_sendout

    row = db.get_or_404(VisitInvestigation, order_id)
    try:
        lab_sendout.recall(row)
    except lab_sendout.SendError as err:
        db.session.rollback()
        flash(t(f"lab_sendout.err_{err}"), "error")
        return redirect(url_for("labs.order", order_id=row.id))
    db.session.commit()
    flash(t("lab_sendout.recalled"), "success")
    return redirect(url_for("labs.order", order_id=row.id))


@labs_bp.route("/send-out/register")
@module_required(MODULE)
def send_register():
    """What went where in a period, what came back, what is late, and the
    turnaround each laboratory kept — the evaluation DAS.13 (ب) asks for."""
    from datetime import timedelta

    from app.utils import lab_sendout
    from app.utils.clock import local_today

    end = _day(request.args.get("to")) or local_today()
    start = _day(request.args.get("from")) or (end - timedelta(days=30))
    if start > end:
        start, end = end, start
    rows, per_lab = lab_sendout.register(start, end)
    return render_template("labs/send_register.html", rows=rows, per_lab=per_lab,
                           start=start, end=end, late=lab_sendout.late,
                           now=datetime.utcnow())


@labs_bp.route("/referral-labs")
@module_required(MODULE)
def referral_labs():
    """The laboratories this one sends to, with their agreements."""
    from app.utils import lab_sendout

    return render_template("labs/referral_labs.html",
                           labs=lab_sendout.laboratories(active_only=False),
                           state=lab_sendout.agreement_state,
                           may_build=current_user.is_admin)


@labs_bp.route("/referral-labs", methods=["POST"])
@labs_bp.route("/referral-labs/<int:lab_id>", methods=["POST"])
@module_required(MODULE)
def referral_lab_save(lab_id=None):
    from app.models import ReferralLab
    from app.utils import lab_sendout

    _admin_only()
    row = db.get_or_404(ReferralLab, lab_id) if lab_id else None
    try:
        lab_sendout.save_laboratory(request.form, row)
    except lab_sendout.SendError as err:
        db.session.rollback()
        flash(t(f"lab_sendout.err_{err}"), "error")
        return redirect(url_for("labs.referral_labs"))
    db.session.commit()
    flash(t("lab_sendout.lab_saved"), "success")
    return redirect(url_for("labs.referral_labs"))


# ------------------------------------------------------------ turnaround --
@labs_bp.route("/turnaround")
@module_required(MODULE)
def turnaround():
    """How long each test took in a period, the late ones with their reason,
    and the STAT list — GAHAR DAS.21 / DAS.22."""
    from datetime import timedelta

    from app.utils import lab_tat
    from app.utils.clock import local_today

    end = _day(request.args.get("to")) or local_today()
    start = _day(request.args.get("from")) or (end - timedelta(days=30))
    if start > end:
        start, end = end, start
    per_test, late_rows = lab_tat.report(start, end)
    return render_template("labs/turnaround.html", per_test=per_test,
                           late_rows=late_rows, start=start, end=end,
                           stat=lab_tat.stat_list(), minutes=lab_tat.minutes)


@labs_bp.route("/order/<int:order_id>/delay", methods=["POST"])
@module_required(MODULE)
def tell_delay(order_id):
    """The requester was told the result is late (GAHAR DAS.21 دليل ٤)."""
    from app.models import ActivityLog
    from app.utils import lab_tat

    row = db.get_or_404(VisitInvestigation, order_id)
    try:
        lab_tat.tell_delay(row, request.form.get("told_to"),
                           reason=request.form.get("reason"), user=current_user)
    except lab_tat.DelayError as err:
        db.session.rollback()
        flash(t(f"lab_tat.err_{err}"), "error")
        return redirect(url_for("labs.order", order_id=row.id))
    ActivityLog.record("lab.delay_told", user_id=current_user.id,
                       entity="visit_investigation", entity_id=row.id,
                       detail=row.delay_told_to)
    db.session.commit()
    flash(t("lab_tat.told"), "success")
    return redirect(url_for("labs.order", order_id=row.id))


@labs_bp.route("/order/<int:order_id>/late-reason", methods=["POST"])
@module_required(MODULE)
def late_reason(order_id):
    """Why a result was late — the investigation (GAHAR DAS.21 دليل ٢)."""
    from app.utils import lab_tat

    row = db.get_or_404(VisitInvestigation, order_id)
    back = (url_for("labs.turnaround") if request.form.get("back") == "report"
            else url_for("labs.order", order_id=row.id))
    try:
        lab_tat.explain(row, request.form.get("reason"))
    except lab_tat.DelayError as err:
        db.session.rollback()
        flash(t(f"lab_tat.err_{err}"), "error")
        return redirect(back)
    db.session.commit()
    flash(t("lab_tat.reason_saved"), "success")
    return redirect(back)


# -------------------------------------------------------------- reagents --
@labs_bp.route("/reagents")
@module_required(MODULE)
def reagents():
    """Reagent lots: what is on the shelf, what is expiring, what was
    refused at the door, and what the store says is running low (DAS.12)."""
    from app.models import StoreItem
    from app.utils import lab_reagents, lab_stock

    store = lab_stock.store()
    items = (StoreItem.query.filter(StoreItem.is_active.is_(True))
             .order_by(StoreItem.name).all())
    return render_template("labs/reagents.html", lots=lab_reagents.shelf(),
                           rejected=lab_reagents.recent_rejected(),
                           low=lab_reagents.low_items(), store=store,
                           items=items, state=lab_reagents.state,
                           warn_days=lab_reagents.warn_days())


@labs_bp.route("/reagents", methods=["POST"])
@module_required(MODULE)
def reagent_receive():
    """A lot arrived and was inspected — accepted, or rejected with why."""
    from app.models import ActivityLog
    from app.utils import lab_reagents

    try:
        lot = lab_reagents.receive(request.form, user=current_user)
    except lab_reagents.LotError as err:
        db.session.rollback()
        flash(t(f"lab_reagents.err_{err}"), "error")
        return redirect(url_for("labs.reagents"))
    ActivityLog.record("lab.reagent_received", user_id=current_user.id,
                       detail=f"{lot.lot_number} {lot.decision}"[:250])
    db.session.commit()
    flash(t("lab_reagents.received_" + lot.decision), "success")
    return redirect(url_for("labs.reagents"))


@labs_bp.route("/reagents/<int:lot_id>/<action>", methods=["POST"])
@module_required(MODULE)
def reagent_act(lot_id, action):
    """Open a lot for use (never an expired one), or finish it."""
    from app.models import ReagentLot
    from app.utils import lab_reagents

    lot = db.get_or_404(ReagentLot, lot_id)
    step = {"open": lab_reagents.open_lot, "finish": lab_reagents.finish}.get(action)
    if step is None:
        abort(404)
    try:
        step(lot, user=current_user)
    except lab_reagents.LotError as err:
        db.session.rollback()
        flash(t(f"lab_reagents.err_{err}"), "error")
        return redirect(url_for("labs.reagents"))
    db.session.commit()
    flash(t(f"lab_reagents.done_{action}"), "success")
    return redirect(url_for("labs.reagents"))


# --------------------------------------------------------- quality control --
@labs_bp.route("/quality")
@module_required(MODULE)
def quality():
    """Internal quality control: the controls, the rules, the monthly
    review (GAHAR DAS.18) — and the door to external quality (DAS.19)."""
    from app.models import LabAnalyte, QcMaterial
    from app.utils import lab_quality

    materials = QcMaterial.query.order_by(QcMaterial.is_active.desc(),
                                          QcMaterial.name).all()
    return render_template("labs/quality.html", materials=materials,
                           analytes=LabAnalyte.query.order_by(LabAnalyte.name).all(),
                           rules=lab_quality.RULES, chosen=lab_quality.chosen_rules(),
                           months=lab_quality.months(),
                           may_review=lab_quality.may_review(current_user),
                           may_build=current_user.is_admin,
                           open_failures=lab_quality.failed_without_action())


@labs_bp.route("/quality/materials", methods=["POST"])
@module_required(MODULE)
def qc_material_add():
    from app.utils import lab_quality

    if not lab_quality.may_review(current_user):
        abort(403, description=t("auth.no_permission"))
    try:
        row = lab_quality.save_material(request.form)
    except lab_quality.QualityError as err:
        db.session.rollback()
        flash(t(f"lab_quality.err_{err}"), "error")
        return redirect(url_for("labs.quality"))
    db.session.commit()
    flash(t("lab_quality.material_saved"), "success")
    return redirect(url_for("labs.qc_material", material_id=row.id))


@labs_bp.route("/quality/material/<int:material_id>")
@module_required(MODULE)
def qc_material(material_id):
    """One control: its Levey-Jennings chart, its runs, and the box for
    today's value."""
    from app.models import QcMaterial
    from app.utils import lab_quality

    row = db.get_or_404(QcMaterial, material_id)
    return render_template("labs/qc_material.html", material=row,
                           points=lab_quality.chart(row),
                           runs=list(reversed(row.runs))[:60],
                           chosen=lab_quality.chosen_rules(),
                           z=lab_quality.z)


@labs_bp.route("/quality/material/<int:material_id>/run", methods=["POST"])
@module_required(MODULE)
def qc_run(material_id):
    from app.models import QcMaterial
    from app.utils import lab_quality

    row = db.get_or_404(QcMaterial, material_id)
    try:
        run = lab_quality.record_run(row, request.form.get("value"), user=current_user,
                                     accepted=request.form.get("accepted") != "0",
                                     action=request.form.get("action"))
    except lab_quality.QualityError as err:
        db.session.rollback()
        flash(t(f"lab_quality.err_{err}"), "error")
        return redirect(url_for("labs.qc_material", material_id=row.id))
    db.session.commit()
    flash(t("lab_quality.run_ok") if run.accepted else t("lab_quality.run_failed"),
          "success" if run.accepted else "warning")
    return redirect(url_for("labs.qc_material", material_id=row.id))


@labs_bp.route("/quality/run/<int:run_id>/action", methods=["POST"])
@module_required(MODULE)
def qc_action(run_id):
    from app.models import QcRun
    from app.utils import lab_quality

    run = db.get_or_404(QcRun, run_id)
    try:
        lab_quality.add_action(run, request.form.get("action"))
    except lab_quality.QualityError as err:
        db.session.rollback()
        flash(t(f"lab_quality.err_{err}"), "error")
        return redirect(url_for("labs.qc_material", material_id=run.material_id))
    db.session.commit()
    flash(t("lab_quality.action_saved"), "success")
    return redirect(url_for("labs.qc_material", material_id=run.material_id))


@labs_bp.route("/quality/rules", methods=["POST"])
@module_required(MODULE)
def qc_rules():
    """Which rules reject a control run — the laboratory's policy."""
    from app.models import ActivityLog
    from app.utils import lab_quality

    _admin_only()
    lab_quality.set_rules(request.form.getlist("rule"))
    ActivityLog.record("lab.qc_rules", user_id=current_user.id,
                       detail=",".join(lab_quality.chosen_rules()))
    db.session.commit()
    flash(t("lab_quality.rules_saved"), "success")
    return redirect(url_for("labs.quality"))


@labs_bp.route("/quality/review", methods=["POST"])
@module_required(MODULE)
def qc_review():
    """A month of control data reviewed by somebody authorized."""
    from app.utils import lab_quality

    try:
        lab_quality.review(request.form.get("month"), current_user,
                           note=request.form.get("note"))
    except lab_quality.QualityError as err:
        db.session.rollback()
        flash(t(f"lab_quality.err_{err}"), "error")
        return redirect(url_for("labs.quality"))
    db.session.commit()
    flash(t("lab_quality.reviewed"), "success")
    return redirect(url_for("labs.quality"))


@labs_bp.route("/eqa")
@module_required(MODULE)
def eqa():
    """External quality rounds and inter-laboratory comparisons (DAS.19)."""
    from app.utils import lab_quality

    return render_template("labs/eqa.html", rounds=lab_quality.rounds(),
                           outcomes=lab_quality.EQA_OUTCOMES,
                           may_review=lab_quality.may_review(current_user))


@labs_bp.route("/eqa", methods=["POST"])
@labs_bp.route("/eqa/<int:round_id>", methods=["POST"])
@module_required(MODULE)
def eqa_save(round_id=None):
    from app.models import EqaRound
    from app.utils import lab_quality

    row = db.get_or_404(EqaRound, round_id) if round_id else None
    try:
        lab_quality.save_round(request.form, user=current_user, row=row)
    except lab_quality.QualityError as err:
        db.session.rollback()
        flash(t(f"lab_quality.err_{err}"), "error")
        return redirect(url_for("labs.eqa"))
    db.session.commit()
    flash(t("lab_quality.round_saved"), "success")
    return redirect(url_for("labs.eqa"))


@labs_bp.route("/eqa/<int:round_id>/grade", methods=["POST"])
@module_required(MODULE)
def eqa_grade(round_id):
    from app.models import EqaRound
    from app.utils import lab_quality

    row = db.get_or_404(EqaRound, round_id)
    try:
        lab_quality.grade_round(row, request.form.get("outcome"),
                                note=request.form.get("grade_note"),
                                remedial=request.form.get("remedial_action"),
                                user=current_user)
    except lab_quality.QualityError as err:
        db.session.rollback()
        flash(t(f"lab_quality.err_{err}"), "error")
        return redirect(url_for("labs.eqa"))
    db.session.commit()
    flash(t("lab_quality.graded"), "success")
    return redirect(url_for("labs.eqa"))


# ---------------------------------------------------- point-of-care testing --
def _may_run_poct_setup():
    from app.utils import lab_poct

    boss = lab_poct.supervisor()
    return current_user.is_admin or (boss is not None and boss.id == current_user.id)


@labs_bp.route("/poct")
@module_required(MODULE)
def poct():
    """Every point-of-care device, where it is, who supervises (DAS.24)."""
    from app.models import PoctDevice, User
    from app.utils import lab_poct

    devices = PoctDevice.query.order_by(PoctDevice.is_active.desc(),
                                        PoctDevice.name).all()
    staff = (User.query.filter(User.is_active.is_(True))
             .order_by(User.full_name).all())
    return render_template("labs/poct.html", devices=devices, staff=staff,
                           supervisor=lab_poct.supervisor(),
                           qc_state=lab_poct.qc_state,
                           may_build=_may_run_poct_setup(),
                           is_admin=current_user.is_admin)


@labs_bp.route("/poct/supervisor", methods=["POST"])
@module_required(MODULE)
def poct_supervisor():
    from app.utils import lab_poct

    _admin_only()
    lab_poct.set_supervisor(request.form.get("user_id", type=int))
    db.session.commit()
    flash(t("lab_poct.supervisor_saved"), "success")
    return redirect(url_for("labs.poct"))


@labs_bp.route("/poct/devices", methods=["POST"])
@labs_bp.route("/poct/device/<int:device_id>/save", methods=["POST"])
@module_required(MODULE)
def poct_device_save(device_id=None):
    from app.models import PoctDevice
    from app.utils import lab_poct

    if not _may_run_poct_setup():
        abort(403, description=t("auth.no_permission"))
    row = db.get_or_404(PoctDevice, device_id) if device_id else None
    try:
        row = lab_poct.save_device(request.form, row)
    except lab_poct.PoctError as err:
        db.session.rollback()
        flash(t(f"lab_poct.err_{err}"), "error")
        return redirect(url_for("labs.poct"))
    db.session.commit()
    flash(t("lab_poct.device_saved"), "success")
    return redirect(url_for("labs.poct_device", device_id=row.id))


@labs_bp.route("/poct/device/<int:device_id>")
@module_required(MODULE)
def poct_device(device_id):
    """One device: its trained operators, its controls, its readings."""
    from app.models import PoctDevice, User
    from app.utils import lab_poct

    row = db.get_or_404(PoctDevice, device_id)
    staff = (User.query.filter(User.is_active.is_(True))
             .order_by(User.full_name).all())
    return render_template("labs/poct_device.html", device=row, staff=staff,
                           checks=list(reversed(row.checks))[:40],
                           readings=lab_poct.readings(row),
                           state=lab_poct.qc_state(row),
                           may_build=_may_run_poct_setup())


@labs_bp.route("/poct/device/<int:device_id>/operators", methods=["POST"])
@module_required(MODULE)
def poct_operator(device_id):
    from app.models import PoctDevice
    from app.utils import lab_poct

    if not _may_run_poct_setup():
        abort(403, description=t("auth.no_permission"))
    row = db.get_or_404(PoctDevice, device_id)
    try:
        lab_poct.add_operator(row, request.form)
    except lab_poct.PoctError as err:
        db.session.rollback()
        flash(t(f"lab_poct.err_{err}"), "error")
        return redirect(url_for("labs.poct_device", device_id=row.id))
    db.session.commit()
    flash(t("lab_poct.operator_saved"), "success")
    return redirect(url_for("labs.poct_device", device_id=row.id))


@labs_bp.route("/poct/device/<int:device_id>/qc", methods=["POST"])
@module_required(MODULE)
def poct_qc(device_id):
    from app.models import PoctDevice
    from app.utils import lab_poct

    row = db.get_or_404(PoctDevice, device_id)
    try:
        check = lab_poct.record_qc(row, request.form, user=current_user)
    except lab_poct.PoctError as err:
        db.session.rollback()
        flash(t(f"lab_poct.err_{err}"), "error")
        return redirect(url_for("labs.poct_device", device_id=row.id))
    db.session.commit()
    flash(t("lab_poct.qc_ok") if check.passed else t("lab_poct.qc_failed"),
          "success" if check.passed else "warning")
    return redirect(url_for("labs.poct_device", device_id=row.id))


@labs_bp.route("/poct/qc/<int:check_id>/action", methods=["POST"])
@module_required(MODULE)
def poct_qc_action(check_id):
    from app.models import PoctQc
    from app.utils import lab_poct

    check = db.get_or_404(PoctQc, check_id)
    try:
        lab_poct.qc_action(check, request.form.get("action"))
    except lab_poct.PoctError as err:
        db.session.rollback()
        flash(t(f"lab_poct.err_{err}"), "error")
        return redirect(url_for("labs.poct_device", device_id=check.device_id))
    db.session.commit()
    flash(t("lab_quality.action_saved"), "success")
    return redirect(url_for("labs.poct_device", device_id=check.device_id))


@labs_bp.route("/rejections")
@module_required(MODULE)
def rejections():
    """Every refused tube in a period, and how many under each reason —
    what the surveyor matches against the policy (GAHAR DAS.15 دليل ٣)."""
    from datetime import timedelta

    from app.utils import lab_reception
    from app.utils.clock import local_today

    today = local_today()
    end = _day(request.args.get("to")) or today
    start = _day(request.args.get("from")) or (end - timedelta(days=30))
    if start > end:
        start, end = end, start
    rows, tally = lab_reception.register(start, end)
    return render_template("labs/rejections.html", rows=rows, tally=tally,
                           start=start, end=end,
                           label=lab_reception.reason_label)


def _day(raw):
    from datetime import date

    try:
        return date.fromisoformat((raw or "").strip())
    except ValueError:
        return None


@labs_bp.route("/reject-reasons", methods=["POST"])
@module_required(MODULE)
def reject_reason_add():
    """A line on the laboratory's list of rejection reasons — its policy,
    so its words (GAHAR DAS.15 أ). Admin only, like the tests list."""
    from app.utils import lab_reception

    if not current_user.is_admin:
        abort(403)
    try:
        lab_reception.add_reason(request.form.get("name"))
    except lab_reception.ReceptionError as err:
        db.session.rollback()
        flash(t(f"lab_reception.err_{err}"), "error")
        return redirect(url_for("labs.tests") + "#reject-reasons")
    db.session.commit()
    flash(t("lab_reception.reason_added"), "success")
    return redirect(url_for("labs.tests") + "#reject-reasons")


@labs_bp.route("/reject-reasons/<int:reason_id>/retire", methods=["POST"])
@module_required(MODULE)
def reject_reason_retire(reason_id):
    """Off the list — retired, so a tube refused under it still names it."""
    from app.models import Lookup
    from app.utils import lab_reception

    if not current_user.is_admin:
        abort(403)
    try:
        lab_reception.retire_reason(db.session.get(Lookup, reason_id))
    except lab_reception.ReceptionError:
        abort(404)
    db.session.commit()
    flash(t("lab_reception.reason_retired"), "success")
    return redirect(url_for("labs.tests") + "#reject-reasons")


@labs_bp.route("/order/<int:order_id>/result", methods=["POST"])
@module_required(MODULE)
def result(order_id):
    """The answer, written on the order it answers."""
    row = db.get_or_404(VisitInvestigation, order_id)
    if lab_results.measured(row):
        return _result_by_analyte(row)
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


@labs_bp.route("/order/<int:order_id>/paper", methods=["POST"])
@module_required(MODULE)
def paper_upload(order_id):
    """The outside laboratory's paper — a photo or a PDF — kept on the order
    it answers, where the assistant can be asked to read it."""
    from app.models import PatientAttachment
    from app.utils.uploads import save_document

    row = db.get_or_404(VisitInvestigation, order_id)
    file = request.files.get("file")
    if not file or not file.filename:
        flash(t("visits.att_need_file"), "error")
        return redirect(url_for("labs.order", order_id=row.id) + "#paper")
    stored = save_document(file)
    if not stored:
        flash(t("visits.att_bad_type"), "warning")
        return redirect(url_for("labs.order", order_id=row.id) + "#paper")
    db.session.add(PatientAttachment(
        patient_id=row.patient_id, visit_id=row.visit_id, investigation_id=row.id,
        filename=stored, original_name=file.filename, kind="result",
        uploaded_by=current_user.id, linked_by=current_user.id,
        linked_at=datetime.utcnow()))
    db.session.commit()
    flash(t("visits.att_uploaded"), "success")
    return redirect(url_for("labs.order", order_id=row.id) + "#paper")


@labs_bp.route("/order/<int:order_id>/read-paper", methods=["POST"])
@module_required(MODULE)
def read_paper(order_id):
    """The assistant reads the outside laboratory's paper into this order's
    form — and stops there. The bench checks it against the paper and saves
    through the ordinary save (``lab_read``)."""
    from app.models import PatientAttachment
    from app.utils import lab_read

    row = db.get_or_404(VisitInvestigation, order_id)
    back = url_for("labs.order", order_id=row.id)
    lines = lab_results.sheet(row) if lab_results.measured(row) else []
    paper = db.session.get(PatientAttachment,
                           request.form.get("attachment_id", type=int) or 0)
    try:
        proposed = (lab_read.read(row, paper, lines) if lines
                    else lab_read.read_report(row, paper))
    except lab_read.ReadError as err:
        key = str(err)
        if key.startswith("ai:"):
            from app.utils import ai

            flash(ai.error_sentence(key[3:]), "error")
        else:
            flash(t(f"lab_read.err_{key}"), "error")
        return redirect(back + "#paper")
    return render_template("visits/read_paper.html", order=row, paper=paper,
                           lines=lines, proposed=proposed, back=back,
                           save_url=url_for("labs.result", order_id=row.id),
                           is_pdf=lab_read.readable(paper) == "application/pdf")


def _result_by_analyte(row):
    """The answer as the laboratory prints it: one value per analyte."""
    from app.models import ActivityLog

    entries = {}
    for key, raw in request.form.items():
        if key.startswith("a_") and key[2:].isdigit():
            entries[int(key[2:])] = raw
    was_critical = row.critical_at is not None
    critical = lab_results.save(row, entries, user=current_user,
                                text=request.form.get("result_text") or "")
    if critical and not was_critical:
        # Kept in the log as well as on the order: a critical value that was
        # later corrected leaves the order clean, and the log is where «was
        # anybody told» is still answerable.
        ActivityLog.record(
            "lab.critical", user_id=current_user.id,
            entity="visit_investigation", entity_id=row.id,
            detail=json.dumps([{"analyte": v.analyte.name, "value": v.shown(),
                                "flag": v.flag} for v in critical],
                              ensure_ascii=False))
    db.session.commit()
    if critical:
        flash(t("lab_result.critical_saved", n=len(critical)), "warning")
    else:
        flash(t("lab.resulted") if row.status == bench.RESULTED
              else t("lab.result_cleared"), "success")
    return redirect(url_for("labs.order", order_id=row.id))


@labs_bp.route("/critical")
@_critical_door
def critical():
    """Critical values nobody has read yet — the lab's list to chase, and a
    doctor's own at the top."""
    rows = lab_results.all_waiting()
    mine = set(lab_results.critical_for(current_user))
    rows.sort(key=lambda r: (r.id not in mine, r.critical_at))
    from app.utils import lab_critical

    return render_template("labs/critical.html", rows=rows, mine=mine,
                           beds=bench.beds_of(rows), now=datetime.utcnow(),
                           may_read=lab_results.reads_results(current_user),
                           late_call=lab_critical.late_call)


@labs_bp.route("/order/<int:order_id>/critical-read", methods=["POST"])
@_critical_door
def critical_read(order_id):
    """A doctor has read the critical value on this order."""
    from app.models import ActivityLog

    row = db.get_or_404(VisitInvestigation, order_id)
    try:
        lab_results.mark_read(row, current_user)
    except PermissionError:
        abort(403, description=t("lab_result.only_a_doctor"))
    except ValueError:
        flash(t("lab_result.nothing_critical"), "error")
        return redirect(_critical_back(row))
    ActivityLog.record("lab.critical_read", user_id=current_user.id,
                       entity="visit_investigation", entity_id=row.id)
    db.session.commit()
    flash(t("lab_result.read_saved"), "success")
    return redirect(_critical_back(row))


@labs_bp.route("/order/<int:order_id>/critical-mark", methods=["POST"])
@_critical_door
def critical_mark(order_id):
    """The technician says this result is critical — one with no number to
    cross a limit (`utils/lab_critical`)."""
    from app.models import ActivityLog
    from app.utils import lab_critical

    row = db.get_or_404(VisitInvestigation, order_id)
    try:
        lab_critical.mark(row, request.form.get("reason"), current_user)
    except lab_critical.CriticalError as err:
        db.session.rollback()
        flash(t(f"lab_critical.err_{err}"), "error")
        return redirect(_critical_back(row))
    ActivityLog.record("lab.critical_mark", user_id=current_user.id,
                       entity="visit_investigation", entity_id=row.id,
                       detail=row.critical_manual)
    db.session.commit()
    flash(t("lab_critical.marked"), "warning")
    return redirect(_critical_back(row))


@labs_bp.route("/order/<int:order_id>/critical-call", methods=["POST"])
@_critical_door
def critical_call(order_id):
    """The lab told a doctor: whom, how, and whether it was read back."""
    from app.models import ActivityLog
    from app.utils import lab_critical

    row = db.get_or_404(VisitInvestigation, order_id)
    back = _critical_back(row)
    try:
        lab_critical.call(row, request.form.get("called_to"),
                          request.form.get("method"),
                          request.form.get("read_back") == "1", current_user,
                          difficulty=request.form.get("difficulty"))
    except lab_critical.CriticalError as err:
        db.session.rollback()
        flash(t(f"lab_critical.err_{err}"), "error")
        return redirect(back)
    ActivityLog.record("lab.critical_call", user_id=current_user.id,
                       entity="visit_investigation", entity_id=row.id,
                       detail=f"{row.critical_called_to}/{row.critical_call_method}")
    db.session.commit()
    flash(t("lab_critical.called"), "success")
    return redirect(back)


@labs_bp.route("/critical/report")
@_critical_door
def critical_report():
    """Every critical result in a period — told, in time, read back, the
    difficulties, read by a doctor: what the hospital monitors (ICD.19 دليل ٤)."""
    from datetime import timedelta

    from app.utils import lab_critical
    from app.utils.clock import local_today

    end = _day(request.args.get("to")) or local_today()
    start = _day(request.args.get("from")) or (end - timedelta(days=30))
    if start > end:
        start, end = end, start
    rows, sums = lab_critical.report(start, end)
    return render_template("labs/critical_report.html", rows=rows, sums=sums,
                           start=start, end=end, timeframe=lab_critical.timeframe(),
                           late=lab_critical.late_call,
                           minutes=lab_critical.minutes_to_call,
                           may_build=current_user.is_admin)


@labs_bp.route("/critical/timeframe", methods=["POST"])
@_critical_door
def critical_timeframe():
    """The hospital's minutes from a critical result to telling a doctor."""
    from app.models import ActivityLog, Setting
    from app.utils import lab_critical

    _admin_only()
    raw = (request.form.get("minutes") or "").strip()
    Setting.set(lab_critical.TIMEFRAME_SETTING, raw if raw.isdigit() and int(raw) > 0 else "")
    ActivityLog.record("lab.critical_timeframe", user_id=current_user.id, detail=raw[:10])
    db.session.commit()
    flash(t("lab_critical.timeframe_saved"), "success")
    return redirect(url_for("labs.critical_report"))


# ------------------------------------------------------------- the tests ---
#: How many tests the list draws at once. A laboratory's catalogue runs to
#: hundreds, and each row is a form with the price list in it.
PAGE = 50


@labs_bp.route("/tests")
@module_required(MODULE)
def tests():
    """The laboratory's tests, and what each is charged as — searched, and a
    page at a time, because a laboratory's list is hundreds long. The scans
    and the device studies keep theirs in their own rooms
    (`labs/catalogue.py`); an old link to them here is sent there."""
    kind = request.args.get("kind")
    if kind in INVESTIGATION_KINDS and kind != "lab":
        return redirect(catalogue.url(kind, q=request.args.get("q"),
                                      category=request.args.get("category"),
                                      page=request.args.get("page")))
    return catalogue.page("lab")


def _poct_util():
    from app.utils import lab_poct

    return lab_poct


def _quality():
    from app.utils import lab_quality

    return lab_quality


def _reagents():
    from app.utils import lab_reagents

    return lab_reagents


def _critical():
    from app.utils import lab_critical

    return lab_critical


def _tat():
    from app.utils import lab_tat

    return lab_tat


def _sendout():
    from app.utils import lab_sendout

    return lab_sendout


def _release():
    from app.utils import lab_release

    return lab_release


def _competency():
    from app.utils import lab_competency

    return lab_competency


def _reception():
    from app.utils import lab_reception

    return lab_reception


def _move_kind(row, kind):
    """A test filed under the wrong room — an echo added as a film before
    the device studies had a room of their own — moved, and its orders not
    yet answered moved with it, so they land on the right worklist."""
    if not kind or kind == row.kind or kind not in INVESTIGATION_KINDS:
        return False
    row.kind = kind
    (VisitInvestigation.query
     .filter(VisitInvestigation.investigation_id == row.id,
             VisitInvestigation.status != bench.RESULTED)
     .update({VisitInvestigation.kind: kind}, synchronize_session=False))
    if kind == bench.DIAGNOSTIC:
        from app.utils import device_board

        device_board.mark_used()
    return True


def _radiation():
    from app.utils import radiation
    return radiation


def _devices():
    from app.models import MedicalDevice

    return (MedicalDevice.query.filter(MedicalDevice.is_active.is_(True))
            .order_by(MedicalDevice.name).all())


def _warehouses():
    from app.models import Warehouse

    return (Warehouse.query.filter(Warehouse.is_active.is_(True))
            .order_by(Warehouse.name).all())


def _lab_store():
    from app.utils import lab_stock

    return lab_stock.store()


def _reference_state(rows):
    """``{test id: {"analytes", "ranges", "drafts"}}`` for the page's rows, in
    one query — the line under each test that says what the laboratory has
    told us about it."""
    from app.models import LabRange, LabTestAnalyte

    ids = [r.id for r in rows]
    if not ids:
        return {}
    out = {i: {"analytes": 0, "ranges": 0, "drafts": 0} for i in ids}
    links = (db.session.query(LabTestAnalyte.investigation_id,
                              LabTestAnalyte.analyte_id)
             .filter(LabTestAnalyte.investigation_id.in_(ids)).all())
    by_analyte = {}
    for test_id, analyte_id in links:
        out[test_id]["analytes"] += 1
        by_analyte.setdefault(analyte_id, []).append(test_id)
    if by_analyte:
        for analyte_id, approved in (db.session.query(LabRange.analyte_id,
                                                      LabRange.approved_at)
                                     .filter(LabRange.analyte_id.in_(
                                         list(by_analyte))).all()):
            for test_id in by_analyte[analyte_id]:
                out[test_id]["ranges"] += 1
                if approved is None:
                    out[test_id]["drafts"] += 1
    return out


# ------------------------------------------------ bringing a list in -------
@labs_bp.route("/tests/import", methods=["GET", "POST"])
@module_required(MODULE)
def import_tests():
    """«استيراد» — the laboratory's sheet, read and shown before anything is
    written. The lab module's own door, and the only one: a clinic without
    the module never reaches it, and the catalogue a clinic is given on
    install and update is not touched by it."""
    _admin_only()
    from app.utils import lab_import

    if request.method == "GET":
        return render_template("labs/import.html", plan=None)
    upload = request.files.get("sheet")
    if upload is None or not (upload.filename or "").lower().endswith(".xlsx"):
        flash(t("lab_import.need_xlsx"), "error")
        return redirect(url_for("labs.import_tests"))
    try:
        plan = lab_import.read(upload.stream)
    except Exception:  # noqa: BLE001 — a sheet a person made can be anything
        flash(t("lab_import.unreadable"), "error")
        return redirect(url_for("labs.import_tests"))
    if not plan["tests"]:
        flash(t("lab_import.nothing_found"), "error")
        return redirect(url_for("labs.import_tests"))
    return redirect(url_for("labs.import_preview",
                            token=lab_import.keep(plan)))


@labs_bp.route("/tests/import/<token>", methods=["GET", "POST"])
@module_required(MODULE)
def import_preview(token):
    """What the sheet holds, what it meets in the catalogue, and what looked
    wrong — before a single row is written. The page's own «import» button
    posts back here (``_import_apply``)."""
    _admin_only()
    from app.models import Investigation as Inv
    from app.utils import lab_import

    if request.method == "POST":
        return _import_apply(token)
    plan = lab_import.load(token)
    if plan is None:
        flash(t("lab_import.expired"), "error")
        return redirect(url_for("labs.import_tests"))
    found = lab_import.match(plan)
    tests_by_key = {x["key"]: x for x in plan["tests"]}
    linked = set(found["auto"]) | {q["pick"] for q in found["questions"]
                                   if q["pick"]}
    fresh = [x for x in plan["tests"] if x["key"] not in linked]
    by_category = {}
    for test in fresh:
        name = test["category"] or "—"
        by_category[name] = by_category.get(name, 0) + 1
    ranges = [r for a in plan["analytes"].values() for r in a["ranges"]]
    return render_template(
        "labs/import.html", plan=plan, token=token, found=found,
        tests_by_key=tests_by_key,
        ours={row.id: row for row in Inv.query.filter(
            Inv.id.in_(list(found["auto"].values()) or [0])).all()},
        fresh=len(fresh), by_category=sorted(by_category.items(),
                                             key=lambda x: -x[1]),
        n_ranges=len(ranges),
        n_sourced=sum(1 for r in ranges if r["source"]),
        n_critical=sum(1 for r in ranges if r["critical_low"] is not None
                       or r["critical_high"] is not None),
        n_parts_missing=sum(1 for x in plan["tests"] if x["parts_missing"]),
        n_tat=sum(1 for x in plan["tests"] if x["tat"]),
        n_tube=sum(1 for x in plan["tests"] if x["tube"]))


def _import_apply(token):
    """Write what the preview showed, with the links as a person left them."""
    from app.models import ActivityLog
    from app.utils import lab_import
    from app.utils.decorators import client_ip

    plan = lab_import.load(token)
    if plan is None:
        flash(t("lab_import.expired"), "error")
        return redirect(url_for("labs.import_tests"))
    answers = {name[2:]: value for name, value in request.form.items()
               if name.startswith("q_")}
    links = lab_import.links_from(plan, answers)
    counts = lab_import.apply(plan, links, user=current_user,
                              show_new=request.form.get("show_new") == "1")
    ActivityLog.record("lab.import", user_id=current_user.id,
                       entity="investigation", entity_id=None,
                       detail=json.dumps(counts), ip_address=client_ip())
    db.session.commit()
    lab_import.forget(token)
    flash(t("lab_import.done", **counts), "success")
    if counts.get("priced") or counts.get("unmatched"):
        flash(t("lab_import.done_money", priced=counts.get("priced", 0),
                unmatched=counts.get("unmatched", 0)),
              "warning" if counts.get("unmatched") else "success")
    return redirect(url_for("labs.tests"))


@labs_bp.route("/tests/template")
@module_required(MODULE)
def tests_template():
    """An empty sheet with every column the import reads, each header noting
    what goes in it — «انزال نموذج تضاف بشكل كامل وترفع»."""
    _admin_only()
    import io

    from flask import send_file

    from app.utils import lab_import

    return send_file(io.BytesIO(lab_import.template()),
                     mimetype="application/vnd.openxmlformats-officedocument."
                              "spreadsheetml.sheet",
                     as_attachment=True, download_name="lab_tests_template.xlsx")


@labs_bp.route("/tests/export")
@module_required(MODULE)
def export_tests():
    """The catalogue as a sheet for the laboratory to complete and send back —
    the same columns the import reads."""
    _admin_only()
    import io

    from flask import send_file

    from app.utils import lab_import

    rows = (Investigation.query.filter(Investigation.kind == "lab")
            .order_by(Investigation.name_ar).all())
    return send_file(io.BytesIO(lab_import.export(rows)),
                     mimetype="application/vnd.openxmlformats-officedocument."
                              "spreadsheetml.sheet",
                     as_attachment=True, download_name="lab_tests.xlsx")


@labs_bp.route("/tests/<int:test_id>/ranges")
@module_required(MODULE)
def test_ranges(test_id):
    """What one test measures, and every range the laboratory has given for
    each — with where it came from and whether it is approved."""
    _admin_only()
    from app.models import StoreItem
    from app.utils import lab_stock

    row = db.get_or_404(Investigation, test_id)
    return render_template(
        "labs/test_ranges.html", test=row,
        store_items=(StoreItem.query.filter(StoreItem.is_active.is_(True))
                     .order_by(StoreItem.name).all()),
        lab_store=lab_stock.store(),
        used_cost=lab_stock.consumables_cost(row),
        double_taken=lab_stock.double_taken(row))


@labs_bp.route("/tests/<int:test_id>/approve", methods=["POST"])
@module_required(MODULE)
def approve_ranges(test_id):
    """The laboratory's director approves this test's ranges. Until then they
    are a reference beside a result and never call it high or low."""
    _admin_only()
    from app.models import ActivityLog
    from app.utils import lab_import
    from app.utils.decorators import client_ip

    row = db.get_or_404(Investigation, test_id)
    done = lab_import.approve_test(row, current_user)
    ActivityLog.record("lab.ranges_approved", user_id=current_user.id,
                       entity="investigation", entity_id=row.id,
                       detail=str(done), ip_address=client_ip())
    db.session.commit()
    flash(t("lab_import.approved", n=done), "success")
    return redirect(url_for("labs.test_ranges", test_id=row.id))


# ------------------------------------------- by hand, on the test's page --
# «مش مفتوح ان المعمل يدخلها او يغيراها بايده؟». Each of these writes a draft
# or a link; nothing here judges a result until the approve button above.
# See `app/utils/lab_hand.py`.

def _hand(test_id, work, done_key):
    from app.utils import lab_hand

    _admin_only()
    row = db.get_or_404(Investigation, test_id)
    try:
        work(row, lab_hand)
    except lab_hand.Refused as why:
        db.session.rollback()
        flash(t(why.key), "error")
        return redirect(url_for("labs.test_ranges", test_id=row.id))
    db.session.commit()
    flash(t(done_key), "success")
    return redirect(url_for("labs.test_ranges", test_id=row.id))


def _range_of(test, range_id):
    """A range that belongs to one of this test's analytes, or 404."""
    from app.models import LabRange

    rng = db.get_or_404(LabRange, range_id)
    if rng.analyte_id not in {link.analyte_id for link in test.analyte_links}:
        abort(404)
    return rng


@labs_bp.route("/tests/<int:test_id>/analytes", methods=["POST"])
@module_required(MODULE)
def add_analyte(test_id):
    return _hand(test_id, lambda row, hand: hand.add_analyte(
        row, request.form.get("name"), request.form.get("name_ar"),
        request.form.get("unit")), "lab_hand.analyte_added")


@labs_bp.route("/tests/<int:test_id>/analytes/<int:analyte_id>/remove",
               methods=["POST"])
@module_required(MODULE)
def remove_analyte(test_id, analyte_id):
    return _hand(test_id, lambda row, hand: hand.remove_analyte(row, analyte_id),
                 "lab_hand.analyte_removed")


@labs_bp.route("/tests/<int:test_id>/analytes/<int:analyte_id>/range",
               methods=["POST"])
@module_required(MODULE)
def add_range(test_id, analyte_id):
    from app.models import LabAnalyte

    def work(row, hand):
        if analyte_id not in {link.analyte_id for link in row.analyte_links}:
            abort(404)
        hand.add_range(db.get_or_404(LabAnalyte, analyte_id), request.form,
                       current_user)
    return _hand(test_id, work, "lab_hand.range_added")


@labs_bp.route("/tests/<int:test_id>/ranges/<int:range_id>", methods=["POST"])
@module_required(MODULE)
def correct_range(test_id, range_id):
    return _hand(test_id, lambda row, hand: hand.correct_range(
        _range_of(row, range_id), request.form, current_user),
        "lab_hand.range_corrected")


@labs_bp.route("/tests/<int:test_id>/ranges/<int:range_id>/drop",
               methods=["POST"])
@module_required(MODULE)
def drop_range(test_id, range_id):
    return _hand(test_id, lambda row, hand: hand.drop_draft(
        _range_of(row, range_id)), "lab_hand.draft_dropped")


@labs_bp.route("/tests/<int:test_id>/stop", methods=["POST"])
@module_required(MODULE)
def stop_test(test_id):
    from app.models import ActivityLog
    from app.utils.decorators import client_ip

    def work(row, hand):
        hand.stop(row, request.form.get("reason"), current_user)
        ActivityLog.record("lab.test_stopped", user_id=current_user.id,
                           entity="investigation", entity_id=row.id,
                           detail=row.stopped_reason, ip_address=client_ip())
    return _hand(test_id, work, "lab_hand.stopped")


@labs_bp.route("/tests/<int:test_id>/resume", methods=["POST"])
@module_required(MODULE)
def resume_test(test_id):
    return _hand(test_id, lambda row, hand: hand.resume(row), "lab_hand.resumed")


@labs_bp.route("/tests/<int:test_id>/details", methods=["POST"])
@module_required(MODULE)
def test_details(test_id):
    """The sample, the tube, the expected time and the preparation — step two
    of defining a test. Times are read the way the sheet writes them."""
    from app.utils.lab_import import minutes

    _admin_only()
    row = db.get_or_404(Investigation, test_id)
    row.sample_type = (request.form.get("sample_type") or "").strip()[:40] or None
    row.tube = (request.form.get("tube") or "").strip()[:60] or None
    row.preparation = (request.form.get("preparation") or "").strip()[:255] or None
    for field, low, high in (("tat", "tat_min", "tat_max"),
                             ("tat_stat", "tat_stat_min", "tat_stat_max")):
        raw = (request.form.get(field) or "").strip()
        span = minutes(raw) if raw else None
        if raw and span is None:
            flash(t("lab_steps.tat_unreadable", v=raw[:40]), "error")
            return redirect(url_for("labs.test_ranges", test_id=row.id) + "#details")
        setattr(row, low, span[0] if span else None)
        setattr(row, high, span[1] if span else None)
    # GAHAR DAS.20 (هـ) — how many days the tube is kept after the result.
    if "keep_days" in request.form:
        raw = (request.form.get("keep_days") or "").strip()
        row.keep_days = (int(raw) if raw.isdigit() and 0 < int(raw) <= 3650
                         else None)
    db.session.commit()
    flash(t("lab.test_saved"), "success")
    return redirect(url_for("labs.test_ranges", test_id=row.id) + "#details")


@labs_bp.route("/tests/<int:test_id>/money", methods=["POST"])
@module_required(MODULE)
def test_money(test_id):
    """What one run costs the lab, and what it uses from the lab's store —
    «علشان التحليل يتسعّر سعر وتكلفة وكل حاجه»."""
    from app.utils import lab_stock
    from app.utils.lab_import import _number

    _admin_only()
    row = db.get_or_404(Investigation, test_id)
    cost = _number(request.form.get("cost"))
    row.cost = cost if cost is not None and cost >= 0 else None
    items = request.form.getlist("item_id")
    qtys = request.form.getlist("qty")
    pairs = []
    for i, raw in enumerate(items):
        if str(raw).strip().isdigit():
            qty = qtys[i] if i < len(qtys) else "1"
            pairs.append((int(raw), int(qty) if str(qty).strip().isdigit() else 0))
    lab_stock.set_consumables(row, pairs)
    db.session.commit()
    flash(t("lab_stock.saved"), "success")
    return redirect(url_for("labs.test_ranges", test_id=row.id) + "#money")


@labs_bp.route("/store", methods=["POST"])
@module_required(MODULE)
def lab_store():
    """Which store the lab draws its strips and reagents from. None chosen,
    nothing is ever taken."""
    from app.utils import lab_stock

    _admin_only()
    lab_stock.set_store(request.form.get("warehouse_id", type=int))
    db.session.commit()
    flash(t("lab_stock.store_saved"), "success")
    return redirect(url_for("labs.tests"))


@labs_bp.route("/tests/add", methods=["POST"])
@module_required(MODULE)
def add_test():
    return catalogue.add(request.form.get("kind") or "lab")


@labs_bp.route("/tests/<int:test_id>", methods=["POST"])
@module_required(MODULE)
def edit_test(test_id):
    """The unit, the sample, and the price. The name too — a clinic renames a
    test and every order already written keeps the name it was written with,
    because the order snapshots it."""
    return catalogue.edit(test_id)


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


# ---------------------------------------------- a tube kept, and thrown away --
@labs_bp.route("/storage")
@module_required(MODULE)
def storage():
    """Where the tubes are — GAHAR DAS.20 (ج)(هـ)(و): the ones to put away,
    the ones past their day, and a search by code or by the child."""
    from app.utils import lab_storage
    from app.utils.clock import local_today

    q = (request.args.get("q") or "").strip()
    return render_template(
        "labs/storage.html", q=q, found=lab_storage.find(q) if q else [],
        waiting=lab_storage.waiting(), due=lab_storage.due(),
        kept_n=len(lab_storage.kept()), places=lab_storage.places(),
        default_days=lab_storage.default_days(),
        place_label=lab_storage.place_label, today=local_today())


@labs_bp.route("/storage/store", methods=["POST"])
@module_required(MODULE)
def storage_store():
    """Put one or several tubes away — by scanning the code, or ticking the
    tubes on the list."""
    from app.utils import lab_storage

    codes = [c for c in request.form.getlist("code") if (c or "").strip()]
    if not codes:
        flash(t("lab_storage.err_unknown"), "warning")
        return redirect(url_for("labs.storage"))
    done = 0
    for code in codes:
        try:
            lab_storage.store(code, place_key=request.form.get("place_key"),
                              place_text=request.form.get("place_text"),
                              user=current_user)
        except lab_storage.StorageError as err:
            db.session.rollback()
            flash(t(f"lab_storage.err_{err}", code=code[:24]), "warning")
            continue
        db.session.commit()
        done += 1
    if done:
        flash(t("lab_storage.stored_n", n=done), "success")
    back = request.form.get("back")
    if back and back.isdigit():
        return redirect(url_for("labs.order", order_id=int(back)))
    return redirect(url_for("labs.storage"))


@labs_bp.route("/storage/dispose", methods=["POST"])
@module_required(MODULE)
def storage_dispose():
    """Thrown away — the tubes ticked, by whoever pressed it; before their
    day only with a reason."""
    from app.models import SpecimenStore
    from app.utils import lab_storage

    done = 0
    for raw in request.form.getlist("store_id"):
        row = db.session.get(SpecimenStore, int(raw)) if raw.isdigit() else None
        try:
            lab_storage.dispose(row, user=current_user,
                                note=request.form.get("note"))
        except lab_storage.StorageError as err:
            db.session.rollback()
            flash(t(f"lab_storage.err_{err}", code=row.sample_code if row else "—"),
                  "warning")
            continue
        db.session.commit()
        done += 1
    if done:
        flash(t("lab_storage.disposed_n", n=done), "success")
    return redirect(url_for("labs.storage"))


@labs_bp.route("/storage/places", methods=["POST"])
@module_required(MODULE)
def storage_place_add():
    """A fridge or a rack on the laboratory's list. Admin only, like the
    other lists the laboratory writes."""
    from app.utils import lab_storage

    if not current_user.is_admin:
        abort(403)
    try:
        lab_storage.add_place(request.form.get("name"))
    except lab_storage.StorageError as err:
        db.session.rollback()
        flash(t(f"lab_storage.err_{err}", code=""), "error")
        return redirect(url_for("labs.storage") + "#storage-settings")
    db.session.commit()
    flash(t("lab_storage.place_added"), "success")
    return redirect(url_for("labs.storage") + "#storage-settings")


@labs_bp.route("/storage/places/<int:place_id>/retire", methods=["POST"])
@module_required(MODULE)
def storage_place_retire(place_id):
    from app.models import Lookup
    from app.utils import lab_storage

    if not current_user.is_admin:
        abort(403)
    try:
        lab_storage.retire_place(db.session.get(Lookup, place_id))
    except lab_storage.StorageError:
        abort(404)
    db.session.commit()
    flash(t("lab_storage.place_retired"), "success")
    return redirect(url_for("labs.storage") + "#storage-settings")


@labs_bp.route("/storage/keep-days", methods=["POST"])
@module_required(MODULE)
def storage_keep_days():
    """The laboratory's general figure — used for a test that has none."""
    from app.utils import lab_storage

    if not current_user.is_admin:
        abort(403)
    lab_storage.set_default_days(request.form.get("days"))
    db.session.commit()
    flash(t("lab_storage.days_saved"), "success")
    return redirect(url_for("labs.storage") + "#storage-settings")


# ------------------------------- the laboratory's documents about its tests --
@labs_bp.route("/documents")
@module_required(MODULE)
def documents():
    """Every test's written procedure and method verification — the ones
    missing or out of date first (GAHAR DAS.16 / DAS.17)."""
    from app.utils import lab_documents
    from app.utils.clock import local_today

    return render_template("labs/documents.html",
                           rows=lab_documents.overview(), today=local_today())


@labs_bp.route("/tests/<int:test_id>/documents")
@module_required(MODULE)
def test_documents(test_id):
    """One test's procedure, every version, and its verifications — read by
    anybody at the bench: *readily available when needed* (DAS.17)."""
    from app.models import METHOD_CHECK_KINDS
    from app.utils import lab_documents
    from app.utils.clock import local_today

    row = db.get_or_404(Investigation, test_id)
    if row.kind != "lab":
        abort(404)
    today = local_today()
    procedures = lab_documents.procedures_for(row.id)
    checks = lab_documents.checks_for(row.id)
    return render_template(
        "labs/test_documents.html", test=row, procedures=procedures,
        checks=checks, today=today, kinds=METHOD_CHECK_KINDS,
        p_state=lab_documents.procedure_state(procedures[0] if procedures else None, today),
        c_state=lab_documents.check_state(checks[0] if checks else None, today),
        may_write=lab_documents.may_write(current_user))


def _documents_back(test_id):
    return redirect(url_for("labs.test_documents", test_id=test_id))


@labs_bp.route("/tests/<int:test_id>/procedure", methods=["POST"])
@module_required(MODULE)
def test_procedure(test_id):
    from app.utils import lab_documents

    if not lab_documents.may_write(current_user):
        abort(403)
    row = db.get_or_404(Investigation, test_id)
    f = request.form
    try:
        lab_documents.add_procedure(
            row, f.get("version"), f.get("location"), f.get("effective_on"),
            review_due=f.get("review_due"), code=f.get("code"),
            approved_by=f.get("approved_by"), user=current_user)
    except lab_documents.DocumentError as err:
        db.session.rollback()
        flash(t(f"lab_docs.err_{err}"), "error")
        return _documents_back(row.id)
    db.session.commit()
    flash(t("lab_docs.procedure_saved"), "success")
    return _documents_back(row.id)


@labs_bp.route("/tests/<int:test_id>/method-check", methods=["POST"])
@module_required(MODULE)
def test_method_check(test_id):
    from app.utils import lab_documents

    if not lab_documents.may_write(current_user):
        abort(403)
    row = db.get_or_404(Investigation, test_id)
    f = request.form
    verdict = {"1": True, "0": False}.get(f.get("accepted"))
    try:
        lab_documents.add_check(
            row, f.get("kind"), f.get("done_on"), f.get("summary"), verdict,
            f.get("signed_by"), due_again=f.get("due_again"),
            user=current_user)
    except lab_documents.DocumentError as err:
        db.session.rollback()
        flash(t(f"lab_docs.err_{err}"), "error")
        return _documents_back(row.id)
    db.session.commit()
    flash(t("lab_docs.check_saved"), "success")
    return _documents_back(row.id)


@labs_bp.route("/manual")
def manual():
    """The laboratory service manual (GAHAR DAS.14 دليل ٢) — for whoever
    orders or draws a test, not only the lab: what each test needs, from the
    catalogue the lab keeps. Wherever the lab module is on."""
    from flask import current_app

    from app.utils import lab_documents
    from app.utils.facility import module_enabled

    if not current_user.is_authenticated:
        return current_app.login_manager.unauthorized()
    if not module_enabled(MODULE):
        abort(404)
    # Whoever works in the lab, and whoever orders — the doctors, by the same
    # rule that lets them read results. Not the front desk or the till.
    if not (current_user.can_access(MODULE)
            or lab_results.reads_results(current_user)):
        abort(403)
    scope_day, scope_by = lab_documents.scope_reviewed()
    return render_template("labs/manual.html", tests=lab_documents.manual_rows(),
                           scope_day=scope_day, scope_by=scope_by,
                           may_write=lab_documents.may_write(current_user),
                           printed_at=datetime.utcnow())


@labs_bp.route("/manual/reviewed", methods=["POST"])
@module_required(MODULE)
def manual_reviewed():
    """The scope of service was reviewed today (GAHAR DAS.10 دليل ٤)."""
    from app.utils import lab_documents

    if not lab_documents.may_write(current_user):
        abort(403)
    lab_documents.mark_scope_reviewed(current_user)
    db.session.commit()
    flash(t("lab_docs.scope_saved"), "success")
    return redirect(url_for("labs.manual"))


# ---------------------------------------------- a referral laboratory's account --
def _may_check_invoices():
    return current_user.is_admin or current_user.can_access("finance")


@labs_bp.route("/referral-labs/<int:lab_id>/account")
@module_required(MODULE)
def referral_account(lab_id):
    """What the samples sent to this laboratory came to in a period, at its
    agreed prices, and its invoices matched against it. A statement — the
    payment is recorded on the expenses screen; nothing here posts."""
    from app.models import ReferralLab
    from app.utils import lab_sendout
    from app.utils.clock import local_today

    lab = db.get_or_404(ReferralLab, lab_id)
    end = _day(request.args.get("to")) or local_today()
    start = _day(request.args.get("from")) or end.replace(day=1)
    if start > end:
        start, end = end, start
    return render_template(
        "labs/referral_account.html", lab=lab, start=start, end=end,
        data=lab_sendout.statement(lab, start, end),
        tests=lab_sendout.priced_tests(lab), prices=lab_sendout.price_list(lab),
        invoices=lab_sendout.invoices(lab),
        may_price=current_user.is_admin, may_check=_may_check_invoices())


@labs_bp.route("/referral-labs/<int:lab_id>/prices", methods=["POST"])
@module_required(MODULE)
def referral_prices(lab_id):
    from app.models import ReferralLab
    from app.utils import lab_sendout

    if not current_user.is_admin:
        abort(403)
    lab = db.get_or_404(ReferralLab, lab_id)
    raw = {int(k[6:]): v for k, v in request.form.items()
           if k.startswith("price_") and k[6:].isdigit()}
    try:
        lab_sendout.set_prices(lab, raw)
    except lab_sendout.SendError as err:
        db.session.rollback()
        flash(t(f"lab_account.err_{err}"), "error")
        return redirect(url_for("labs.referral_account", lab_id=lab.id))
    db.session.commit()
    flash(t("lab_account.prices_saved"), "success")
    return redirect(url_for("labs.referral_account", lab_id=lab.id))


@labs_bp.route("/referral-labs/<int:lab_id>/invoice", methods=["POST"])
@module_required(MODULE)
def referral_invoice(lab_id):
    from app.models import ReferralLab
    from app.utils import lab_sendout

    if not _may_check_invoices():
        abort(403)
    lab = db.get_or_404(ReferralLab, lab_id)
    f = request.form
    start, end = _day(f.get("from")), _day(f.get("to"))
    try:
        lab_sendout.check_invoice(lab, f.get("number"), start, end,
                                  f.get("amount"), note=f.get("note"),
                                  user=current_user)
    except lab_sendout.SendError as err:
        db.session.rollback()
        flash(t(f"lab_account.err_{err}"), "error")
    else:
        db.session.commit()
        flash(t("lab_account.invoice_saved"), "success")
    return redirect(url_for("labs.referral_account", lab_id=lab.id,
                            **({"from": start.isoformat(), "to": end.isoformat()}
                               if start and end else {})))
