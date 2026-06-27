"""Application factory for GROWELL CLINIC."""
import os
from datetime import datetime

from flask import render_template

from config import config as config_map

from app import i18n
from app.extensions import db, login_manager


def create_app(config_name="default"):
    app = Flask_app()

    # Resolve and apply configuration.
    cfg = config_map.get(config_name, config_map["default"])
    app.config.from_object(cfg)

    # Ensure the instance folder (for SQLite) exists.
    os.makedirs(app.instance_path, exist_ok=True)

    # Extensions.
    db.init_app(app)
    login_manager.init_app(app)
    i18n.init_app(app)

    # Make sure models are imported so tables are registered.
    with app.app_context():
        from app import models  # noqa: F401

    # Blueprints.
    from app.blueprints.ai import ai_bp
    from app.blueprints.appointments import appointments_bp
    from app.blueprints.auth import auth_bp
    from app.blueprints.finance import finance_bp
    from app.blueprints.growth import growth_bp
    from app.blueprints.inventory import inventory_bp
    from app.blueprints.main import main_bp
    from app.blueprints.messages import messages_bp
    from app.blueprints.patients import patients_bp
    from app.blueprints.prescriptions import prescriptions_bp
    from app.blueprints.reports import reports_bp
    from app.blueprints.settings import settings_bp
    from app.blueprints.users import users_bp
    from app.blueprints.vaccinations import vaccinations_bp
    from app.blueprints.visits import visits_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(patients_bp)
    app.register_blueprint(appointments_bp)
    app.register_blueprint(visits_bp)
    app.register_blueprint(growth_bp)
    app.register_blueprint(vaccinations_bp)
    app.register_blueprint(prescriptions_bp)
    app.register_blueprint(inventory_bp)
    app.register_blueprint(finance_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(messages_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(users_bp)
    app.register_blueprint(ai_bp)

    # Template globals for navigation rendering.
    from app.models.permissions import MODULE_ICONS, MODULES

    # Endpoints implemented so far; modules without one render as inert links
    # ("coming soon") until their phase lands.
    module_endpoints = {
        "dashboard": "main.dashboard",
        "patients": "patients.index",
        "appointments": "appointments.index",
        "visits": "visits.index",
        "growth": "growth.index",
        "vaccinations": "vaccinations.index",
        "prescriptions": "prescriptions.index",
        "inventory": "inventory.index",
        "finance": "finance.index",
        "reports": "reports.index",
        "ai": "ai.index",
        "messages": "messages.index",
        "settings": "settings.index",
        "users": "users.index",
    }

    @app.context_processor
    def inject_navigation():
        return {
            "ALL_MODULES": MODULES,
            "MODULE_ICONS": MODULE_ICONS,
            "MODULE_ENDPOINTS": module_endpoints,
            "clinic_name": app.config.get("CLINIC_NAME", "GROWELL CLINIC"),
            "now_date": datetime.utcnow().date().isoformat(),
            "now_weekday": datetime.utcnow().weekday(),
            "copyright_notice": (
                "© Eng. Mohamed Khafaga — All rights reserved · "
                "يُحظر نسخه أو تعديله أو إعادة استخدامه بدون إذن صريح"
            ),
        }

    @app.context_processor
    def inject_notifications():
        """Topbar bell: live alerts filtered to the current user's modules."""
        from flask_login import current_user

        from app.utils.notifications import get_notifications

        try:
            items = get_notifications(current_user)
        except Exception:  # noqa: BLE001 - never break a page over the bell
            items = []
        return {
            "notifications": items,
            "notif_count": sum(i.get("count", 0) for i in items),
        }

    @app.context_processor
    def inject_clinic_settings():
        """Expose clinic identity/logo + product brand to all templates."""
        from flask import g, url_for

        product_default = "PediaPro"
        defaults = {
            "name": app.config.get("CLINIC_NAME", "GROWELL CLINIC"),
            "name_ar": None, "logo": None, "logo_url": None,
            "show_logo_login": True, "show_logo_print": True,
            "phone": None, "address": None, "address_en": None, "tagline": None,
        }
        try:
            from app.models import Setting

            rows = {r.key: r.value for r in Setting.query.all()}
            logo = rows.get("clinic_logo") or None
            lang = getattr(g, "lang", "ar")
            product = ((rows.get("product_name_en") if lang == "en" else None)
                       or rows.get("product_name") or product_default)
            # Program (PediaPro) identity — distinct from the clinic's own logo.
            # An uploaded logo (Settings) wins; otherwise fall back to the
            # default logo bundled in the repo at static/img/brand/ if present.
            prog_logo = rows.get("program_logo") or None
            if prog_logo:
                program_logo_url = url_for("static", filename="uploads/clinic/" + prog_logo)
            else:
                bundled = os.path.join(app.static_folder, "img", "brand",
                                       "pediapro-logo.png")
                program_logo_url = (url_for("static", filename="img/brand/pediapro-logo.png")
                                    if os.path.exists(bundled) else None)
            slogan_default = ("Smart Pediatrics Care Solution" if lang == "en"
                              else "حلول طب الأطفال الذكية")
            program_slogan = ((rows.get("program_slogan_en") if lang == "en"
                               else rows.get("program_slogan_ar")) or slogan_default)
            return {
                "clinic": {
                    "name": rows.get("clinic_name") or defaults["name"],
                    "name_ar": rows.get("clinic_name_ar"),
                    "tagline": rows.get("clinic_tagline"),
                    "logo": logo,
                    "logo_url": (url_for("static", filename="uploads/clinic/" + logo)
                                 if logo else None),
                    "show_logo_login": (rows.get("show_logo_login", "1") != "0"),
                    "show_logo_print": (rows.get("show_logo_print", "1") != "0"),
                    "phone": rows.get("clinic_phone"),
                    "address": rows.get("clinic_address"),
                    "address_en": rows.get("clinic_address_en"),
                },
                "product_name": product,
                "program": {
                    "name": product,
                    "slogan": program_slogan,
                    "logo_url": program_logo_url,
                },
            }
        except Exception:  # noqa: BLE001 - DB not ready yet (e.g. pre-init)
            return {"clinic": defaults, "product_name": product_default,
                    "program": {"name": product_default,
                                "slogan": "حلول طب الأطفال الذكية", "logo_url": None}}

    register_error_handlers(app)
    register_cli(app)

    return app


def Flask_app():
    """Create the bare Flask object with project template/static folders."""
    from flask import Flask

    return Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
        instance_relative_config=True,
    )


def register_error_handlers(app):
    @app.errorhandler(403)
    def forbidden(error):
        return render_template("errors/403.html"), 403

    @app.errorhandler(404)
    def not_found(error):
        return render_template("errors/404.html"), 404

    @app.errorhandler(500)
    def server_error(error):
        db.session.rollback()
        return render_template("errors/500.html"), 500


def register_cli(app):
    """Register custom ``flask`` CLI commands (init-db, seed, create-admin)."""
    from app.cli import register_commands

    register_commands(app)
