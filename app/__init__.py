"""Application factory for GROWELL CLINIC."""
import os
import sqlite3
from datetime import datetime

from flask import render_template
from sqlalchemy import event
from sqlalchemy.engine import Engine

from config import config as config_map

from app import i18n
from app.extensions import db, login_manager
from app.utils.brand import PRIMARY as BRAND_PRIMARY
from app.utils.clock import local_today


@event.listens_for(Engine, "connect")
def _set_sqlite_pragmas(dbapi_connection, _record):
    """Make SQLite robust under the threaded dev server / bulk imports.

    WAL lets a writer and readers work concurrently, and a busy-timeout makes a
    momentarily-locked database wait instead of raising 'database is locked'
    (e.g. during patient bulk import). No-ops for non-SQLite backends."""
    if isinstance(dbapi_connection, sqlite3.Connection):
        cur = dbapi_connection.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=15000")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.close()


def _protect_forms(app):
    """Refuse a POST that didn't come from one of our own screens.

    Without this, any page anywhere can make a logged-in member of staff's
    browser submit a form here — their session goes along automatically. A
    refund, a deleted patient, a permission change: the member of staff sees
    nothing, and the audit log records *them* doing it.

    Every form carries the token, and ``base.html`` adds it to POSTs made by
    script. The public webhooks are exempt: a provider cannot know a token,
    and they prove themselves by signature instead (``webhook_auth``).
    """
    from flask_wtf.csrf import CSRFProtect

    csrf = CSRFProtect()
    csrf.init_app(app)
    app.extensions["csrf"] = csrf
    return csrf


def _harden_responses(app):
    """Headers that stop a stored file from becoming a page.

    Patient documents are served from the clinic's own origin, which means a
    file the browser decides to treat as HTML runs with the session of whoever
    opened it. ``save_document`` already refuses anything whose bytes aren't an
    image or a PDF; ``nosniff`` is the other half — it stops the browser
    second-guessing the type we sent and re-interpreting an X-ray as markup.

    The frame header is for the login form: a clinic reachable on the practice
    network should not be loadable inside somebody else's page.
    """
    @app.after_request
    def _headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("Referrer-Policy",
                                    "strict-origin-when-cross-origin")
        return response

    return app


def _apply_environment(app):
    """Let the environment override the config — read *now*, not at import.

    The config classes evaluate ``os.environ`` while their class bodies run,
    which is when ``config`` is first imported. ``run.py`` imports the app
    (and therefore config) at the top of the file and only reads
    ``clinic.env`` afterwards, so every value a clinic put in that file was
    read too late and silently ignored — the database location and the
    session key included, the two that matter most.

    Reading them here, as the app is built, is what makes ``clinic.env`` mean
    anything. An empty value is not an override: a blank ``SECRET_KEY=`` line
    must not hand the clinic an empty key.
    """
    for key in ("SECRET_KEY", "CLINIC_NAME", "DEFAULT_LANGUAGE",
                "BACKUP_PASSWORD"):
        value = (os.environ.get(key) or "").strip()
        if value:
            app.config[key] = value
    database = (os.environ.get("DATABASE_URL") or "").strip()
    if database:
        app.config["SQLALCHEMY_DATABASE_URI"] = database
    # Secure cookies are correct behind TLS and a lock-out without it.
    if not app.config.get("DEBUG") and not app.config.get("TESTING"):
        behind_tls = (os.environ.get("HTTPS") or "0").strip() == "1"
        app.config["SESSION_COOKIE_SECURE"] = behind_tls
        app.config["REMEMBER_COOKIE_SECURE"] = behind_tls


def create_app(config_name="default"):
    app = Flask_app()

    # Resolve and apply configuration.
    cfg = config_map.get(config_name, config_map["default"])
    app.config.from_object(cfg)
    _apply_environment(app)

    # Ensure the instance folder (for SQLite) exists.
    os.makedirs(app.instance_path, exist_ok=True)

    # Extensions.
    db.init_app(app)
    login_manager.init_app(app)
    csrf = _protect_forms(app)
    _harden_responses(app)
    i18n.init_app(app)
    from app.utils import money as _money
    _money.init_app(app)

    # Make sure models are imported so tables are registered.
    with app.app_context():
        from app import models  # noqa: F401

    # Blueprints.
    from app.blueprints.ai import ai_bp
    from app.blueprints.appointments import appointments_bp
    from app.blueprints.auth import auth_bp
    from app.blueprints.feedback import feedback_bp
    from app.blueprints.webhooks import webhooks_bp
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
    app.register_blueprint(feedback_bp)
    app.register_blueprint(webhooks_bp)
    # The providers post from their own servers and cannot carry a token of
    # ours; they prove themselves by signature instead (see webhook_auth).
    csrf.exempt(webhooks_bp)

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
        # Not `occasions`: that is where the WhatsApp connection and the
        # message templates are configured, and somebody whose job is
        # answering people arrived there every morning.
        "messages": "messages.desk",
        "settings": "settings.index",
        "users": "users.index",
    }

    @app.context_processor
    def inject_navigation():
        from app.models import Setting
        from app.utils.facility import module_enabled
        return {
            "ALL_MODULES": MODULES,
            "MODULE_ICONS": MODULE_ICONS,
            "MODULE_ENDPOINTS": module_endpoints,
            "module_enabled": module_enabled,
            "small_clinic_mode": Setting.get("small_clinic_mode", "0") == "1",
            "clinic_name": app.config.get("CLINIC_NAME", "GROWELL CLINIC"),
            "now_date": local_today().isoformat(),
            "now_weekday": datetime.utcnow().weekday(),
            # Two forms, because the sidebar and the About page are asking
            # different questions. The short one is a credit line; the long one
            # is the licence terms, and terms squeezed into a 250px column at
            # 0.64rem are terms nobody has read.
            "copyright_short": "© Eng. Mohamed Khafaga",
            "copyright_notice": (
                "© Eng. Mohamed Khafaga — All rights reserved · "
                "يُحظر نسخه أو تعديله أو إعادة استخدامه بدون إذن صريح"
            ),
            "app_version": "0.1",
        }

    @app.context_processor
    def inject_paging():
        """The pager macro needs the offered page sizes and "showing 51–75"
        arithmetic; both belong to the paging helper, not to Jinja."""
        from app.utils.paging import (PER_PAGE_CHOICES, page_window, per_page)
        return {
            "per_page_choices": PER_PAGE_CHOICES,
            "current_per_page": per_page,
            "page_window": page_window,
        }

    @app.context_processor
    def inject_visit_types():
        """Expose the editable visit-type catalogue to templates: an active
        list for selects, plus label/colour resolvers for any stored key."""
        from flask import g
        from app.utils import visit_types as vt
        lang = getattr(g, "lang", "ar")
        return {
            "visit_types": vt.active_types(),
            "visit_type_label": lambda key: vt.label(key, lang),
            "visit_type_color": vt.color,
        }

    @app.context_processor
    def inject_open_shift():
        """Topbar "close your shift" chip for cashiers with an open till."""
        from flask_login import current_user

        try:
            if (getattr(current_user, "is_authenticated", False)
                    and current_user.can_access("finance")):
                from app.models import CashierShift
                return {"my_open_shift": CashierShift.open_for(current_user.id)}
        except Exception:  # noqa: BLE001 - never break a page over the chip
            pass
        return {"my_open_shift": None}

    @app.context_processor
    def inject_category_label():
        """``category_label(key)`` — a client category's name for this clinic.

        Templates used to print ``t('categories.' ~ key)``, which only worked
        for the four built-in keys. A clinic-added category has no dictionary
        entry, so that printed the raw key at the user.
        """
        from flask import g

        def category_label(key):
            from app.utils.client_categories import label

            return label(key, getattr(g, "lang", "ar"))

        def client_categories_for(current=None):
            """The categories a dropdown should offer — the active ones, plus
            whichever this family is already on even if it was hidden, so
            saving their profile doesn't quietly move them."""
            from app.utils.client_categories import choices_for

            return choices_for(current)

        def payer_type_label(key):
            """A payer kind's name — same fix, same reason: the screens printed
            ``t('payer_types.' ~ key)``, which shows the raw key for anything
            a clinic added."""
            from app.utils.payer_types import label

            return label(key, getattr(g, "lang", "ar"))

        return {"category_label": category_label,
                "client_categories_for": client_categories_for,
                "payer_type_label": payer_type_label}

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
                    # The brand's own blue when the clinic has not chosen a
                    # colour. The program has shipped as PediaPro all along
                    # and looked nothing like its own logo.
                    "accent": ((rows.get("clinic_accent") or "").strip()
                               or BRAND_PRIMARY),
                },
            }
        except Exception:  # noqa: BLE001 - DB not ready yet (e.g. pre-init)
            return {"clinic": defaults, "product_name": product_default,
                    "program": {"name": product_default, "accent": BRAND_PRIMARY,
                                "slogan": "حلول طب الأطفال الذكية",
                                "logo_url": None, "accent": None}}

    @app.before_request
    def _auto_backup():
        """Daily automatic DB snapshot (throttled, silent, never breaks a request)."""
        from app.utils.backups import auto_backup_if_due
        auto_backup_if_due()

    @app.before_request
    def _first_run_wizard():
        """Send the admin to the setup wizard until the facility is configured.

        Everyone else keeps working on the sensible defaults (all modules on).
        """
        from flask import redirect, request, url_for
        from flask_login import current_user

        # Only the owner can run the facility setup, so only trap the owner;
        # a plain admin keeps working on the sensible defaults until then.
        if not current_user.is_authenticated or not current_user.is_owner:
            return None
        endpoint = request.endpoint or ""
        # Don't trap static assets, auth, the wizard itself, or public pages.
        # The readiness checklist is allowed through too. It is the screen
        # that *explains* what setup is still missing, so trapping it behind
        # the very step it is meant to introduce leaves a new owner with a
        # single form and no map.
        allowed = ("static", "settings.setup", "settings.wizard",
                   "auth.logout", "auth.login", "main.set_theme")
        # `settings.wizard*` covers the checklist's own actions too — a POST
        # that gets swallowed by this redirect looks to the user like a button
        # that does nothing, which is exactly how the drug seeder behaved.
        if (endpoint in allowed or endpoint.startswith("settings.wizard")
                or endpoint.startswith(("feedback.", "webhooks."))):
            return None
        from app.utils.facility import is_configured
        try:
            if not is_configured():
                return redirect(url_for("settings.setup"))
        except Exception:  # noqa: BLE001 - never break on a half-built DB
            return None
        return None

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
