"""The rounds: readings taken again and again, at the interval a doctor set.

Asked for by the person who runs the clinic, about the two places a single
reading per visit is useless: *"لازم مديول الطوارئ والحضانة بيقيسوا vital
signs حسب ما الدكتور بيطلب كل ربع ساعة او كل ساعة ولازم تكون مديول ما يقصرش
على العيادات"*.

**A module, and off until somebody asks for it.** A single-doctor clinic seeing
outpatients has no rounds and must not find a rounds screen in its sidebar
after an upgrade. Same rule as dentistry and the specialty panels, and the
same consequence: every address here answers 404 for a clinic that has not
switched it on — not an empty page, not a disabled button.

**Two jobs, two people.** The doctor orders the interval; whoever is at the
bedside records the readings. So ordering and stopping are the doctor's (and
the owner's), and recording is open to everybody the module reaches — which is
nursing, because that is who holds the thermometer at three in the morning.

**No clinical judgement is made here.** Whether 38.9 is a fever and whether 92%
is hypoxia are answered by ``red_flags`` and ``vital_bands``, which every other
screen already asks. This one collects numbers and prints what those two say
about them.
"""
from datetime import datetime

from flask import (abort, flash, redirect, render_template, request, url_for)
from flask_login import current_user

from app.blueprints.observations import observations_bp
from app.extensions import db
from app.i18n import t
from app.models import Patient, Visit
from app.models.observation import (AVPU, INTERVALS, OXYGEN_SUPPORT,
                                    Observation, ObservationOrder)
from app.utils import observations as rounds
from app.utils.clock import local_now, to_utc
from app.utils.decorators import module_required

MODULE = "observations"


def _float(name):
    raw = (request.form.get(name) or "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _int(name):
    raw = (request.form.get(name) or "").strip()
    if not raw:
        return None
    try:
        return int(float(raw))
    except ValueError:
        return None


def _may_order():
    """Who may start and stop the rounds.

    The doctor treating the child, and whoever runs the clinic. A nurse
    recording a reading is doing their job; a nurse changing quarter-hourly
    observations to four-hourly is overruling an instruction, and the person
    who gave it would have no way of knowing.
    """
    return (current_user.is_admin
            or current_user.role == "doctor"
            or getattr(current_user, "is_practitioner", False))


@observations_bp.route("/")
@module_required(MODULE)
def index():
    """The station board: who is under observation and who is overdue.

    Sorted worst-first by the util rather than here, because the same order
    has to hold anywhere else this list is shown.
    """
    rows = rounds.board()
    return render_template("observations/index.html", rows=rows,
                           may_order=_may_order(),
                           late=rounds.LATE, due=rounds.DUE)


@observations_bp.route("/patient/<int:patient_id>")
@module_required(MODULE)
def chart(patient_id):
    """One child: the readings, the order they were taken under, and the form.

    The form sits at the top rather than under the table. A tablet at the
    bedside opens this to *write*, and putting the readings first means
    scrolling past twelve hours of history to reach the one control anybody
    came for.
    """
    from app.utils.vital_bands import read as read_bands

    patient = Patient.query.get_or_404(patient_id)
    order = rounds.running_order(patient_id)
    readings = rounds.chart(patient_id)
    last = readings[0] if readings else None
    age_months = _age_months(patient)
    return render_template(
        "observations/chart.html",
        patient=patient, order=order, readings=readings,
        bands={row.id: read_bands(row, age_months) for row in readings},
        state=rounds.state(order, last.taken_at if last else None),
        # Prefilled with the clinic's own wall clock, not the server's: the
        # nurse is typing the hour they wrote on the paper chart, and a form
        # that opens three hours out is a form that files every reading three
        # hours out.
        now_local=local_now().strftime("%Y-%m-%dT%H:%M"),
        intervals=INTERVALS, oxygen=OXYGEN_SUPPORT, avpu=AVPU,
        may_order=_may_order(), late=rounds.LATE, due=rounds.DUE,
        open_visit=_open_visit(patient_id))


def _age_months(patient):
    """The child's age in months, from ``red_flags`` — not a second copy.

    It is the same arithmetic the triage bands use, and two implementations of
    "how old is this child" is exactly the sort of pair that drifts by one
    month and puts a two-month-old in the wrong fever band.
    """
    from app.utils.red_flags import _age_months as months

    return months(patient)


def _open_visit(patient_id):
    """The visit these readings belong to, if the child is in one.

    Nullable on purpose (see the model): observations outlive the visit that
    started them, and an admission — which is not a visit at all — is coming.
    A reading taken with no open visit is still a reading, and refusing it
    would make the screen useless in exactly the department it was built for.
    """
    return (Visit.query
            .filter(Visit.patient_id == patient_id, Visit.status == "open")
            .order_by(Visit.created_at.desc(), Visit.id.desc()).first())


@observations_bp.route("/patient/<int:patient_id>/record", methods=["POST"])
@module_required(MODULE)
def record(patient_id):
    """Save one set of readings."""
    patient = Patient.query.get_or_404(patient_id)
    order = rounds.running_order(patient_id)
    visit = _open_visit(patient_id)

    taken = _taken_at()
    row = Observation(
        patient_id=patient.id,
        visit_id=visit.id if visit else None,
        order_id=order.id if order else None,
        taken_at=taken,
        recorded_at=datetime.utcnow(),
        recorded_by=current_user.id,
        temperature_c=_float("temperature_c"),
        pulse_bpm=_int("pulse_bpm"),
        resp_rate=_int("resp_rate"),
        spo2=_int("spo2"),
        bp_systolic=_int("bp_systolic"),
        bp_diastolic=_int("bp_diastolic"),
        bp_arm=(request.form.get("bp_arm") or "").strip()[:10] or None,
        glucose_mgdl=_int("glucose_mgdl"),
        pain_score=_int("pain_score"),
        note=(request.form.get("note") or "").strip()[:255] or None,
    )
    # Both come from a fixed list on the screen, and a value that is not on it
    # was not typed by a nurse. Dropped rather than refused: the numbers in the
    # same submission are real readings and must not be lost to a bad select.
    avpu = (request.form.get("avpu") or "").strip().upper()
    row.avpu = avpu if avpu in AVPU else None
    oxygen = (request.form.get("oxygen_support") or "").strip()
    row.oxygen_support = oxygen if oxygen in OXYGEN_SUPPORT else None

    if row.is_empty:
        flash(t("observations.nothing_measured"), "error")
        return redirect(url_for("observations.chart", patient_id=patient.id))

    db.session.add(row)
    db.session.commit()
    flash(t("observations.saved"), "success")
    return redirect(url_for("observations.chart", patient_id=patient.id))


def _taken_at():
    """When the reading was taken, in UTC.

    The screen offers the clinic's own local time, prefilled with now, because
    a nurse entering four readings from a paper chart is typing the hours they
    were written at. What arrives is therefore a **local** wall-clock time and
    has to be converted, which is the one mistake this program has already
    paid for four times in the money reports: comparing a local time with a
    stored UTC one and being three hours out every night.

    Anything unparseable falls back to now rather than refusing the save — a
    reading in hand with the wrong minute on it is worth more than a reading
    nobody recorded.
    """
    raw = (request.form.get("taken_at") or "").strip()
    if raw:
        for shape in ("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M"):
            try:
                return to_utc(datetime.strptime(raw, shape))
            except ValueError:
                continue
    return datetime.utcnow()


@observations_bp.route("/patient/<int:patient_id>/order", methods=["POST"])
@module_required(MODULE)
def order(patient_id):
    """Start the rounds on this child, or change how often.

    Changing the interval **stops the old order and starts a new one** rather
    than editing the number in place. The chart then says what was asked for
    at every hour of the stay, which is the question asked afterwards when
    somebody wants to know whether the child was being watched closely enough
    at the time.
    """
    patient = Patient.query.get_or_404(patient_id)
    if not _may_order():
        abort(403, description=t("auth.no_permission"))

    every = _int("every_minutes")
    if every not in INTERVALS:
        flash(t("observations.pick_an_interval"), "error")
        return redirect(url_for("observations.chart", patient_id=patient.id))

    running = rounds.running_order(patient.id)
    if running is not None:
        if running.every_minutes == every:
            return redirect(url_for("observations.chart",
                                    patient_id=patient.id))
        running.stopped_at = datetime.utcnow()
        running.stopped_by = current_user.id

    visit = _open_visit(patient.id)
    db.session.add(ObservationOrder(
        patient_id=patient.id,
        visit_id=visit.id if visit else None,
        every_minutes=every,
        reason=(request.form.get("reason") or "").strip()[:120] or None,
        started_at=datetime.utcnow(),
        ordered_by=current_user.id))
    db.session.commit()
    flash(t("observations.order_started"), "success")
    return redirect(url_for("observations.chart", patient_id=patient.id))


@observations_bp.route("/order/<int:order_id>/stop", methods=["POST"])
@module_required(MODULE)
def stop(order_id):
    """End the rounds. The order stays on file, stopped — never deleted."""
    row = ObservationOrder.query.get_or_404(order_id)
    if not _may_order():
        abort(403, description=t("auth.no_permission"))
    if row.is_running:
        row.stopped_at = datetime.utcnow()
        row.stopped_by = current_user.id
        db.session.commit()
        flash(t("observations.order_stopped"), "success")
    return redirect(url_for("observations.chart", patient_id=row.patient_id))
