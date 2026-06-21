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
    "clinic_address", "clinic_address_en",
    # WhatsApp / messaging.
    "wa_provider", "wa_country_code", "wa_cloud_token", "wa_cloud_phone_id",
    "wa_wapilot_key", "wa_wapilot_endpoint",
    "wa_tpl_appt_confirm", "wa_tpl_doctor_schedule", "wa_tpl_vaccine_given",
    "queue_mode", "crm_mode",
    # ETA e-invoicing.
    "eta_mode", "eta_environment", "eta_client_id", "eta_client_secret",
    "eta_tax_number", "eta_activity_code", "eta_company_name",
    "eta_branch_address", "eta_signing_url", "eta_default_tax",
    "eta_vat_rate", "eta_send_gap", "eta_default_item_type", "eta_client_secret2",
]
TOGGLE_KEYS = ["show_logo_login", "show_logo_print", "eta_enabled"]


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

        ActivityLog.record("settings.update", user_id=current_user.id,
                           entity="settings", ip_address=client_ip())
        db.session.commit()
        flash(t("settings.saved"), "success")
        return redirect(url_for("settings.index"))

    values = {row.key: row.value for row in Setting.query.all()}
    return render_template("settings/index.html", values=values)


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


def _remove_logo_file(filename):
    if not filename:
        return
    path = os.path.join(_logo_dir(), filename)
    if os.path.isfile(path):
        try:
            os.remove(path)
        except OSError:
            pass
