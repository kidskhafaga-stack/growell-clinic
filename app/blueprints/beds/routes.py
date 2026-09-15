"""The beds, and the children in them.

أساس ٢ of ``HOSPITAL_PLAN.md``: a stay is not a visit. ``Visit.visit_date`` is
a single day, which is right for an outpatient and cannot hold a child who is
here until Thursday.

**One module for four departments.** Emergency, the incubators, intensive care
and the ward are not four systems — they are four *kinds of unit* over the same
three levels, which is what the person who runs the place described: partitions
in emergency, rooms on the ward, an open bay with one or two isolation
partitions in intensive care, and cots, incubators and transport capsules in
the nursery. A module each would have been the same screen written four times.

**Opt-in, and absent when off.** A single-doctor clinic has no beds. Every
address here answers 404 for them — not an empty ward screen.

**Who does what.** Admitting, moving and discharging are clinical acts:
doctors, nursing, and whoever runs the clinic. Building the place itself —
adding a unit, a room, a bed — is the owner's, because it is configuration and
not care.
"""
from datetime import datetime

from flask import (abort, flash, g, redirect, render_template, request,
                   url_for)
from flask_login import current_user
from werkzeug.routing import BuildError

from app.blueprints.beds import beds_bp
from app.extensions import db
from app.i18n import t
from app.models import Patient, Visit
from app.models.admission import OUTCOMES, Admission
from app.models.discharge_summary import DischargeSummary
from app.models.medication import (DOSE_OUTCOMES, ROUTES, MedicationOrder)
from app.models.place import BED_KINDS, SPACE_KINDS, UNIT_KINDS, Bed, Space, Unit
from app.models.prescription import Drug
from app.models.round_note import ROUND_TRENDS
from app.utils import beds as ward
from app.utils import bed_billing
from app.utils import drug_round
from app.utils.clock import local_today
from app.utils import discharge_summary as summary
from app.utils import risks
from app.utils import round_billing
from app.utils import rounds as ward_round
from app.utils.clock import to_local, to_utc
from app.utils.decorators import capability_required, module_required

MODULE = "beds"


@beds_bp.route("/")
@module_required(MODULE)
def index():
    """The board: every unit, every space, every bed and who is in it."""
    return render_template("beds/index.html",
                           units=ward.board(),
                           counts=ward.counts(),
                           may_build=current_user.is_admin)


# ------------------------------------------------------------ building it ---
@beds_bp.route("/setup")
@module_required(MODULE)
def setup():
    """Where a hospital grows: add a unit, a space, a bed.

    From the screen, never from a release. A clinic adding incubator number
    seven, or turning a room into intensive care, is a Tuesday afternoon — the
    same principle that let nine specialties arrive as a JSON edit.
    """
    if not current_user.is_admin:
        abort(403, description=t("auth.no_permission"))
    from app.models.service import Service

    return render_template("beds/setup.html",
                           bases=bed_billing.BASES,
                           units=ward.board(),
                           unit_kinds=UNIT_KINDS, space_kinds=SPACE_KINDS,
                           bed_kinds=BED_KINDS,
                           taken=ward.occupied_bed_ids(),
                           # What a night may be priced at. The clinic's own
                           # services, because a night is a service.
                           services=(Service.query
                                     .filter(Service.is_active.is_(True))
                                     .order_by(Service.name).all()))


def _admin_only():
    if not current_user.is_admin:
        abort(403, description=t("auth.no_permission"))


@beds_bp.route("/unit", methods=["POST"])
@module_required(MODULE)
def add_unit():
    _admin_only()
    name = (request.form.get("name") or "").strip()[:80]
    kind = (request.form.get("kind") or "").strip()
    if not name or kind not in UNIT_KINDS:
        flash(t("beds.name_and_kind"), "error")
        return redirect(url_for("beds.setup"))
    db.session.add(Unit(name=name, kind=kind,
                        # Emergency is charged by the hour and a ward by the
                        # night. A preset, editable from this same screen —
                        # what it buys is that nobody has to know that before
                        # their first emergency bill comes out wrong.
                        billing_basis=bed_billing.default_basis(kind),
                        sort_order=Unit.query.count()))
    db.session.commit()
    flash(t("beds.unit_added"), "success")
    return redirect(url_for("beds.setup"))


@beds_bp.route("/unit/<int:unit_id>/space", methods=["POST"])
@module_required(MODULE)
def add_space(unit_id):
    _admin_only()
    unit = Unit.query.get_or_404(unit_id)
    name = (request.form.get("name") or "").strip()[:60]
    kind = (request.form.get("kind") or "").strip()
    if not name or kind not in SPACE_KINDS:
        flash(t("beds.name_and_kind"), "error")
        return redirect(url_for("beds.setup"))
    db.session.add(Space(
        unit_id=unit.id, name=name, kind=kind,
        # Isolation is asked here and stored here, never on the bed: what
        # isolates a child is the walls around them, not the bed frame.
        is_isolation=bool(request.form.get("is_isolation")),
        sort_order=len(unit.spaces)))
    db.session.commit()
    flash(t("beds.space_added"), "success")
    return redirect(url_for("beds.setup"))


@beds_bp.route("/space/<int:space_id>/bed", methods=["POST"])
@module_required(MODULE)
def add_bed(space_id):
    _admin_only()
    space = Space.query.get_or_404(space_id)
    name = (request.form.get("name") or "").strip()[:40]
    kind = (request.form.get("kind") or "").strip()
    if not name or kind not in BED_KINDS:
        flash(t("beds.name_and_kind"), "error")
        return redirect(url_for("beds.setup"))
    db.session.add(Bed(space_id=space.id, name=name, kind=kind,
                       sort_order=len(space.beds)))
    db.session.commit()
    flash(t("beds.bed_added"), "success")
    return redirect(url_for("beds.setup"))


@beds_bp.route("/rate", methods=["POST"])
@module_required(MODULE)
def set_rate():
    """What a night here costs — on a unit, or on one bed inside it.

    **The door to the daily bed charge, and its switch.** A clinic that never
    sets a rate is never charged for a night and never shown a figure: the
    feature is absent for them the way a module that is off is absent. Which
    means it has to be reachable, or it is a feature nobody can turn on —
    the failure this project has walked into six times.

    A service and not a number, so the night sits in the one price list where
    the discounts, the payer rules, the commission and the tax code already
    work.
    """
    _admin_only()
    service_id = request.form.get("service_id", type=int) or None
    unit_id = request.form.get("unit_id", type=int)
    space_id = request.form.get("space_id", type=int)
    bed_id = request.form.get("bed_id", type=int)
    # Bed, room or department — the three levels a clinic may price at. Which
    # one it uses is its own business; the charge reads the nearest one set.
    if unit_id:
        target = Unit.query.get_or_404(unit_id)
    elif space_id:
        target = Space.query.get_or_404(space_id)
    else:
        target = Bed.query.get_or_404(bed_id)
    target.rate_service_id = service_id
    if unit_id:
        basis = (request.form.get("billing_basis") or "").strip()
        if basis in bed_billing.BASES:
            target.billing_basis = basis
    db.session.commit()
    flash(t("beds.rate_saved"), "success")
    return redirect(url_for("beds.setup"))


@beds_bp.route("/bed/<int:bed_id>/service", methods=["POST"])
@module_required(MODULE)
def bed_service(bed_id):
    """Take a bed out of service, or bring it back.

    Never deleted. A deleted bed takes its stays with it, and last month's
    occupancy is a number a hospital reports on. A bed with a child in it
    cannot be taken out of service — the child is the reason it is not
    available, and hiding the bed would hide them with it.
    """
    _admin_only()
    bed = Bed.query.get_or_404(bed_id)
    if bed.is_active and bed.id in ward.occupied_bed_ids():
        flash(t("beds.occupied_bed"), "error")
        return redirect(url_for("beds.setup"))
    bed.is_active = not bed.is_active
    bed.out_of_service_note = (
        (request.form.get("note") or "").strip()[:120] or None
        if not bed.is_active else None)
    db.session.commit()
    return redirect(url_for("beds.setup"))


# --------------------------------------------------------- the stay itself --
@beds_bp.route("/admit/<int:patient_id>", methods=["POST"])
@module_required(MODULE)
def admit(patient_id):
    """Put a child in a bed.

    The bed is re-checked here even though the screen only offered free ones:
    the list was drawn seconds ago, and a ward fills up between a page loading
    and a button being pressed.
    """
    patient = Patient.query.get_or_404(patient_id)
    bed = Bed.query.get(request.form.get("bed_id", type=int))
    visit = (Visit.query
             .filter(Visit.patient_id == patient.id, Visit.status == "open")
             .order_by(Visit.created_at.desc(), Visit.id.desc()).first())
    try:
        admission = ward.admit(patient, bed, user=current_user, visit=visit,
                               doctor_id=(current_user.id
                                          if current_user.role == "doctor"
                                          else None),
                               reason=request.form.get("reason"))
    except ward.BedTaken as why:
        db.session.rollback()
        # Each refusal says which one it was. "The bed is taken" and "this
        # child is already admitted" send whoever is standing at the desk to
        # two completely different next steps, and one message for both wastes
        # the trip.
        reasons = {"occupied": "beds.refused_occupied",
                   "already admitted": "beds.refused_admitted",
                   "out of service": "beds.refused_service",
                   "no bed": "beds.refused_no_bed"}
        flash(t(reasons.get(str(why), "beds.refused_occupied")), "error")
        return redirect(request.referrer or url_for("beds.index"))
    db.session.commit()
    flash(t("beds.admitted"), "success")
    return redirect(url_for("beds.admission", admission_id=admission.id))


@beds_bp.route("/admission/<int:admission_id>")
@module_required(MODULE)
def admission(admission_id):
    """One stay: where they are, where they have been, and how it ended."""
    row = Admission.query.get_or_404(admission_id)
    # Read once. The headline counts and the rows under them come off the same
    # list, so they cannot end up saying different things about one stay.
    risk_rows = risks.panel(row)
    return render_template(
        "beds/admission.html", admission=row,
        free=ward.free_beds(), outcomes=OUTCOMES, trends=ROUND_TRENDS,
        rounds=sorted(row.round_notes, key=lambda n: (n.at, n.id),
                      reverse=True),
        # The chart, and what the clinic's own safety check makes of it. Not a
        # second check: `rx_safety` is the one the prescription screen uses,
        # and an inpatient order is handed to it unchanged.
        meds=drug_round.for_admissions([row.id]).get(row.id) or {},
        # The ward's own shelf, so an order can point at what it takes.
        store_items=_ward_items(),
        # The document the stay ends with (GAHAR ACT.15). Six of its nine
        # elements are written and three are read off the record, so the
        # screen can show a doctor which ones need them and which are already
        # answered — and can say «not written» about a stay that has none,
        # which is a different fact from one whose boxes are empty.
        # The three risks GAHAR requires a hospital to look for — ICD.10
        # falls, ICD.11 pressure ulcers, ICD.12 VTE. One row per risk the
        # clinic looks for, present whether or not anybody has assessed it:
        # an absence has no row of its own to find, and an unassessed risk is
        # the thing this panel is for.
        risk_panel=risk_rows,
        risk_unassessed=risks.unassessed(risk_rows),
        risk_bare=risks.without_plan(risk_rows),
        discharge_summary=summary.for_admission(row),
        summary_state=summary.state(row),
        summary_missing=summary.missing(row),
        summary_elements=summary.assemble(row),
        summary_delay=summary.delay_hours(row),
        provisional=summary.provisional_diagnoses(row),
        # The second door into the theatres. A day case is booked from the
        # theatre list; a child already in a bed is booked from here, where
        # whoever is looking after them is standing. One door would have
        # hidden the other kind of case — the gap this program has now found
        # seven times. Empty when the module is off, and the screen draws
        # nothing: a module off is a module absent, not a dead button.
        theatre_rooms=_theatre_rooms(),
        stopped=[o for o in row.medication_orders if not o.is_running],
        safety=drug_round.safety(row, lang=getattr(g, "lang", "ar")),
        routes=ROUTES, dose_outcomes=DOSE_OUTCOMES,
        may_order=current_user.can("medication_order"),
        # Shown, never posted by opening a page. Money is written onto a
        # family's account by somebody pressing something.
        due_nights=bed_billing.outstanding(row),
        # The consultant's rounds nobody has billed yet, shown the same way
        # and for the same reason. Empty in every clinic that has not priced
        # a round, which is the switch — see `utils/round_billing`.
        due_rounds=round_billing.unbilled(admission_id=row.id),
        round_service=round_billing.round_service(),
        charged=sorted(row.bed_charges, key=lambda c: c.on_date),
        # What an hourly stay has run up so far. Shown while it is open and
        # never charged until it closes — the number is still moving.
        basis=bed_billing.basis_for(row.bed),
        running_hours=(bed_billing.hours_so_far(row)
                       if row.is_open
                       and bed_billing.basis_for(row.bed) == bed_billing.HOUR
                       else 0))


@beds_bp.route("/admission/<int:admission_id>/nights", methods=["POST"])
@module_required(MODULE)
def post_nights(admission_id):
    """Charge the nights this stay owes and nobody has billed.

    Safe to press twice, and pressed by a person on purpose. There is no
    timer writing money onto a family's account overnight — the screen shows
    what is outstanding and somebody decides.
    """
    row = Admission.query.get_or_404(admission_id)
    # `charge`, not `post`: it commits the bill before journalling it, because
    # a ledger failure rolls the session back and would otherwise take the
    # invoice with it.
    result = bed_billing.charge(row, user=current_user,
                                lang=getattr(g, "lang", "ar"))
    if not result["periods"] and not result["doses"] \
            and not result["operations"] and not result["tests"] \
            and not result["rounds"]:
        flash(t("beds.nights_none"), "info")
        return redirect(url_for("beds.admission", admission_id=row.id))
    if result["periods"]:
        flash(t("beds.nights_posted", n=result["periods"],
                total=result["total"],
                number=result["invoice"].invoice_number), "success")
    if result["doses"]:
        # Said out loud rather than discovered on the bill: the drugs given
        # on the ward are money and stock, and both moved.
        flash(t("meds.n_doses_charged", n=result["doses"]), "success")
    if result["operations"]:
        flash(t("theatre.n_charged", n=result["operations"]), "success")
    if result["tests"]:
        flash(t("lab.n_charged", n=result["tests"]), "success")
    if result["rounds"]:
        flash(t("rounds.n_charged", n=result["rounds"]), "success")
    return redirect(url_for("beds.admission", admission_id=row.id))


@beds_bp.route("/admission/<int:admission_id>/move", methods=["POST"])
@module_required(MODULE)
def move(admission_id):
    row = Admission.query.get_or_404(admission_id)
    bed = Bed.query.get(request.form.get("bed_id", type=int))
    try:
        ward.move(row, bed, user=current_user, note=request.form.get("note"))
    except ward.BedTaken:
        db.session.rollback()
        flash(t("beds.refused_occupied"), "error")
        return redirect(url_for("beds.admission", admission_id=row.id))
    db.session.commit()
    flash(t("beds.moved"), "success")
    return redirect(url_for("beds.admission", admission_id=row.id))


@beds_bp.route("/admission/<int:admission_id>/summary", methods=["POST"])
@module_required(MODULE)
def write_summary(admission_id):
    """Write or correct this stay's discharge summary (GAHAR ACT.15).

    Six boxes, because the other three of the standard's nine elements are
    already in the record and the program will not ask anybody to type them
    twice — see ``app/utils/discharge_summary.py``.
    """
    row = Admission.query.get_or_404(admission_id)
    summary.write(row, user=current_user,
                  **{name: request.form.get(name)
                     for name in DischargeSummary.WRITTEN})
    db.session.commit()
    # Which elements are still blank, said now rather than found by a surveyor
    # — and "signed short" is a state this program already names elsewhere.
    short = summary.missing(row)
    flash(t("summary.saved_short", n=len(short)) if short
          else t("summary.saved"), "warning" if short else "success")
    return redirect(url_for("beds.admission", admission_id=row.id))


@beds_bp.route("/admission/<int:admission_id>/summary/given", methods=["POST"])
@module_required(MODULE)
def summary_given(admission_id):
    """Record that a copy reached the family — ACT.15 evidence 4."""
    row = Admission.query.get_or_404(admission_id)
    if summary.hand_over(row, user=current_user) is None:
        flash(t("summary.nothing_to_give"), "warning")
        return redirect(url_for("beds.admission", admission_id=row.id))
    db.session.commit()
    flash(t("summary.given"), "success")
    return redirect(url_for("beds.admission", admission_id=row.id))


@beds_bp.route("/admission/<int:admission_id>/summary/print")
@module_required(MODULE)
def summary_print(admission_id):
    """The copy. Evidence 3 keeps one in the record, evidence 4 hands one over.

    All nine elements on one sheet, the derived ones read off the record at
    the moment of printing — so a summary printed after somebody linked the
    missing operation carries it, without anybody rewriting the document.
    """
    row = Admission.query.get_or_404(admission_id)
    return render_template(
        "beds/summary_print.html", admission=row,
        summary=summary.for_admission(row),
        elements=summary.assemble(row),
        investigations=summary.investigations_during(row),
        procedures=summary.procedures_during(row),
        meds_during=summary.medicines_during(row),
        meds_before=summary.medicines_before(row),
        today=local_today(), generated_by=current_user)


@beds_bp.route("/admission/<int:admission_id>/discharge", methods=["POST"])
@module_required(MODULE)
def discharge(admission_id):
    """End the stay. The bed is freed by the stay closing, not by a flag."""
    row = Admission.query.get_or_404(admission_id)
    ward.discharge(row, (request.form.get("outcome") or "").strip(),
                   user=current_user, note=request.form.get("note"))
    db.session.flush()
    # The nights, at the one moment the whole stay is finally known. A
    # discharge is already a deliberate act with a form in front of it, so
    # this is not money appearing behind anybody's back — and it is said out
    # loud in the flash rather than left to be discovered on the bill.
    billed = bed_billing.charge(row, user=current_user,
                                lang=getattr(g, "lang", "ar"))
    flash(t("beds.discharged"), "success")
    if billed["periods"]:
        flash(t("beds.nights_posted", n=billed["periods"],
                total=billed["total"],
                number=billed["invoice"].invoice_number), "info")
    if billed["doses"]:
        flash(t("meds.n_doses_charged", n=billed["doses"]), "info")
    if billed["operations"]:
        flash(t("theatre.n_charged", n=billed["operations"]), "info")
    if billed["tests"]:
        flash(t("lab.n_charged", n=billed["tests"]), "info")
    if billed["rounds"]:
        flash(t("rounds.n_charged", n=billed["rounds"]), "info")
    return redirect(url_for("beds.admission", admission_id=row.id))


# ------------------------------------------------------------ the round -----
@beds_bp.route("/admission/<int:admission_id>/round", methods=["POST"])
@module_required(MODULE)
def round_note(admission_id):
    """One stop on the ward round.

    **Here and not on the ward blueprint**, although the ward is where it is
    used most. Three department screens post to this address — the wards,
    intensive care and the incubators — and a clinic may run any one of them
    without the others. Hanging the action off `ward` would have meant a
    nursery with no wards getting 404 on the round it walks every morning:
    the same "a module off is a module absent" rule, aimed at itself. Every
    department that has rounds has `beds` on, because the stay is here.
    """
    row = Admission.query.get_or_404(admission_id)
    try:
        ward_round.record(
            row, (request.form.get("trend") or "").strip(),
            user=current_user,
            assessment=request.form.get("assessment"),
            plan=request.form.get("plan"),
            expected_discharge=_a_date(request.form.get("expected_discharge")),
            at=_happened_at())
    except ValueError:
        db.session.rollback()
        # The blank round, refused out loud. Silence here would look exactly
        # like a round that saved, and the board would stop asking about a
        # child nobody had been to see — which is the failure the whole "not
        # rounded today" flag exists to prevent.
        flash(t("rounds.needs_trend"), "error")
        return _back_to(row)
    db.session.commit()
    flash(t("rounds.saved"), "success")
    return _back_to(row)


@beds_bp.route("/admission/<int:admission_id>/risk", methods=["POST"])
@module_required(MODULE)
def risk_assessment(admission_id):
    """Record one look at one of the three required risks — ICD.10/11/12.

    **No capability of its own, like the round**, and for the same reason: the
    person who assesses a child for falls is whoever is standing at the bed,
    and on a night shift that is nursing. A capability here would have put the
    assessment behind the ward's door twice.
    """
    row = Admission.query.get_or_404(admission_id)
    try:
        risks.record(
            row.patient, (request.form.get("kind") or "").strip(),
            user=current_user, admission=row,
            tool=request.form.get("tool"),
            level=request.form.get("level"),
            at_risk=_yes_no(request.form.get("at_risk")),
            general_measures=request.form.get("general_measures"),
            plan=request.form.get("plan"),
            family_told=_yes_no(request.form.get("family_told")),
            at=_happened_at())
    except ValueError:
        db.session.rollback()
        # Said out loud rather than swallowed. A post that quietly saved
        # nothing would leave a nurse believing the record carries an
        # assessment it does not — the failure this whole screen exists to
        # make visible, arriving through the screen itself.
        flash(t("risks.not_saved"), "error")
        return redirect(url_for("beds.admission", admission_id=row.id))
    db.session.commit()
    flash(t("risks.saved"), "success")
    return redirect(url_for("beds.admission", admission_id=row.id))


def _yes_no(raw):
    """``"yes"``/``"no"`` as a boolean, and everything else as ``None``.

    The third state is the point: the form's blank option means nobody
    committed to an answer, which is not "no" — see the model's docstring on
    why ``at_risk`` and ``family_told`` are nullable.
    """
    said = (raw or "").strip().lower()
    if said == "yes":
        return True
    if said == "no":
        return False
    return None


def _back_to(admission):
    """Back to the screen the round was written from.

    The referrer decides, because one address serves three department boards
    and the stay screen — but it is matched against our own endpoints rather
    than followed, since a redirect that trusts a request header is an open
    redirect wherever it appears.
    """
    here = request.referrer or ""
    for endpoint in ("ward.index", "icu.index", "nicu.index"):
        try:
            known = url_for(endpoint)
        except BuildError:
            continue
        if here.endswith(known):
            return redirect(known)
    return redirect(url_for("beds.admission", admission_id=admission.id))


def _theatre_rooms():
    """The operating rooms, or nothing at all when the module is off."""
    from app.utils.facility import module_enabled

    if not module_enabled("theatres"):
        return []
    from app.models.theatre import Theatre

    return (Theatre.query.filter(Theatre.is_active.is_(True))
            .order_by(Theatre.sort_order, Theatre.id).all())


def _a_date(raw):
    """A date the screen sent, or nothing. Never today by default: an expected
    discharge nobody typed is not a plan, and defaulting it would put one in
    the record."""
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        return None


def _happened_at():
    """When the round happened, in UTC.

    The screen offers the clinic's local wall clock prefilled with now,
    because a doctor typing this at eleven is recording a round they walked at
    nine. Converting is not optional: comparing a local time against stored
    UTC is the mistake this program has already paid for in four money
    reports. Unparseable falls back to now — a round with the wrong minute on
    it is worth more than a round nobody wrote down.
    """
    raw = (request.form.get("at") or "").strip()
    if raw:
        for shape in ("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M"):
            try:
                return to_utc(datetime.strptime(raw, shape))
            except ValueError:
                continue
    return datetime.utcnow()


@beds_bp.route("/order/<int:order_id>/answer", methods=["POST"])
@module_required(MODULE)
def answer_query(order_id):
    """The doctor's reply to the clinical pharmacist's question.

    **Here and not on the pharmacy screen**, which is where the first version
    put it — and the doctor could not open that screen at all, because the
    `pharmacy` module is not theirs. A question that can only be answered on a
    screen the person who has to answer it cannot reach is a question nobody
    answers, and the pharmacist would have gone on waiting with no way to tell
    that from being ignored.

    So the question arrives on the stay screen, where the doctor is standing
    with the chart in front of them, and the reply goes back from there.
    """
    from app.models.medication import MedicationOrder
    from app.utils import clinical_pharmacy

    row = db.get_or_404(MedicationOrder, order_id)
    try:
        clinical_pharmacy.answer(row, note=request.form.get("note"),
                                 user=current_user)
    except ValueError:
        db.session.rollback()
        flash(t("cpharm.nothing_asked"), "error")
        return redirect(url_for("beds.admission",
                                admission_id=row.admission_id))
    db.session.commit()
    flash(t("cpharm.answered"), "success")
    return redirect(url_for("beds.admission", admission_id=row.admission_id))


# ------------------------------------------------------- the drug round -----
@beds_bp.route("/drugs")
@module_required(MODULE)
def drugs():
    """The station board: every child owed something, most overdue first.

    Whoever is on at three in the morning covers more than one ward, so this
    is the whole hospital by default and narrows to one kind of department
    from the link on that department's screen.

    A child on nothing is deliberately not a row. They are on every other ward
    screen; putting them here as well would bury the four who are actually
    owed a dose under the twenty who are not.
    """
    kind = (request.args.get("kind") or "").strip() or None
    return render_template("beds/drugs.html",
                           rows=drug_round.board(kind), kind=kind,
                           levels=drug_round, routes=ROUTES,
                           outcomes=DOSE_OUTCOMES)


@beds_bp.route("/drug-search")
@module_required(MODULE)
def drug_search():
    """Autocomplete for the order box — the same search the prescription
    writer and the visit screen use.

    A thin route of its own rather than borrowing the one under ``visits``:
    that address is behind the visits module, and while every department
    capability happens to switch visits on today, a ward whose autocomplete
    stops working because somebody turned off an unrelated module is a bug
    waiting on a settings change.
    """
    from flask import jsonify

    from app.utils.drug_search import search_drugs

    return jsonify(search_drugs(request.args.get("q"),
                                lang=getattr(g, "lang", "ar"), limit=12))


@beds_bp.route("/admission/<int:admission_id>/medication", methods=["POST"])
@module_required(MODULE)
@capability_required("medication_order")
def add_medication(admission_id):
    """Write a standing order.

    Behind ``medication_order`` and not behind the module, because deciding
    what a child is on and giving it are two jobs — the oldest safety rule on
    a ward, and the one the module gate is too coarse to express.
    """
    row = Admission.query.get_or_404(admission_id)
    drug = db.session.get(Drug, request.form.get("drug_id", type=int))
    try:
        drug_round.order(
            row,
            (request.form.get("drug_name") or "").strip() or (
                drug.trade_name if drug else ""),
            user=current_user, drug=drug,
            dose=request.form.get("dose"),
            route=(request.form.get("route") or "oral").strip(),
            every_hours=request.form.get("every_hours", type=int),
            is_prn=bool(request.form.get("is_prn")),
            min_gap_hours=request.form.get("min_gap_hours", type=int),
            # What comes off the shelf when this is given, and how many units
            # of it. Left empty the order works exactly as before and touches
            # neither the stock nor the bill.
            store_item_id=request.form.get("store_item_id", type=int),
            units_per_dose=request.form.get("units_per_dose", type=int),
            note=request.form.get("note"))
    except ValueError as why:
        db.session.rollback()
        # Each refusal names itself. "You did not say which drug" and "you did
        # not say how often" send whoever is at the keyboard to two different
        # boxes, and one message for both wastes the trip.
        flash(t({"no drug": "meds.needs_drug",
                 "no interval": "meds.needs_interval"}.get(
                     str(why), "meds.refused")), "error")
        return redirect(url_for("beds.admission", admission_id=row.id))
    db.session.commit()
    flash(t("meds.ordered"), "success")
    return redirect(url_for("beds.admission", admission_id=row.id))


@beds_bp.route("/medication/<int:order_id>/stop", methods=["POST"])
@module_required(MODULE)
@capability_required("medication_order")
def stop_medication(order_id):
    """Stop an order. Its doses stay — a drug that was stopped is not a drug
    the child was never on, and the file has to be able to say what they were
    on last Tuesday."""
    row = MedicationOrder.query.get_or_404(order_id)
    drug_round.stop(row, user=current_user, reason=request.form.get("reason"))
    db.session.commit()
    flash(t("meds.stopped"), "success")
    return redirect(url_for("beds.admission", admission_id=row.admission_id))


@beds_bp.route("/medication/<int:order_id>/dose", methods=["POST"])
@module_required(MODULE)
def dose(order_id):
    """Given, held, or refused — recorded by whoever stood at the bed.

    **Not** behind ``medication_order``: giving is the nurse's act, and it is
    the whole reason the two are separate capabilities.
    """
    row = MedicationOrder.query.get_or_404(order_id)
    try:
        drug_round.give(row, (request.form.get("outcome") or "given").strip(),
                        user=current_user, at=_happened_at(),
                        reason=request.form.get("reason"),
                        note=request.form.get("note"))
    except drug_round.NoReason:
        db.session.rollback()
        flash(t("meds.needs_reason"), "error")
        return _back_from_dose(row)
    except drug_round.TooSoon as floor:
        db.session.rollback()
        flash(t("meds.too_soon", at=to_local(floor.args[0]).strftime("%H:%M")),
              "error")
        return _back_from_dose(row)
    except ValueError:
        db.session.rollback()
        flash(t("meds.refused"), "error")
        return _back_from_dose(row)
    db.session.commit()
    flash(t("meds.recorded"), "success")
    return _back_from_dose(row)


def _ward_items():
    """What the store holds that a ward order could be written against.

    Drugs first and everything else after: an order is written for a drug,
    and a list that opens on gauze is a list somebody scrolls past. Inactive
    items stay out — an order cannot be written against something the clinic
    has stopped stocking.
    """
    from app.models import StoreItem

    return (StoreItem.query
            .filter(StoreItem.is_active.is_(True))
            .order_by((StoreItem.item_type != "drug"), StoreItem.name).all())


def _back_from_dose(order_row):
    """Back to the drug board when that is where the nurse was, otherwise to
    the stay. Matched against our own addresses rather than followed, like
    every other referrer in this file."""
    here = request.referrer or ""
    board = url_for("beds.drugs")
    if board in here:
        return redirect(here if here.startswith(request.host_url) else board)
    return redirect(url_for("beds.admission",
                            admission_id=order_row.admission_id))
