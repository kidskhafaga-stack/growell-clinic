"""The safety program's screens — rounds (EFS.02, EFS.07, EFS.09, OGM.14),
hazardous materials, waste and pests (EFS.06, EFS.07 d), construction
(EFS.08), being ready (EFS.09 g, EFS.13) and the plans register (EFS.01).
The logic is in ``utils/safety_program`` and ``utils/preparedness``; the door
is the building's (``routes._door``)."""
from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user

from app.blueprints.facility import facility_bp
from app.blueprints.facility.routes import _door, _staff
from app.extensions import db
from app.i18n import t
from app.models.facility_safety import SHIFTS, TRAINING_TOPICS, FireDrill
from app.models.preparedness import HAZARD_KINDS, PLAN_KINDS, CallTreeEntry, EmergencyHazard, \
    ExternalInspection, HospitalPlan
from app.models.safety_program import (HAZARD_TYPES, PCRA_ITEMS, PROJECT_STATES, RISK_LEVELS,
                                       ROUND_FOCUS, WASTE_CATEGORIES, ConstructionProject,
                                       HazardousMaterial, RoundFinding)
from app.utils import facility_safety as fs
from app.utils import preparedness as prep
from app.utils import safety_program as sp
from app.utils.clock import local_today


def _go(fn, where):
    try:
        fn()
    except fs.FacilityError as err:
        db.session.rollback()
        flash(t(f"facility.err_{err}"), "error")
        return redirect(where)
    db.session.commit()
    flash(t("facility.saved"), "success")
    return redirect(where)


def _upload(name):
    """A posted file kept as a document, or ``None``; a file of a type that
    is not allowed is a refusal, not a silent drop."""
    from app.utils.uploads import save_document

    file = request.files.get(name)
    if not file or not file.filename:
        return None
    stored = save_document(file)
    if stored is None:
        raise fs.FacilityError("bad_file")
    return stored


# ================================================================== rounds ==
@facility_bp.route("/rounds")
@_door
def rounds():
    year = request.args.get("year", type=int) or local_today().year
    return render_template("facility/rounds.html", data=sp.rounds_board(year, local_today()),
                           staff=_staff(), focuses=ROUND_FOCUS, risks=RISK_LEVELS,
                           today=local_today(), quarter=sp.quarter_of(local_today()))


@facility_bp.route("/rounds", methods=["POST"])
@_door
def round_new():
    return _go(lambda: sp.save_round(current_user, request.form), url_for("facility.rounds"))


@facility_bp.route("/finding/<int:finding_id>/close", methods=["POST"])
@_door
def finding_close(finding_id):
    row = db.get_or_404(RoundFinding, finding_id)
    return _go(lambda: sp.close_finding(row, current_user, request.form),
               url_for("facility.rounds") + "#open")


@facility_bp.route("/rounds/quarter")
@_door
def round_quarter():
    """EFS.02 ev. 5 — the quarter's rounds as the governing body reads them."""
    quarter = (request.args.get("q") or sp.quarter_of(local_today())).strip()
    if len(quarter) != 7 or quarter[4:6] != "-Q" or quarter[6] not in "1234" or not quarter[:4].isdigit():
        abort(404)
    return render_template("facility/round_quarter.html", data=sp.quarter_summary(quarter))


# ====================================================== hazardous materials ==
@facility_bp.route("/hazmat")
@_door
def hazmat():
    year = request.args.get("year", type=int) or local_today().year
    return render_template("facility/hazmat.html", data=sp.materials_board(),
                           waste=sp.waste_by_month(year), year=year, pest=sp.pest_board(local_today()),
                           hazards=HAZARD_TYPES, categories=WASTE_CATEGORIES, today=local_today())


@facility_bp.route("/hazmat", methods=["POST"])
@_door
def hazmat_new():
    return _go(lambda: sp.save_material(request.form, sds_file=_upload("sds")),
               url_for("facility.hazmat") + "#materials")


@facility_bp.route("/hazmat/<int:material_id>", methods=["POST"])
@_door
def hazmat_edit(material_id):
    row = db.get_or_404(HazardousMaterial, material_id)
    return _go(lambda: sp.save_material(request.form, row=row, sds_file=_upload("sds")),
               url_for("facility.hazmat") + f"#m{row.id}")


@facility_bp.route("/hazmat/<int:material_id>/retire", methods=["POST"])
@_door
def hazmat_retire(material_id):
    row = db.get_or_404(HazardousMaterial, material_id)
    return _go(lambda: sp.retire_material(row), url_for("facility.hazmat") + "#materials")


@facility_bp.route("/waste", methods=["POST"])
@_door
def waste():
    return _go(lambda: sp.hand_over_waste(current_user, request.form), url_for("facility.hazmat") + "#waste")


@facility_bp.route("/pest", methods=["POST"])
@_door
def pest():
    return _go(lambda: sp.pest_visit(current_user, request.form), url_for("facility.hazmat") + "#pest")


# ============================================================ construction ==
@facility_bp.route("/construction")
@_door
def construction():
    return render_template("facility/construction.html", data=sp.projects_board(), items=PCRA_ITEMS,
                           risks=RISK_LEVELS, states=PROJECT_STATES, today=local_today())


@facility_bp.route("/construction", methods=["POST"])
@_door
def construction_new():
    return _go(lambda: sp.save_project(current_user, request.form), url_for("facility.construction"))


@facility_bp.route("/construction/<int:project_id>/permit", methods=["POST"])
@_door
def construction_permit(project_id):
    row = db.get_or_404(ConstructionProject, project_id)
    return _go(lambda: sp.permit(row, request.form), url_for("facility.construction") + f"#p{row.id}")


@facility_bp.route("/construction/<int:project_id>/state", methods=["POST"])
@_door
def construction_state(project_id):
    row = db.get_or_404(ConstructionProject, project_id)
    return _go(lambda: sp.set_state(row, request.form.get("state")),
               url_for("facility.construction") + f"#p{row.id}")


@facility_bp.route("/construction/<int:project_id>/check", methods=["POST"])
@_door
def construction_check(project_id):
    row = db.get_or_404(ConstructionProject, project_id)
    return _go(lambda: sp.check_project(row, current_user, request.form),
               url_for("facility.construction") + f"#p{row.id}")


# ========================================================== being ready ==
@facility_bp.route("/preparedness")
@_door
def preparedness():
    today = local_today()
    year = request.args.get("year", type=int) or today.year
    return render_template("facility/preparedness.html", hazards=prep.hazards(), tree=prep.call_tree(),
                           abduction=fs.half_years("abduction", year), disaster=fs.half_years("disaster", year),
                           untrained={k: fs.untrained_this_year(today, k) for k in TRAINING_TOPICS},
                           topics=TRAINING_TOPICS, hazard_kinds=HAZARD_KINDS, staff=_staff(),
                           shifts=SHIFTS, today=today)


@facility_bp.route("/hazard", methods=["POST"])
@_door
def hazard_new():
    return _go(lambda: prep.save_hazard(current_user, request.form),
               url_for("facility.preparedness") + "#hazards")


@facility_bp.route("/hazard/<int:hazard_id>/retire", methods=["POST"])
@_door
def hazard_retire(hazard_id):
    row = db.get_or_404(EmergencyHazard, hazard_id)
    return _go(lambda: prep.retire(row), url_for("facility.preparedness") + "#hazards")


@facility_bp.route("/contact", methods=["POST"])
@_door
def contact_new():
    return _go(lambda: prep.save_contact(request.form), url_for("facility.preparedness") + "#tree")


@facility_bp.route("/contact/<int:contact_id>/retire", methods=["POST"])
@_door
def contact_retire(contact_id):
    row = db.get_or_404(CallTreeEntry, contact_id)
    return _go(lambda: prep.retire(row), url_for("facility.preparedness") + "#tree")


@facility_bp.route("/drill/<int:drill_id>/told", methods=["POST"])
@_door
def drill_told(drill_id):
    row = db.get_or_404(FireDrill, drill_id)
    return _go(lambda: fs.tell_committee(row, request.form),
               url_for("facility.preparedness") + f"#{row.kind}")


# =================================================================== plans ==
@facility_bp.route("/plans")
@_door
def plans():
    return render_template("facility/plans.html", data=prep.plans_board(local_today()),
                           inspections=prep.inspections_board(local_today()), kinds=PLAN_KINDS,
                           today=local_today())


@facility_bp.route("/plans", methods=["POST"])
@_door
def plan_new():
    return _go(lambda: prep.save_plan(current_user, request.form, file=_upload("file")),
               url_for("facility.plans") + "#plans")


@facility_bp.route("/plans/<int:plan_id>/replace", methods=["POST"])
@_door
def plan_replace(plan_id):
    old = db.get_or_404(HospitalPlan, plan_id)
    return _go(lambda: prep.save_plan(current_user, request.form, file=_upload("file"), replaces=old),
               url_for("facility.plans") + "#plans")


@facility_bp.route("/inspection", methods=["POST"])
@_door
def inspection_new():
    return _go(lambda: prep.save_inspection(current_user, request.form, file=_upload("file")),
               url_for("facility.plans") + "#inspections")


@facility_bp.route("/inspection/<int:inspection_id>/close", methods=["POST"])
@_door
def inspection_close(inspection_id):
    row = db.get_or_404(ExternalInspection, inspection_id)
    return _go(lambda: prep.close_inspection(row, request.form), url_for("facility.plans") + "#inspections")
