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
    "wa_tpl_appt_confirm", "wa_tpl_doctor_schedule", "queue_mode",
]
TOGGLE_KEYS = ["show_logo_login", "show_logo_print"]


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
