"""The dental chart, for a clinic that has said it is a dental clinic.

Every route here is behind ``module_required("dentistry")``, and dentistry is
an **opt-in** module: off until somebody switches it on, even on a copy that
has never run the setup wizard. A paediatric clinic that has not asked for
this does not get a tooth chart on its patients' files, and every address
below answers 404 for them rather than existing quietly.
"""

from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user

from app.blueprints.dentistry import dentistry_bp
from app.extensions import db
from app.i18n import t
from app.models import Patient
from app.models.dental import (ALL_TEETH, CONDITIONS, PERMANENT_TEETH,
                               PRIMARY_TEETH, WHOLE_TOOTH,
                               WHOLE_TOOTH_CONDITIONS, ToothFinding, chart_for,
                               history_for, is_primary, surfaces_of)
from app.utils.clock import local_today
from app.utils.decorators import module_required

MODULE = "dentistry"


@dentistry_bp.route("/patient/<int:patient_id>")
@module_required(MODULE)
def chart(patient_id):
    """One child's mouth as it stands.

    Both dentitions on one page, because between six and twelve a child has
    both and a chart that shows one of them is showing half a mouth.
    """
    patient = db.get_or_404(Patient, patient_id)
    return render_template(
        "dentistry/chart.html", patient=patient,
        chart=chart_for(patient.id),
        permanent=PERMANENT_TEETH, primary=PRIMARY_TEETH,
        conditions=CONDITIONS, whole=WHOLE_TOOTH,
        whole_only=sorted(WHOLE_TOOTH_CONDITIONS),
        surfaces_of=surfaces_of, today=local_today())


@dentistry_bp.route("/patient/<int:patient_id>/record", methods=["POST"])
@module_required(MODULE)
def record(patient_id):
    """Write down one thing about one surface of one tooth.

    Refused rather than stored when the tooth has no such surface. A lower
    incisor has no biting table, so an occlusal finding on one is not a
    detail to tidy up later — it is a fact about a place that does not exist,
    and the chart would draw it somewhere.
    """
    patient = db.get_or_404(Patient, patient_id)
    # The tooth comes from the form, not the address. One form on the chart
    # records any of fifty-two teeth, and building the address from the
    # dropdown in script is how it ends up posting to whichever tooth the
    # markup happened to name.
    tooth = request.form.get("tooth", type=int)
    if tooth not in ALL_TEETH:
        flash(t("dental.err_tooth"), "danger")
        return redirect(url_for("dentistry.chart", patient_id=patient.id))

    condition = (request.form.get("condition") or "").strip()
    if condition not in CONDITIONS:
        flash(t("dental.err_condition"), "danger")
        return redirect(url_for("dentistry.chart", patient_id=patient.id))

    surface = (request.form.get("surface") or WHOLE_TOOTH).strip()
    # Some findings are about the tooth, not one of its faces: a tooth is not
    # missing "on the buccal side".
    if condition in WHOLE_TOOTH_CONDITIONS:
        surface = WHOLE_TOOTH
    if surface not in surfaces_of(tooth):
        flash(t("dental.err_surface"), "danger")
        return redirect(url_for("dentistry.chart", patient_id=patient.id))

    db.session.add(ToothFinding(
        patient_id=patient.id, tooth=tooth, surface=surface,
        condition=condition,
        note=(request.form.get("note") or "").strip()[:300] or None,
        found_on=local_today(),
        visit_id=request.form.get("visit_id", type=int) or None,
        recorded_by=current_user.id))
    db.session.commit()
    flash(t("common.saved"), "success")
    return redirect(url_for("dentistry.chart", patient_id=patient.id))


@dentistry_bp.route("/patient/<int:patient_id>/tooth/<int:tooth>/history")
@module_required(MODULE)
def tooth_history(patient_id, tooth):
    """Everything ever recorded about one tooth.

    A tooth filled last year and decayed again this year is the argument for
    a crown, and the chart alone cannot make it — it shows what is true now.
    """
    patient = db.get_or_404(Patient, patient_id)
    if tooth not in ALL_TEETH:
        abort(404)
    return render_template("dentistry/tooth.html", patient=patient,
                           tooth=tooth, primary=is_primary(tooth),
                           rows=history_for(patient.id, tooth))
