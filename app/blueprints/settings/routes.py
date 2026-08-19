"""System settings (admin): clinic identity, logo and printout options."""
import os
import uuid

from flask import (current_app, flash, g, redirect, render_template, request,
                   url_for)
from flask_login import current_user
from werkzeug.utils import secure_filename

from app.blueprints.settings import settings_bp
from app.extensions import db
from app.i18n import t
from app.models import ActivityLog, Setting
from app.utils.decorators import admin_required, client_ip, owner_required

ALLOWED_LOGO = {"png", "jpg", "jpeg", "webp", "svg", "gif"}

# Settings exposed on the form (text fields).
TEXT_KEYS = [
    "clinic_name", "clinic_name_ar", "clinic_phone",
    "clinic_address", "clinic_address_en", "clinic_tagline",
    "product_name", "product_name_en",
    "program_slogan_ar", "program_slogan_en", "thermal_footer_text",
    "clinic_accent",
    # Where the clinic is. Needed wherever a stored UTC moment has to be
    # compared with a time a person typed (see app/utils/clock.py).
    "clinic_timezone",
    # Which published guideline the vaccination engine follows. A policy the
    # clinic sets, not a code path: the same product can have two positions —
    # Bexsero's course is the European label's from two months and the CDC's
    # from ten years — and switching recomputes from the doses already on file
    # without re-entering one.
    "vaccine_guideline_profile",
    # NOTE: WhatsApp / CRM settings (crm_mode, wa_*, queue_mode, templates) now
    # live in the unified Patient Customer Service hub (messages.occasions).
    # Visit quick-chips (one per line) — common complaints + exam findings.
    "visit_complaint_chips", "visit_exam_chips", "visit_plan_chips",
    # ETA e-invoicing.
    "eta_mode", "eta_environment", "eta_client_id", "eta_client_secret",
    "eta_tax_number", "eta_activity_code", "eta_company_name",
    "eta_branch_address", "eta_signing_url", "eta_default_tax",
    "eta_vat_rate", "eta_send_gap", "eta_default_item_type", "eta_client_secret2",
    # AI assistant (provider-agnostic).
    "ai_provider", "ai_api_key", "ai_model", "ai_base_url", "ai_system_prompt",
    # ICD-11 from WHO. The credentials are the clinic's own, registered free
    # at icd.who.int/icdapi — there is no key of ours to embed, and one key
    # shared by every install is one key to be rate-limited for everybody.
    "icd11_client_id", "icd11_client_secret", "icd11_release",
    # Document numbering (F1): patient file + invoice/receipt series.
    "patient_number_scheme", "patient_number_prefix", "patient_number_prefix_fixed",
    "invoice_number_prefix", "invoice_number_scheme", "invoice_number_start",
    # Warehouse documents (W1): yearly (GRN-2026-000001) or continuous series.
    "store_number_scheme",
    # Unified currency (Financial Formatter): every amount renders with it.
    "currency_code",
    # Login security: lock an account after N failed attempts for M minutes.
    "login_max_attempts", "login_lockout_minutes",
]
TOGGLE_KEYS = ["show_logo_login", "show_logo_print", "eta_enabled", "ai_enabled",
               "ai_patient_context", "ai_anonymize",
               # Appointments board: visit-type breakdown panel + its parts.
               "board_show_breakdown", "board_breakdown_month",
               "board_breakdown_newold",
               # Workflow policies: doctor privacy + refund manager sign-off
               # + the cashier shift gate (no open shift, no collection).
               "doctors_see_own_only", "refund_approval_required",
               "require_shift_to_collect"]


def _logo_dir():
    return os.path.join(current_app.static_folder, "uploads", "clinic")


def _ai_form_config():
    """The AI settings as the form has them right now, over what was saved.

    Both the test and the model list work on the *unsaved* form, because
    pasting a key and finding out whether it works before committing it is the
    order a person actually works in.
    """
    from app.utils.ai import AI_PROVIDERS, get_config

    cfg = get_config()
    provider = (request.form.get("ai_provider") or "").strip()
    if provider not in AI_PROVIDERS:
        return cfg
    meta = AI_PROVIDERS[provider]
    cfg = dict(
        cfg, provider=provider, provider_label=meta["label"],
        local=bool(meta.get("local")),
        model=(request.form.get("ai_model") or "").strip() or meta["default_model"],
        base_url=(request.form.get("ai_base_url") or "").strip() or meta["base_url"],
    )
    # An empty key box means "use the saved one" rather than "no key": the
    # field renders blank on a saved password, and treating that as a deletion
    # would report a working setup as broken.
    typed = (request.form.get("ai_api_key") or "").strip()
    if typed:
        cfg["api_key"] = typed
    return cfg


@settings_bp.route("/ai/models", methods=["POST"])
@admin_required
def ai_models():
    """Which models this key may actually use, asked of the provider.

    The bundled suggestions went stale in the way bundled lists always do: a
    clinic pressed "use the free setup", pasted a fresh key, and got *"this
    model is no longer available to new users"*. The id was right when it was
    written and wrong by the time somebody installed the program.

    Vendors retire models on their own schedule and nobody is going to ship a
    release of this program every time one does — so the list comes from the
    account that will be billed for it.
    """
    from flask import jsonify

    from app.utils.ai import list_models

    return jsonify(list_models(_ai_form_config()))


@settings_bp.route("/ai/test", methods=["POST"])
@admin_required
def ai_test():
    """Ask the provider one trivial question and say exactly what came back.

    Tested from the *unsaved* form when the form sends one, so somebody can
    paste a key and find out before committing it to the settings — which is
    the order a person actually works in.

    This is what makes the assistant something another clinic can set up
    alone. Until now they saved and found out whether it worked when a doctor
    pressed "suggest a dose" mid-consultation and nothing happened, with no
    way to tell a wrong key from a wrong model from a blocked firewall.
    """
    from app.utils.ai import test_connection

    tested = _ai_form_config()
    result = test_connection(tested)
    if result.get("ok"):
        flash(t("settings.ai_test_ok").replace("{p}", result["provider"])
              .replace("{m}", result["model"]), "success")
        # It worked — on values that are still only in the form. Without this
        # line somebody tests successfully, never presses save, and then finds
        # the assistant reporting itself "not ready" with no idea why.
        from app.utils.ai import same_as_saved
        if not same_as_saved(tested):
            flash(t("settings.ai_test_unsaved"), "warning")
    else:
        flash(t("settings.ai_test_failed").replace("{e}", str(result.get("error"))),
              "danger")
    return redirect(url_for("settings.index") + "#ai")


@settings_bp.route("/icd11/test", methods=["POST"])
@admin_required
def icd11_test():
    """One token request against WHO, so a mistyped secret costs a second.

    Separate from the import on purpose. The import is a walk of thousands of
    requests and takes minutes; discovering a wrong secret at the end of it is
    how a clinic decides the feature does not work and stops pressing the
    button.
    """
    from app.utils import icd_who

    result = icd_who.test_connection()
    if result.get("ok"):
        flash(t("icd11.test_ok"), "success")
    else:
        flash(_who_error(result.get("error")), "danger")
    return redirect(url_for("settings.index") + "#icd11")


def _who_error(error, walked=None, shape=None):
    """WHO's failure in the clinic's own words where we can name it.

    ``who_bad_credentials`` is the overwhelmingly common one and the only one
    the clinic can fix themselves, so it gets a sentence telling them where to
    re-copy the two strings. Anything else falls back to showing the raw
    reason rather than a reassuring translation of a problem we did not
    anticipate.
    """
    error = str(error or "")
    if error.startswith("who_"):
        named = t("icd11.error_" + error)
        if named != "icd11.error_" + error:      # a translation exists
            # How far the walk actually got, when the failure is one that
            # cannot be told apart without it.
            named = named.replace("{n}",
                                  str(walked if walked is not None else "?"))
            # The field names WHO actually sent, when there are any. Without a
            # way to reach the API from where this is written, this line is
            # how the shape of a response gets reported back.
            if shape:
                named += "  [" + ", ".join(shape) + "]"
            return named
    return t("icd11.test_failed").replace("{e}", error)


@settings_bp.route("/icd11/import", methods=["POST"])
@admin_required
def icd11_import():
    """Fetch the whole of ICD-11 once, then never speak to WHO again.

    Runs in the request rather than in a worker because this program has no
    worker and a clinic imports this exactly once, deliberately, while
    watching. The alternative — a background thread whose failure nobody sees
    — is worse for a one-off action somebody is standing in front of.
    """
    from flask import jsonify

    from app.utils import icd_progress, icd_who

    # The walk already counted — it takes an ``on_progress`` callback and its
    # own docstring says a spinner with no number cannot be told apart from a
    # hang. Nothing was passed, so every number it computed was discarded and
    # the screen sat still for minutes. See app/utils/icd_progress.py.
    icd_progress.start()
    result = icd_who.import_all(on_progress=icd_progress.note)
    icd_progress.finish(result.get("codes"), ok=result.get("ok"))

    if result.get("ok"):
        message, kind = t("icd11.import_ok").replace(
            "{n}", str(result["codes"])), "success"
    else:
        message, kind = _who_error(result.get("error"),
                                   result.get("walked"),
                                   result.get("shape")), "danger"

    # Answered as JSON when the page asked that way. The page has to stay
    # alive to poll for the count, so the button posts in the background
    # instead of navigating; a plain form post still works and still
    # redirects, which is what happens with no JavaScript.
    if request.headers.get("X-Requested-With") == "fetch":
        return jsonify({"ok": bool(result.get("ok")), "message": message,
                        "codes": result.get("codes") or 0})
    flash(message, kind)
    return redirect(url_for("settings.index") + "#icd11")


@settings_bp.route("/icd11/progress")
@admin_required
def icd11_progress():
    """How far the import has got — asked by the page while it runs."""
    from flask import jsonify

    from app.utils import icd_progress

    return jsonify(icd_progress.status())


def _provider_switch_fixups():
    """Fields that must not survive a change of AI provider.

    Reported as "the provider doesn't save — it stays on the first one", and
    the provider was in fact saving perfectly. What did not change was the
    address it talks to: ``ai_base_url`` is a free-text box holding whichever
    provider's endpoint was there first, and :func:`app.utils.ai.get_config`
    prefers a saved value over the selected provider's default. So a clinic
    that set up Claude and later picked Gemini kept posting Gemini's key to
    ``api.anthropic.com`` — the screen said one thing and the program did
    another, which is indistinguishable from the selection being ignored.

    A value is only kept across the switch when it was meant for the new
    provider: either the box was edited in this same submission, or the
    provider is ``custom``, where supplying the URL is the entire point.
    Otherwise it is cleared, and ``get_config`` falls back to the provider's
    own default — which stays right even when that default changes in a later
    release, as a copied-in literal would not.
    """
    from app.utils.ai import AI_PROVIDERS

    new = (request.form.get("ai_provider") or "").strip()
    old = (Setting.get("ai_provider") or "").strip()
    if not new or new == old or new not in AI_PROVIDERS:
        return {}

    out = {}
    for key in ("ai_base_url", "ai_model"):
        if key == "ai_base_url" and new == "custom":
            continue
        posted = (request.form.get(key) or "").strip()
        if posted == (Setting.get(key) or "").strip():
            out[key] = ""       # untouched, so it belongs to the old provider
    return out


# The tabs on the settings screen, as the template names them. A posted tab is
# looked up in this list rather than trusted: it lands in a redirect URL, and a
# name arriving from a form is not somewhere to put unchecked text.
SETTINGS_TABS = ["clinic", "logo", "numbering", "board", "phrases", "policies",
                 "eta", "ai"]


def _saved_tab():
    tab = (request.form.get("active_tab") or "").strip()
    return tab if tab in SETTINGS_TABS else "clinic"


@settings_bp.route("/", methods=["GET", "POST"])
@admin_required
def index():
    if request.method == "POST":
        # Worked out before anything is written, because it compares what was
        # posted against what is still saved.
        overrides = _provider_switch_fixups()
        for key in TEXT_KEYS:
            if key in overrides:
                Setting.set(key, overrides[key])
                continue
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
        # Come back to the tab that was being edited. Every tab on this screen
        # posts the *same* form, so saving the tax settings used to answer by
        # redrawing the clinic-name tab — the person saving had to find their
        # way back to where they were, on every save. The hash is never sent
        # to a server, so the tab rides along as a field instead.
        return redirect(url_for("settings.index", _anchor=_saved_tab()))

    from app.utils.ai import AI_PROVIDERS, free_providers, trial_defaults
    from app.utils import phrases

    from app.utils.clock import COMMON_ZONES, DEFAULT_TZ, valid_zone
    from app.utils.icd import coverage as icd_coverage
    from app.utils.money import CURRENCIES

    values = {row.key: row.value for row in Setting.query.all()}
    return render_template(
        "settings/index.html", values=values, ai_providers=AI_PROVIDERS,
        free_ai=free_providers(), trial_ai=trial_defaults(),
        # How many codes each classification actually holds, so the screen can
        # say "not loaded" rather than let a doctor's empty search say it.
        icd_coverage=icd_coverage(),
        currencies=CURRENCIES, zones=COMMON_ZONES, default_tz=DEFAULT_TZ,
        # A zone the machine cannot resolve is the Windows-without-tzdata
        # case, and it has to be visible: silently falling back would put the
        # wrong-by-three-hours numbers back on the screen.
        zone_broken=not valid_zone(values.get("clinic_timezone") or DEFAULT_TZ),
        # The *clinic's* list, not the signed-in doctor's. This screen used to
        # call the doctor-aware reader, so an admin with phrases of their own
        # was shown them under a heading that said "the clinic's" — and saving
        # wrote them over it.
        complaint_chips=phrases.clinic_phrases("complaint"),
        exam_chips=phrases.clinic_phrases("exam"),
        plan_chips=phrases.clinic_phrases("plan"),
    )


@settings_bp.route("/setup", methods=["GET", "POST"])
@owner_required
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
        # The ticked services/specialties bring their base coded services with
        # them (idempotent — re-running the wizard only adds what's new).
        from app.utils.services import seed_services_for_caps
        n_services = seed_services_for_caps(caps)
        ActivityLog.record("settings.facility_setup", user_id=current_user.id,
                           entity="settings", detail=type_key, ip_address=client_ip())
        db.session.commit()
        if n_services:
            flash(t("wizard.services_seeded").replace("{n}", str(n_services)), "info")

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


def _device_matches(dev, needle, lang):
    """Name in either language, plus the maker, model and serial — a device is
    usually looked for by the label on its side, not by what we called it."""
    if not needle:
        return True
    haystack = " ".join(filter(None, [
        dev.name, dev.name_en, dev.manufacturer, dev.model, dev.serial_number,
        dev.display_name(lang)])).lower()
    return all(word in haystack for word in needle.lower().split())


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
        # A device with no fields cannot have a study recorded on it, so a new
        # one arrives with the ones its type normally captures. Only ever fills
        # an empty device, so editing one never resurrects deleted fields.
        from app.utils.device_templates import seed_device_measurements

        if seed_device_measurements(dev):
            flash(t("devices.template_seeded"), "info")
        flash(t("devices.saved"), "success")
        return redirect(url_for("settings.devices"))

    every = (MedicalDevice.query
             .order_by(MedicalDevice.device_type, MedicalDevice.name).all())
    lang = getattr(g, "lang", "ar")
    q = (request.args.get("q") or "").strip()
    f_type = (request.args.get("type") or "").strip()
    f_conn = (request.args.get("conn") or "").strip()
    f_status = (request.args.get("status") or "").strip()

    rows = [d for d in every if _device_matches(d, q, lang)]
    if f_type:
        rows = [d for d in rows if d.device_type == f_type]
    if f_conn:
        rows = [d for d in rows if d.connection_type == f_conn]
    if f_status == "active":
        rows = [d for d in rows if d.is_active]
    elif f_status == "inactive":
        rows = [d for d in rows if not d.is_active]

    return render_template(
        "settings/devices.html", devices=every, rows=rows,
        q=q, f_type=f_type, f_conn=f_conn, f_status=f_status,
        device_types=DEVICE_TYPES, connection_types=CONNECTION_TYPES,
        import_modes=IMPORT_MODES)


@settings_bp.route("/devices/<int:device_id>/measurements", methods=["GET", "POST"])
@admin_required
def device_measurements(device_id):
    """Define the measurement fields a device's report captures (its template):
    name, unit and a normal range per field, so manual results can be flagged."""
    from app.models import DeviceMeasurement, MedicalDevice

    device = db.get_or_404(MedicalDevice, device_id)

    if request.method == "POST":
        action = request.form.get("action")
        if action == "delete":
            m = db.session.get(DeviceMeasurement, request.form.get("id", type=int))
            if m is not None and m.device_id == device.id:
                db.session.delete(m)
                db.session.commit()
                flash(t("measure.deleted"), "info")
            return redirect(url_for("settings.device_measurements", device_id=device.id))

        def _num(name):
            raw = (request.form.get(name) or "").strip()
            try:
                return float(raw) if raw != "" else None
            except ValueError:
                return None

        name = (request.form.get("name") or "").strip()
        if not name:
            flash(t("common.required") + ": " + t("measure.name"), "danger")
            return redirect(url_for("settings.device_measurements", device_id=device.id))
        m = (db.session.get(DeviceMeasurement, request.form.get("id", type=int))
             if action == "edit" else DeviceMeasurement(device_id=device.id))
        m.name = name
        m.name_en = (request.form.get("name_en") or "").strip() or None
        m.unit = (request.form.get("unit") or "").strip() or None
        m.normal_low = _num("normal_low")
        m.normal_high = _num("normal_high")
        m.sort_order = request.form.get("sort_order", type=int) or 0
        if action != "edit":
            db.session.add(m)
        db.session.commit()
        flash(t("measure.saved"), "success")
        return redirect(url_for("settings.device_measurements", device_id=device.id))

    return render_template("settings/device_measurements.html", device=device)


@settings_bp.route("/data")
@admin_required
def data_tools():
    from app.models import Invoice, Patient
    from app.utils.backups import list_backups

    stats = {
        "patients": Patient.query.count(),
        "invoices": Invoice.query.count(),
        "seeded": Setting.get("demo_seeded") == "1",
    }
    bset = {
        "enabled": Setting.get("backup_auto_enabled", "1") != "0",
        "hour": Setting.get("backup_hour", "2"),
        "keep": Setting.get("backup_keep", "14"),
        "every": Setting.get("backup_every_days", "1"),
        "include_files": Setting.get("backup_include_files", "1") != "0",
    }
    from app.utils.backups import backup_password
    # Whether a passphrase is set — never the passphrase itself. A screen that
    # prints it back has undone the point of keeping it out of the database.
    bset["encrypted"] = bool(backup_password())
    # Each kind carries its own rhythm and its own count. A shared quota would
    # let the nightly database snapshots push the weekly full archives off the
    # end — a fortnight of databases and not one copy of the photographs.
    bset["full_every"] = Setting.get("backup_full_every_days", "7")
    bset["full_keep"] = Setting.get("backup_full_keep", "4")
    # The number the split makes necessary: a clinic taking only the quick
    # snapshot can believe it is covered for months, and find out on the day
    # the disk dies that every photograph is gone.
    from app.utils.backups import full_backup_age_days, full_backup_overdue
    bset["full_age"] = full_backup_age_days()
    bset["full_overdue"] = full_backup_overdue(bset["full_age"],
                                               bset["full_every"])
    from app.utils.export import datasets_for, parse_date
    start = parse_date(request.args.get("from"))
    end = parse_date(request.args.get("to"))
    return render_template("settings/data.html", stats=stats,
                           backups=list_backups(), bset=bset,
                           exports=datasets_for(start, end),
                           ex_from=request.args.get("from", ""),
                           ex_to=request.args.get("to", ""))


@settings_bp.route("/data/export/<kind>")
@admin_required
def data_export(kind):
    """Download a dataset (patients / invoices / appointments / vaccinations)
    as CSV or Excel (?fmt=xlsx)."""
    from app.models import ActivityLog
    from app.utils.export import export_response

    from app.utils.export import parse_date

    start = parse_date(request.args.get("from"))
    end = parse_date(request.args.get("to"))
    resp = export_response(kind, (request.args.get("fmt") or "csv").lower(),
                           start=start, end=end)
    if resp is None:
        flash(t("common.not_found"), "warning")
        return redirect(url_for("settings.data_tools"))
    # The range goes in the audit line too: "somebody exported the invoices" and
    # "somebody exported March" are different events to be reading about later.
    span = f"{start or '-'}..{end or '-'}"
    ActivityLog.record("data.export", user_id=current_user.id, entity="export",
                       detail=f"{kind} {span}", ip_address=client_ip())
    db.session.commit()
    return resp


@settings_bp.route("/data/backup-settings", methods=["POST"])
@admin_required
def backup_settings():
    Setting.set("backup_auto_enabled",
                "1" if request.form.get("backup_auto_enabled") else "0")
    hour = request.form.get("backup_hour", type=int)
    Setting.set("backup_hour", str(min(max(hour if hour is not None else 2, 0), 23)))
    every = request.form.get("backup_every_days", type=int)
    if every not in (1, 2, 7):
        every = 1
    Setting.set("backup_every_days", str(every))
    # How often the *full* archive (with the pictures) is taken. Separate from
    # the quick one because the halves have different natures: the database is
    # small and changes constantly, the uploads are large and barely change.
    full_every = request.form.get("backup_full_every_days", type=int)
    if full_every not in (1, 7, 14, 30):
        full_every = 7
    Setting.set("backup_full_every_days", str(full_every))
    keep = request.form.get("backup_keep", type=int)
    Setting.set("backup_keep", str(min(max(keep if keep is not None else 14, 1), 365)))
    # And its own count. Sharing one quota would let the nightly database
    # snapshots evict the weekly full archives, leaving a clinic with a
    # fortnight of databases and no copy of the photographs at all — the exact
    # loss the full archive exists to prevent.
    full_keep = request.form.get("backup_full_keep", type=int)
    Setting.set("backup_full_keep",
                str(min(max(full_keep if full_keep is not None else 4, 1), 365)))
    # Photos live on disk, not in the database — without them a restore brings
    # every record back with a broken picture beside it.
    Setting.set("backup_include_files",
                "1" if request.form.get("backup_include_files") else "0")
    db.session.commit()
    flash(t("settings.saved"), "success")
    return redirect(url_for("settings.data_tools"))


MIN_BACKUP_PASSWORD = 8


@settings_bp.route("/data/backup-password", methods=["POST"])
@admin_required
def backup_password_set():
    """Set (or clear) the passphrase new backups are encrypted with.

    Written to ``clinic.env`` and not to the settings table. A key kept beside
    the thing it locks is decoration: anyone who took the database would have
    taken the passphrase in the same file.

    Only *new* snapshots are affected. Re-encrypting the existing ones would
    mean decrypting every archive on disk with a passphrase the admin may have
    typed wrong, and a backup folder is not a place to be clever.
    """
    from app import settings_file
    from app.utils.backups import backup_password

    value = (request.form.get("backup_password") or "").strip()

    # Turning encryption *off* has to be proved, and until now it was the one
    # thing on this screen that needed no proof at all: an empty box cleared
    # the passphrase, so anybody who reached this page could quietly unlock
    # every backup the clinic would take from then on — without knowing the
    # current passphrase and with nothing on screen to mark it as a decision.
    #
    # Two ways through, both deliberate. The passphrase itself, which is what
    # somebody who set it will have. Or the signed-in owner's own password,
    # for the case this exists to answer — the passphrase was lost, and the
    # clinic still has to be able to take backups it can restore. That second
    # door does not open any *existing* archive: those keep the key they were
    # written with, and nothing here can change that.
    current = backup_password()
    if current and not value:
        given = (request.form.get("current_password") or "").strip()
        owner = (request.form.get("owner_password") or "").strip()
        # No ``is_admin`` here: this endpoint is ``@admin_required``, so
        # anybody reaching this line already is one. Repeating the check would
        # read like the guarantee and be dead code — the real guarantee is on
        # the route, and that is where a test has to point.
        by_passphrase = bool(given) and given == current
        by_owner = bool(owner) and current_user.check_password(owner)
        if not (by_passphrase or by_owner):
            flash(t("backups.unlock_denied"), "danger")
            return redirect(url_for("settings.data_tools"))
        ActivityLog.record(
            "backup.unlock", user_id=current_user.id, entity="system",
            detail="owner_password" if by_owner and not by_passphrase
            else "passphrase", ip_address=client_ip())

    if value and len(value) < MIN_BACKUP_PASSWORD:
        flash(t("backups.pwd_too_short").replace(
            "{n}", str(MIN_BACKUP_PASSWORD)), "danger")
        return redirect(url_for("settings.data_tools"))
    if value and value != (request.form.get("backup_password_confirm") or "").strip():
        flash(t("backups.pwd_mismatch"), "danger")
        return redirect(url_for("settings.data_tools"))
    if not settings_file.set_value("BACKUP_PASSWORD", value):
        flash(t("backups.pwd_failed"), "danger")
        return redirect(url_for("settings.data_tools"))
    current_app.config["BACKUP_PASSWORD"] = value
    # The value never goes near the audit log — only that it changed.
    ActivityLog.record("backup.password", user_id=current_user.id,
                       entity="system", detail="set" if value else "cleared",
                       ip_address=client_ip())
    db.session.commit()
    flash(t("backups.pwd_set" if value else "backups.pwd_cleared"), "success")
    return redirect(url_for("settings.data_tools"))


@settings_bp.route("/data/backup", methods=["POST"])
@admin_required
def backup_create():
    from app.utils.backups import create_backup

    # "db" is the quick one: the database without the pictures. Anything else
    # means the full archive, which is what an unqualified "take a backup" has
    # always meant and must keep meaning.
    kind = "db" if (request.form.get("kind") or "").strip() == "db" else "full"
    try:
        name = create_backup("manual", kind=kind)
    except Exception:  # noqa: BLE001 - surfaced to the admin as a flash
        flash(t("backups.failed"), "danger")
        return redirect(url_for("settings.data_tools"))
    ActivityLog.record("backup.create", user_id=current_user.id,
                       entity="system", detail=name, ip_address=client_ip())
    db.session.commit()
    flash(t("backups.created"), "success")
    return redirect(url_for("settings.data_tools"))


@settings_bp.route("/data/backup/upload", methods=["POST"])
@admin_required
def backup_upload():
    """Accept a backup file from the admin's device (e.g. moving PCs or
    restoring an off-site copy). Validated as one of our SQLite databases,
    stored as backup-…-uploaded.db, restorable via the normal restore flow."""
    from app.utils.backups import save_uploaded_backup

    file = request.files.get("backup_file")
    if not file or not file.filename:
        flash(t("backups.upload_need_file"), "danger")
        return redirect(url_for("settings.data_tools"))
    try:
        name = save_uploaded_backup(
            file, password=(request.form.get("password") or "").strip() or None)
    except ValueError as exc:
        key = {"not_sqlite": "upload_not_sqlite", "too_big": "upload_too_big",
               "corrupt": "upload_corrupt", "wrong_app": "upload_wrong_app",
               "bad_password": "bad_password"}.get(
            str(exc), "upload_failed")
        flash(t(f"backups.{key}"), "danger")
        return redirect(url_for("settings.data_tools"))
    except Exception:  # noqa: BLE001 - surfaced to the admin as a flash
        flash(t("backups.upload_failed"), "danger")
        return redirect(url_for("settings.data_tools"))
    ActivityLog.record("backup.upload", user_id=current_user.id,
                       entity="system", detail=name, ip_address=client_ip())
    db.session.commit()
    flash(t("backups.uploaded", name=name), "success")
    return redirect(url_for("settings.data_tools"))


@settings_bp.route("/data/backup/<name>/download")
@admin_required
def backup_download(name):
    from flask import abort, send_file
    from app.utils.backups import backup_path

    path = backup_path(name)
    if not path:
        abort(404)
    return send_file(path, as_attachment=True, download_name=name)


@settings_bp.route("/data/backup/<name>/restore", methods=["POST"])
@admin_required
def backup_restore(name):
    from app.utils.backups import restore_backup

    # Typed confirmation — restoring overwrites the live database.
    if (request.form.get("confirm") or "").strip() != "RESTORE":
        flash(t("backups.bad_confirm"), "danger")
        return redirect(url_for("settings.data_tools"))
    password = (request.form.get("password") or "").strip() or None
    try:
        pre = restore_backup(name, password=password)
    except ValueError as exc:
        # Two failures worth naming rather than calling both "restore failed",
        # which sends somebody looking for a corrupt file that isn't corrupt:
        # a snapshot taken under a passphrase since changed, and one written
        # by a newer version of the program.
        keys = {"bad_password": "backups.bad_password",
                "backup_newer": "backups.newer_refused"}
        flash(t(keys.get(str(exc), "backups.restore_failed")), "danger")
        return redirect(url_for("settings.data_tools"))
    except Exception:  # noqa: BLE001 - surfaced to the admin as a flash
        flash(t("backups.restore_failed"), "danger")
        return redirect(url_for("settings.data_tools"))
    ActivityLog.record("backup.restore", user_id=current_user.id,
                       entity="system", detail=f"{name} (pre={pre})",
                       ip_address=client_ip())
    db.session.commit()
    flash(t("backups.restored", pre=pre), "success")
    # Say when the shape was brought forward. It already happened silently, and
    # silence is what made the original problem so hard to place.
    from app.utils.backups import restore_check
    _ok, reason, info = restore_check(name, password)
    if reason == "older":
        flash(t("backups.upgraded_from").replace(
            "{version}", str(info.get("app_version") or "—")), "info")
    return redirect(url_for("settings.data_tools"))


@settings_bp.route("/data/backup/<name>/delete", methods=["POST"])
@admin_required
def backup_delete(name):
    from app.utils.backups import delete_backup

    if delete_backup(name):
        ActivityLog.record("backup.delete", user_id=current_user.id,
                           entity="system", detail=name, ip_address=client_ip())
        db.session.commit()
        flash(t("backups.deleted"), "info")
    return redirect(url_for("settings.data_tools"))


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
@owner_required
def reset_data():
    from app.utils.demo import reset_all

    # Require an explicit typed confirmation to avoid accidents.
    if (request.form.get("confirm") or "").strip() != "DELETE":
        flash(t("data_tools.bad_confirm"), "danger")
        return redirect(url_for("settings.data_tools"))

    reset_all()
    # A reset clinic still needs its base coded services + visit-type pricing.
    from app.utils.services import seed_services
    seed_services()
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


# ------------------------------------------------------- readiness wizard --
@settings_bp.route("/wizard")
@admin_required
def wizard():
    """One screen that says whether this clinic can open, and what is missing.

    A clinic is installed once and configured over a fortnight, in the wrong
    order, by whoever is free — and the pieces depend on each other without
    saying so. Commissions need services. Booking needs working hours. Taking
    money needs a till. The gap is found on the first real morning, with a
    family already at the desk.

    Deliberately a **checklist that inspects**, not a slideshow that asks.
    Every row is answered by looking at the database, so it is right whether
    the setting was made here, on the ordinary screen, or restored from a
    backup — and a clinic can do half of it, leave, and come back to exactly
    where it stopped without being asked anything twice.
    """
    from app.utils.readiness import summary

    return render_template("settings/wizard.html", state=summary())


@settings_bp.route("/wizard/dismiss", methods=["POST"])
@admin_required
def wizard_dismiss():
    """Stop the reminder. The screen stays reachable from settings.

    A clinic that has decided it does not want vaccinations should not be
    nagged about vaccinations for ever — but the checklist itself remains,
    because "what did we never finish setting up" is a question that comes
    back six months later.
    """
    Setting.set("wizard_dismissed", "0" if request.form.get("undo") else "1")
    db.session.commit()
    return redirect(url_for("settings.wizard"))


@settings_bp.route("/wizard/seed-drugs", methods=["POST"])
@admin_required
def wizard_seed_drugs():
    """Load the Egyptian drug register — 25,000 trade names with their prices.

    Offered as a press rather than done silently at install: it is the
    clinic's catalogue, and a clinic that keeps its own short curated list
    should be able to say no.
    """
    from app.utils.egypt_drugs import seed_register

    added = seed_register()
    ActivityLog.record("settings.seed_drugs", user_id=current_user.id,
                       entity="settings", detail=str(added),
                       ip_address=client_ip())
    db.session.commit()
    flash(t("wizard.drugs_seeded").replace("{n}", str(added)), "success")
    return redirect(url_for("settings.wizard"))
