"""Visit / examination module (Phase 4).

Vital signs, chief complaint, clinical exam, ICD-10/11 diagnoses (working /
secondary / final), and visit completion — which also closes a linked
appointment and mirrors growth measurements into growth_records.
"""
from datetime import datetime

from flask import (
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user
from sqlalchemy import or_

from app.blueprints.visits import visits_bp
from app.extensions import db
from app.i18n import t
from app.models import (
    ActivityLog,
    Appointment,
    Diagnosis,
    Feedback,
    GrowthRecord,
    Investigation,
    Patient,
    PatientAttachment,
    Service,
    Setting,
    Visit,
    VisitInvestigation,
    VisitService,
    VitalSigns,
)
from app.utils import whatsapp as wa
from app.utils.decorators import client_ip, module_required
from app.utils.icd import search_icd
from app.utils.uploads import ATTACHMENT_KINDS, remove_document, save_document

MODULE = "visits"

# Quick "write less" chips in the visit — editable in Settings, with sensible
# bilingual pediatric defaults. Stored one per line as "ar|en" (en optional);
# the chip shows and inserts in the program language.
DEFAULT_COMPLAINT_CHIPS = [
    ("حرارة", "Fever"), ("كحة", "Cough"), ("رشح", "Runny nose"),
    ("إسهال", "Diarrhea"), ("قيء", "Vomiting"), ("مغص", "Colic"),
    ("إمساك", "Constipation"), ("طفح جلدي", "Skin rash"),
    ("التهاب حلق", "Sore throat"), ("التهاب أذن", "Ear infection"),
    ("صعوبة تنفس", "Difficulty breathing"), ("صفير بالصدر", "Wheezing"),
    ("ضعف شهية", "Poor appetite"), ("خمول", "Lethargy"),
    ("تسنين", "Teething"), ("احمرار عين", "Red eye"),
    ("ألم بطن", "Abdominal pain"), ("صداع", "Headache"),
    ("متابعة نمو", "Growth follow-up"), ("متابعة تطعيم", "Vaccination follow-up"),
    ("إعادة كشف", "Re-examination"),
]
DEFAULT_EXAM_CHIPS = [
    ("الحالة العامة جيدة", "General condition good"),
    ("الصدر: دخول هواء ثنائي متساوٍ بدون صفير", "Chest: equal bilateral air entry, no wheeze"),
    ("القلب: أصوات منتظمة بدون لغط", "Heart: regular sounds, no murmur"),
    ("البطن: لين غير منتفخ غير مؤلم", "Abdomen: soft, not distended, non-tender"),
    ("الحلق: محتقن", "Throat: congested"),
    ("الأذن: طبلة محتقنة", "Ear: congested tympanic membrane"),
    ("لا توجد علامات جفاف", "No signs of dehydration"),
    ("الغدد الليمفاوية غير متضخمة", "Lymph nodes not enlarged"),
    ("الجلد: سليم", "Skin: intact"),
]


def _visit_chips(key, defaults):
    """Bilingual quick-phrase chips as ``[{"ar":…, "en":…}]``.

    Stored one per line as ``ar|en`` (English optional). Falls back to the
    pediatric defaults when the clinic hasn't set its own.
    """
    raw = Setting.get(key)
    if raw:
        chips = []
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            ar, _, en = line.partition("|")
            chips.append({"ar": ar.strip(), "en": en.strip()})
        if chips:
            return chips
    return [{"ar": ar, "en": en} for ar, en in defaults]


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


# --------------------------------------------------------------- index -----
@visits_bp.route("/")
@module_required(MODULE)
def index():
    from app.utils.privacy import doctor_locked_id

    query = Visit.query
    locked = doctor_locked_id()
    if locked:
        query = query.filter(or_(Visit.doctor_id == locked,
                                 Visit.doctor_id.is_(None)))
    pagination = query.order_by(Visit.created_at.desc()).paginate(
        page=request.args.get("page", 1, type=int), per_page=25, error_out=False
    )
    return render_template(
        "visits/list.html", visits=pagination.items, pagination=pagination
    )


# --------------------------------------------------------------- start -----
@visits_bp.route("/start/<int:patient_id>")
@module_required(MODULE)
def start(patient_id):
    """Create (or reopen) an open visit for a patient and go to the record."""
    patient = db.get_or_404(Patient, patient_id)
    appointment_id = request.args.get("appointment_id", type=int)

    visit = (
        Visit.query.filter_by(patient_id=patient.id, status="open")
        .order_by(Visit.created_at.desc())
        .first()
    )
    if visit is None:
        doctor_id = current_user.id
        if appointment_id:
            appt = db.session.get(Appointment, appointment_id)
            if appt:
                doctor_id = appt.doctor_id
        visit = Visit(
            patient_id=patient.id,
            doctor_id=doctor_id,
            appointment_id=appointment_id,
        )
        db.session.add(visit)
        ActivityLog.record(
            "visit.start", user_id=current_user.id, entity="visit",
            entity_id=None, detail=patient.patient_number, ip_address=client_ip(),
        )
        db.session.commit()
    return redirect(url_for("visits.record", visit_id=visit.id))


# -------------------------------------------------------------- record -----
@visits_bp.route("/<int:visit_id>/record", methods=["GET", "POST"])
@module_required(MODULE)
def record(visit_id):
    from app.utils.privacy import can_see_visit

    visit = db.get_or_404(Visit, visit_id)
    if not can_see_visit(visit):
        flash(t("visits.not_yours"), "warning")
        return redirect(url_for("visits.index"))

    if request.method == "POST":
        visit.chief_complaint = (request.form.get("chief_complaint") or "").strip()
        visit.clinical_exam = (request.form.get("clinical_exam") or "").strip()
        visit.plan = (request.form.get("plan") or "").strip()
        visit.notes = (request.form.get("notes") or "").strip()

        _save_vitals(visit)
        ActivityLog.record(
            "visit.update", user_id=current_user.id, entity="visit",
            entity_id=visit.id, ip_address=client_ip(),
        )
        db.session.commit()
        flash(t("visits.saved"), "success")
        return redirect(url_for("visits.record", visit_id=visit.id))

    # Continuity context: what the doctor should see when the patient returns
    # for the follow-up consultation — the recent visits (to follow treatment
    # progress / changes across consultations).
    recent_visits = (
        Visit.query.filter(Visit.patient_id == visit.patient_id,
                           Visit.id != visit.id,
                           Visit.visit_date <= visit.visit_date)
        .order_by(Visit.visit_date.desc(), Visit.id.desc())
        .limit(3).all()
    )
    # Investigations requested in earlier visits that still have no result —
    # the doctor reviews/fills them now, in the consultation.
    pending_investigations = (
        VisitInvestigation.query.filter(
            VisitInvestigation.patient_id == visit.patient_id,
            VisitInvestigation.visit_id != visit.id,
            VisitInvestigation.status == "requested",
        ).order_by(VisitInvestigation.created_at.desc()).all()
    )
    recent_attachments = (
        PatientAttachment.query.filter(
            PatientAttachment.patient_id == visit.patient_id,
            PatientAttachment.visit_id != visit.id,
        ).order_by(PatientAttachment.created_at.desc()).limit(5).all()
    )
    procedure_services = (
        Service.query.filter(Service.is_active.is_(True),
                             Service.category.in_(("procedure", "lab", "radiology")))
        .order_by(Service.name).all()
    )
    # Vaccination snapshot for the visit tab, framed as "what can I give now"
    # (received history + in-stock optional vaccines + out-of-stock suggestions).
    from app.models import Vaccine
    from app.utils.vaccines import visit_vaccine_panel
    vac_panel = visit_vaccine_panel(visit.patient, getattr(g, "lang", "ar"))
    # Mandatory (EPI) vaccines aren't suggested, but the doctor can add one
    # deliberately (e.g. recording a government-unit dose).
    mandatory_vaccines = (Vaccine.query
                          .filter_by(is_mandatory=True, is_discontinued=False)
                          .order_by(Vaccine.sort_order).all())
    # Medication reconciliation reference: the patient's recent meds.
    from app.utils.meds import recent_medications
    recent_meds = recent_medications(visit.patient_id)
    from app.utils import ai
    return render_template(
        "visits/record.html", visit=visit, recent_visits=recent_visits,
        pending_investigations=pending_investigations,
        recent_attachments=recent_attachments,
        procedure_services=procedure_services, recent_meds=recent_meds,
        vac_panel=vac_panel, mandatory_vaccines=mandatory_vaccines,
        complaint_chips=_visit_chips("visit_complaint_chips", DEFAULT_COMPLAINT_CHIPS),
        exam_chips=_visit_chips("visit_exam_chips", DEFAULT_EXAM_CHIPS),
        ai_ready=ai.is_ready(),
    )


def _visit_clinical_text(visit, anonymize=True):
    """Flatten a visit's saved structured data into plain text for the AI.
    Sends clinical content only; the patient's name is withheld when the AI
    anonymize option is on (age/sex is enough clinical context)."""
    p = visit.patient
    yrs, mos = p.age_parts
    who = "A child" if anonymize else p.full_name
    lines = [f"{who}, {yrs}y {mos}m, {p.gender}."]
    v = visit.vitals
    if v:
        vit = []
        if v.weight_kg:
            vit.append(f"weight {v.weight_kg}kg")
        if v.height_cm:
            vit.append(f"height {v.height_cm}cm")
        if v.head_circ_cm:
            vit.append(f"head circ {v.head_circ_cm}cm")
        if v.temperature_c:
            vit.append(f"temp {v.temperature_c}C")
        if v.pulse_bpm:
            vit.append(f"pulse {v.pulse_bpm}")
        if v.resp_rate:
            vit.append(f"resp {v.resp_rate}")
        if v.spo2:
            vit.append(f"SpO2 {v.spo2}%")
        if vit:
            lines.append("Vitals: " + ", ".join(vit) + ".")
    if visit.chief_complaint:
        lines.append("Chief complaint: " + visit.chief_complaint)
    if visit.clinical_exam:
        lines.append("Examination: " + visit.clinical_exam)
    dx = [d.title for d in visit.diagnoses if d.title]
    if dx:
        lines.append("Diagnoses: " + "; ".join(dx))
    meds = [it.drug_name for rx in getattr(visit, "prescriptions", [])
            for it in rx.items if it.drug_name]
    if meds:
        lines.append("Medications: " + "; ".join(meds))
    invs = [i.name for i in visit.investigations if i.name]
    if invs:
        lines.append("Investigations: " + "; ".join(invs))
    if visit.plan:
        lines.append("Plan: " + visit.plan)
    if visit.notes:
        lines.append("Notes: " + visit.notes)
    return "\n".join(lines)


@visits_bp.route("/<int:visit_id>/ai-summary", methods=["POST"])
@module_required(MODULE)
def ai_summary(visit_id):
    """Draft a concise clinical visit summary from the saved notes, using the
    clinic's configured AI provider. Never auto-saved — it's returned for the
    doctor to review, edit and paste into the notes/plan."""
    from app.utils import ai
    from app.utils.privacy import can_see_visit

    visit = db.get_or_404(Visit, visit_id)
    if not can_see_visit(visit):
        return jsonify({"ok": False, "error": "forbidden"}), 403
    if not ai.is_ready():
        return jsonify({"ok": False, "error": "not_configured"})

    if not (visit.chief_complaint or visit.clinical_exam or visit.diagnoses
            or visit.plan or visit.notes or visit.vitals):
        return jsonify({"ok": False, "error": "empty"})

    lang_name = "Arabic" if getattr(g, "lang", "ar") == "ar" else "English"
    system = (
        f"You are a pediatric clinical scribe. Write a concise, professional visit "
        f"summary in {lang_name} from the structured notes provided, under short "
        f"headings: Chief complaint, Examination, Assessment, Plan. Only use what is "
        f"in the notes — never invent findings, medications, doses or diagnoses. "
        f"This is a draft for the treating doctor to review and edit."
    )
    text = _visit_clinical_text(visit, anonymize=ai.anonymize_enabled())
    res = ai.chat([{"role": "user", "content": text}], system=system)
    if res.get("ok"):
        ActivityLog.record("visit.ai_summary", user_id=current_user.id,
                           entity="visit", entity_id=visit.id, ip_address=client_ip())
        db.session.commit()
    return jsonify(res)


# ------------------------------------------------------- nurse station -----
@visits_bp.route("/station")
@module_required(MODULE)
def station():
    """Nurse vitals station: today's checked-in queue with a quick vitals entry
    per child, so weight/height/temp/… are captured before the doctor sees them.
    Saving pre-fills the open visit the doctor then continues."""
    from app.models import Appointment

    today = datetime.utcnow().date()
    appts = (Appointment.query
             .filter(Appointment.appt_date == today,
                     Appointment.status.in_(("waiting", "in_progress")))
             .order_by(Appointment.appt_time)
             .all())
    rows = []
    for a in appts:
        v = (Visit.query.filter_by(patient_id=a.patient_id, status="open")
             .order_by(Visit.created_at.desc()).first())
        rows.append({"appt": a, "patient": a.patient,
                     "vitals": v.vitals if v else None,
                     "done": bool(v and v.vitals and v.vitals.has_growth)})
    return render_template("visits/station.html", rows=rows, today=today)


@visits_bp.route("/station/<int:appointment_id>/vitals", methods=["POST"])
@module_required(MODULE)
def station_vitals(appointment_id):
    """Record (or update) a waiting child's vitals from the nurse station.

    Reuses the open visit if one exists (so the doctor continues the same
    encounter) or opens one attached to the appointment; then upserts vitals via
    the shared helper, which also mirrors the growth measurements."""
    from app.models import Appointment

    appt = db.get_or_404(Appointment, appointment_id)
    visit = (Visit.query.filter_by(patient_id=appt.patient_id, status="open")
             .order_by(Visit.created_at.desc()).first())
    if visit is None:
        visit = Visit(patient_id=appt.patient_id, doctor_id=appt.doctor_id,
                      appointment_id=appt.id)
        db.session.add(visit)
        db.session.flush()
    _save_vitals(visit)
    ActivityLog.record(
        "visit.vitals_station", user_id=current_user.id, entity="visit",
        entity_id=visit.id, detail=appt.patient.patient_number,
        ip_address=client_ip(),
    )
    db.session.commit()
    flash(t("visits.station_saved", name=appt.patient.display_name(g.get("lang", "ar"))),
          "success")
    return redirect(url_for("visits.station"))


def _save_vitals(visit):
    """Upsert the visit's vitals and mirror growth measurements."""
    vitals = visit.vitals or VitalSigns(visit_id=visit.id)
    vitals.weight_kg = _float("weight_kg")
    vitals.height_cm = _float("height_cm")
    vitals.head_circ_cm = _float("head_circ_cm")
    vitals.temperature_c = _float("temperature_c")
    vitals.pulse_bpm = _int("pulse_bpm")
    vitals.resp_rate = _int("resp_rate")
    vitals.spo2 = _int("spo2")
    if visit.vitals is None:
        db.session.add(vitals)
        visit.vitals = vitals

    # Mirror weight/height/head into a growth record for this visit.
    if vitals.has_growth:
        gr = GrowthRecord.query.filter_by(visit_id=visit.id).first()
        if gr is None:
            gr = GrowthRecord(patient_id=visit.patient_id, visit_id=visit.id,
                              source="visit")
            db.session.add(gr)
        gr.record_date = visit.visit_date
        gr.weight_kg = vitals.weight_kg
        gr.height_cm = vitals.height_cm
        gr.head_circ_cm = vitals.head_circ_cm
        gr.bmi = vitals.bmi


# ----------------------------------------------------------- diagnoses -----
@visits_bp.route("/<int:visit_id>/diagnoses", methods=["POST"])
@module_required(MODULE)
def add_diagnosis(visit_id):
    visit = db.get_or_404(Visit, visit_id)
    # Bilingual snapshot: the hidden title_ar/title_en come from the ICD pick;
    # a manually-typed title falls back to the visible field.
    title = (request.form.get("title_ar") or request.form.get("title") or "").strip()
    title_en = (request.form.get("title_en") or "").strip()
    if not title:
        flash(t("common.required") + ": " + t("visits.diagnosis"), "danger")
        return redirect(url_for("visits.record", visit_id=visit.id) + "#dx")

    dx_type = (request.form.get("dx_type") or "working").strip()
    version = (request.form.get("icd_version") or "10").strip()
    db.session.add(Diagnosis(
        visit_id=visit.id,
        code=(request.form.get("code") or "").strip() or None,
        title=title,
        title_en=title_en or None,
        icd_version=version if Diagnosis.valid_version(version) else "10",
        dx_type=dx_type if Diagnosis.valid_type(dx_type) else "working",
    ))
    db.session.commit()
    flash(t("visits.diagnosis_added"), "success")
    return redirect(url_for("visits.record", visit_id=visit.id) + "#dx")


@visits_bp.route("/diagnoses/<int:dx_id>/delete", methods=["POST"])
@module_required(MODULE)
def delete_diagnosis(dx_id):
    dx = db.get_or_404(Diagnosis, dx_id)
    visit_id = dx.visit_id
    db.session.delete(dx)
    db.session.commit()
    flash(t("visits.diagnosis_removed"), "info")
    return redirect(url_for("visits.record", visit_id=visit_id) + "#dx")


# -------------------------------------------- investigations (labs/imaging) -
@visits_bp.route("/investigations/search")
@module_required(MODULE)
def investigation_search():
    """Autocomplete for ordering lab tests / imaging in the visit."""
    q = (request.args.get("q") or "").strip()
    kind = (request.args.get("kind") or "").strip()
    if len(q) < 1:
        return jsonify([])
    like = f"%{q}%"
    query = Investigation.query.filter(Investigation.is_active.is_(True)).filter(
        or_(Investigation.name_ar.ilike(like), Investigation.name_en.ilike(like))
    )
    if kind in ("lab", "imaging"):
        query = query.filter(Investigation.kind == kind)
    rows = query.order_by(Investigation.name_ar).limit(15).all()
    return jsonify([{"id": x.id, "name": x.display_name(), "name_ar": x.name_ar,
                     "name_en": x.name_en or "", "kind": x.kind,
                     "category": x.category or ""} for x in rows])


@visits_bp.route("/<int:visit_id>/investigations", methods=["POST"])
@module_required(MODULE)
def add_investigation(visit_id):
    """Order a lab test / imaging study during the visit."""
    visit = db.get_or_404(Visit, visit_id)
    # Bilingual snapshot: hidden name_ar/name_en come from the catalogue pick;
    # a manually-typed name falls back to the visible field.
    name = (request.form.get("name_ar") or request.form.get("name") or "").strip()
    name_en = (request.form.get("name_en") or "").strip()
    if not name:
        flash(t("visits.inv_need_name"), "danger")
        return redirect(url_for("visits.record", visit_id=visit.id) + "#inv")
    kind = request.form.get("kind") if request.form.get("kind") in ("lab", "imaging") else "lab"
    inv_id = request.form.get("investigation_id", type=int) or None

    # Let the doctor grow the catalogue: a typed-but-unknown test can be saved
    # to the investigations list so it shows up next time (idempotent by name).
    if inv_id is None and request.form.get("add_to_catalog"):
        existing = Investigation.query.filter_by(name_ar=name, kind=kind).first()
        if existing is None:
            existing = Investigation(name_ar=name, name_en=name_en or None,
                                     kind=kind, is_active=True)
            db.session.add(existing)
            db.session.flush()
        inv_id = existing.id

    db.session.add(VisitInvestigation(
        visit_id=visit.id, patient_id=visit.patient_id,
        investigation_id=inv_id, kind=kind, name=name, name_en=name_en or None,
        request_notes=(request.form.get("request_notes") or "").strip() or None,
    ))
    db.session.commit()
    flash(t("visits.inv_added"), "success")
    return redirect(url_for("visits.record", visit_id=visit.id) + "#inv")


@visits_bp.route("/<int:visit_id>/services", methods=["POST"])
@module_required(MODULE)
def add_service(visit_id):
    """Add a chargeable procedure/service performed during the visit."""
    visit = db.get_or_404(Visit, visit_id)
    service = db.session.get(Service, request.form.get("service_id", type=int))
    if service is None:
        flash(t("visits.proc_need"), "danger")
        return redirect(url_for("visits.record", visit_id=visit.id) + "#proc")
    db.session.add(VisitService(
        visit_id=visit.id, service_id=service.id,
        name=service.display_name(getattr(g, "lang", "ar")),
        quantity=max(request.form.get("quantity", type=int) or 1, 1),
        notes=(request.form.get("notes") or "").strip() or None,
    ))
    ActivityLog.record("visit.add_service", user_id=current_user.id, entity="visit",
                       entity_id=visit.id, detail=service.name, ip_address=client_ip())
    db.session.commit()
    flash(t("visits.proc_added"), "success")
    return redirect(url_for("visits.record", visit_id=visit.id) + "#proc")


@visits_bp.route("/services/<int:vs_id>/delete", methods=["POST"])
@module_required(MODULE)
def delete_service(vs_id):
    vs = db.get_or_404(VisitService, vs_id)
    visit_id = vs.visit_id
    db.session.delete(vs)
    db.session.commit()
    flash(t("visits.proc_removed"), "info")
    return redirect(url_for("visits.record", visit_id=visit_id) + "#proc")


@visits_bp.route("/<int:visit_id>/give-vaccine", methods=["POST"])
@module_required(MODULE)
def give_vaccine(visit_id):
    """Administer a vaccine dose during the visit: deduct stock + record the
    dose. Billing is handled automatically by the cashier, which sweeps up
    recently-given uncharged doses — so we never bill here (no double charge).
    """
    from app.models import Vaccine
    from app.utils.vaccines import administer_dose, chosen_brand

    visit = db.get_or_404(Visit, visit_id)
    vaccine = db.session.get(Vaccine, request.form.get("vaccine_id", type=int))
    if vaccine is None:
        flash(t("vaccinations.no_brand"), "danger")
        return redirect(url_for("visits.record", visit_id=visit.id) + "#vac")

    brand_id = request.form.get("brand_id", type=int)
    req_brand = next((b for b in vaccine.brands if b.id == brand_id), None)
    # Deliberately mixing brands is allowed, but flag it so it's never silent.
    locked, is_locked = chosen_brand(visit.patient_id, vaccine)
    if is_locked and not vaccine.is_seasonal and req_brand and locked and req_brand.id != locked.id:
        lang = getattr(g, "lang", "ar")
        flash(t("vaccinations.brand_mixed_warn", old=locked.display_name(lang),
                new=req_brand.display_name(lang)), "warning")
    pv, result = administer_dose(
        visit.patient, vaccine, brand=req_brand,
        dose_number=request.form.get("dose_number", type=int),
        doctor_id=visit.doctor_id or current_user.id,
        given_outside=bool(request.form.get("given_outside")),
    )
    if pv is None:
        flash(t(f"vaccinations.{result}"),
              {"dose_exists": "warning", "all_done": "info"}.get(result, "danger"))
        return redirect(url_for("visits.record", visit_id=visit.id) + "#vac")

    ActivityLog.record("visit.give_vaccine", user_id=current_user.id, entity="visit",
                       entity_id=visit.id, detail=f"{vaccine.code}#{pv.dose_number}",
                       ip_address=client_ip())
    db.session.commit()
    # COGS for the consumed dose (W3): Dr 5020 / Cr 1040 at batch cost.
    # Best-effort — a bookkeeping hiccup must never block care.
    try:
        from app.utils import accounting as acct
        acct.post_dose_cogs(pv, user_id=current_user.id)
    except Exception:  # noqa: BLE001
        db.session.rollback()
    flash(t("visits.vac_given"), "success")
    return redirect(url_for("visits.record", visit_id=visit.id) + "#vac")


@visits_bp.route("/<int:visit_id>/plan-dose", methods=["POST"])
@module_required(MODULE)
def plan_dose(visit_id):
    """The doctor sets/updates the expected date of an upcoming dose — their
    schedule wins over the computed one (shows on the tab, prints, reminders)."""
    from datetime import date as _date

    from app.models import Vaccine
    from app.utils.vaccines import plan_dose as _plan

    visit = db.get_or_404(Visit, visit_id)
    vaccine = db.session.get(Vaccine, request.form.get("vaccine_id", type=int))
    dose_number = request.form.get("dose_number", type=int)
    raw = (request.form.get("planned_date") or "").strip()
    try:
        on_date = _date.fromisoformat(raw)
    except ValueError:
        on_date = None
    if vaccine is None or not dose_number or on_date is None:
        flash(t("visits.vac_plan_bad"), "danger")
        return redirect(url_for("visits.record", visit_id=visit.id) + "#vac")
    row = _plan(visit.patient, vaccine, dose_number, on_date)
    if row is None:
        flash(t("vaccinations.no_brand"), "danger")
        return redirect(url_for("visits.record", visit_id=visit.id) + "#vac")
    ActivityLog.record("visit.plan_dose", user_id=current_user.id, entity="visit",
                       entity_id=visit.id,
                       detail=f"{vaccine.code}#{dose_number}={on_date.isoformat()}",
                       ip_address=client_ip())
    db.session.commit()
    flash(t("visits.vac_plan_saved"), "success")
    return redirect(url_for("visits.record", visit_id=visit.id) + "#vac")


@visits_bp.route("/investigations/<int:inv_id>/result", methods=["POST"])
@module_required(MODULE)
def result_investigation(inv_id):
    """Record the result text + the doctor's interpretation/comment."""
    inv = db.get_or_404(VisitInvestigation, inv_id)
    inv.result_text = (request.form.get("result_text") or "").strip() or None
    inv.result_comment = (request.form.get("result_comment") or "").strip() or None
    if inv.has_result:
        inv.status = "resulted"
        inv.resulted_at = datetime.utcnow()
    else:
        inv.status = "requested"
        inv.resulted_at = None
    db.session.commit()
    flash(t("visits.inv_result_saved"), "success")
    # Return to the page the result was entered from (e.g. the follow-up
    # consultation reviewing a previous visit's pending test).
    return redirect(request.referrer or (url_for("visits.record", visit_id=inv.visit_id) + "#inv"))


@visits_bp.route("/investigations/<int:inv_id>/delete", methods=["POST"])
@module_required(MODULE)
def delete_investigation(inv_id):
    inv = db.get_or_404(VisitInvestigation, inv_id)
    visit_id = inv.visit_id
    db.session.delete(inv)
    db.session.commit()
    flash(t("visits.inv_removed"), "info")
    return redirect(url_for("visits.record", visit_id=visit_id) + "#inv")


# ---------------------------------------------- patient file attachments ----
@visits_bp.route("/<int:visit_id>/attachments", methods=["POST"])
@module_required(MODULE)
def upload_attachment(visit_id):
    """Upload a result/report file to the patient's file from the visit."""
    visit = db.get_or_404(Visit, visit_id)
    file = request.files.get("file")
    if not file or not file.filename:
        flash(t("visits.att_need_file"), "danger")
        return redirect(url_for("visits.record", visit_id=visit.id) + "#files")
    stored = save_document(file)
    if not stored:
        flash(t("visits.att_bad_type"), "warning")
        return redirect(url_for("visits.record", visit_id=visit.id) + "#files")

    kind = request.form.get("kind")
    db.session.add(PatientAttachment(
        patient_id=visit.patient_id, visit_id=visit.id,
        filename=stored, original_name=file.filename,
        kind=kind if kind in ATTACHMENT_KINDS else "report",
        label=(request.form.get("label") or "").strip() or None,
        uploaded_by=current_user.id,
    ))
    db.session.commit()
    flash(t("visits.att_uploaded"), "success")
    return redirect(url_for("visits.record", visit_id=visit.id) + "#files")


@visits_bp.route("/attachments/<int:att_id>/delete", methods=["POST"])
@module_required(MODULE)
def delete_attachment(att_id):
    att = db.get_or_404(PatientAttachment, att_id)
    visit_id = att.visit_id
    remove_document(att.filename)
    db.session.delete(att)
    db.session.commit()
    flash(t("visits.att_removed"), "info")
    fallback = url_for("visits.record", visit_id=visit_id) + "#files" if visit_id else url_for("visits.index")
    return redirect(request.referrer or fallback)


def _send_feedback_survey(visit, force=False):
    """Queue/send a post-visit satisfaction survey.

    Auto path (``force=False``): only when the ``feedback`` type is active and
    no survey exists yet for the visit. Manual path (``force=True``): always,
    reusing the visit's existing survey token if there is one. Returns the
    MessageLog, or None when skipped.
    """
    tpl = wa.template_for("feedback")
    if not force and (tpl is None or not tpl.is_active):   # type switched off
        return None
    patient = visit.patient
    phone = patient.contact_phone if patient else None
    if not phone:
        return None

    fb = Feedback.query.filter_by(visit_id=visit.id).first()
    if fb is None:
        fb = Feedback(patient_id=visit.patient_id, visit_id=visit.id,
                      doctor_id=visit.doctor_id, token=Feedback.new_token(),
                      created_by=current_user.id)
        db.session.add(fb)
    elif not force:                                        # already sent
        return None

    lang = getattr(g, "lang", "ar")
    # {link} depends on the survey delivery mode: the built-in page, an
    # external form (Google Form — works when the program is LAN-only), or
    # nothing (inline mode: the questions ride inside the message itself and
    # the patient just replies on WhatsApp).
    from app.utils.feedback import inline_survey_text, survey_delivery
    mode, ext_url = survey_delivery()
    if mode == "external" and ext_url:
        link = ext_url
    elif mode == "inline":
        link = ""
    else:
        link = wa.feedback_link(fb.token)
    body = wa.render(wa.template_body("feedback"), {
        "patient": patient.display_name(lang) if patient else "",
        "clinic": Setting.get("clinic_name_ar") or Setting.get("clinic_name") or "",
        "doctor": visit.doctor.display_name(lang) if visit.doctor else "",
        "link": link,
    }).strip()
    if mode == "inline":
        body = f"{body}\n\n{inline_survey_text(lang)}"
    # Honour the template's schedule (e.g. "send the survey N days after the
    # visit"); None means send as soon as due.
    from app.models.message import _template_schedule
    schedule_at = _template_schedule(tpl) if tpl is not None else None
    return wa.send(body, phone, patient_id=visit.patient_id, user_id=current_user.id,
                   template_type="feedback", image_url=wa.template_image("feedback"),
                   scheduled_at=schedule_at)


@visits_bp.route("/<int:visit_id>/send-survey", methods=["POST"])
@module_required(MODULE)
def send_survey(visit_id):
    """Manually send (or re-send) the satisfaction survey for a visit."""
    visit = db.get_or_404(Visit, visit_id)
    log = _send_feedback_survey(visit, force=True)
    db.session.commit()
    if log is None:
        flash(t("visits.survey_no_phone"), "warning")
    elif log.status == "link":
        flash(t("visits.survey_link_ready"), "success")
    else:
        flash(t("visits.survey_sent"), "success")
    return redirect(request.referrer or url_for("visits.view", visit_id=visit.id))


# ------------------------------------------------------------ complete -----
@visits_bp.route("/<int:visit_id>/complete", methods=["POST"])
@module_required(MODULE)
def complete(visit_id):
    visit = db.get_or_404(Visit, visit_id)
    visit.status = "completed"
    visit.completed_at = datetime.utcnow()

    # Close a linked, still-active appointment.
    if visit.appointment and visit.appointment.status in ("waiting", "in_progress", "scheduled"):
        visit.appointment.apply_status("completed")

    ActivityLog.record(
        "visit.complete", user_id=current_user.id, entity="visit",
        entity_id=visit.id, ip_address=client_ip(),
    )
    _send_feedback_survey(visit)  # post-visit satisfaction survey (if enabled)
    db.session.commit()
    flash(t("visits.completed"), "success")
    return redirect(url_for("visits.view", visit_id=visit.id))


# ---------------------------------------------------------------- view -----
@visits_bp.route("/<int:visit_id>")
@module_required(MODULE)
def view(visit_id):
    visit = db.get_or_404(Visit, visit_id)
    return render_template("visits/view.html", visit=visit)


# -------------------------------------------------------- icd search -------
@visits_bp.route("/icd")
@module_required(MODULE)
def icd():
    return jsonify({"results": search_icd(request.args.get("q", ""))})


# ================================================= device studies (C.2) =====
@visits_bp.route("/studies/new/<int:patient_id>", methods=["GET", "POST"])
@module_required(MODULE)
def study_new(patient_id):
    """Record a manually-entered device study (spirometry/ECG/…) for a patient:
    pick a device and enter its measurement-template values, flagged in/out of
    the normal range."""
    from datetime import datetime as _dt

    from app.models import DeviceStudy, DeviceStudyValue, MedicalDevice

    patient = db.get_or_404(Patient, patient_id)
    devices = (MedicalDevice.query.filter_by(is_active=True)
               .order_by(MedicalDevice.name).all())
    device_id = request.values.get("device_id", type=int)
    device = db.session.get(MedicalDevice, device_id) if device_id else None

    if request.method == "POST" and device is not None:
        try:
            sdate = _dt.strptime((request.form.get("study_date") or "").strip(),
                                 "%Y-%m-%d").date()
        except ValueError:
            sdate = _dt.utcnow().date()
        # Attach to the patient's open visit, if any.
        open_visit = (Visit.query.filter_by(patient_id=patient.id, status="open")
                      .order_by(Visit.created_at.desc()).first())
        study = DeviceStudy(
            patient_id=patient.id, device_id=device.id,
            visit_id=open_visit.id if open_visit else None, study_date=sdate,
            performed_by=current_user.id,
            conclusion=(request.form.get("conclusion") or "").strip() or None,
            notes=(request.form.get("notes") or "").strip() or None)
        for m in device.measurements:
            raw = (request.form.get(f"value_{m.id}") or "").strip()
            if raw == "":
                continue
            study.values.append(DeviceStudyValue(
                measurement_id=m.id, name=m.name, unit=m.unit,
                value=raw, flag=m.flag(raw)))
        db.session.add(study)
        ActivityLog.record("study.create", user_id=current_user.id,
                           entity="device_study", detail=device.name,
                           ip_address=client_ip())
        db.session.commit()
        flash(t("study.saved"), "success")
        return redirect(url_for("visits.study_view", study_id=study.id))

    return render_template("visits/study_new.html", patient=patient,
                           devices=devices, device=device,
                           today=datetime.utcnow().date().isoformat())


@visits_bp.route("/studies/<int:study_id>")
@module_required(MODULE)
def study_view(study_id):
    from app.models import DeviceStudy
    from app.utils.spirometry import analyse

    study = db.get_or_404(DeviceStudy, study_id)
    return render_template("visits/study_view.html", study=study,
                           spiro=analyse(study))


@visits_bp.route("/studies/<int:study_id>/print")
@module_required(MODULE)
def study_print(study_id):
    """Printable device-study report with a per-print language choice (?lang=)."""
    from app.models import DeviceStudy
    from app.utils.spirometry import analyse

    lang = request.args.get("lang")
    if lang in ("ar", "en"):
        from app.i18n import get_direction
        g.lang = lang
        g.direction = get_direction(lang)
    study = db.get_or_404(DeviceStudy, study_id)
    return render_template("visits/study_print.html", study=study,
                           spiro=analyse(study), today=datetime.utcnow().date())
