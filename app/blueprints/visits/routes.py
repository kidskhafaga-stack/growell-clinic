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
    VisitMedication,
    VisitService,
    VitalSigns,
)
from app.utils import whatsapp as wa
from app.utils.decorators import client_ip, module_required
from app.utils.paging import paginate
from app.utils.icd import available_versions, search_icd
from app.utils import phrases
from app.utils.uploads import ATTACHMENT_KINDS, remove_document, save_document
from app.utils.clock import local_today

MODULE = "visits"


def _visit_chips(field, user=None):
    """This doctor's quick phrases for a visit field.

    The phrases themselves, the storage format and the doctor-versus-clinic
    fallback all live in ``app.utils.phrases`` now. They used to be spelt out
    in three files, which is how the settings screen came to show the
    signed-in doctor's list under a heading that said "the clinic's".
    """
    return phrases.for_user(user if user is not None else current_user, field)


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
    # The list prints each visit's patient and its diagnoses.
    from sqlalchemy.orm import selectinload

    pagination = paginate(
        query.options(selectinload(Visit.patient),
                      selectinload(Visit.diagnoses))
        .order_by(Visit.created_at.desc()))
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
def _stamp_consultation_start(visit):
    """Mark the consultation as begun, because the doctor just opened it.

    The appointment has carried a ``started_at`` column for a long time and it
    was almost always empty: the only thing that set it was a status button on
    the board, and in a running clinic nobody stops to press it. So the timing
    reports were averaging a field that barely existed.

    Opening the record is the honest moment. It is the doctor's own action, it
    happens exactly when the consultation starts, and nobody at the front desk
    can move it earlier or later.

    Three guards, each for a way the stamp would otherwise lie:

    * **Only the visit's own doctor.** An admin or a colleague opening the
      file to look something up is not the start of a consultation — and with
      the privacy policy off, plenty of people can open it.
    * **Only once.** A doctor opens and closes the screen several times in one
      consultation; the first time is the one that means anything.
    * **Only from a status that precedes it.** A completed appointment
      reopened next week to fix a typo must not be dragged back into today.
    """
    appt = visit.appointment
    if appt is None or appt.started_at is not None:
        return
    if current_user.id != visit.doctor_id:
        return
    if not appt.can_transition_to("in_progress"):
        return
    appt.apply_status("in_progress")
    db.session.commit()


@visits_bp.route("/<int:visit_id>/record", methods=["GET", "POST"])
@module_required(MODULE)
def record(visit_id):
    from app.utils.privacy import can_see_visit

    visit = db.get_or_404(Visit, visit_id)
    if not can_see_visit(visit):
        flash(t("visits.not_yours"), "warning")
        return redirect(url_for("visits.index"))

    _stamp_consultation_start(visit)

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
    # Files on this child's record answering nothing yet — what the doctor
    # picks from when the matcher couldn't be sure (a report sent with no
    # caption, a scan taken at the desk).
    linkable_files = (
        PatientAttachment.query.filter(
            PatientAttachment.patient_id == visit.patient_id,
            PatientAttachment.investigation_id.is_(None),
        ).order_by(PatientAttachment.created_at.desc()).limit(20).all()
    )
    procedure_services = (
        Service.query.filter(Service.is_active.is_(True),
                             Service.category.in_(("procedure", "lab", "radiology")))
        .order_by(Service.name).all()
    )
    # What this doctor actually performs, first — and everything else still
    # underneath it. Split by the *visit's* doctor, not by whoever is logged
    # in: reception opening Dr X's visit is choosing from Dr X's list.
    from app.utils import patient_meds as _meds
    from app.utils.doctor_services import split as _split_services
    my_services, other_services = _split_services(visit.doctor, procedure_services)
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
    # Informed consent, where it is actually needed: what this visit calls for
    # (a procedure, a study, a vaccine) and what the file already has signed.
    from app.utils.consent import (all_statements as consent_statements,
                                   default_guardian, visit_status)
    consent = visit_status(visit)
    consent_guardian = default_guardian(visit.patient)
    # Devices the doctor can run in this visit, with what each one charges —
    # so "book an echo" and "the echo is on the bill" are the same action.
    from app.models import MedicalDevice
    study_devices = []
    for dev in (MedicalDevice.query.filter_by(is_active=True)
                .order_by(MedicalDevice.name).all()):
        svc = next((sv for sv in dev.services if sv.is_active), None)
        charged_row = next((vs for vs in visit.services
                            if svc and vs.service_id == svc.id), None)
        study_devices.append({
            "device": dev, "service": svc,
            "price": (svc.price_for(visit.doctor) if svc else None),
            "charged": charged_row is not None,
            # Already on an invoice? then the cashier has taken it — the study
            # screen says so instead of leaving the doctor to wonder.
            "invoiced": bool(charged_row and charged_row.invoice_id),
            "consumables": [(c.item.display_name(getattr(g, "lang", "ar")), c.quantity)
                            for c in (svc.consumables if svc else []) if c.item],
        })
    # Medicines written in this visit + their safety check (dose for this
    # child's weight/age, and interactions between what's on the list).
    from app.utils.rx_safety import check as rx_check
    med_safety = rx_check(visit.medications, patient=visit.patient,
                          lang=getattr(g, "lang", "ar"))
    # Which of them already printed on a prescription for this visit — so the
    # room list and the prescription read as one thing, not two parallel lists.
    prescribed_names = {(" ".join((it.drug_name or "").split())).lower()
                        for rx in visit.prescriptions for it in rx.items}
    # The same judgement the nurse's station makes, in front of the person who
    # decides. The numbers were already on this screen — a red-tinted input box
    # says "38.7 is high" but not "38.7 is high *for a child this age*", and the
    # age band is the whole point. A doctor who has read the thermometer still
    # benefits from the line that names the rule, and one who is half-way
    # through a busy morning benefits from it more.
    from app.utils.red_flags import assess_visit
    red_flag = assess_visit(visit)
    from app.utils import ai
    return render_template(
        "visits/record.html", visit=visit, recent_visits=recent_visits,
        red_flag=red_flag,
        med_safety=med_safety, prescribed_names=prescribed_names,
        study_devices=study_devices, consent=consent,
        consent_guardian=consent_guardian,
        consent_statements=consent_statements(),
        pending_investigations=pending_investigations,
        recent_attachments=recent_attachments, linkable_files=linkable_files,
        procedure_services=procedure_services, recent_meds=recent_meds,
        # Medication reconciliation (GAHAR): the child's ongoing medicines and
        # what has already been decided about each at *this* encounter.
        ongoing_meds=_meds.current(visit.patient),
        reviewed_meds=_meds.reviewed_ids(visit.patient, visit),
        meds_reconciled=_meds.reconciled(visit.patient, visit),
        my_services=my_services, other_services=other_services,
        vac_panel=vac_panel, mandatory_vaccines=mandatory_vaccines,
        complaint_chips=_visit_chips("complaint"),
        exam_chips=_visit_chips("exam"),
        plan_chips=_visit_chips("plan"),
        # The codes the browser expands as the doctor types: "نورمال" and a
        # space becomes the paragraph they wrote once.
        phrase_codes=phrases.codes(current_user, getattr(g, "lang", "ar")),
        # Only the classifications this machine actually holds. ICD-11 joins
        # the list the moment it is imported, and stays out of it until then.
        icd_versions=available_versions(),
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
    res = ai.chat([{"role": "user", "content": text}], system=system,
                  feature="visit_summary")
    if res.get("ok"):
        ActivityLog.record("visit.ai_summary", user_id=current_user.id,
                           entity="visit", entity_id=visit.id, ip_address=client_ip())
        db.session.commit()
    return jsonify(ai.as_json(res))


# ------------------------------------------------------- nurse station -----
@visits_bp.route("/station")
@module_required(MODULE)
def station():
    """Nurse vitals station: today's checked-in queue with a quick vitals entry
    per child, so weight/height/temp/… are captured before the doctor sees them.
    Saving pre-fills the open visit the doctor then continues."""
    from app.models import Appointment

    from app.utils.patients import apply_patient_search
    from app.utils.red_flags import assess

    from app.models import NursingStation

    today = local_today()
    # Which station this screen is standing at. A nurse serving three of eight
    # عيادات was shown all eight and had to find their children in somebody
    # else's list every time.
    #
    # The scope hangs off the **station**, not the nurse: staff rotate, and a
    # preference stored on the person walks off with them the day they cover
    # another shift. The choice is remembered per user only so nobody re-picks
    # it every morning — the switcher on the screen changes it in one press.
    stations = (NursingStation.query.filter_by(is_active=True)
                .order_by(NursingStation.sort_order, NursingStation.id).all())
    asked = request.args.get("station", type=int)
    station = None
    if asked:
        station = next((s for s in stations if s.id == asked), None)
    elif current_user.nursing_station_id:
        station = next((s for s in stations
                        if s.id == current_user.nursing_station_id), None)
    if asked and station is not None and current_user.nursing_station_id != station.id:
        current_user.nursing_station_id = station.id
        db.session.commit()

    appts = (Appointment.query
             .filter(Appointment.appt_date == today,
                     Appointment.status.in_(("waiting", "in_progress")))
             .order_by(Appointment.appt_time)
             .all())
    if station is not None:
        # Rooms, resolved to today's doctors. A station with no rooms yet
        # covers nobody rather than everybody — see the model for why.
        mine = station.doctor_ids_on(today)
        appts = [a for a in appts if a.doctor_id in mine]
    # A nurse looking for one child should not scroll a morning's list. The
    # search narrows what is already here rather than opening the register —
    # somebody not checked in today is not somebody this station can weigh.
    query = (request.args.get("q") or "").strip()
    if query:
        matched = {p.id for p in apply_patient_search(Patient.query, query).all()}
        appts = [a for a in appts if a.patient_id in matched]

    rows = []
    for a in appts:
        v = (Visit.query.filter_by(patient_id=a.patient_id, status="open")
             .order_by(Visit.created_at.desc()).first())
        vitals = v.vitals if v else None
        # Read the moment they are saved rather than when the child's turn
        # comes. The numbers were always in the file; nobody was reading them.
        flag = assess(a.patient, vitals,
                      " ".join(filter(None, [a.reason,
                                             getattr(v, "chief_complaint", "")])))
        rows.append({"appt": a, "patient": a.patient, "visit": v,
                     "vitals": vitals, "flag": flag,
                     "done": bool(vitals and vitals.has_growth)})
    # The ones that should not still be sitting there come first. Nothing is
    # reordered anywhere else — this is a nurse's worklist, not the queue.
    order = {"urgent": 0, "watch": 1}
    rows.sort(key=lambda r: (order.get(r["flag"]["level"], 2),
                             r["appt"].appt_time))
    return render_template("visits/station.html", rows=rows, today=today,
                           q=query, stations=stations, station=station)


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
    # The nurse hears the story the guardian tells at the scale, and it is
    # usually fuller than the one line booked at reception. Appended rather
    # than replaced: "متابعة" typed a week ago is not wrong, it is just not
    # all of it — and the red-flag read depends on those words.
    typed = (request.form.get("reason") or "").strip()
    if typed and typed != (appt.reason or "").strip():
        appt.reason = typed[:200]
    # The moment the nurse is done — it splits the wait at reception from the
    # wait at the doctor's door, which are two different queues with two
    # different causes. Stamped once: the nurse may correct a weight later,
    # and a correction is not a second visit to the station.
    if appt.vitals_at is None:
        appt.vitals_at = datetime.utcnow()
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


# ------------------------------------------------ medicines in the visit ----
def _search_age_months():
    """The age of the child the search is being run for, when we know it.

    Passed as ``patient_id`` by the screen doing the asking. Absent is a real
    answer — a search with no patient behind it ranks on the text alone, which
    is exactly what it did before.
    """
    from app.models import Patient
    from app.utils.dosing import age_months_of

    patient_id = request.args.get("patient_id", type=int)
    if not patient_id:
        return None
    patient = db.session.get(Patient, patient_id)
    return age_months_of(patient) if patient is not None else None


@visits_bp.route("/drugs/search")
@module_required(MODULE)
def drug_search():
    """Autocomplete for writing a medicine inside the visit (brand or
    ingredient), carrying the dosing rule so the room can check it live.

    Same search the prescription writer uses — see
    :mod:`app.utils.drug_search` for why there is only one of them now.
    """
    from app.utils.drug_search import search_drugs

    return jsonify(search_drugs(request.args.get("q"),
                                age_months=_search_age_months(),
                                lang=getattr(g, "lang", "ar"), limit=12))


@visits_bp.route("/<int:visit_id>/reconcile/<int:med_id>", methods=["POST"])
@module_required(MODULE)
def reconcile_medication(visit_id, med_id):
    """Record the decision taken about one ongoing medicine at this visit.

    Continue is stored like the others rather than skipped. Storing only the
    stops and changes would leave a medicine somebody deliberately continued
    and a medicine nobody looked at with the same trace — nothing — and
    reconciliation is precisely the claim that the whole list was looked at.
    """
    from app.models import PatientMedication
    from app.utils import patient_meds as meds

    visit = db.get_or_404(Visit, visit_id)
    row = db.get_or_404(PatientMedication, med_id)
    if row.patient_id != visit.patient_id:
        flash(t("visits.not_yours"), "danger")
        return redirect(url_for("visits.record", visit_id=visit.id) + "#meds")

    saved = meds.review(row, (request.form.get("decision") or "").strip(),
                        user=current_user, visit=visit,
                        note=request.form.get("note"))
    flash(t("meds.reviewed") if saved else t("meds.bad_decision"),
          "success" if saved else "danger")
    return redirect(url_for("visits.record", visit_id=visit.id) + "#meds")


@visits_bp.route("/<int:visit_id>/medications", methods=["POST"])
@module_required(MODULE)
def add_medication(visit_id):
    """Write a medicine during the visit. It carries over to the prescription,
    and its dose/interactions are checked against this child on the spot."""
    from app.models import Drug, GenericDrug

    visit = db.get_or_404(Visit, visit_id)
    name = (request.form.get("name") or "").strip()
    drug = db.session.get(Drug, request.form.get("drug_id", type=int)) \
        if request.form.get("drug_id", type=int) else None
    generic_id = request.form.get("generic_id", type=int) or (
        drug.generic_id if drug is not None else None)
    if not name and drug is not None:
        name = drug.label(getattr(g, "lang", "ar"))
    if not name:
        flash(t("visits.med_need_name"), "danger")
        return redirect(url_for("visits.record", visit_id=visit.id) + "#meds")
    med = VisitMedication(
        visit_id=visit.id, patient_id=visit.patient_id,
        drug_id=drug.id if drug is not None else None,
        generic_id=(generic_id
                    if generic_id and db.session.get(GenericDrug, generic_id)
                    else None),
        name=name,
        dose=(request.form.get("dose") or "").strip() or None,
        frequency=(request.form.get("frequency") or "").strip() or None,
        duration=(request.form.get("duration") or "").strip() or None,
        instructions=(request.form.get("instructions") or "").strip() or None,
    )
    db.session.add(med)
    db.session.commit()
    # Say it now, in the room: a dose flag or a clash with what's already written.
    from app.utils.rx_safety import check as rx_check
    result = rx_check(visit.medications, patient=visit.patient,
                      lang=getattr(g, "lang", "ar"))
    for line in result["lines"]:
        if line["name"] != med.name:
            continue
        alg = line.get("allergy")
        if alg:
            # The loudest warning in the room: the file says this child reacts
            # to it. Never a block — the doctor decides, knowingly.
            flash(t("allergy.flash_" + alg["level"])
                  .replace("{drug}", med.name)
                  .replace("{allergy}", alg["allergy"]), "danger")
        for w in line["warnings"]:
            flash(f"{med.name}: " + t("drugbook.warn_" + w), "warning")
    for r in result["interactions"]:
        a, b = r.pair_names(getattr(g, "lang", "ar"))
        msg = t("rx.interaction_line").replace("{a}", a).replace("{b}", b)
        if r.note:
            msg += " — " + r.note
        if r.alternative:
            msg += " · " + t("rx.alternative") + ": " + r.alternative
        flash(msg, "danger" if r.severity == "severe" else "warning")
    flash(t("visits.med_added"), "success")
    return redirect(url_for("visits.record", visit_id=visit.id) + "#meds")


@visits_bp.route("/medications/<int:med_id>/delete", methods=["POST"])
@module_required(MODULE)
def delete_medication(med_id):
    med = db.get_or_404(VisitMedication, med_id)
    visit_id = med.visit_id
    db.session.delete(med)
    db.session.commit()
    flash(t("visits.med_removed"), "info")
    return redirect(url_for("visits.record", visit_id=visit_id) + "#meds")


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


def _interval_message(vaccine, warn):
    """The warning in words, with the dates in it — "too soon" on its own
    leaves the doctor to go and look up when the last one was."""
    return t("vaccinations.interval_warn",
             vaccine=vaccine.display_name(getattr(g, "lang", "ar")),
             dose=warn["previous_dose"], days=warn["days"],
             date=warn["previous_date"].isoformat(), min=warn["minimum"])


@visits_bp.route("/<int:visit_id>/give-vaccine", methods=["POST"])
@module_required(MODULE)
def give_vaccine(visit_id):
    """Administer a vaccine dose during the visit: deduct stock + record the
    dose. Billing is handled automatically by the cashier, which sweeps up
    recently-given uncharged doses — so we never bill here (no double charge).
    """
    from app.models import Vaccine
    from app.utils.vaccines import (administer_dose, chosen_brand,
                                    interval_warning)

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
    # Too soon after the last dose of this same vaccine — the thing that let
    # two doses go into one visit without a word. Read before the record is
    # written, because afterwards "the last dose" is the one being given.
    too_soon = interval_warning(visit.patient_id, vaccine)
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

    if too_soon:
        flash(_interval_message(vaccine, too_soon), "warning")
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

    # The message to the family. It used to be written only by the
    # vaccinations screen, so a dose given here — which is where most of them
    # are given — told the parent nothing about the next one.
    from app.utils.vaccine_notify import notify_dose

    _, reason = notify_dose(visit.patient, vaccine, pv.brand, pv.dose_number,
                            pv.given_date, user_id=current_user.id,
                            lang=getattr(g, "lang", "ar"))
    db.session.commit()
    if reason:
        flash(t("crm.not_sent", why=t("crm.reason_" + reason)), "warning")
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


@visits_bp.route("/results")
@module_required(MODULE)
def results():
    """The results that came back and nobody has read.

    Everything needed to deal with one is on its row: what was asked for, the
    file itself, how long it has been sitting there — and the family's
    conversation, because the answer to "the film is here" is usually
    something the doctor has to say to them, not a note to themselves.
    """
    from app.utils.privacy import doctor_locked_id
    from app.utils.results_inbox import arrived_unread

    mine = request.args.get("scope", "mine") != "all"
    doctor_id = doctor_locked_id() or (current_user.id if mine else None)
    # An admin or a receptionist has no films of their own to read; showing
    # them an empty list would look broken rather than scoped.
    if not current_user.is_practitioner and not doctor_locked_id():
        doctor_id = None
        mine = False
    rows = arrived_unread(doctor_id=doctor_id)
    return render_template("visits/results.html", rows=rows, mine=mine,
                           can_scope=bool(doctor_locked_id() is None
                                          and current_user.is_practitioner))


@visits_bp.route("/investigations/<int:inv_id>/decide", methods=["POST"])
@module_required(MODULE)
def decide_on_result(inv_id):
    """Read the result, decide, tell the family — and write it in the file.

    One action because it is one thought. Splitting it would leave the three
    halves able to disagree: an order marked read with no decision, a message
    sent with nothing recorded, a note in the file the family never heard.
    """
    from app.utils.teleconsult import message_for, record_decision

    order = db.get_or_404(VisitInvestigation, inv_id)
    decision = (request.form.get("decision") or "").strip()
    note = (request.form.get("note") or "").strip() or None
    new_test = {"name": request.form.get("test_name"),
                "kind": request.form.get("test_kind"),
                "notes": request.form.get("test_notes")}

    visit, error = record_decision(
        order, current_user, decision, note=note, new_test=new_test,
        result_text=request.form.get("result_text"),
        result_comment=request.form.get("result_comment"))
    if visit is None:
        flash(t(f"teleconsult.{error}"), "danger")
        return redirect(url_for("visits.results"))

    # Tell the family, from the clinic's number. Best-effort: the record of
    # the decision is the part that must not be lost, and a provider outage
    # must never cost it.
    lang = getattr(g, "lang", "ar")
    body = (request.form.get("message") or "").strip() \
        or message_for(order, decision, note, lang)
    phone = order.patient.contact_phone if order.patient else None
    sent = False
    if body and phone:
        try:
            wa.send(body, phone, patient_id=order.patient_id,
                    user_id=current_user.id)
            sent = True
        except Exception:  # noqa: BLE001 - never lose the record over a send
            pass

    ActivityLog.record("visit.teleconsult", user_id=current_user.id,
                       entity="visit", entity_id=visit.id,
                       detail=f"{decision}:{order.id}", ip_address=client_ip())
    db.session.commit()
    flash(t("teleconsult.recorded" if sent else "teleconsult.recorded_no_send"),
          "success" if sent else "warning")
    return redirect(url_for("visits.results"))


@visits_bp.route("/investigations/<int:inv_id>/attach", methods=["POST"])
@module_required(MODULE)
def attach_to_investigation(inv_id):
    """Tie a file already on the child's record to the order it answers.

    The matcher links what it is sure of and leaves the rest alone; this is
    how a person settles the rest — the report sent with no caption, the film
    the matcher gave to the wrong one of two outstanding orders, the scan
    reception took at the desk. A link made here is signed, so the screen can
    tell a doctor's decision apart from the program's guess.
    """
    inv = db.get_or_404(VisitInvestigation, inv_id)
    att = db.session.get(PatientAttachment,
                         request.form.get("attachment_id", type=int))
    # Only this child's files: an order must never be able to reach across
    # into another patient's record.
    if att is None or att.patient_id != inv.patient_id:
        flash(t("visits.inv_file_not_found"), "danger")
        return redirect(url_for("visits.record", visit_id=inv.visit_id) + "#inv")
    att.investigation_id = inv.id
    att.linked_by = current_user.id
    att.linked_at = datetime.utcnow()
    ActivityLog.record("visit.link_result", user_id=current_user.id,
                       entity="investigation", entity_id=inv.id,
                       detail=str(att.id), ip_address=client_ip())
    db.session.commit()
    flash(t("visits.inv_file_linked"), "success")
    return redirect(request.referrer
                    or (url_for("visits.record", visit_id=inv.visit_id) + "#inv"))


@visits_bp.route("/attachments/<int:att_id>/unlink", methods=["POST"])
@module_required(MODULE)
def unlink_attachment(att_id):
    """Take a file off an order — the match was wrong, or it answered another
    question. The file stays on the child's record; only the link goes."""
    att = db.get_or_404(PatientAttachment, att_id)
    inv = att.investigation
    att.investigation_id = None
    att.linked_by = None
    att.linked_at = None
    ActivityLog.record("visit.unlink_result", user_id=current_user.id,
                       entity="investigation",
                       entity_id=inv.id if inv else None, detail=str(att.id),
                       ip_address=client_ip())
    db.session.commit()
    flash(t("visits.inv_file_unlinked"), "info")
    fallback = (url_for("visits.record", visit_id=inv.visit_id) + "#inv"
                if inv else url_for("patients.view", patient_id=att.patient_id))
    return redirect(request.referrer or fallback)


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


def _survey_unsent(visit, reason):
    """Record that the post-visit survey did not go out, and why.

    The row is returned, not swallowed: a caller that wants to tell the doctor
    "the survey did not go, and here is why" needs the reason, and a caller
    that only wants to know whether anything was sent can read the status.
    """
    from app.models import MessageLog

    log = MessageLog(patient_id=visit.patient_id, body="",
                     to_phone=visit.patient.contact_phone if visit.patient else None,
                     template_type="feedback", status="skipped", error=reason,
                     created_by=getattr(current_user, "id", None))
    db.session.add(log)
    return log


def _send_feedback_survey(visit, force=False):
    """Queue/send a post-visit satisfaction survey.

    Auto path (``force=False``): only when the ``feedback`` type is active and
    no survey exists yet for the visit. Manual path (``force=True``): always,
    reusing the visit's existing survey token if there is one. Returns the
    MessageLog, or None when skipped.
    """
    tpl = wa.template_for("feedback")
    patient = visit.patient
    if not force and wa.type_is_off("feedback"):
        # Switched off deliberately. A clinic that has simply never opened the
        # templates screen still gets the survey, with the built-in wording —
        # treating "not set up" as "off" is how a clinic ends up never asking
        # a single family how the visit went.
        return _survey_unsent(visit, "type_off")
    phone = patient.contact_phone if patient else None
    if not phone:
        # A file with no number on it. Recorded rather than dropped: "the
        # message after the visit is not generated" was reported as a fault in
        # the program, and this is one of the two things it actually was.
        return _survey_unsent(visit, "missing_phone")

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
    elif log.status == "skipped":
        # No number on the file, or a family that asked not to be messaged —
        # two different things, and the screen used to call both "no phone".
        flash(t("crm.not_sent", why=t("crm.reason_" + (log.error or "missing_phone"))),
              "warning")
    elif log.status == "link":
        flash(t("visits.survey_link_ready"), "success")
    else:
        flash(t("visits.survey_sent"), "success")
    return redirect(request.referrer or url_for("visits.view", visit_id=visit.id))


# ------------------------------------------------- nursing and referral -----
@visits_bp.route("/<int:visit_id>/nurse-instructions", methods=["POST"])
@module_required(MODULE)
def nurse_instructions(visit_id):
    """What the doctor wants nursing to do with this child.

    Written in the room and read at the station. It was being called across a
    corridor — which is how an instruction reaches the wrong child, or nobody.
    """
    visit = db.get_or_404(Visit, visit_id)
    visit.nurse_instructions = (request.form.get("nurse_instructions")
                                or "").strip() or None
    ActivityLog.record("visit.nurse_instructions", user_id=current_user.id,
                       entity="visit", entity_id=visit.id, ip_address=client_ip())
    db.session.commit()
    flash(t("visits.nurse_saved"), "success")
    return redirect(request.referrer or url_for("visits.record", visit_id=visit.id))


@visits_bp.route("/<int:visit_id>/refer", methods=["POST"])
@module_required(MODULE)
def refer(visit_id):
    """Send this child to emergency, and say so on every screen that lists them.

    Recorded rather than remembered. The child leaves mid-encounter, and a
    visit that simply stops reads as a consultation somebody abandoned — the
    one record that has to survive the panic is where they went and why.

    Reversible, because a referral written on the wrong child is a thing that
    happens in exactly the minutes this button is pressed in.
    """
    visit = db.get_or_404(Visit, visit_id)
    if request.form.get("undo"):
        visit.referred_at = None
        visit.referred_to = None
        visit.referral_note = None
        db.session.commit()
        flash(t("visits.referral_undone"), "info")
        return redirect(request.referrer or url_for("visits.record", visit_id=visit.id))

    visit.referred_at = datetime.utcnow()
    visit.referred_to = (request.form.get("referred_to") or "").strip() or None
    visit.referral_note = (request.form.get("referral_note") or "").strip() or None
    ActivityLog.record("visit.refer", user_id=current_user.id, entity="visit",
                       entity_id=visit.id, detail=visit.referred_to or "",
                       ip_address=client_ip())
    db.session.commit()
    flash(t("visits.referred_ok"), "warning")
    return redirect(request.referrer or url_for("visits.record", visit_id=visit.id))


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
    log = _send_feedback_survey(visit)  # post-visit survey (if enabled)
    db.session.commit()
    flash(t("visits.completed"), "success")
    # Said here, once, rather than left for somebody to notice a month later
    # that no family has been asked how the visit went.
    if log is not None and log.status == "skipped":
        flash(t("crm.not_sent", why=t("crm.reason_" + (log.error or "type_off"))),
              "warning")
    return redirect(url_for("visits.view", visit_id=visit.id))


# ---------------------------------------------------------------- view -----
@visits_bp.route("/<int:visit_id>")
@module_required(MODULE)
def view(visit_id):
    visit = db.get_or_404(Visit, visit_id)
    return render_template("visits/view.html", visit=visit)


# ----------------------------------------------------- my quick phrases -----
@visits_bp.route("/phrases", methods=["GET", "POST"])
@module_required(MODULE)
def phrases_screen():
    """Each doctor's own shorthand — the phrases and the codes that write them.

    *"طبيب السكر غير طبيب حديثي الولادة، دكتور القلب غير حد تاني، والغدد"*.
    One clinic-wide list is the wrong shape: it grows until finding a sentence
    costs more than typing it, and most of it belongs to somebody else's
    specialty. This screen is the signed-in user's own list; leaving a field
    empty means "use the clinic's", so clearing it is how a doctor goes back
    to the defaults rather than ending up with nothing.

    The clinic's list is edited in settings, by whoever can reach settings.
    This is deliberately not that screen: a doctor should not need the
    settings module to write down the sentence they say forty times a day.
    """
    if request.method == "POST":
        for field in phrases.FIELDS:
            key = phrases.key_for(field)
            setattr(current_user, key,
                    (request.form.get(key) or "").strip() or None)
        db.session.commit()
        flash(t("phrases.saved"), "success")
        return redirect(url_for("visits.phrases_screen"))

    return render_template(
        "visits/phrases.html",
        fields=[{"key": phrases.key_for(f), "name": f,
                 "rows": phrases.for_user(current_user, f),
                 "mine": bool(getattr(current_user, phrases.key_for(f), None))}
                for f in phrases.FIELDS],
    )


# -------------------------------------------------------- icd search -------
@visits_bp.route("/icd")
@module_required(MODULE)
def icd():
    # A bare list, like ``prescriptions.icd_search``. One question asked from
    # two screens was answered in two shapes, which is the same drift that put
    # a missing ``strength`` in the drug list.
    return jsonify(search_icd(request.args.get("q", "")))


@visits_bp.route("/<int:visit_id>/consent", methods=["POST"])
@module_required(MODULE)
def add_visit_consent(visit_id):
    """Record a consent from inside the visit — the room is where the guardian
    is standing when the procedure is about to happen."""
    from app.utils.consent import record

    visit = db.get_or_404(Visit, visit_id)
    guardian = (request.form.get("guardian_name") or "").strip()
    if not guardian:
        flash(t("common.required") + ": " + t("consent.guardian_name"), "danger")
        return redirect(url_for("visits.record", visit_id=visit.id) + "#consent")
    row = record(
        visit.patient, (request.form.get("consent_type") or "general").strip(),
        guardian_name=guardian,
        relation=(request.form.get("guardian_relation") or "").strip() or None,
        id_no=(request.form.get("guardian_id_no") or "").strip() or None,
        notes=(request.form.get("notes") or "").strip() or None,
        user_id=current_user.id, on_date=visit.visit_date)
    ActivityLog.record("consent.add", user_id=current_user.id, entity="patient",
                       entity_id=visit.patient_id, detail=row.consent_type,
                       ip_address=client_ip())
    db.session.commit()
    flash(t("consent.added"), "success")
    return redirect(url_for("visits.record", visit_id=visit.id) + "#consent")


def _charge_study(device, visit):
    """Put the device's service on the visit so the study gets billed.

    Returns the added ``VisitService`` (or None when there's nothing to charge
    or it is already there — a study must never bill the family twice)."""
    if visit is None or device is None:
        return None
    service = next((s for s in device.services if s.is_active), None)
    if service is None:
        return None
    if any(vs.service_id == service.id for vs in visit.services):
        return None
    row = VisitService(
        visit_id=visit.id, service_id=service.id,
        name=service.display_name(getattr(g, "lang", "ar")), quantity=1)
    db.session.add(row)
    return row


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
            sdate = local_today()
        # Attach to the visit it was opened from, else the patient's open one.
        visit_id = request.values.get("visit_id", type=int)
        open_visit = db.session.get(Visit, visit_id) if visit_id else None
        if open_visit is None or open_visit.patient_id != patient.id:
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
        # Running a device costs money: the study charges its device's service
        # on the visit (once), and the cashier collects it like any other
        # procedure. Nothing is charged twice if the doctor already added it.
        charged = _charge_study(device, open_visit)
        ActivityLog.record("study.create", user_id=current_user.id,
                           entity="device_study", detail=device.name,
                           ip_address=client_ip())
        db.session.commit()
        flash(t("study.saved"), "success")
        if charged is not None:
            flash(t("study.charged").replace("{name}", charged.name), "info")
        return redirect(url_for("visits.study_view", study_id=study.id))

    return render_template("visits/study_new.html", patient=patient,
                           devices=devices, device=device,
                           visit_id=request.values.get("visit_id", type=int),
                           today=local_today().isoformat())


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
                           spiro=analyse(study), today=local_today())
