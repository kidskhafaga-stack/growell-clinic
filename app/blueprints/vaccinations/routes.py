"""Vaccinations module — Phase 6, Part 1.

Per-patient vaccination plan with brand selection (no mixing brands), the
Egyptian schedule, visual due/done/upcoming states, next-due suggestion, dose
recording (with lot number), and a printable vaccination certificate.
"""
import io
from datetime import datetime

from flask import (
    current_app,
    flash,
    g,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user

from app.blueprints.vaccinations import vaccinations_bp
from app.extensions import db
from app.i18n import t
from app.models import (
    VACCINE_ROUTES,
    VACCINE_TYPES,
    ActivityLog,
    Patient,
    PatientVaccine,
    Setting,
    Vaccine,
    VaccineBrand,
    VaccineBrandDose,
    VaccineScheduleDose,
    VaccineScheduleTemplate,
)
from app.utils import whatsapp as wa
from app.utils.decorators import client_ip, module_required
from app.utils.paging import paginate
from app.utils.dose_labels import dose_choices, dose_label
from app.utils.patients import apply_patient_search
from app.utils.clock import local_today
from app.utils.vaccine_notify import notify_dose
from app.utils.vaccines import (
    SHUT,
    administer_dose,
    interval_warning,
    chosen_brand,
    immunization_compliance,
    next_due_dose,
    patient_due_reminders,
    patient_plan,
    plan_summary,
)

MODULE = "vaccinations"


@vaccinations_bp.route("/")
@module_required(MODULE)
def index():
    q = (request.args.get("q") or "").strip()
    query = apply_patient_search(
        Patient.query.filter_by(is_active=True), q
    ).order_by(Patient.full_name)
    pagination = paginate(query)
    return render_template(
        "vaccinations/index.html", patients=pagination.items,
        pagination=pagination, q=q
    )


@vaccinations_bp.route("/<int:patient_id>")
@module_required(MODULE)
def view(patient_id):
    patient = db.get_or_404(Patient, patient_id)
    lang = request.cookies.get("lang", "ar")
    plan = patient_plan(patient, lang)
    summary = plan_summary(plan)
    nxt = next_due_dose(plan)
    from app.utils.course_state import annotate
    from app.utils.vaccines import OPEN_GROUPS, group_plan

    # Said, not counted. "3/4" leaves the reader to work out whether the one
    # missing is a primary dose the child is behind on or the booster that
    # falls due next year — a phone call and a diary note, not the same job.
    annotate(plan)
    # The agreed plan, and what is left to agree on. Only the optional
    # schedule is offered: the national one is given at the government unit
    # and agreeing to it here would promise something this clinic does not do.
    from app.models.vaccine_plan import VaccinePlanItem

    agreed = (VaccinePlanItem.query.filter_by(patient_id=patient.id)
              .join(Vaccine).order_by(Vaccine.sort_order).all())
    on_plan = {row.vaccine_id for row in agreed}
    offerable = [item["vaccine"] for item in plan
                 if not item["vaccine"].is_mandatory
                 and not item["vaccine"].on_demand
                 and item["vaccine"].id not in on_plan]
    return render_template(
        "vaccinations/view.html",
        patient=patient, plan=plan, summary=summary, next_due=nxt,
        agreed=agreed, offerable=offerable,
        groups=group_plan(plan), open_groups=OPEN_GROUPS,
        # Which dose is which, per vaccine — so the doctor picks "the second
        # dose" by name instead of typing a number and hoping.
        dose_options=_dose_options(patient, plan, lang),
        today=local_today().isoformat(),
    )


def _dose_options(patient, plan, lang="ar"):
    """``{vaccine_id: [{number, label, given, booster, ...}]}`` for the form."""
    out = {}
    for item in plan:
        vaccine = item["vaccine"]
        brand = item.get("brand") or vaccine.default_brand
        given = {d["dose_number"] for d in item.get("doses", [])
                 if d.get("given_date")}
        out[vaccine.id] = dose_choices(vaccine, brand, given, lang)
    return out


def _settle_paid_vaccines(patient, on_date):
    """Reconcile the day's paid vaccine lines with what was really done.
    Never blocks the clinical record: a billing hiccup must not lose a dose."""
    try:
        from app.utils.vaccine_settlement import sync_for_patient
        return sync_for_patient(patient.id, on_date)
    except Exception:                                   # pragma: no cover
        current_app.logger.exception("vaccine settlement sync failed")
        return []


@vaccinations_bp.route("/reminder/act", methods=["POST"])
@module_required(MODULE)
def reminder_act():
    """Record that somebody dealt with a reminder, so it stops asking.

    The work list is rebuilt from birthdays and doses every time it opens, so
    a row worked yesterday comes back this morning looking untouched.
    Reception rings a family, the family says "next month", and tomorrow the
    list says ring them. A list that cannot remember is one people stop
    believing — quietly, by working the top of it and ignoring the rest.

    Nothing is deleted. The row is held back and counted, and the screen will
    show what it is holding, because a reminder that disappears for good is
    how a child stops being followed without anybody deciding that.
    """
    from app.models.reminder_action import ACTIONS, ReminderAction, default_until
    from app.utils.export import parse_date

    action = (request.form.get("action") or "").strip()
    patient_id = request.form.get("patient_id", type=int)
    vaccine_id = request.form.get("vaccine_id", type=int)
    if action not in ACTIONS or not patient_id or not vaccine_id:
        flash(t("vact.bad"), "warning")
        return redirect(request.referrer or url_for("vaccinations.reminders"))

    until = default_until(action, parse_date(request.form.get("until")))
    if action == "snoozed" and until is None:
        # "Later" without a date is how a row goes quiet for ever by accident.
        flash(t("vact.needs_date"), "warning")
        return redirect(request.referrer or url_for("vaccinations.reminders"))

    db.session.add(ReminderAction(
        patient_id=patient_id, vaccine_id=vaccine_id,
        dose_number=request.form.get("dose_number", type=int),
        action=action, until=until,
        note=(request.form.get("note") or "").strip()[:200] or None,
        created_by_id=current_user.id))
    ActivityLog.record("vaccine.reminder_act", user_id=current_user.id,
                       entity="patient", entity_id=patient_id,
                       detail=f"{action} v={vaccine_id}", ip_address=client_ip())
    db.session.commit()
    flash(t("vact." + action), "success")
    return redirect(request.referrer or url_for("vaccinations.reminders"))


@vaccinations_bp.route("/reminder/<int:action_id>/undo", methods=["POST"])
@module_required(MODULE)
def reminder_undo(action_id):
    """Put a held-back reminder back on the list."""
    from app.models.reminder_action import ReminderAction

    row = db.get_or_404(ReminderAction, action_id)
    patient_id = row.patient_id
    db.session.delete(row)
    ActivityLog.record("vaccine.reminder_undo", user_id=current_user.id,
                       entity="patient", entity_id=patient_id,
                       ip_address=client_ip())
    db.session.commit()
    flash(t("vact.undone"), "info")
    return redirect(request.referrer or url_for("vaccinations.plans"))


@vaccinations_bp.route("/plans")
@module_required(MODULE)
def plans():
    """The cases the clinic agreed a plan with, and what they still owe them.

    Its own screen rather than a filter on the dose reminders, because it
    answers a different question. Reminders ask "who is late"; this asks "who
    did we promise something to, and are we keeping it" — and the second is
    the one somebody works through on a Sunday morning with the fridge open.

    The filters are the ones every screen here should carry: a date range, a
    vaccine, and nothing else to learn. The purchase order is built from
    **whatever the filter is showing**, the same rule the reminders screen and
    the invoice export already follow, so what you take away is what you were
    looking at.

    A dose the family is buying themselves is on the list and never in the
    order. They still need the visit arranged and the dose recorded; putting a
    vial on the order for it fills the fridge with stock nobody will pay for.
    """
    from app.models.vaccine_plan import VaccinePlanItem
    from app.utils.export import parse_date
    from app.utils.vaccine_due import due_list, order_suggestion, summarise

    lang = getattr(g, "lang", "ar")
    start = parse_date(request.args.get("from"))
    end = parse_date(request.args.get("to"))
    vaccine_id = request.args.get("vaccine_id", type=int)

    on_plan = {}
    for item in VaccinePlanItem.query.all():
        on_plan.setdefault(item.patient_id, set()).add(item.vaccine_id)
    if not on_plan:
        found, rows = [], []
    else:
        # Kept whole before filtering: `due_list` carries how many rows it
        # held back on the object it returns, and a list comprehension makes
        # an ordinary list that has forgotten. Measured — the "N hidden"
        # notice rendered as zero and the way to see them never appeared.
        found = due_list(start=start, end=end, vaccine_id=vaccine_id,
                         lang=lang)
        rows = [r for r in found
                if r["vaccine"].id in on_plan.get(r["patient"].id, ())]

    people = {}
    for row in rows:
        people.setdefault(row["patient"].id, {
            "patient": row["patient"], "rows": []})["rows"].append(row)

    # What is being held back, and by what — so the screen can both say how
    # many and offer them back. A count alone tells somebody a number they
    # cannot act on.
    from app.models.reminder_action import ReminderAction

    show_hidden = request.args.get("hidden") == "1"
    held = []
    if show_hidden:
        held = (ReminderAction.query
                .filter(db.or_(ReminderAction.until.is_(None),
                               ReminderAction.until > local_today()))
                .order_by(ReminderAction.created_at.desc()).limit(100).all())

    return render_template(
        "vaccinations/plans.html",
        people=sorted(people.values(),
                      key=lambda p: p["patient"].display_name(lang)),
        rows=rows, counts=summarise(rows),
        order=order_suggestion(rows),
        held_back=getattr(found, "held_back", 0),
        held=held, show_hidden=show_hidden,
        today=local_today().isoformat(),
        # How many children are on a plan at all, so an empty result reads as
        # "nothing due" rather than "nobody has a plan".
        total_on_plan=len(on_plan),
        vaccines=Vaccine.query.order_by(Vaccine.sort_order).all(),
        f_from=request.args.get("from", ""), f_to=request.args.get("to", ""),
        vaccine_id=vaccine_id,
    )


@vaccinations_bp.route("/<int:patient_id>/plan/add", methods=["POST"])
@module_required(MODULE)
def plan_add(patient_id):
    """Agree a vaccine with this family, so the program starts following it.

    One press per vaccine and nothing else to fill in. The doses and their
    dates come from the schedule the child is already on — asking the doctor
    to type them would be asking them to restate what the program computed,
    and a date typed twice is a date that eventually disagrees with itself.
    Any one of them can still be moved afterwards, which is what the pencilled
    dates were always for.
    """
    from app.models import Vaccine
    from app.models.vaccine_plan import VaccinePlanItem

    patient = db.get_or_404(Patient, patient_id)
    vaccine_id = request.form.get("vaccine_id", type=int)
    vaccine = db.session.get(Vaccine, vaccine_id) if vaccine_id else None
    if vaccine is None:
        flash(t("vplan.pick_one"), "warning")
        return redirect(url_for("vaccinations.view", patient_id=patient.id))

    existing = VaccinePlanItem.query.filter_by(
        patient_id=patient.id, vaccine_id=vaccine.id).first()
    if existing is not None:
        flash(t("vplan.already"), "info")
        return redirect(url_for("vaccinations.view", patient_id=patient.id))

    item = VaccinePlanItem(
        patient_id=patient.id, vaccine_id=vaccine.id,
        brand_id=request.form.get("brand_id", type=int) or None,
        # The family is bringing this one: still a plan, never an order.
        supplied_outside=bool(request.form.get("supplied_outside")),
        note=(request.form.get("note") or "").strip()[:200] or None,
        added_by_id=current_user.id)
    db.session.add(item)
    ActivityLog.record("vaccine.plan_add", user_id=current_user.id,
                       entity="patient", entity_id=patient.id,
                       detail=vaccine.code or vaccine.name_ar,
                       ip_address=client_ip())
    db.session.commit()
    flash(t("vplan.added"), "success")
    return redirect(url_for("vaccinations.view", patient_id=patient.id))


@vaccinations_bp.route("/plan/<int:item_id>/remove", methods=["POST"])
@module_required(MODULE)
def plan_remove(item_id):
    """Take a vaccine off the plan.

    The course goes back to being a suggestion for the child's age rather than
    disappearing — the family did not become younger, and the doctor may only
    have changed their mind about the timing.
    """
    from app.models.vaccine_plan import VaccinePlanItem

    item = db.get_or_404(VaccinePlanItem, item_id)
    patient_id = item.patient_id
    ActivityLog.record("vaccine.plan_remove", user_id=current_user.id,
                       entity="patient", entity_id=patient_id,
                       detail=str(item.vaccine_id), ip_address=client_ip())
    db.session.delete(item)
    db.session.commit()
    flash(t("vplan.removed"), "info")
    return redirect(url_for("vaccinations.view", patient_id=patient_id))


@vaccinations_bp.route("/<int:patient_id>/record", methods=["POST"])
@module_required(MODULE)
def record(patient_id):
    patient = db.get_or_404(Patient, patient_id)
    vaccine = db.get_or_404(Vaccine, request.form.get("vaccine_id", type=int))

    brand_id = request.form.get("brand_id", type=int)
    req_brand = next((b for b in vaccine.brands if b.id == brand_id), None)

    raw_date = (request.form.get("given_date") or "").strip()
    try:
        given_date = datetime.strptime(raw_date, "%Y-%m-%d").date() if raw_date \
            else local_today()
    except ValueError:
        given_date = local_today()

    # Same guard as the visit room: a dose of this vaccine given too recently.
    # Read before the record is written — afterwards the newest dose is the one
    # being added, and every check would compare it against itself.
    too_soon = interval_warning(patient.id, vaccine, given_date)
    pv, result = administer_dose(
        patient, vaccine, brand=req_brand,
        dose_number=request.form.get("dose_number", type=int),
        doctor_id=request.form.get("doctor_id", type=int) or current_user.id,
        given_date=given_date,
        lot_number=(request.form.get("lot_number") or "").strip() or None,
        given_outside=bool(request.form.get("given_outside")),
        outside_place=(request.form.get("outside_place") or "").strip() or None,
        adverse_events=(request.form.get("adverse_events") or "").strip() or None,
        notes=(request.form.get("notes") or "").strip() or None,
    )
    if pv is None:
        flash(t(f"vaccinations.{result}"),
              {"dose_exists": "warning", "all_done": "info"}.get(result, "danger"))
        return redirect(url_for("vaccinations.view", patient_id=patient.id))
    if too_soon:
        flash(t("vaccinations.interval_warn",
                vaccine=vaccine.display_name(getattr(g, "lang", "ar")),
                dose=too_soon["previous_dose"], days=too_soon["days"],
                date=too_soon["previous_date"].isoformat(),
                min=too_soon["minimum"]), "warning")
    brand = result            # the resolved brand (for the next-dose reminder)
    dose_number = pv.dose_number

    ActivityLog.record(
        "vaccine.record", user_id=current_user.id, entity="patient",
        entity_id=patient.id, detail=f"{vaccine.code}#{dose_number}",
        ip_address=client_ip(),
    )
    # A vaccine already paid for at reception but swapped in the room leaves
    # money to settle — raise it now so the cashier sees the difference.
    _settle_paid_vaccines(patient, given_date)
    db.session.commit()
    flash(t("vaccinations.recorded"), "success")

    # Auto-notify the guardian via the unified CRM engine (dose + next due).
    # The wording and every reason it might not go live in one place, because
    # the visit room gives doses too and used to send nothing at all.
    log, reason = notify_dose(patient, vaccine, brand, dose_number, given_date,
                              user_id=current_user.id,
                              lang=getattr(g, "lang", "ar"))
    db.session.commit()
    if reason:
        flash(t("crm.not_sent", why=t("crm.reason_" + reason)), "warning")
        return redirect(url_for("vaccinations.view", patient_id=patient.id))
    return render_template(
        "messages/sent.html", log=log, appt=None,
        back_url=url_for("vaccinations.view", patient_id=patient.id))


@vaccinations_bp.route("/<int:patient_id>/record-event", methods=["POST"])
@module_required(MODULE)
def record_event(patient_id):
    """Document a dose as refused or delayed (not given) with a reason."""
    patient = db.get_or_404(Patient, patient_id)
    vaccine = db.get_or_404(Vaccine, request.form.get("vaccine_id", type=int))
    dose_number = request.form.get("dose_number", type=int) or 1
    event_type = request.form.get("event_type")
    if event_type not in ("refused", "delayed"):
        flash(t("vaccinations.bad_event"), "warning")
        return redirect(url_for("vaccinations.view", patient_id=patient.id))

    # Don't override an already-given dose.
    if PatientVaccine.query.filter_by(patient_id=patient.id, vaccine_id=vaccine.id,
                                      dose_number=dose_number, event_type="given").first():
        flash(t("vaccinations.dose_exists"), "warning")
        return redirect(url_for("vaccinations.view", patient_id=patient.id))

    # Replace any previous event for the same dose.
    PatientVaccine.query.filter(
        PatientVaccine.patient_id == patient.id,
        PatientVaccine.vaccine_id == vaccine.id,
        PatientVaccine.dose_number == dose_number,
        PatientVaccine.event_type != "given",
    ).delete(synchronize_session=False)

    brand = chosen_brand(patient.id, vaccine)[0] or vaccine.default_brand
    db.session.add(PatientVaccine(
        patient_id=patient.id, vaccine_id=vaccine.id,
        brand_id=brand.id if brand else None, dose_number=dose_number,
        given_date=local_today(), event_type=event_type,
        refusal_reason=(request.form.get("reason") or "").strip() or None,
    ))
    ActivityLog.record(f"vaccine.{event_type}", user_id=current_user.id,
                       entity="patient", entity_id=patient.id,
                       detail=f"{vaccine.code}#{dose_number}", ip_address=client_ip())
    # Refusing a dose the parent already paid for owes them the price back.
    _settle_paid_vaccines(patient, local_today())
    db.session.commit()
    flash(t("vaccinations.event_saved"), "success")
    return redirect(url_for("vaccinations.view", patient_id=patient.id))


@vaccinations_bp.route("/dose/<int:pv_id>/delete", methods=["POST"])
@module_required(MODULE)
def delete_dose(pv_id):
    pv = db.get_or_404(PatientVaccine, pv_id)
    patient_id = pv.patient_id
    db.session.delete(pv)
    db.session.commit()
    flash(t("vaccinations.dose_removed"), "info")
    return redirect(url_for("vaccinations.view", patient_id=patient_id))


# =================================================================
#  Vaccine catalogue management (add/edit vaccines, brands, schedules)
# =================================================================
def _parse_ages(raw):
    """Parse a comma/Arabic-comma separated list of month ages into ints."""
    ages = []
    for part in (raw or "").replace("،", ",").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            ages.append(int(float(part)))
        except ValueError:
            continue
    return sorted(set(ages))


def _set_brand_doses(brand, ages):
    VaccineBrandDose.query.filter_by(brand_id=brand.id).delete()
    for i, age in enumerate(ages, start=1):
        db.session.add(VaccineBrandDose(brand_id=brand.id, dose_number=i, age_months=age))


@vaccinations_bp.route("/manage")
@module_required(MODULE)
def manage():
    # Opens on what the clinic actually dispenses.
    #
    # The government (EPI) set is given at the government unit: the clinic
    # neither buys it, prices it nor stocks it — this screen already declines
    # to show a stock figure for those rows, because there is none. Opening on
    # "all" still put forty-seven of them in front of somebody whose business
    # here is the handful they sell, which is what was reported: it scatters
    # the person using it.
    #
    # Nothing is hidden and nothing is deleted. The government set keeps its
    # own tab one click away with its count on it, and the child's vaccination
    # schedule — a different screen — still shows every dose, government
    # included, because that is where a dose given elsewhere gets recorded.
    cat = (request.args.get("cat") or "optional").strip()
    all_vaccines = (Vaccine.query
                    .order_by(Vaccine.is_mandatory.desc(), Vaccine.sort_order).all())
    counts = {
        "all": len(all_vaccines),
        "mandatory": sum(1 for v in all_vaccines if v.is_mandatory),
        "optional": sum(1 for v in all_vaccines if not v.is_mandatory),
    }
    if cat == "mandatory":
        vaccines = [v for v in all_vaccines if v.is_mandatory]
    elif cat == "optional":
        vaccines = [v for v in all_vaccines if not v.is_mandatory]
    else:
        cat = "all"
        vaccines = all_vaccines
    return render_template("vaccinations/manage.html", vaccines=vaccines,
                           routes=VACCINE_ROUTES, cat=cat, counts=counts,
                           load_gov=Setting.get("load_gov_vaccines", "1") != "0",
                           load_optional=Setting.get("load_optional_vaccines", "1") != "0")


@vaccinations_bp.route("/manage/catalogue", methods=["POST"])
@module_required(MODULE)
def catalogue_settings():
    """Save which bundled sets auto-load (government EPI / optional) and, when
    asked, load the enabled sets now. Loading is additive — it adds what's
    missing (with its WHO/manufacturer schedule + catch-up) and never deletes."""
    Setting.set("load_gov_vaccines", "1" if request.form.get("load_gov") else "0")
    Setting.set("load_optional_vaccines", "1" if request.form.get("load_optional") else "0")
    db.session.commit()
    if request.form.get("load_now"):
        from app.utils.vaccines import seed_vaccine_schedules, seed_vaccines
        n = seed_vaccines()
        seed_vaccine_schedules()
        db.session.commit()
        flash(t("vaccinations.catalogue_loaded").replace("{n}", str(n)), "success")
    else:
        flash(t("common.saved"), "success")
    return redirect(url_for("vaccinations.manage"))


@vaccinations_bp.route("/manage/vaccine/new", methods=["POST"])
@module_required(MODULE)
def vaccine_new():
    code = (request.form.get("code") or "").strip().upper()
    name_ar = (request.form.get("name_ar") or "").strip()
    if not code or not name_ar:
        flash(t("common.required") + ": " + t("vaccinations.vaccine_name_ar"), "danger")
        return redirect(url_for("vaccinations.manage"))
    if Vaccine.query.filter_by(code=code).first():
        flash(t("vaccinations.code_taken"), "warning")
        return redirect(url_for("vaccinations.manage"))

    is_mandatory = (request.form.get("category") or "mandatory") == "mandatory"
    route = (request.form.get("route") or "").strip()
    vaccine = Vaccine(
        code=code, name_ar=name_ar,
        name_en=(request.form.get("name_en") or "").strip() or None,
        is_mandatory=is_mandatory,
        route=route in VACCINE_ROUTES and route or None,
        sort_order=request.form.get("sort_order", type=int) or 100,
    )
    db.session.add(vaccine)
    db.session.flush()

    # Create the first brand (government for mandatory) + its dose schedule.
    brand = VaccineBrand(
        vaccine_id=vaccine.id,
        name=(request.form.get("brand_name") or ("حكومي" if is_mandatory else name_ar)).strip(),
        manufacturer=(request.form.get("manufacturer") or "").strip() or None,
        price=request.form.get("price", type=float),
        purchase_price=request.form.get("purchase_price", type=float),
        max_discount=request.form.get("max_discount", type=float),
        is_default=True,
    )
    db.session.add(brand)
    db.session.flush()
    _set_brand_doses(brand, _parse_ages(request.form.get("dose_ages")))

    ActivityLog.record("vaccine.create", user_id=current_user.id, entity="vaccine",
                       entity_id=vaccine.id, detail=code, ip_address=client_ip())
    db.session.commit()
    flash(t("vaccinations.vaccine_added"), "success")
    return redirect(url_for("vaccinations.manage"))


@vaccinations_bp.route("/manage/vaccine/<int:vaccine_id>/edit", methods=["POST"])
@module_required(MODULE)
def vaccine_edit(vaccine_id):
    vaccine = db.get_or_404(Vaccine, vaccine_id)
    vaccine.name_ar = (request.form.get("name_ar") or vaccine.name_ar).strip()
    vaccine.name_en = (request.form.get("name_en") or "").strip() or None
    vaccine.is_mandatory = (request.form.get("category") or "mandatory") == "mandatory"
    route = (request.form.get("route") or "").strip()
    vaccine.route = route if route in VACCINE_ROUTES else None
    if request.form.get("sort_order", type=int) is not None:
        vaccine.sort_order = request.form.get("sort_order", type=int)
    vaccine.is_discontinued = bool(request.form.get("is_discontinued"))
    rb = request.form.get("replaced_by_id", type=int)
    vaccine.replaced_by_id = rb if (rb and rb != vaccine.id) else None
    db.session.commit()
    flash(t("vaccinations.vaccine_updated"), "success")
    return redirect(url_for("vaccinations.manage"))


@vaccinations_bp.route("/manage/vaccine/<int:vaccine_id>/medical", methods=["POST"])
@module_required(MODULE)
def vaccine_medical(vaccine_id):
    """Save the vaccine's medical metadata (PDF "Medical Information")."""
    vaccine = db.get_or_404(Vaccine, vaccine_id)
    f = request.form
    vaccine.diseases_covered = (f.get("diseases_covered") or "").strip() or None
    vaccine.min_age_months = f.get("min_age_months", type=int)
    vaccine.max_age_months = f.get("max_age_months", type=int)
    vaccine.booster_required = bool(f.get("booster_required"))
    vaccine.is_seasonal = bool(f.get("is_seasonal"))
    vaccine.pregnancy_recommendation = (f.get("pregnancy_recommendation") or "").strip() or None
    vaccine.risk_groups = (f.get("risk_groups") or "").strip() or None
    vaccine.contraindications = (f.get("contraindications") or "").strip() or None
    vaccine.adverse_events_info = (f.get("adverse_events_info") or "").strip() or None
    vtype = (f.get("vaccine_type") or "").strip()
    vaccine.vaccine_type = vtype if vtype in VACCINE_TYPES else None
    vaccine.min_interval_days = f.get("min_interval_days", type=int)
    vaccine.on_demand = bool(f.get("on_demand"))
    vaccine.catch_up_notes = (f.get("catch_up_notes") or "").strip() or None
    vaccine.coadministration_notes = (f.get("coadministration_notes") or "").strip() or None
    vaccine.precautions = (f.get("precautions") or "").strip() or None
    vaccine.reference = (f.get("reference") or "").strip() or None
    db.session.commit()
    flash(t("vaccinations.medical_saved"), "success")
    return redirect(url_for("vaccinations.schedule_templates", vaccine_id=vaccine.id))


# --------------------------------------------- schedule templates (A/B/C/D) -
@vaccinations_bp.route("/manage/vaccine/<int:vaccine_id>/schedules")
@module_required(MODULE)
def schedule_templates(vaccine_id):
    vaccine = db.get_or_404(Vaccine, vaccine_id)
    return render_template("vaccinations/schedules.html", vaccine=vaccine,
                           vaccine_types=VACCINE_TYPES)


@vaccinations_bp.route("/manage/vaccine/<int:vaccine_id>/schedules/new", methods=["POST"])
@module_required(MODULE)
def template_new(vaccine_id):
    vaccine = db.get_or_404(Vaccine, vaccine_id)
    code = (request.form.get("code") or "").strip().upper()
    if not code:
        flash(t("common.required") + ": " + t("vaccinations.tpl_code"), "danger")
        return redirect(url_for("vaccinations.schedule_templates", vaccine_id=vaccine.id))
    source = (request.form.get("source") or "custom").strip()
    # The band the program chooses by, and whose leaflet it came from. Both
    # are settings rather than code on purpose: a schedule that needs a
    # programmer to change is one the clinic cannot correct when a leaflet is
    # revised, and leaflets are revised.
    brand_id = request.form.get("brand_id", type=int)
    if brand_id and not any(b.id == brand_id for b in vaccine.brands):
        brand_id = None                 # not this vaccine's — ignore it
    tpl = VaccineScheduleTemplate(
        vaccine_id=vaccine.id, code=code, brand_id=brand_id,
        label=(request.form.get("label") or "").strip() or None,
        age_group=(request.form.get("age_group") or "").strip() or None,
        start_age_min_months=request.form.get("start_age_min_months", type=int),
        start_age_max_months=request.form.get("start_age_max_months", type=int),
        is_catch_up=bool(request.form.get("is_catch_up")),
        source=source if source in VaccineScheduleTemplate.SOURCES else "custom",
        sort_order=request.form.get("sort_order", type=int) or 0,
    )
    db.session.add(tpl)
    db.session.commit()
    flash(t("vaccinations.tpl_added"), "success")
    return redirect(url_for("vaccinations.schedule_templates", vaccine_id=vaccine.id))


@vaccinations_bp.route("/manage/schedules/<int:template_id>/edit", methods=["POST"])
@module_required(MODULE)
def template_edit(template_id):
    """Correct a schedule in place.

    Seeded bands arrive labelled "للمراجعة" and are meant to be corrected: a
    leaflet is revised, a clinic follows the CDC rather than the European
    label, a country's programme differs. Without this the only way to change
    one is to delete it and rebuild its doses, which is how people end up
    leaving a wrong schedule alone.
    """
    tpl = db.get_or_404(VaccineScheduleTemplate, template_id)
    f = request.form
    brand_id = f.get("brand_id", type=int)
    if brand_id and not any(b.id == brand_id for b in tpl.vaccine.brands):
        brand_id = None
    tpl.brand_id = brand_id
    tpl.label = (f.get("label") or "").strip() or None
    tpl.age_group = (f.get("age_group") or "").strip() or None
    tpl.start_age_min_months = f.get("start_age_min_months", type=int)
    tpl.start_age_max_months = f.get("start_age_max_months", type=int)
    tpl.is_catch_up = bool(f.get("is_catch_up"))
    tpl.is_active = bool(f.get("is_active"))
    source = (f.get("source") or tpl.source).strip()
    if source in VaccineScheduleTemplate.SOURCES:
        tpl.source = source
    ActivityLog.record("vaccine.schedule_edit", user_id=current_user.id,
                       entity="vaccine", entity_id=tpl.vaccine_id,
                       detail=tpl.code, ip_address=client_ip())
    db.session.commit()
    flash(t("vaccinations.tpl_saved"), "success")
    return redirect(url_for("vaccinations.schedule_templates",
                            vaccine_id=tpl.vaccine_id))


@vaccinations_bp.route("/manage/schedules/<int:template_id>/delete", methods=["POST"])
@module_required(MODULE)
def template_delete(template_id):
    tpl = db.get_or_404(VaccineScheduleTemplate, template_id)
    vid = tpl.vaccine_id
    db.session.delete(tpl)
    db.session.commit()
    flash(t("vaccinations.tpl_deleted"), "info")
    return redirect(url_for("vaccinations.schedule_templates", vaccine_id=vid))


@vaccinations_bp.route("/manage/schedules/<int:template_id>/dose", methods=["POST"])
@module_required(MODULE)
def template_dose_add(template_id):
    tpl = db.get_or_404(VaccineScheduleTemplate, template_id)
    dose_number = request.form.get("dose_number", type=int)
    if not dose_number:
        dose_number = (max((d.dose_number for d in tpl.doses), default=0) + 1)
    db.session.add(VaccineScheduleDose(
        template_id=tpl.id,
        dose_number=dose_number,
        recommended_age_months=request.form.get("recommended_age_months", type=int),
        min_interval_days=request.form.get("min_interval_days", type=int),
        max_interval_days=request.form.get("max_interval_days", type=int),
        booster_required=bool(request.form.get("booster_required")),
    ))
    db.session.commit()
    flash(t("vaccinations.tpl_dose_added"), "success")
    return redirect(url_for("vaccinations.schedule_templates", vaccine_id=tpl.vaccine_id))


@vaccinations_bp.route("/manage/schedules/dose/<int:dose_id>/delete", methods=["POST"])
@module_required(MODULE)
def template_dose_delete(dose_id):
    dose = db.get_or_404(VaccineScheduleDose, dose_id)
    vid = dose.template.vaccine_id
    db.session.delete(dose)
    db.session.commit()
    flash(t("vaccinations.tpl_dose_removed"), "info")
    return redirect(url_for("vaccinations.schedule_templates", vaccine_id=vid))


@vaccinations_bp.route("/manage/vaccine/<int:vaccine_id>/delete", methods=["POST"])
@module_required(MODULE)
def vaccine_delete(vaccine_id):
    vaccine = db.get_or_404(Vaccine, vaccine_id)
    if PatientVaccine.query.filter_by(vaccine_id=vaccine.id).first():
        flash(t("vaccinations.cannot_delete_used"), "warning")
        return redirect(url_for("vaccinations.manage"))
    db.session.delete(vaccine)
    db.session.commit()
    flash(t("vaccinations.vaccine_deleted"), "info")
    return redirect(url_for("vaccinations.manage"))


@vaccinations_bp.route("/manage/vaccine/<int:vaccine_id>/brand/new", methods=["POST"])
@module_required(MODULE)
def brand_new(vaccine_id):
    vaccine = db.get_or_404(Vaccine, vaccine_id)
    name = (request.form.get("name") or "").strip()
    if not name:
        flash(t("common.required") + ": " + t("vaccinations.brand_name"), "danger")
        return redirect(url_for("vaccinations.manage"))
    brand = VaccineBrand(
        vaccine_id=vaccine.id, name=name,
        name_en=(request.form.get("name_en") or "").strip() or None,
        manufacturer=(request.form.get("manufacturer") or "").strip() or None,
        price=request.form.get("price", type=float),
        purchase_price=request.form.get("purchase_price", type=float),
        doctor_fee=request.form.get("doctor_fee", type=float),
        max_discount=request.form.get("max_discount", type=float),
        price_policy=("auto" if request.form.get("price_policy") == "auto" else "manual"),
        margin_percent=request.form.get("margin_percent", type=float),
        doses_per_vial=max(request.form.get("doses_per_vial", type=int) or 1, 1),
        is_discontinued=bool(request.form.get("is_discontinued")),
        is_default=not vaccine.brands,
    )
    db.session.add(brand)
    db.session.flush()
    _set_brand_doses(brand, _parse_ages(request.form.get("dose_ages")))
    db.session.commit()
    flash(t("vaccinations.brand_added"), "success")
    return redirect(url_for("vaccinations.manage"))


@vaccinations_bp.route("/manage/brand/<int:brand_id>/edit", methods=["POST"])
@module_required(MODULE)
def brand_edit(brand_id):
    brand = db.get_or_404(VaccineBrand, brand_id)
    brand.name = (request.form.get("name") or brand.name).strip()
    brand.name_en = (request.form.get("name_en") or "").strip() or None
    brand.manufacturer = (request.form.get("manufacturer") or "").strip() or None
    brand.price = request.form.get("price", type=float)
    brand.purchase_price = request.form.get("purchase_price", type=float)
    brand.doctor_fee = request.form.get("doctor_fee", type=float)
    brand.max_discount = request.form.get("max_discount", type=float)
    brand.price_policy = "auto" if request.form.get("price_policy") == "auto" else "manual"
    brand.margin_percent = request.form.get("margin_percent", type=float)
    brand.doses_per_vial = max(request.form.get("doses_per_vial", type=int) or 1, 1)
    brand.catch_up_notes = (request.form.get("catch_up_notes") or "").strip() or None
    brand.is_discontinued = bool(request.form.get("is_discontinued"))
    ages = _parse_ages(request.form.get("dose_ages"))
    if ages:
        _set_brand_doses(brand, ages)
    db.session.commit()
    flash(t("vaccinations.brand_updated"), "success")
    return redirect(url_for("vaccinations.manage"))


@vaccinations_bp.route("/manage/brand/<int:brand_id>/prefer", methods=["POST"])
@module_required(MODULE)
def brand_prefer(brand_id):
    """Star a brand as the doctor's first-choice (default) for its vaccine.

    Clears the star from the vaccine's other brands so exactly one is preferred;
    the preferred brand is what a new course and the visit panel suggest first.
    """
    brand = db.get_or_404(VaccineBrand, brand_id)
    for b in brand.vaccine.brands:
        b.is_default = (b.id == brand.id)
    db.session.commit()
    flash(t("vaccinations.brand_preferred_set"), "success")
    return redirect(url_for("vaccinations.manage"))


@vaccinations_bp.route("/manage/brand/<int:brand_id>/delete", methods=["POST"])
@module_required(MODULE)
def brand_delete(brand_id):
    brand = db.get_or_404(VaccineBrand, brand_id)
    if PatientVaccine.query.filter_by(brand_id=brand.id).first():
        flash(t("vaccinations.cannot_delete_used"), "warning")
        return redirect(url_for("vaccinations.manage"))
    vid = brand.vaccine_id
    db.session.delete(brand)
    db.session.commit()
    flash(t("vaccinations.brand_deleted"), "info")
    return redirect(url_for("vaccinations.manage"))


def _qr_svg(url, scale=3):
    """Return an inline SVG QR for ``url`` (or None if QR libs unavailable)."""
    try:
        import segno
    except ImportError:  # pragma: no cover - segno is in requirements
        return None
    buf = io.BytesIO()
    segno.make(url, error="m").save(buf, kind="svg", scale=scale, border=0)
    return buf.getvalue().decode("utf-8")


def _apply_print_lang():
    """Per-print language choice (?lang=ar|en): reports/certificates can be
    handed to the family in either language regardless of the UI language."""
    lang = request.args.get("lang")
    if lang in ("ar", "en"):
        from app.i18n import get_direction

        g.lang = lang
        g.direction = get_direction(lang)


@vaccinations_bp.route("/<int:patient_id>/certificate")
@module_required(MODULE)
def certificate(patient_id):
    _apply_print_lang()
    from app.utils.vaccines import certificate_cards, certificate_totals

    patient = db.get_or_404(Patient, patient_id)
    lang = getattr(g, "lang", "ar")
    plan = patient_plan(patient, lang)
    # A card per vaccine rather than one date-ordered list of every dose: the
    # three doses of one course used to sit pages apart, so "did they finish
    # it?" could only be answered by reading the whole page and counting.
    cards = certificate_cards(plan)
    totals = certificate_totals(cards)
    # Optional upcoming-plan table (?schedule=1): every not-yet-given dose
    # with its expected date — doctor-planned dates included — so the family
    # leaves knowing exactly what is next and when.
    # Two different tables, because they make two different claims.
    #
    # "What is left" is this clinic's own commitment: the remaining doses of
    # courses it began. That is the table a family should be handed.
    #
    # "What the age suggests" is everything else the child is old enough for —
    # true, but not a promise anybody here made, and mostly the national
    # schedule that is given at the government unit. Printed only when the
    # doctor asks for it, because a certificate implying this clinic owes the
    # government's doses is a certificate that misleads the family holding it.
    #
    # A refused dose appears in neither. The family said no; reprinting it as
    # outstanding is asking again on paper, every time the certificate is
    # issued.
    def _rows(items):
        rows = []
        for v in items:
            for d in v["doses"]:
                # The national schedule and the on-demand vaccines belong on
                # the certificate as a **record** — a dose given at a
                # government unit is part of the child's history and is why a
                # parent carries the paper at all. They do not belong in the
                # *suggestions*: nobody here promised them, and a page telling
                # a family they are behind on nine government vaccines is
                # frightening, useless and not this clinic's to say.
                # A shut window is not a suggestion at any time: the series
                # can no longer be completed, so printing it asks a family for
                # something no clinic can give them.
                #
                # The national schedule stays. This table prints only when the
                # doctor asks for it (`?suggest=1`), and being "what the age
                # suggests" rather than anything this clinic promised is the
                # whole reason it is opt-in — which in Egypt is mostly the
                # government schedule. Taking it out of a table somebody
                # deliberately switched on deletes the feature rather than
                # fixing it; two older tests exist to say so, and caught this.
                if (d["status"] == "done" or d.get("event_type") == "refused"
                        or d["status"] in SHUT):
                    continue
                rows.append({"vaccine": v["vaccine"], "brand": v["brand"],
                             "dose_number": d["dose_number"],
                             "due_date": d["due_date"],
                             "planned": d.get("planned"),
                             "age_label": d["age_label"]})
        rows.sort(key=lambda r: r["due_date"] or "9999")
        return rows

    upcoming = suggested = []
    if request.args.get("schedule") == "1":
        upcoming = _rows([v for v in plan if v.get("started")])
    if request.args.get("suggest") == "1":
        suggested = _rows([v for v in plan if not v.get("started")])
    # Ensure a stable verification token and build the public QR.
    patient.ensure_qr_token()
    db.session.commit()
    verify_url = url_for("vaccinations.verify", token=patient.qr_token, _external=True)
    return render_template(
        "vaccinations/certificate.html", patient=patient,
        cards=cards, totals=totals,
        upcoming=upcoming, suggested=suggested, with_schedule=request.args.get("schedule") == "1",
        with_suggestions=request.args.get("suggest") == "1",
        now_date=local_today().isoformat(),
        qr_svg=_qr_svg(verify_url), verify_url=verify_url,
    )


# ---------------------------------------------------- compliance panel -----
@vaccinations_bp.route("/compliance")
@module_required(MODULE)
def compliance():
    """Population immunization-compliance panel: up-to-date vs overdue across
    patients we vaccinate, per-vaccine coverage and the most-overdue patients."""
    lang = getattr(g, "lang", "ar")
    data = immunization_compliance(lang)
    return render_template("vaccinations/compliance.html", data=data,
                           now_date=local_today().isoformat())


# ------------------------------------------------------ due reminders ------
@vaccinations_bp.route("/reminders")
@module_required(MODULE)
def reminders():
    """Who is due a dose — and, from the same list, what to order for them.

    Only patients who already have a dose recorded with us are considered: a
    clinic never chases a vaccine it never gave, because the child may be
    getting it somewhere else and the call would only annoy the family. That
    also keeps this cheap with thousands of patients on the books.

    The filters are what make one screen do two jobs. "Who do I call this week"
    and "what will I need next month" are the same data over different windows,
    and the purchase order is built from **whatever the filter is currently
    showing** — the same rule as the invoice export: what you take away is what
    you were looking at.
    """
    from app.utils.export import parse_date
    from app.utils.vaccine_due import due_list, order_suggestion, summarise

    lang = getattr(g, "lang", "ar")
    start = parse_date(request.args.get("from"))
    end = parse_date(request.args.get("to"))
    vaccine_id = request.args.get("vaccine_id", type=int)
    brand_id = request.args.get("brand_id", type=int)
    status = (request.args.get("status") or "").strip()
    if status not in ("overdue", "due", "seasonal"):
        status = ""

    found = due_list(start=start, end=end, vaccine_id=vaccine_id,
                     brand_id=brand_id, status=status or None, lang=lang)
    rows = [{"patient": r["patient"], "vaccine": r["vaccine"],
             "brand": r["brand"], "dose_number": r["dose_number"],
             "due_date": r["due_date"], "status": r["status"],
             "phone": r["patient"].contact_phone} for r in found]

    from app.models import Vaccine, VaccineBrand
    from app.utils import vaccine_back

    return render_template(
        "vaccinations/reminders.html", rows=rows,
        counts=summarise(found), order=order_suggestion(found),
        # The families who were told to come while the shelf was empty, for
        # every item that now has stock again.
        back=vaccine_back.brands_with_people_waiting(),
        vaccines=Vaccine.query.order_by(Vaccine.sort_order, Vaccine.id).all(),
        brands=VaccineBrand.query.order_by(VaccineBrand.name).all(),
        f_from=request.args.get("from", ""), f_to=request.args.get("to", ""),
        f_vaccine=vaccine_id, f_brand=brand_id, f_status=status,
        now_date=local_today().isoformat())


@vaccinations_bp.route("/<int:patient_id>/remind-due")
@module_required(MODULE)
def remind_due(patient_id):
    """Send the patient's guardian a "dose due" reminder via the CRM template."""
    patient = db.get_or_404(Patient, patient_id)
    lang = getattr(g, "lang", "ar")
    due_list = patient_due_reminders(patient, lang)
    if not due_list:
        flash(t("vaccinations.no_due"), "info")
        return redirect(url_for("vaccinations.reminders"))
    due = due_list[0]
    phone = patient.contact_phone
    if not phone:
        flash(t("occasions.no_phone"), "warning")
        return redirect(url_for("vaccinations.reminders"))
    body = wa.render(wa.template_body("vaccine_due"), {
        "patient": patient.display_name(lang),
        "vaccine": due["vaccine"].display_name(lang),
        "dose": dose_label(due["dose_number"], lang),
        "due_date": due["due_date"] or "—",
        "clinic": Setting.get("clinic_name_ar") or Setting.get("clinic_name") or "",
    })
    log = wa.send(body, phone, patient_id=patient.id, user_id=current_user.id,
                  template_type="vaccine_due",
                  image_url=wa.template_image("vaccine_due"))
    # Which item this was about. It is the only thing that lets the clinic
    # answer "who did we tell?" when the stock finally arrives — a reminder
    # sent into an empty fridge is a promise, and the promise has to be
    # findable.
    if due.get("brand") is not None:
        log.vaccine_brand_id = due["brand"].id
    db.session.commit()
    return render_template("messages/sent.html", log=log, appt=None,
                           back_url=url_for("vaccinations.reminders"))


@vaccinations_bp.route("/back-in-stock/<int:brand_id>", methods=["POST"])
@module_required(MODULE)
def back_in_stock(brand_id):
    """Tell the families who were told to come while the shelf was empty.

    Deliberately a button rather than something that happens by itself when a
    delivery is booked in. Messaging a hundred families is not a side effect of
    a store screen, and the person receiving the box is not always the person
    who decides the clinic is ready to see them.
    """
    from app.utils import vaccine_back

    brand = db.get_or_404(VaccineBrand, brand_id)
    logs = vaccine_back.notify(brand, user_id=current_user.id,
                               lang=getattr(g, "lang", "ar"))
    if not logs:
        flash(t("vaccinations.back_none"), "info")
        return redirect(request.referrer or url_for("vaccinations.reminders"))
    ActivityLog.record("vaccine.back_in_stock", user_id=current_user.id,
                       entity="vaccine_brand", entity_id=brand.id,
                       detail=f"{len(logs)}", ip_address=client_ip())
    db.session.commit()
    flash(t("vaccinations.back_sent", n=len(logs)), "success")
    return redirect(url_for("messages.index"))


@vaccinations_bp.route("/verify/<token>")
def verify(token):
    """Public certificate verification reached via the QR code (no login)."""
    patient = Patient.query.filter_by(qr_token=token).first()
    if patient is None:
        return render_template("vaccinations/verify.html", patient=None, given=[]), 404
    given = (
        PatientVaccine.query.filter_by(patient_id=patient.id)
        .filter(PatientVaccine.event_type == "given")
        .order_by(PatientVaccine.given_date)
        .all()
    )
    clinic = (Setting.get("clinic_name_ar") or Setting.get("clinic_name")
              or "GROWELL CLINIC")
    return render_template(
        "vaccinations/verify.html", patient=patient, given=given,
        clinic=clinic, now_date=local_today().isoformat(),
    )


@vaccinations_bp.route("/dose/<int:pv_id>/correct", methods=["POST"])
@module_required(MODULE)
def correct_dose(pv_id):
    """Correct a recorded dose: its number, its date, or where it was given.

    This exists because of what an imported history cannot know. The old
    program's file holds what happened **at this clinic**, and the dose numbers
    were inferred from the order of those dates — so a child who had two doses
    here, one somewhere else, and the booster here comes out numbered 1, 2, 3
    when they are really 1, 3, 4. Nothing in the data can see the gap.

    Reported exactly that way: *"the doctor sees he had 2 with me and one
    outside and the booster with me"*. So the inference is a starting point the
    doctor overrides, not a fact. Without this screen the imported history is a
    wall a doctor cannot fix, and a clinic that cannot fix it goes back to its
    old program.
    """
    dose = db.get_or_404(PatientVaccine, pv_id)
    patient_id = dose.patient_id

    number = request.form.get("dose_number", type=int)
    if number and number > 0:
        # A second record of the same dose number would make the course read as
        # complete when it is not.
        clash = PatientVaccine.query.filter(
            PatientVaccine.patient_id == patient_id,
            PatientVaccine.vaccine_id == dose.vaccine_id,
            PatientVaccine.dose_number == number,
            PatientVaccine.event_type == "given",
            PatientVaccine.id != dose.id).first()
        if clash is not None:
            flash(t("vaccinations.dose_exists"), "warning")
            return redirect(url_for("vaccinations.view", patient_id=patient_id))
        dose.dose_number = number

    given = (request.form.get("given_date") or "").strip()
    if given:
        try:
            dose.given_date = datetime.strptime(given, "%Y-%m-%d").date()
        except ValueError:
            pass

    # "Given outside" is the whole point: it keeps the dose in the child's
    # record — so the course is not restarted — while saying this clinic did
    # not give it, which is what the stock and the money must not assume.
    outside = bool(request.form.get("given_outside"))
    dose.given_outside = outside
    dose.outside_place = ((request.form.get("outside_place") or "").strip()[:160]
                          or None) if outside else None

    ActivityLog.record("vaccine.correct", user_id=current_user.id,
                       entity="patient", entity_id=patient_id,
                       detail=f"dose {dose.id} -> #{dose.dose_number}"
                              f"{' outside' if outside else ''}",
                       ip_address=client_ip())
    db.session.commit()
    flash(t("vaccinations.dose_corrected"), "success")
    return redirect(url_for("vaccinations.view", patient_id=patient_id))
