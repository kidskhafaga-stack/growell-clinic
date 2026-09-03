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

from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user
from werkzeug.routing import BuildError

from app.blueprints.beds import beds_bp
from app.extensions import db
from app.i18n import t
from app.models import Patient, Visit
from app.models.admission import OUTCOMES, Admission
from app.models.place import BED_KINDS, SPACE_KINDS, UNIT_KINDS, Bed, Space, Unit
from app.models.round_note import ROUND_TRENDS
from app.utils import beds as ward
from app.utils import rounds as ward_round
from app.utils.clock import to_utc
from app.utils.decorators import module_required

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
    return render_template("beds/setup.html",
                           units=ward.board(),
                           unit_kinds=UNIT_KINDS, space_kinds=SPACE_KINDS,
                           bed_kinds=BED_KINDS,
                           taken=ward.occupied_bed_ids())


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
    return render_template("beds/admission.html", admission=row,
                           free=ward.free_beds(), outcomes=OUTCOMES,
                           trends=ROUND_TRENDS,
                           rounds=sorted(row.round_notes,
                                         key=lambda n: (n.at, n.id),
                                         reverse=True))


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


@beds_bp.route("/admission/<int:admission_id>/discharge", methods=["POST"])
@module_required(MODULE)
def discharge(admission_id):
    """End the stay. The bed is freed by the stay closing, not by a flag."""
    row = Admission.query.get_or_404(admission_id)
    ward.discharge(row, (request.form.get("outcome") or "").strip(),
                   user=current_user, note=request.form.get("note"))
    db.session.commit()
    flash(t("beds.discharged"), "success")
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
