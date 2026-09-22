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
from app.models.blood import PRODUCTS as BLOOD_PRODUCTS
from app.models.blood import URGENCIES as BLOOD_URGENCIES
from app.models.discharge_summary import DischargeSummary
from app.models.medication import (DOSE_OUTCOMES, ROUTES, MedicationOrder)
from app.models.place import BED_KINDS, SPACE_KINDS, UNIT_KINDS, Bed, Space, Unit
from app.models.prescription import Drug
from app.models.round_note import ROUND_TRENDS
from app.utils import beds as ward
from app.utils import pain as _pain_utils
from app.utils import nursing as _nursing_utils
from app.utils import bed_billing
from app.utils import blood
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
    blood_rows = blood.panel(row)
    from app.models import (LINE_HIGH_RISK, LINE_KINDS, RESTRAINT_KINDS,
                            RESUS_OUTCOMES)
    from app.utils import lines as _lines
    from app.utils import nutrition as _food
    from app.utils import restraint as _tied
    from app.utils import resuscitation as _cpr
    return render_template(
        "beds/admission.html", admission=row,
        # `ACT.07` — مين ينفع يبقى مسؤول، من اللي العيادة مشغّلاهم.
        doctors=_doctors(),
        # `ICD.09` — أدوات العيادة (فاضية لحد ما تكتبها)، وآخر فرز.
        pain_tools=_pain_utils.tool_list(),
        pain_latest=_pain_utils.latest_screen(row.patient_id),
        pain_gaps=_pain_utils.missing,
        # `ICD.07` — التقييم الأول، وآخر واحد، واللي الملف بيعرفه أصلاً.
        nursing_initial=_nursing_utils.initial_for(row.id),
        nursing_latest=_nursing_utils.latest_for(row.id),
        nursing_known=_nursing_utils.assembled(row),
        nursing_gaps=_nursing_utils.missing,
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
        # GAHAR ICD.20/ICD.21 — what was ordered and why, and whether anybody
        # checked the bag and watched the child. The monitoring is ordinary
        # observations tied to the bag, so nothing here is a second copy of a
        # reading; see `utils/blood`.
        blood_panel=blood_rows,
        # Counted once, in the util the board reads too — so the badge on this
        # screen and the ward's safety board can never say different numbers.
        blood_unwatched=blood.unwatched(row),
        blood_products=BLOOD_PRODUCTS,
        blood_urgencies=BLOOD_URGENCIES,
        ward_people=_ward_people(),
        # التقييد والإنعاش على نفس الشاشة: الفعل بيتعمل جنب الطفل،
        # واللوحة بتقول اللي غلط. والقرايتين من نفس الدوال اللي اللوحة
        # بتقراها، فمستحيل الشاشتين يقولوا حاجتين.
        # **خريطة القساطر** — `CSS.03` (د) بيطلبها كجزء من التسليم،
        # وبتتحسب من الصفوف كل مرة بدل ما تتخزّن وتفرق عنها.
        # التغذية على شاشة الإقامة: اللي بيكتب الأكل واقف جنب الطفل،
        # والقايمة بتاعة العيادة مش بتاعتنا.
        diet_now=_food.current_diet(row.patient_id),
        diet_list=_food.diet_list(),
        food_assessment=_food.latest_assessment(row.patient_id),
        line_map=_lines.map_for(row.patient_id),
        line_kinds=LINE_KINDS,
        line_high_risk=LINE_HIGH_RISK,
        tied_now=[r for r in _tied.for_patient(row.patient_id)
                  if r.ended_at is None],
        restraint_kinds=RESTRAINT_KINDS,
        arrests=_cpr.for_patient(row.patient_id, limit=10),
        resus_outcomes=RESUS_OUTCOMES,
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


# ---------------------------------------------------------------- blood -----
# GAHAR ICD.20 (requesting) and ICD.21 (transfusing). Four addresses, because
# the four things happen at four different moments and by four different
# people: a doctor orders it, the blood bank confirms the sample, two nurses
# hang the bag, and whoever is at the bedside watches it. One form holding all
# of that would have asked the person who ordered the blood to know what the
# bag's number would be.
#
# **No capability beyond the ward's**, like the round and the risk assessment:
# the person watching a transfusion at three in the morning is nursing, and a
# capability here would have put the record behind the ward's door twice.
@beds_bp.route("/admission/<int:admission_id>/blood", methods=["POST"])
@module_required(MODULE)
def blood_request(admission_id):
    """Order blood for this child — ICD.20."""
    row = Admission.query.get_or_404(admission_id)
    try:
        blood.request(
            row.patient, (request.form.get("product") or "").strip(),
            request.form.get("indication"),
            user=current_user, admission=row,
            units=request.form.get("units", type=int),
            urgency=(request.form.get("urgency") or "").strip(),
            product_note=request.form.get("product_note"),
            family_told=_yes_no(request.form.get("family_told")),
            at=_happened_at())
    except ValueError:
        db.session.rollback()
        # Said out loud. The indication is the one thing ICD.20 evidence 3 is
        # about, and a request that silently saved nothing would put the gap
        # in the blood bank instead of on this screen.
        flash(t("blood.not_requested"), "error")
        return redirect(url_for("beds.admission", admission_id=row.id))
    db.session.commit()
    flash(t("blood.requested"), "success")
    return redirect(url_for("beds.admission", admission_id=row.id))


@beds_bp.route("/blood/<int:request_id>/sample", methods=["POST"])
@module_required(MODULE)
def blood_sample(request_id):
    """ICD.20 (ز) — the label on the sample matches the form."""
    from app.models import BloodRequest

    row = BloodRequest.query.get_or_404(request_id)
    blood.sample_checked(row, user=current_user)
    db.session.commit()
    flash(t("blood.sample_ok"), "success")
    return redirect(_blood_back(row))


@beds_bp.route("/blood/<int:request_id>/hang", methods=["POST"])
@module_required(MODULE)
def blood_hang(request_id):
    """Start one bag — ICD.21."""
    from app.models import BloodRequest, User

    row = BloodRequest.query.get_or_404(request_id)
    # The second name is chosen from the ward's own people and checked against
    # the user table, because the whole of ICD.21's intent is that two people
    # looked — and a name typed into a box is not a person who looked.
    second = User.query.get(request.form.get("checked_by", type=int) or 0)
    try:
        blood.hang(row, unit_code=request.form.get("unit_code"),
                   given_by=current_user, checked_by=second,
                   bag_checked=_yes_no(request.form.get("bag_checked")),
                   bag_note=request.form.get("bag_note"),
                   rate=request.form.get("rate"), at=_happened_at())
    except ValueError:
        db.session.rollback()
        flash(t("blood.not_hung"), "error")
        return redirect(_blood_back(row))
    db.session.commit()
    flash(t("blood.hung"), "success")
    return redirect(_blood_back(row))


@beds_bp.route("/blood/bag/<int:bag_id>/watch", methods=["POST"])
@module_required(MODULE)
def blood_watch(bag_id):
    """ICD.21 evidence 4 — one set of readings taken to watch the bag."""
    from app.models import Transfusion

    bag = Transfusion.query.get_or_404(bag_id)
    try:
        blood.watch(bag, user=current_user, at=_happened_at(),
                    temperature_c=request.form.get("temperature_c", type=float),
                    pulse_bpm=request.form.get("pulse_bpm", type=int),
                    resp_rate=request.form.get("resp_rate", type=int),
                    spo2=request.form.get("spo2", type=int),
                    bp_systolic=request.form.get("bp_systolic", type=int),
                    bp_diastolic=request.form.get("bp_diastolic", type=int),
                    note=(request.form.get("note") or "").strip() or None)
    except ValueError:
        db.session.rollback()
        # An empty reading would clear «محدّش بيشوفه» without anybody having
        # gone near the child — the same refusal the blank round is built on.
        flash(t("blood.needs_a_reading"), "error")
        return redirect(_blood_back(bag.request))
    db.session.commit()
    flash(t("blood.watched"), "success")
    return redirect(_blood_back(bag.request))


@beds_bp.route("/blood/bag/<int:bag_id>/finish", methods=["POST"])
@module_required(MODULE)
def blood_finish(bag_id):
    """The bag is down — and whether anything happened, or not."""
    from app.models import Transfusion

    bag = Transfusion.query.get_or_404(bag_id)
    blood.finish(bag, reaction=_yes_no(request.form.get("reaction")),
                 reaction_note=request.form.get("reaction_note"),
                 stopped_early=bool(request.form.get("stopped_early")),
                 at=_happened_at())
    db.session.commit()
    flash(t("blood.finished"), "success")
    return redirect(_blood_back(bag.request))


@beds_bp.route("/blood/<int:request_id>/cancel", methods=["POST"])
@module_required(MODULE)
def blood_cancel(request_id):
    """The blood is not going to be given."""
    from app.models import BloodRequest

    row = BloodRequest.query.get_or_404(request_id)
    if blood.cancel(row, reason=request.form.get("cancel_reason")) is None:
        # A request a bag was already hung against cannot be un-asked.
        flash(t("blood.cannot_cancel"), "error")
        return redirect(_blood_back(row))
    db.session.commit()
    flash(t("blood.cancelled"), "info")
    return redirect(_blood_back(row))


@beds_bp.route("/watch")
@module_required(MODULE)
def watch():
    """What the ward has to look at **right now**, across every open stay.

    **This screen is the door three readers did not have.** `blood.unwatched`,
    `blood.emergencies_waiting` and `risks.unassessed` were written, tested and
    reachable from nothing — the exact failure this project has now found on
    itself seven times, and the one the file screen was rebuilt for.

    Three questions, and each is a *now* question, which is why they are on one
    board and not three: a bag going into a child with nothing written down, an
    emergency unit nobody has issued, and a stay whose required risks nobody
    has looked at. A ward manager asks all three standing in the same doorway.

    Read-only, and nothing here sends or books. Every row is a link to the stay
    where the thing is actually done.
    """
    stays = (Admission.query.filter(Admission.discharged_at.is_(None))
             .order_by(Admission.admitted_at).all())
    watching = []
    for stay in stays:
        bags = blood.unwatched(stay)
        gaps = risks.unassessed(risks.panel(stay))
        if bags or gaps:
            watching.append({"stay": stay, "bags": bags, "risks": gaps})
    # **والخامسة والسادسة على نفس الباب.** الدوكسترينج فوق بيقول إن مدير
    # القسم بيسأل التلاتة وهو واقف في نفس الباب — والاتنين دول من نفس
    # الشكل بالظبط: حاجة **دلوقتي**، ليها مكان واحد بتتعمل فيه، ومحدّش
    # عنده شاشة بتقولها.
    #
    # وأمر تقييد خلص والطفل لسه مربوط هو أخطرهم: مش ورقة ناقصة، ده تقييد
    # بقى من غير إذن، وبيعدّي لأن مفيش حاجة بتتغيّر على أي شاشة لما ساعة
    # تعدّي.
    from app.utils import restraint as tied
    from app.utils import resuscitation as cpr
    from app.utils import verbal_order as vo
    from app.utils import refusal as no
    from app.utils import lines as _lines
    from app.utils import opinions as op
    from app.utils import nutrition as food
    from app.utils import responsibility as _who
    from app.utils import pain as _pain
    from app.utils import nursing as _nursing
    watch_minutes = tied.interval_minutes()
    # بتتحسب هنا بأسماء كاملة بدل ما تتكسر جوّه الاستدعاء — سطر
    # زي `food.\n    assessed_but...` بيشتغل، بس بيخفي الندا عن أي
    # حاجة بتدوّر عليه، وده اللي الحارس مسكه.
    _food_gaps = food.assessed_but_nothing_ordered(limit=20)
    _food_unassessed = food.ordered_without_assessment(limit=20)
    _food_family = food.unanswered_family_food(limit=20)
    return render_template("beds/watch.html", rows=watching,
                           emergencies=blood.emergencies_waiting(),
                           open_stays=len(stays),
                           restraints_expired=tied.expired(),
                           restraints_unlimited=tied.no_limit_set(),
                           restraints_unwatched=tied.unwatched(),
                           restraint_minutes=watch_minutes,
                           resus_running=cpr.running(),
                           resus_unanswered=cpr.never_answered(limit=20),
                           # وسابعة من نفس الشكل: أمر شفهي لسه ناقصه
                           # قراية بصوت عالي أو تأكيد من اللي قاله.
                           # ودي مش ورقة ناقصة كمان — ده أمر علاج
                           # شغّال محدّش راجعه.
                           verbal_open=vo.open_orders(limit=20),
                           verbal_late=vo.late(limit=20),
                           verbal_gaps=vo.missing,
                           # وتامنة: خرجوا ضد النصيحة ومفيش لهم
                           # استمارة رفض. **ودي القراية اللي مكانش ينفع
                           # تتسأل قبل ما الاستمارة تبقى موجودة** —
                           # البرنامج كان عارف إن الطفل مشي، وما كانش
                           # عنده الطرف التاني من المقارنة.
                           refusals_missing=no.undocumented(limit=20),
                           refusals_short=no.incomplete(limit=20),
                           # ودي حقيقة تانية غير «ناقصها بند»: المحتوى
                           # حاجة والدليل إن اللي رفض شافها حاجة تانية.
                           # ورقة مكتوبة صح ومحدّش وقّع عليها دعوى مش
                           # مستند — نفس قاعدة `Consent` بالظبط.
                           refusals_unsigned=no.unsigned(limit=20),
                           # وتاسعة: قسطرة عالية الخطورة من غير ملصق.
                           # النية بتقول العاقبة بالنص — المادة الغلط من
                           # **الطريق الغلط** — والملصق هو اللي بيمنعها.
                           lines_unlabelled=_lines.unlabelled_high_risk(
                               limit=20),
                           lines_left_in=_lines.still_in_after_discharge(
                               limit=20),
                           lines_unnamed=_lines.unnamed_other(limit=20),
                           # وعاشرة: طلب استشارة عدّى مهلة العيادة ولسه
                           # من غير رد. نية `ACT.10` بتسمّي «الرد
                           # المتأخّر» كشكل فشل بالنص.
                           # **واللي مستنّي بيبان حتى لو المهلة
                           # مش مكتوبة.** `overdue` ساكتة من غير رقم
                           # العيادة — وطلب استشارة محدّش رد عليه
                           # مايبقاش مخفي علشان المستشفى ما كتبتش
                           # سياستها لسه.
                           opinions_waiting=op.waiting(limit=20),
                           opinions_overdue=op.overdue(limit=20),
                           opinions_short=op.incomplete(limit=20),
                           # وحداشر: تقييم تغذية قال «محتاج نظام خاص»
                           # ومحدّش كتب أكل. النية بتقول إن التقييم
                           # **لازم** يأدّي لحاجة — والصف ده بيبان
                           # مكتمل في أي جرد، علشان كده محتاج قراية.
                           food_nothing_ordered=_food_gaps,
                           food_no_assessment=_food_unassessed,
                           food_family_unanswered=_food_family,
                           # واتناشر: **مين مسؤول** — `ACT.07`. إقامة
                           # مفتوحة ومحدّش مسؤول عنها، وطبيب سلّم
                           # ومحدّش استلم. والتانية هي الخطر: الصف
                           # بيبان إنه اتسلّم، والأول ماشي وهو فاكر
                           # إنها مشيت.
                           mrp_missing=_who.without_mrp(limit=20),
                           mrp_limbo=_who.in_limbo(limit=20),
                           # وتلتاشر: **الألم** — `ICD.09`. اتفرز وطلع
                           # فيه ألم ومحدّش قيّمه؛ وإقامة محدّش فرزها
                           # خالص؛ وتقييم محدّش رجع له. والأولانية هي
                           # اللي بتبان مكتملة: أداة ورقم ووقت واسم.
                           pain_unassessed=_pain.positive_without_assessment(
                               limit=20),
                           pain_unscreened=_pain.unscreened_stays(limit=20),
                           pain_awaiting=_pain.awaiting_reassessment(limit=20),
                           pain_overdue=_pain.overdue_reassessment(limit=20),
                           pain_hours=_pain.reassess_hours(),
                           pain_gaps=_pain.missing,
                           # وأربعتاشر: **تقييم التمريض** — `ICD.07`.
                           # إقامة محدّش عمل لها تقييم أول، واللي عدّت
                           # عليهم مهلة العيادة، واللي عدّى وقت إعادتهم.
                           # والتلاتة بتشتغل من غير رقم للأولى وبرقم
                           # للتانية والتالتة — نفس شكل الألم.
                           nursing_missing=_nursing.without_initial(limit=20),
                           nursing_late=_nursing.late_initial(limit=20),
                           nursing_overdue=_nursing.overdue_reassessment(
                               limit=20),
                           nursing_hours=_nursing.initial_hours())


def _ward_people():
    """Who can be named as the second pair of eyes on a bag.

    ICD.21's intent is about *misidentification*, so the second checker is
    picked from the people this clinic actually employs rather than typed —
    a name in a free box is not a person who looked.
    """
    from app.models import User

    return (User.query.filter(User.is_active.is_(True))
            .order_by(User.full_name).all())


# ------------------------------------------------- التغذية `ICD.13` ----
@beds_bp.route("/stay/<int:admission_id>/nutrition", methods=["POST"])
@module_required(MODULE)
def nutrition_assess(admission_id):
    """تقييم تغذية — دليل ٣ و٥."""
    from app.utils import nutrition as food

    stay = db.get_or_404(Admission, admission_id)
    try:
        food.assess(stay.patient, user=current_user, admission=stay,
                    findings=request.form.get("findings"),
                    plan=request.form.get("plan"),
                    needs=_tri(request.form.get("needs")))
    except ValueError:
        db.session.rollback()
        flash(t("food.not_saved"), "error")
        return _stay_back(admission_id, "#food")
    db.session.commit()
    flash(t("food.assessed"), "success")
    return _stay_back(admission_id, "#food")


@beds_bp.route("/stay/<int:admission_id>/diet", methods=["POST"])
@module_required(MODULE)
def diet_order(admission_id):
    """أمر أكل — (د)(٣).

    والنظام لازم يكون من **قايمة العيادة**؛ المسار بيرفض غير كده علشان
    ما يبقاش في الملف صف بيشاور على حاجة محدّش عرّفها.
    """
    from app.utils import nutrition as food

    stay = db.get_or_404(Admission, admission_id)
    try:
        food.order(stay.patient, request.form.get("diet_key"),
                   user=current_user, admission=stay,
                   detail=request.form.get("detail"),
                   meal_times=request.form.get("meal_times"),
                   family_food=_tri(request.form.get("family_food")),
                   family_note=request.form.get("family_note"))
    except ValueError:
        db.session.rollback()
        flash(t("food.not_saved"), "error")
        return _stay_back(admission_id, "#food")
    db.session.commit()
    flash(t("food.ordered"), "success")
    return _stay_back(admission_id, "#food")


@beds_bp.route("/diet/<int:order_id>/stop", methods=["POST"])
@module_required(MODULE)
def diet_stop(order_id):
    """الأمر وقف — **لحظة مش مسح**."""
    from app.models import DietOrder
    from app.utils import nutrition as food

    row = db.get_or_404(DietOrder, order_id)
    food.stop(row, user=current_user)
    db.session.commit()
    flash(t("food.stopped"), "success")
    return _stay_back(row.admission_id, "#food") if row.admission_id else \
        redirect(url_for("patients.view", patient_id=row.patient_id) + "#food")


def _tri(raw):
    """ثلاثية من الشاشة: «» محدّش قال · ``yes`` · ``no``."""
    value = (raw or "").strip()
    if value == "yes":
        return True
    if value == "no":
        return False
    return None


# ------------------------------------------ القساطر والأنابيب `CSS.03` ----
@beds_bp.route("/stay/<int:admission_id>/line", methods=["POST"])
@module_required(MODULE)
def line_insert(admission_id):
    """قسطرة أو أنبوبة اتركّبت.

    **ومفيش صلاحية زيادة عن القسم**، لأن اللي بيركّب كانيولا أو أنبوبة
    معدة تمريض في أغلب الوقت — ونفس اللي بيركّبها هو اللي المفروض
    يسجّلها، وإلا بتتسجّل بعدين من الذاكرة أو ما بتتسجّلش.
    """
    from app.utils import lines as _lines

    stay = db.get_or_404(Admission, admission_id)
    try:
        _lines.insert(stay.patient, (request.form.get("kind") or "").strip(),
                      user=current_user, admission=stay,
                      site=request.form.get("site"),
                      size=request.form.get("size"),
                      label=request.form.get("label"),
                      kind_note=request.form.get("kind_note"))
    except ValueError:
        db.session.rollback()
        flash(t("lines.not_saved"), "error")
        return _stay_back(admission_id, "#lines")
    db.session.commit()
    flash(t("lines.inserted"), "success")
    return _stay_back(admission_id, "#lines")


@beds_bp.route("/line/<int:line_id>/label", methods=["POST"])
@module_required(MODULE)
def line_label(line_id):
    """(ب) الملصق — والقايمة اللي بتلاقي الناقص هي اللي بتقفله."""
    from app.models import Line
    from app.utils import lines as _lines

    row = db.get_or_404(Line, line_id)
    _lines.label(row, request.form.get("label"))
    db.session.commit()
    flash(t("lines.labelled"), "success")
    return _stay_back(row.admission_id, "#lines") if row.admission_id else \
        redirect(url_for("patients.view", patient_id=row.patient_id) + "#lines")


@beds_bp.route("/line/<int:line_id>/remove", methods=["POST"])
@module_required(MODULE)
def line_remove(line_id):
    """اتشالت — **لحظة مش مسح**."""
    from app.models import Line
    from app.utils import lines as _lines

    row = db.get_or_404(Line, line_id)
    _lines.remove(row, user=current_user,
                  reason=request.form.get("reason"))
    db.session.commit()
    flash(t("lines.removed"), "success")
    return _stay_back(row.admission_id, "#lines") if row.admission_id else \
        redirect(url_for("patients.view", patient_id=row.patient_id) + "#lines")


# ------------------------------------------------- التقييد والإنعاش ----
def _stay_back(admission_id, anchor):
    """رجوع لشاشة الإقامة.

    **اسم المسار `beds.admission` مش `beds.stay`.** الستّ مسارات اللي
    تحت كانوا كلهم بيرجّعوا على اسم مش موجود، والاختبارات كانت بتعدّي
    لأنها بتنده الدوال على طول — أول ضغطة من شاشة كانت هتقع.
    """
    return redirect(url_for("beds.admission", admission_id=admission_id)
                    + anchor)


@beds_bp.route("/stay/<int:admission_id>/restraint", methods=["POST"])
@module_required(MODULE)
@capability_required("patient_medical")
def restraint_start(admission_id):
    """أمر تقييد — `CSS.12` (أ) و(ب).

    **الصلاحية هنا مش زي التثقيف.** التثقيف متعدّد التخصصات بالنص، وده
    أمر طبيب بالنص كمان — والفرق ده مكتوب في المعيارين نفسهم.
    """
    from app.utils import restraint as tied

    stay = db.get_or_404(Admission, admission_id)
    try:
        tied.start(stay.patient, (request.form.get("kind") or "").strip(),
                   request.form.get("reason"), current_user,
                   method=request.form.get("method"),
                   alternatives=request.form.get("alternatives"),
                   valid_until=_a_moment("valid_until"),
                   admission=stay)
    except ValueError:
        db.session.rollback()
        flash(t("restraint.needs_reason_and_order"), "error")
        return _stay_back(admission_id, "#restraint")
    db.session.commit()
    flash(t("restraint.started"), "success")
    return _stay_back(admission_id, "#restraint")


@beds_bp.route("/restraint/<int:restraint_id>/renew", methods=["POST"])
@module_required(MODULE)
@capability_required("patient_medical")
def restraint_renew(restraint_id):
    """تجديد — (ز). صف جديد، والقديم بيتقفل."""
    from app.models import Restraint
    from app.utils import restraint as tied

    row = db.get_or_404(Restraint, restraint_id)
    tied.renew(row, current_user, valid_until=_a_moment("valid_until"))
    db.session.commit()
    flash(t("restraint.renewed"), "success")
    return _stay_back(row.admission_id, "#restraint")


@beds_bp.route("/restraint/<int:restraint_id>/end", methods=["POST"])
@module_required(MODULE)
@capability_required("patient_medical")
def restraint_end(restraint_id):
    """فكّ التقييد — (ط)."""
    from app.models import Restraint
    from app.utils import restraint as tied

    row = db.get_or_404(Restraint, restraint_id)
    tied.end(row, current_user, reason=request.form.get("reason"))
    db.session.commit()
    flash(t("restraint.ended"), "success")
    return _stay_back(row.admission_id, "#restraint")


@beds_bp.route("/stay/<int:admission_id>/arrest", methods=["POST"])
@module_required(MODULE)
def resus_start(admission_id):
    """توقّف اتعرف — `CSS.05`.

    **ومفيش صلاحية زيادة عن القسم.** اللي بيشوف الطفل واقف هو اللي بيفتح
    السجل، ومش هيبقى دايماً طبيب — ودليل ٣ بيقول إن حامل الإنعاش الأساسي
    بيبدأ **فوراً**. شاشة بترفض بتحوّل الثواني دي لورق يتكتب بعدين.
    """
    from app.utils import resuscitation as cpr

    stay = db.get_or_404(Admission, admission_id)
    cpr.start(stay.patient, user=current_user,
              place=request.form.get("place"), admission=stay)
    db.session.commit()
    flash(t("resus.started"), "success")
    return _stay_back(admission_id, "#arrest")


@beds_bp.route("/arrest/<int:resus_id>/mark", methods=["POST"])
@module_required(MODULE)
def resus_mark(resus_id):
    """الاستغاثة اتبعتت، أو الفريق وصل — (هـ) و(و).

    زرار واحد لكل لحظة، مش فورم بتتملّى بعدين: الأوقات دي هي بالظبط اللي
    الذاكرة بتضيّعها، والمعيار بيقيس عليها.
    """
    from app.models import Resuscitation
    from app.utils import resuscitation as cpr

    row = db.get_or_404(Resuscitation, resus_id)
    what = (request.form.get("what") or "").strip()
    if what == "called":
        cpr.called(row)
    elif what == "team":
        cpr.team_arrived(row, lead=current_user)
    else:
        flash(t("resus.not_saved"), "error")
        return _stay_back(row.admission_id, "#arrest")
    db.session.commit()
    flash(t("resus.marked"), "success")
    return _stay_back(row.admission_id, "#arrest")


@beds_bp.route("/arrest/<int:resus_id>/finish", methods=["POST"])
@module_required(MODULE)
def resus_finish(resus_id):
    """خلص — النتيجة واللي اتعمل (ح)."""
    from app.models import Resuscitation
    from app.utils import resuscitation as cpr

    row = db.get_or_404(Resuscitation, resus_id)
    try:
        cpr.finish(row, (request.form.get("outcome") or "").strip(),
                   management=request.form.get("management"),
                   user=current_user)
    except ValueError:
        db.session.rollback()
        flash(t("resus.not_saved"), "error")
        return _stay_back(row.admission_id, "#arrest")
    db.session.commit()
    flash(t("resus.finished"), "success")
    return _stay_back(row.admission_id, "#arrest")


def _a_moment(field):
    """``datetime-local`` من الفورم، أو ``None``.

    و``None`` هنا معناها **محدّش حطّ مدة** — وهي بنفسها ملاحظة بتتعدّ على
    الشاشة، مش قيمة فاضية بتتجاهل.
    """
    from datetime import datetime

    raw = (request.form.get(field) or "").strip()
    if not raw:
        return None
    for shape in ("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, shape)
        except ValueError:
            continue
    return None


def _blood_back(request_row):
    """Back to the stay the blood belongs to, or to the board without one."""
    if request_row is not None and request_row.admission_id:
        return url_for("beds.admission", admission_id=request_row.admission_id)
    return url_for("beds.index")


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


# ------------------------------------------ المسؤولية `ACT.07` ----------
def _doctors():
    """مين ينفع يبقى مسؤول.

    من اللي العيادة مشغّلاهم فعلاً، مش خانة نص: `ACT.07` بيطلب إن السجل
    **يحدّد** الطبيب، واسم مكتوب بإيد مش تحديد — ولا ينفع تسأله بعدين
    عن الخطوات المعلّقة.
    """
    from app.models import User

    return (User.query
            .filter(User.is_active.is_(True),
                    db.or_(User.role == "doctor", User.is_practitioner.is_(True)))
            .order_by(User.full_name).all())


@beds_bp.route("/stay/<int:admission_id>/responsible", methods=["POST"])
@module_required(MODULE)
def assign_responsible(admission_id):
    """دليل ٣ — إقامة محدّش مسؤول عنها بتلاقي مسؤول.

    **واللي بيقرا الفراغ هو اللي بيقفله**: الفورم دي جوّه نفس الصف اللي
    بيقول «مفيش مسؤول»، مش بادچ بيقول روح شوف.
    """
    from app.models import User
    from app.utils import responsibility as who

    stay = db.get_or_404(Admission, admission_id)
    doctor = db.session.get(User, request.form.get("doctor_id", type=int))
    try:
        who.assign(stay, doctor, user=current_user)
    except ValueError:
        flash(t("mrp.not_assigned"), "error")
        return redirect(request.referrer or url_for("beds.admission",
                                                    admission_id=stay.id))
    db.session.commit()
    flash(t("mrp.assigned"), "success")
    return redirect(request.referrer or url_for("beds.admission",
                                                admission_id=stay.id))


@beds_bp.route("/stay/<int:admission_id>/handover", methods=["POST"])
@module_required(MODULE)
def hand_over_responsible(admission_id):
    """(ج) التسليم — **والخطوات المعلّقة معاه**."""
    from app.models import User
    from app.utils import responsibility as who

    stay = db.get_or_404(Admission, admission_id)
    doctor = db.session.get(User, request.form.get("doctor_id", type=int))
    try:
        who.hand_over(stay, doctor, pending=request.form.get("pending"),
                      user=current_user)
    except ValueError:
        flash(t("mrp.not_handed"), "error")
        return redirect(request.referrer or url_for("beds.admission",
                                                    admission_id=stay.id))
    db.session.commit()
    flash(t("mrp.handed"), "warning")
    return redirect(request.referrer or url_for("beds.admission",
                                                admission_id=stay.id))


@beds_bp.route("/stay/<int:admission_id>/accept", methods=["POST"])
@module_required(MODULE)
def accept_responsible(admission_id):
    """(د) الطرف التاني بيستلم — **واللي سلّم ما يقدرش يوقّع لنفسه**."""
    from app.models import User
    from app.utils import responsibility as who

    stay = db.get_or_404(Admission, admission_id)
    doctor = (db.session.get(User, request.form.get("doctor_id", type=int))
              or current_user)
    try:
        who.accept(stay, doctor, user=current_user)
    except ValueError:
        flash(t("mrp.not_accepted"), "error")
        return redirect(request.referrer or url_for("beds.admission",
                                                    admission_id=stay.id))
    db.session.commit()
    flash(t("mrp.accepted"), "success")
    return redirect(request.referrer or url_for("beds.admission",
                                                admission_id=stay.id))


# ------------------------------------------------- الألم `ICD.09` -------
@beds_bp.route("/stay/<int:admission_id>/pain-screen", methods=["POST"])
@module_required(MODULE)
def pain_screen(admission_id):
    """دليل ٣ — الفرز. **والإجابة بتتكتب صراحةً، مش بتتستنتج من الرقم.**"""
    from app.utils import pain

    stay = db.get_or_404(Admission, admission_id)
    answer = (request.form.get("has_pain") or "").strip()
    try:
        pain.screen(stay.patient, answer == "yes",
                    tool_key=request.form.get("tool_key"),
                    score=request.form.get("score", type=int),
                    user=current_user, admission=stay)
    except ValueError:
        flash(t("pain.not_screened"), "error")
        return redirect(request.referrer or url_for("beds.admission",
                                                    admission_id=stay.id))
    db.session.commit()
    flash(t("pain.screened"), "success")
    return redirect(request.referrer or url_for("beds.admission",
                                                admission_id=stay.id))


@beds_bp.route("/pain/<int:screen_id>/assess", methods=["POST"])
@module_required(MODULE)
def pain_assess(screen_id):
    """(ب) و(د) — التقييم الكامل والخطة، من نفس الصف اللي بيقول ناقص."""
    from app.models import PainScreen
    from app.utils import pain

    row = db.get_or_404(PainScreen, screen_id)
    try:
        pain.assess(row, user=current_user,
                    intensity=request.form.get("intensity"),
                    character=request.form.get("character"),
                    location=request.form.get("location"),
                    frequency=request.form.get("frequency"),
                    duration=request.form.get("duration"),
                    plan=request.form.get("plan"))
    except ValueError:
        flash(t("pain.not_assessed"), "error")
        return redirect(request.referrer or url_for("beds.admission",
                                                    admission_id=row.admission_id))
    db.session.commit()
    flash(t("pain.assessed"), "success")
    return redirect(request.referrer or url_for("beds.admission",
                                                admission_id=row.admission_id))


@beds_bp.route("/pain-assessment/<int:assessment_id>", methods=["POST"])
@module_required(MODULE)
def pain_describe(assessment_id):
    """البنود اللي فضلت من الخمسة، والخطة."""
    from app.models import PainAssessment
    from app.utils import pain

    row = db.get_or_404(PainAssessment, assessment_id)
    pain.describe(row,
                  intensity=request.form.get("intensity"),
                  character=request.form.get("character"),
                  location=request.form.get("location"),
                  frequency=request.form.get("frequency"),
                  duration=request.form.get("duration"),
                  plan=request.form.get("plan"))
    db.session.commit()
    flash(t("common.saved"), "success")
    return redirect(request.referrer or url_for("beds.watch"))


# --------------------------------------- تقييم التمريض `ICD.07` ---------
@beds_bp.route("/stay/<int:admission_id>/nursing", methods=["POST"])
@module_required(MODULE)
def nursing_record(admission_id):
    """دليل ٣ و٤ — التقييم الأول أو إعادته."""
    from app.utils import nursing

    stay = db.get_or_404(Admission, admission_id)
    fields = {name: request.form.get(name)
              for name in ("airway", "breathing", "circulation", "disability",
                           "skin", "hydration", "outputs", "focus")}
    try:
        nursing.record(stay, kind=(request.form.get("kind") or "initial"),
                       user=current_user, **fields)
    except ValueError:
        flash(t("nursing.not_saved"), "error")
        return redirect(request.referrer or url_for("beds.admission",
                                                    admission_id=stay.id))
    db.session.commit()
    flash(t("nursing.saved"), "success")
    return redirect(request.referrer or url_for("beds.admission",
                                                admission_id=stay.id))


@beds_bp.route("/nursing/<int:assessment_id>", methods=["POST"])
@module_required(MODULE)
def nursing_describe(assessment_id):
    """البنود اللي فضلت — من نفس الصف اللي بيقول ناقص."""
    from app.models import NursingAssessment
    from app.utils import nursing

    row = db.get_or_404(NursingAssessment, assessment_id)
    nursing.describe(row, **{
        name: request.form.get(name)
        for name in ("airway", "breathing", "circulation", "disability",
                     "skin", "hydration", "outputs", "focus")})
    db.session.commit()
    flash(t("common.saved"), "success")
    return redirect(request.referrer or url_for("beds.admission",
                                                admission_id=row.admission_id))
