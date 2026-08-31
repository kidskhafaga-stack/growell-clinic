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
    from app.models import TreatmentPlan
    from app.models.dental import outstanding

    patient = db.get_or_404(Patient, patient_id)
    drawn = chart_for(patient.id)
    # The draft this chart can send a tooth to, if there is one. A chart that
    # offered "add to plan" with nowhere to add it would be a button that
    # opens a form; one that silently started a plan would leave drafts behind
    # every time somebody clicked to see what it did.
    draft = (TreatmentPlan.query
             .filter_by(patient_id=patient.id, status="draft")
             .order_by(TreatmentPlan.id.desc()).first())
    # Teeth already spoken for, so the chart does not offer the same tooth
    # twice and a doctor can see at a glance what is already accounted for.
    planned = set()
    for plan_row in TreatmentPlan.query.filter(
            TreatmentPlan.patient_id == patient.id,
            TreatmentPlan.status.in_(("draft", "accepted"))).all():
        planned |= {i.tooth for i in plan_row.live_items if i.tooth}
    return render_template(
        "dentistry/chart.html", patient=patient,
        chart=drawn, outstanding=outstanding(drawn),
        draft=draft, planned=planned,
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


# ======================================================================
#   Treatment plans, and the money they commit a family to
# ======================================================================
@dentistry_bp.route("/patient/<int:patient_id>/plans")
@module_required(MODULE)
def plans(patient_id):
    """Every plan this child has had, newest first."""
    from app.models import TreatmentPlan

    patient = db.get_or_404(Patient, patient_id)
    rows = (TreatmentPlan.query.filter_by(patient_id=patient.id)
            .order_by(TreatmentPlan.id.desc()).all())
    return render_template("dentistry/plans.html", patient=patient, plans=rows)


@dentistry_bp.route("/patient/<int:patient_id>/plans/new", methods=["POST"])
@module_required(MODULE)
def plan_new(patient_id):
    """Start a draft. Costs nothing and commits nobody."""
    from app.models import TreatmentPlan

    patient = db.get_or_404(Patient, patient_id)
    plan = TreatmentPlan(
        patient_id=patient.id,
        title=(request.form.get("title") or "").strip()[:120] or None,
        doctor_id=request.form.get("doctor_id", type=int) or None,
        created_by=current_user.id)
    db.session.add(plan)
    db.session.commit()
    return redirect(url_for("dentistry.plan", plan_id=plan.id))


@dentistry_bp.route("/plan/<int:plan_id>")
@module_required(MODULE)
def plan(plan_id):
    """One plan: what was agreed, how far it has got, and what is owed."""
    from app.models import Service, TreatmentPlan
    from app.utils.dental_money import minimum_deposit

    row = db.get_or_404(TreatmentPlan, plan_id)
    # Arrived from a tooth on the chart. The fact travels — which tooth, which
    # face, what was found — and the procedure does not: caries can be a
    # filling, a pulpotomy or an extraction depending on how deep it has gone,
    # and that is the dentist's call in front of the child rather than
    # something to infer from a keyword.
    from_tooth = request.args.get("tooth", type=int)
    if from_tooth not in ALL_TEETH:
        from_tooth = None
    # The face only travels with the tooth it is a face of. Carried
    # separately, `?tooth=99&surface=occlusal` puts a surface into the form
    # with no tooth chosen — and it then submits against whichever tooth the
    # dentist picks by hand, which is a fact half-carried and worse than one
    # not carried at all.
    from_surface = (request.args.get("surface") or "").strip() or None
    if from_tooth is None or from_surface not in surfaces_of(from_tooth):
        from_surface = None
    return render_template(
        "dentistry/plan.html", plan=row, patient=row.patient,
        teeth=ALL_TEETH, from_tooth=from_tooth, from_surface=from_surface,
        found=(chart_for(row.patient_id).get(from_tooth) or {})
        if from_tooth else {},
        services=(Service.query.filter_by(is_active=True)
                  .order_by(Service.name).all()),
        minimum=minimum_deposit(row.total))


@dentistry_bp.route("/plan/<int:plan_id>/item", methods=["POST"])
@module_required(MODULE)
def plan_item(plan_id):
    """Add a line. Only to a draft — see `TreatmentPlan.editable`."""
    from app.models import Service, TreatmentPlan, TreatmentPlanItem

    row = db.get_or_404(TreatmentPlan, plan_id)
    if not row.editable:
        flash(t("dental.err_accepted"), "warning")
        return redirect(url_for("dentistry.plan", plan_id=row.id))

    tooth = request.form.get("tooth", type=int)
    if tooth and tooth not in ALL_TEETH:
        flash(t("dental.err_tooth"), "danger")
        return redirect(url_for("dentistry.plan", plan_id=row.id))

    service_id = request.form.get("service_id", type=int) or None
    service = db.session.get(Service, service_id) if service_id else None
    description = (request.form.get("description") or "").strip()
    if service is not None and not description:
        description = service.name
    if not description:
        flash(t("dental.err_description"), "danger")
        return redirect(url_for("dentistry.plan", plan_id=row.id))

    price = request.form.get("price", type=float)
    if price is None and service is not None:
        price = service.price
    db.session.add(TreatmentPlanItem(
        plan_id=row.id, tooth=tooth or None,
        surface=(request.form.get("surface") or "").strip() or None,
        service_id=service_id, description=description[:200],
        price=max(round(price or 0, 2), 0)))
    db.session.commit()
    return redirect(url_for("dentistry.plan", plan_id=row.id))


@dentistry_bp.route("/plan/<int:plan_id>/accept", methods=["POST"])
@module_required(MODULE)
def plan_accept(plan_id):
    """Turn the agreed plan into a bill.

    The one moment a plan becomes money. Refusals come back as a message on
    the plan rather than an error page — the person pressing this is at a desk
    with a family in front of them.
    """
    from app.models import TreatmentPlan
    from app.utils import dental_money

    row = db.get_or_404(TreatmentPlan, plan_id)
    try:
        dental_money.accept(row, user_id=current_user.id)
    except dental_money.DentalMoneyError as exc:
        db.session.rollback()
        flash(t(f"dental.err_{exc}"), "danger")
        return redirect(url_for("dentistry.plan", plan_id=row.id))
    db.session.commit()
    flash(t("dental.accepted"), "success")
    return redirect(url_for("dentistry.plan", plan_id=row.id))


@dentistry_bp.route("/plan/<int:plan_id>/deposit", methods=["POST"])
@module_required(MODULE)
def plan_deposit(plan_id):
    """Take money against an accepted plan."""
    from app.models import TreatmentPlan
    from app.utils import dental_money

    row = db.get_or_404(TreatmentPlan, plan_id)
    if not current_user.can_collect:
        abort(403)
    try:
        dental_money.take_deposit(
            row, request.form.get("amount"),
            method=(request.form.get("method") or "cash"),
            user_id=current_user.id)
    except dental_money.DentalMoneyError as exc:
        db.session.rollback()
        flash(t(f"dental.err_{exc}"), "danger")
        return redirect(url_for("dentistry.plan", plan_id=row.id))
    db.session.commit()
    flash(t("dental.deposit_taken"), "success")
    return redirect(url_for("dentistry.plan", plan_id=row.id))


@dentistry_bp.route("/plan/item/<int:item_id>/done", methods=["POST"])
@module_required(MODULE)
def item_done(item_id):
    """Mark one procedure carried out. Does not bill — the plan already did."""
    from app.models import TreatmentPlanItem

    item = db.get_or_404(TreatmentPlanItem, item_id)
    item.status = "done"
    item.done_on = local_today()
    item.visit_id = request.form.get("visit_id", type=int) or item.visit_id
    # A plan whose every line is carried out is finished. Said here rather
    # than left for somebody to notice, so the list of open plans is the list
    # of work outstanding.
    plan_row = item.plan
    if plan_row.accepted and all(i.status == "done" for i in plan_row.live_items):
        plan_row.status = "done"
    db.session.commit()
    return redirect(url_for("dentistry.plan", plan_id=item.plan_id))
