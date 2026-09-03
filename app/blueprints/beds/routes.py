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
from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user

from app.blueprints.beds import beds_bp
from app.extensions import db
from app.i18n import t
from app.models import Patient, Visit
from app.models.admission import OUTCOMES, Admission
from app.models.place import BED_KINDS, SPACE_KINDS, UNIT_KINDS, Bed, Space, Unit
from app.utils import beds as ward
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
                           free=ward.free_beds(), outcomes=OUTCOMES)


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
