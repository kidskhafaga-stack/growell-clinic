"""Drugs & prescriptions (clinic): catalogue, writing, safety alerts, print."""
from datetime import datetime, timedelta

from flask import (
    flash, g, jsonify, redirect, render_template, request, url_for,
)
from flask_login import current_user
from sqlalchemy import or_

from app.blueprints.prescriptions import prescriptions_bp
from app.extensions import db
from app.i18n import t
from app.models import (
    DRUG_FORMS,
    ActivityLog,
    Drug,
    DrugInteraction,
    Patient,
    Prescription,
    PrescriptionItem,
    RxPrintTemplate,
    User,
)
from app.utils.decorators import admin_required, client_ip, module_required

MODULE = "prescriptions"


def interaction_warnings(drug_ids):
    """Return interaction rows among the given drug ids."""
    ids = [i for i in drug_ids if i]
    if len(ids) < 2:
        return []
    rows = DrugInteraction.query.filter(
        DrugInteraction.drug_a_id.in_(ids), DrugInteraction.drug_b_id.in_(ids)
    ).all()
    return rows


@prescriptions_bp.route("/")
@module_required(MODULE)
def index():
    page = request.args.get("page", 1, type=int)
    pagination = (
        Prescription.query.order_by(Prescription.id.desc())
        .paginate(page=page, per_page=25, error_out=False)
    )
    return render_template("prescriptions/index.html", pagination=pagination,
                           prescriptions=pagination.items)


# ----------------------------------------------------- drug catalogue ------
@prescriptions_bp.route("/drugs")
@admin_required
def drugs():
    q = (request.args.get("q") or "").strip()
    query = Drug.query
    if q:
        like = f"%{q}%"
        query = query.filter(or_(Drug.trade_name.ilike(like),
                                 Drug.generic_name.ilike(like)))
    drugs = query.order_by(Drug.trade_name).limit(500).all()
    return render_template("prescriptions/drugs.html", drugs=drugs,
                           forms=DRUG_FORMS, q=q)


@prescriptions_bp.route("/drugs/new", methods=["POST"])
@admin_required
def drug_new():
    trade = (request.form.get("trade_name") or "").strip()
    if not trade:
        flash(t("common.required") + ": " + t("rx.trade_name"), "danger")
        return redirect(url_for("prescriptions.drugs"))
    db.session.add(Drug(
        trade_name=trade,
        generic_name=(request.form.get("generic_name") or "").strip() or None,
        form=(request.form.get("form") or "").strip() or None,
        strength=(request.form.get("strength") or "").strip() or None,
        default_dose=(request.form.get("default_dose") or "").strip() or None,
        default_frequency=(request.form.get("default_frequency") or "").strip() or None,
        default_instructions=(request.form.get("default_instructions") or "").strip() or None,
        max_daily_dose=(request.form.get("max_daily_dose") or "").strip() or None,
    ))
    db.session.commit()
    flash(t("rx.drug_added"), "success")
    return redirect(url_for("prescriptions.drugs"))


@prescriptions_bp.route("/drugs/<int:drug_id>/edit", methods=["POST"])
@admin_required
def drug_edit(drug_id):
    d = db.get_or_404(Drug, drug_id)
    d.trade_name = (request.form.get("trade_name") or d.trade_name).strip()
    d.generic_name = (request.form.get("generic_name") or "").strip() or None
    d.form = (request.form.get("form") or "").strip() or None
    d.strength = (request.form.get("strength") or "").strip() or None
    d.default_dose = (request.form.get("default_dose") or "").strip() or None
    d.default_frequency = (request.form.get("default_frequency") or "").strip() or None
    d.default_instructions = (request.form.get("default_instructions") or "").strip() or None
    d.max_daily_dose = (request.form.get("max_daily_dose") or "").strip() or None
    d.is_active = bool(request.form.get("is_active"))
    db.session.commit()
    flash(t("rx.drug_updated"), "success")
    return redirect(url_for("prescriptions.drugs"))


@prescriptions_bp.route("/drugs/<int:drug_id>/delete", methods=["POST"])
@admin_required
def drug_delete(drug_id):
    d = db.get_or_404(Drug, drug_id)
    db.session.delete(d)
    db.session.commit()
    flash(t("rx.drug_deleted"), "info")
    return redirect(url_for("prescriptions.drugs"))


@prescriptions_bp.route("/drugs/search")
@module_required(MODULE)
def drug_search():
    """Autocomplete for the prescription writer (trade + generic)."""
    q = (request.args.get("q") or "").strip()
    if len(q) < 1:
        return jsonify([])
    like = f"%{q}%"
    drugs = (
        Drug.query.filter(Drug.is_active.is_(True))
        .filter(or_(Drug.trade_name.ilike(like), Drug.generic_name.ilike(like)))
        .order_by(Drug.trade_name).limit(15).all()
    )
    return jsonify([{
        "id": d.id, "trade": d.trade_name, "generic": d.generic_name or "",
        "label": d.label(), "form": d.form or "",
        "dose": d.default_dose or "", "frequency": d.default_frequency or "",
        "instructions": d.default_instructions or "", "max": d.max_daily_dose or "",
    } for d in drugs])


# ----------------------------------------------------- writing -------------
@prescriptions_bp.route("/new", methods=["GET", "POST"])
@module_required(MODULE)
def new():
    if request.method == "POST":
        patient = db.session.get(Patient, request.form.get("patient_id", type=int))
        if patient is None:
            flash(t("rx.need_patient"), "danger")
            return redirect(url_for("prescriptions.new"))

        rx = Prescription(
            patient_id=patient.id,
            doctor_id=request.form.get("doctor_id", type=int) or (
                current_user.id if current_user.role == "doctor" else None),
            diagnosis=(request.form.get("diagnosis") or "").strip() or None,
            notes=(request.form.get("notes") or "").strip() or None,
            created_by=current_user.id,
        )
        db.session.add(rx)
        db.session.flush()

        drug_ids = request.form.getlist("item_drug_id")
        names = request.form.getlist("item_name")
        doses = request.form.getlist("item_dose")
        freqs = request.form.getlist("item_frequency")
        durs = request.form.getlist("item_duration")
        instrs = request.form.getlist("item_instructions")
        used_ids, count = [], 0
        for i in range(len(names)):
            name = (names[i] or "").strip()
            if not name:
                continue
            did = None
            try:
                did = int(drug_ids[i]) if i < len(drug_ids) and drug_ids[i] else None
            except (ValueError, TypeError):
                did = None
            rx.items.append(PrescriptionItem(
                drug_id=did, drug_name=name,
                dose=(doses[i].strip() if i < len(doses) else "") or None,
                frequency=(freqs[i].strip() if i < len(freqs) else "") or None,
                duration=(durs[i].strip() if i < len(durs) else "") or None,
                instructions=(instrs[i].strip() if i < len(instrs) else "") or None,
            ))
            used_ids.append(did)
            count += 1
        if count == 0:
            db.session.rollback()
            flash(t("rx.need_item"), "warning")
            return redirect(url_for("prescriptions.new", patient_id=patient.id))

        ActivityLog.record("rx.create", user_id=current_user.id, entity="prescription",
                           detail=patient.patient_number, ip_address=client_ip())
        db.session.commit()
        if interaction_warnings(used_ids):
            flash(t("rx.interaction_flash"), "warning")
        return redirect(url_for("prescriptions.view", rx_id=rx.id))

    patient = db.session.get(Patient, request.args.get("patient_id", type=int))
    return render_template(
        "prescriptions/new.html", patient=patient,
        patients=Patient.query.filter_by(is_active=True).order_by(Patient.full_name).limit(500).all(),
        doctors=User.query.filter_by(role="doctor", is_active=True).order_by(User.full_name).all(),
    )


def resolve_template(doctor, override_id=None):
    """Pick the print template: explicit override → doctor's → default → built-in."""
    if override_id:
        tpl = db.session.get(RxPrintTemplate, override_id)
        if tpl:
            return tpl
    if doctor is not None and doctor.rx_template_id:
        tpl = db.session.get(RxPrintTemplate, doctor.rx_template_id)
        if tpl:
            return tpl
    tpl = RxPrintTemplate.query.filter_by(is_default=True).first()
    return tpl or RxPrintTemplate.default_instance()


@prescriptions_bp.route("/<int:rx_id>")
@module_required(MODULE)
def view(rx_id):
    rx = db.get_or_404(Prescription, rx_id)
    warnings = interaction_warnings([it.drug_id for it in rx.items])
    tpl = resolve_template(rx.doctor, request.args.get("template", type=int))
    return render_template("prescriptions/view.html", rx=rx, warnings=warnings,
                           tpl=tpl, templates=RxPrintTemplate.query.order_by(RxPrintTemplate.name).all())


# ----------------------------------------------------- print templates -----
@prescriptions_bp.route("/templates")
@admin_required
def templates():
    return render_template("prescriptions/templates.html",
                           templates=RxPrintTemplate.query.order_by(RxPrintTemplate.name).all())


def _save_template(tpl):
    tpl.name = (request.form.get("name") or tpl.name or "قالب").strip()
    tpl.mode = "preprinted" if request.form.get("mode") == "preprinted" else "white"
    ls = request.form.get("logo_source")
    tpl.logo_source = ls if ls in ("clinic", "personal", "none") else "clinic"
    tpl.font_size = request.form.get("font_size", type=int) or 14
    tpl.margin_mm = request.form.get("margin_mm", type=int) or 12
    tpl.top_offset_mm = request.form.get("top_offset_mm", type=int) or 0
    for b in RxPrintTemplate.BOOLS:
        setattr(tpl, b, bool(request.form.get(b)))


@prescriptions_bp.route("/templates/new", methods=["POST"])
@admin_required
def template_new():
    tpl = RxPrintTemplate()
    _save_template(tpl)
    if not RxPrintTemplate.query.first():
        tpl.is_default = True
    db.session.add(tpl)
    db.session.commit()
    flash(t("rxtpl.added"), "success")
    return redirect(url_for("prescriptions.templates"))


@prescriptions_bp.route("/templates/<int:tpl_id>/edit", methods=["POST"])
@admin_required
def template_edit(tpl_id):
    tpl = db.get_or_404(RxPrintTemplate, tpl_id)
    _save_template(tpl)
    db.session.commit()
    flash(t("rxtpl.updated"), "success")
    return redirect(url_for("prescriptions.templates"))


@prescriptions_bp.route("/templates/<int:tpl_id>/default", methods=["POST"])
@admin_required
def template_default(tpl_id):
    tpl = db.get_or_404(RxPrintTemplate, tpl_id)
    RxPrintTemplate.query.update({RxPrintTemplate.is_default: False})
    tpl.is_default = True
    db.session.commit()
    flash(t("rxtpl.default_set"), "success")
    return redirect(url_for("prescriptions.templates"))


@prescriptions_bp.route("/templates/<int:tpl_id>/delete", methods=["POST"])
@admin_required
def template_delete(tpl_id):
    tpl = db.get_or_404(RxPrintTemplate, tpl_id)
    db.session.delete(tpl)
    db.session.commit()
    flash(t("rxtpl.deleted"), "info")
    return redirect(url_for("prescriptions.templates"))


@prescriptions_bp.route("/<int:rx_id>/delete", methods=["POST"])
@module_required(MODULE)
def delete(rx_id):
    rx = db.get_or_404(Prescription, rx_id)
    pid = rx.patient_id
    db.session.delete(rx)
    db.session.commit()
    flash(t("rx.deleted"), "info")
    return redirect(url_for("patients.view", patient_id=pid))
