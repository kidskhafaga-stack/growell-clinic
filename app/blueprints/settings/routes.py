"""System settings (admin): clinic identity, logo and printout options."""
import os
import uuid

from flask import current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user
from werkzeug.utils import secure_filename

from app.blueprints.settings import settings_bp
from app.extensions import db
from app.i18n import t
from app.models import ActivityLog, Setting
from app.utils.decorators import admin_required, client_ip

ALLOWED_LOGO = {"png", "jpg", "jpeg", "webp", "svg", "gif"}

# Settings exposed on the form (text fields).
TEXT_KEYS = [
    "clinic_name", "clinic_name_ar", "clinic_phone",
    "clinic_address", "clinic_address_en", "clinic_tagline",
    "product_name", "product_name_en",
    "program_slogan_ar", "program_slogan_en", "thermal_footer_text",
    "clinic_accent",
    # NOTE: WhatsApp / CRM settings (crm_mode, wa_*, queue_mode, templates) now
    # live in the unified Patient Customer Service hub (messages.occasions).
    # Visit quick-chips (one per line) — common complaints + exam findings.
    "visit_complaint_chips", "visit_exam_chips",
    # ETA e-invoicing.
    "eta_mode", "eta_environment", "eta_client_id", "eta_client_secret",
    "eta_tax_number", "eta_activity_code", "eta_company_name",
    "eta_branch_address", "eta_signing_url", "eta_default_tax",
    "eta_vat_rate", "eta_send_gap", "eta_default_item_type", "eta_client_secret2",
    # AI assistant (provider-agnostic).
    "ai_provider", "ai_api_key", "ai_model", "ai_base_url", "ai_system_prompt",
]
TOGGLE_KEYS = ["show_logo_login", "show_logo_print", "eta_enabled", "ai_enabled",
               "ai_patient_context", "ai_anonymize",
               # Appointments board: visit-type breakdown panel + its parts.
               "board_show_breakdown", "board_breakdown_month",
               "board_breakdown_newold"]


def _logo_dir():
    return os.path.join(current_app.static_folder, "uploads", "clinic")


@settings_bp.route("/", methods=["GET", "POST"])
@admin_required
def index():
    if request.method == "POST":
        for key in TEXT_KEYS:
            Setting.set(key, (request.form.get(key) or "").strip())
        for key in TOGGLE_KEYS:
            Setting.set(key, "1" if request.form.get(key) else "0")

        # Logo upload.
        file = request.files.get("logo")
        if file and file.filename:
            ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
            if ext in ALLOWED_LOGO:
                name = f"{uuid.uuid4().hex}.{ext}"
                os.makedirs(_logo_dir(), exist_ok=True)
                file.save(os.path.join(_logo_dir(), secure_filename(name)))
                _remove_logo_file(Setting.get("clinic_logo"))
                Setting.set("clinic_logo", name)
            else:
                flash(t("settings.bad_logo"), "warning")

        # Program (PediaPro) logo upload — the software's own brand mark.
        pfile = request.files.get("program_logo")
        if pfile and pfile.filename:
            ext = pfile.filename.rsplit(".", 1)[-1].lower() if "." in pfile.filename else ""
            if ext in ALLOWED_LOGO:
                name = f"{uuid.uuid4().hex}.{ext}"
                os.makedirs(_logo_dir(), exist_ok=True)
                pfile.save(os.path.join(_logo_dir(), secure_filename(name)))
                _remove_logo_file(Setting.get("program_logo"))
                Setting.set("program_logo", name)
            else:
                flash(t("settings.bad_logo"), "warning")

        ActivityLog.record("settings.update", user_id=current_user.id,
                           entity="settings", ip_address=client_ip())
        db.session.commit()
        flash(t("settings.saved"), "success")
        return redirect(url_for("settings.index"))

    from app.utils.ai import AI_PROVIDERS
    from app.blueprints.visits.routes import (
        DEFAULT_COMPLAINT_CHIPS, DEFAULT_EXAM_CHIPS, _visit_chips,
    )

    values = {row.key: row.value for row in Setting.query.all()}
    return render_template(
        "settings/index.html", values=values, ai_providers=AI_PROVIDERS,
        complaint_chips=_visit_chips("visit_complaint_chips", DEFAULT_COMPLAINT_CHIPS),
        exam_chips=_visit_chips("visit_exam_chips", DEFAULT_EXAM_CHIPS),
    )


@settings_bp.route("/setup", methods=["GET", "POST"])
@admin_required
def setup():
    """First-run wizard (and later editor) for the facility profile — three
    separate layers: administrative type, capabilities (services & specialties)
    and the software modules they switch on. Optionally seeds demo data."""
    from app.utils.facility import (
        BASE_MODULES, CAPABILITY_GROUPS, CAPABILITY_MODULES,
        DEFAULT_FACILITY_TYPE, FACILITY_TYPES, TEMPLATES, TOGGLEABLE_MODULES,
        apply_facility, capabilities, default_caps_for, facility_type,
        is_configured, module_enabled,
    )

    if request.method == "POST":
        type_key = (request.form.get("facility_type") or "").strip()
        if type_key not in FACILITY_TYPES:
            type_key = DEFAULT_FACILITY_TYPE
        name = (request.form.get("facility_name") or "").strip()
        caps = request.form.getlist("capabilities")
        modules = request.form.getlist("modules")
        apply_facility(type_key, name, caps, modules)
        ActivityLog.record("settings.facility_setup", user_id=current_user.id,
                           entity="settings", detail=type_key, ip_address=client_ip())
        db.session.commit()

        if request.form.get("seed_demo"):
            from app.utils.demo import seed_demo
            if not seed_demo().get("skipped"):
                db.session.commit()
                flash(t("wizard.seeded"), "success")

        flash(t("wizard.saved"), "success")
        return redirect(url_for("main.dashboard"))

    configured = is_configured()
    current_type = facility_type()
    if configured:
        current_caps = set(capabilities())
        current_modules = {m for m in TOGGLEABLE_MODULES if module_enabled(m)}
    else:
        current_caps = set(default_caps_for(current_type))
        from app.utils.facility import derive_modules
        current_modules = set(derive_modules(current_caps))
    # Client-side maps so the UI can auto-tick capabilities/modules.
    type_caps = {k: FACILITY_TYPES[k]["caps"] for k in FACILITY_TYPES}
    cap_modules = {c: sorted(m) for c, m in CAPABILITY_MODULES.items()}
    template_data = {k: {"type": v["type"], "caps": v["caps"]}
                     for k, v in TEMPLATES.items()}
    return render_template(
        "settings/setup.html", facility_types=FACILITY_TYPES,
        capability_groups=CAPABILITY_GROUPS, toggleable=TOGGLEABLE_MODULES,
        templates=TEMPLATES, current_type=current_type,
        current_caps=current_caps, current_modules=current_modules,
        type_caps=type_caps, cap_modules=cap_modules, base_modules=BASE_MODULES,
        template_data=template_data, configured=configured,
    )


@settings_bp.route("/visit-types", methods=["GET", "POST"])
@admin_required
def visit_types():
    """Manage the editable visit-type catalogue (كشف / متابعة / تطعيم / …)."""
    from app.models import VISIT_TYPE_COLORS, VisitType
    from app.utils.visit_types import ensure_seeded
    import re

    ensure_seeded()
    if request.method == "POST":
        action = request.form.get("action")
        if action == "add":
            key = re.sub(r"[^a-z0-9_]", "", (request.form.get("key") or "").strip().lower())
            if not key:
                flash(t("visit_types.bad_key"), "danger")
            elif VisitType.query.filter_by(key=key).first():
                flash(t("visit_types.dup_key"), "warning")
            else:
                last = db.session.query(db.func.max(VisitType.sort_order)).scalar() or 0
                color = request.form.get("color") or "blue"
                db.session.add(VisitType(
                    key=key, name_ar=(request.form.get("name_ar") or "").strip() or None,
                    name_en=(request.form.get("name_en") or "").strip() or None,
                    minutes=request.form.get("minutes", type=int) or 15,
                    color=color if color in VISIT_TYPE_COLORS else "blue",
                    sort_order=last + 1, is_active=True, is_system=False))
                ActivityLog.record("settings.visit_type_add", user_id=current_user.id,
                                   entity="visit_type", detail=key, ip_address=client_ip())
                db.session.commit()
                flash(t("visit_types.added"), "success")
        elif action == "edit":
            vt = db.session.get(VisitType, request.form.get("id", type=int))
            if vt is not None:
                vt.name_ar = (request.form.get("name_ar") or "").strip() or None
                vt.name_en = (request.form.get("name_en") or "").strip() or None
                vt.minutes = request.form.get("minutes", type=int) or vt.minutes
                color = request.form.get("color") or vt.color
                vt.color = color if color in VISIT_TYPE_COLORS else vt.color
                vt.is_active = bool(request.form.get("is_active"))
                db.session.commit()
                flash(t("visit_types.saved"), "success")
        elif action == "delete":
            vt = db.session.get(VisitType, request.form.get("id", type=int))
            if vt is None or vt.is_system:
                flash(t("visit_types.cant_delete"), "warning")
            else:
                db.session.delete(vt)
                db.session.commit()
                flash(t("visit_types.deleted"), "info")
        return redirect(url_for("settings.visit_types"))

    types = VisitType.query.order_by(VisitType.sort_order, VisitType.id).all()
    return render_template("settings/visit_types.html", types=types,
                           colors=VISIT_TYPE_COLORS)


@settings_bp.route("/devices", methods=["GET", "POST"])
@admin_required
def devices():
    """Manage the medical-device registry (Spirometry / ECG / Echo / …)."""
    from app.models import (CONNECTION_TYPES, DEVICE_TYPES, IMPORT_MODES,
                            MedicalDevice)

    def _date(name):
        raw = (request.form.get(name) or "").strip()
        if not raw:
            return None
        from datetime import datetime as _dt
        try:
            return _dt.strptime(raw, "%Y-%m-%d").date()
        except ValueError:
            return None

    if request.method == "POST":
        action = request.form.get("action")
        if action == "delete":
            dev = db.session.get(MedicalDevice, request.form.get("id", type=int))
            if dev is not None:
                if dev.services:
                    dev.is_active = False  # keep history, just deactivate
                    flash(t("devices.deactivated"), "info")
                else:
                    db.session.delete(dev)
                    flash(t("devices.deleted"), "info")
                db.session.commit()
            return redirect(url_for("settings.devices"))

        dev = (db.session.get(MedicalDevice, request.form.get("id", type=int))
               if action == "edit" else MedicalDevice())
        name = (request.form.get("name") or "").strip()
        if not name:
            flash(t("common.required") + ": " + t("devices.name"), "danger")
            return redirect(url_for("settings.devices"))
        dev.name = name
        dev.name_en = (request.form.get("name_en") or "").strip() or None
        dev.manufacturer = (request.form.get("manufacturer") or "").strip() or None
        dev.model = (request.form.get("model") or "").strip() or None
        dtype = (request.form.get("device_type") or "other").strip()
        dev.device_type = dtype if dtype in DEVICE_TYPES else "other"
        conn = (request.form.get("connection_type") or "manual").strip()
        dev.connection_type = conn if conn in CONNECTION_TYPES else "manual"
        imode = (request.form.get("import_mode") or "manual").strip()
        dev.import_mode = imode if imode in IMPORT_MODES else "manual"
        dev.software = (request.form.get("software") or "").strip() or None
        dev.serial_number = (request.form.get("serial_number") or "").strip() or None
        dev.purchase_date = _date("purchase_date")
        dev.warranty_until = _date("warranty_until")
        dev.is_active = bool(request.form.get("is_active")) if action == "edit" else True
        if action != "edit":
            db.session.add(dev)
        ActivityLog.record(f"settings.device_{action or 'add'}", user_id=current_user.id,
                           entity="medical_device", detail=name, ip_address=client_ip())
        db.session.commit()
        flash(t("devices.saved"), "success")
        return redirect(url_for("settings.devices"))

    return render_template(
        "settings/devices.html",
        devices=MedicalDevice.query.order_by(MedicalDevice.device_type, MedicalDevice.name).all(),
        device_types=DEVICE_TYPES, connection_types=CONNECTION_TYPES,
        import_modes=IMPORT_MODES)


@settings_bp.route("/data")
@admin_required
def data_tools():
    from app.models import Invoice, Patient

    stats = {
        "patients": Patient.query.count(),
        "invoices": Invoice.query.count(),
        "seeded": Setting.get("demo_seeded") == "1",
    }
    return render_template("settings/data.html", stats=stats)


@settings_bp.route("/data/seed-demo", methods=["POST"])
@admin_required
def seed_demo_data():
    from app.utils.demo import seed_demo

    result = seed_demo()
    if result.get("skipped"):
        flash(t("data_tools.already_seeded"), "warning")
    else:
        ActivityLog.record("data.seed_demo", user_id=current_user.id,
                           entity="system", ip_address=client_ip())
        db.session.commit()
        flash(t("data_tools.seeded"), "success")
    return redirect(url_for("settings.data_tools"))


@settings_bp.route("/data/reset", methods=["POST"])
@admin_required
def reset_data():
    from app.utils.demo import reset_all

    # Require an explicit typed confirmation to avoid accidents.
    if (request.form.get("confirm") or "").strip() != "DELETE":
        flash(t("data_tools.bad_confirm"), "danger")
        return redirect(url_for("settings.data_tools"))

    reset_all()
    ActivityLog.record("data.reset", user_id=current_user.id, entity="system",
                       ip_address=client_ip())
    db.session.commit()
    flash(t("data_tools.reset_done"), "success")
    return redirect(url_for("settings.data_tools"))


@settings_bp.route("/logo/delete", methods=["POST"])
@admin_required
def delete_logo():
    _remove_logo_file(Setting.get("clinic_logo"))
    Setting.set("clinic_logo", "")
    db.session.commit()
    flash(t("settings.logo_removed"), "info")
    return redirect(url_for("settings.index"))


@settings_bp.route("/program-logo/delete", methods=["POST"])
@admin_required
def delete_program_logo():
    _remove_logo_file(Setting.get("program_logo"))
    Setting.set("program_logo", "")
    db.session.commit()
    flash(t("settings.logo_removed"), "info")
    return redirect(url_for("settings.index"))


def _remove_logo_file(filename):
    if not filename:
        return
    path = os.path.join(_logo_dir(), filename)
    if os.path.isfile(path):
        try:
            os.remove(path)
        except OSError:
            pass
