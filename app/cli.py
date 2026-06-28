"""Custom Flask CLI commands for database setup and seeding.

    flask --app run init-db         create all tables
    flask --app run seed            create demo users (one per role)
    flask --app run create-admin    interactively create an admin user
"""
import click

from app.extensions import db
from app.models import Setting, User


# Demo accounts created by ``seed`` — handy during Phase 1 development.
DEMO_USERS = [
    ("admin", "admin123", "مدير النظام", "System Administrator", "admin"),
    ("doctor", "doctor123", "د. سارة أحمد", "Dr. Sarah Ahmed", "doctor"),
    ("reception", "reception123", "موظف الاستقبال", "Reception Desk", "reception"),
    ("accountant", "accountant123", "المحاسب", "Accountant", "accountant"),
    ("pharmacy", "pharmacy123", "الصيدلية", "Pharmacy", "pharmacy"),
]

DEFAULT_SETTINGS = {
    "clinic_name": "GROWELL CLINIC",
    "clinic_name_ar": "جروويل كلينك",
    # Product/marketing brand (the software name) — editable in settings.
    "product_name": "PediaPro",
    "product_name_en": "PediaPro",
    "clinic_tagline": "",
    "default_language": "ar",
    "currency": "EGP",
    "default_growth_reference": "WHO",
    # Patient file numbering (see app/utils/patients.py).
    "patient_number_scheme": "yearly",      # "yearly" | "fixed"
    "patient_number_prefix": "PM",          # used by the yearly scheme
    "patient_number_prefix_fixed": "GC",    # used by the fixed scheme
    # WhatsApp / messaging.
    "crm_mode": "manual",                   # "manual" (wa.me links) | "automatic" (API)
    "wa_provider": "web",                   # "web" | "cloud_api" | "wapilot"
    "wa_country_code": "20",
    "queue_mode": "number",                 # "number" | "time"
    "wa_tpl_appt_confirm": (
        "مرحباً {patient}،\n"
        "تم تأكيد موعدك في {clinic} يوم {date} الساعة {time} مع {doctor}.\n"
        "دورك رقم: {queue}\n"
        "نتمنى لكم الصحة والعافية."
    ),
    "wa_tpl_doctor_schedule": (
        "د. {doctor}، جدول حجوزات اليوم {date} ({count} حجز):\n{list}"
    ),
    "wa_tpl_vaccine_given": (
        "تم بحمد الله تطعيم {patient} — {vaccine} ({dose}).\n"
        "الجرعة القادمة بتاريخ: {next_date}\n"
        "مع تحيات {clinic}."
    ),
    # ETA e-invoicing (demo mode by default so it works without credentials).
    "eta_enabled": "0",
    "eta_mode": "demo",
    "eta_environment": "preprod",
    "eta_default_tax": "exempt",
    "eta_vat_rate": "14",
    "eta_send_gap": "0",
    "eta_default_item_type": "EGS",
}


def register_commands(app):
    @app.cli.command("init-db")
    def init_db():
        """Create all database tables."""
        db.create_all()
        _ensure_default_settings()
        _ensure_default_roles()
        _seed_drugs_safe()
        db.session.commit()
        click.secho("Database initialised.", fg="green")

    @app.cli.command("upgrade-db")
    def upgrade_db():
        """Safely apply additive schema changes to an existing database.

        Creates any new tables and adds new nullable columns that later
        phases introduced, without touching existing data. Idempotent.
        """
        from sqlalchemy import inspect, text

        db.create_all()  # creates any brand-new tables (suppliers, inventory…)
        inspector = inspect(db.engine)

        # (table, column, column DDL type) added by later phases.
        additions = [
            ("vaccine_brands", "purchase_price", "FLOAT"),
            ("vaccine_brands", "max_discount", "FLOAT"),
            ("vaccine_brands", "doses_per_vial", "INTEGER DEFAULT 1"),
            ("vaccine_brands", "doctor_fee", "FLOAT"),
            ("patient_vaccines", "doctor_id", "INTEGER"),
            ("patient_vaccines", "invoice_id", "INTEGER"),
            ("appointments", "vaccine_brand_id", "INTEGER"),
            ("appointments", "vaccine_dose", "INTEGER"),
            ("doctor_service_commissions", "price_override", "FLOAT"),
            ("patient_vaccines", "inventory_id", "INTEGER"),
            ("invoices", "payer_id", "INTEGER"),
            ("invoices", "coverage_card", "VARCHAR(60)"),
            ("invoices", "coverage_expiry", "DATE"),
            ("invoices", "is_tax", "BOOLEAN DEFAULT 0"),
            ("services", "eta_item_type", "VARCHAR(8) DEFAULT 'EGS'"),
            ("vaccines", "route", "VARCHAR(20)"),
            ("users", "photo", "VARCHAR(255)"),
            ("users", "job_title", "VARCHAR(120)"),
            ("users", "branch", "VARCHAR(120)"),
            ("users", "rx_display_name", "VARCHAR(160)"),
            ("users", "professional_title", "VARCHAR(40)"),
            ("users", "specialty", "VARCHAR(160)"),
            ("users", "sub_specialties", "VARCHAR(255)"),
            ("users", "license_no", "VARCHAR(60)"),
            ("users", "signature_file", "VARCHAR(255)"),
            ("users", "stamp_file", "VARCHAR(255)"),
            ("users", "personal_logo", "VARCHAR(255)"),
            ("users", "accent_color", "VARCHAR(20)"),
            ("users", "rx_template_id", "INTEGER"),
            ("users", "theme", "VARCHAR(10)"),
            ("users", "font_scale", "VARCHAR(4)"),
            ("users", "default_landing", "VARCHAR(30)"),
            ("users", "is_practitioner", "BOOLEAN DEFAULT 0"),
            ("appointments", "appt_type", "VARCHAR(20) DEFAULT 'new'"),
            ("appointments", "is_walk_in", "BOOLEAN DEFAULT 0"),
            ("appointments", "cancel_reason", "VARCHAR(200)"),
            ("appointments", "rescheduled_from", "VARCHAR(120)"),
            ("vaccines", "diseases_covered", "VARCHAR(255)"),
            ("vaccines", "min_age_months", "INTEGER"),
            ("vaccines", "max_age_months", "INTEGER"),
            ("vaccines", "booster_required", "BOOLEAN DEFAULT 0"),
            ("vaccines", "is_seasonal", "BOOLEAN DEFAULT 0"),
            ("vaccines", "pregnancy_recommendation", "VARCHAR(120)"),
            ("vaccines", "risk_groups", "VARCHAR(255)"),
            ("vaccines", "contraindications", "TEXT"),
            ("vaccines", "adverse_events_info", "TEXT"),
            ("patient_vaccines", "event_type", "VARCHAR(20) DEFAULT 'given'"),
            ("patient_vaccines", "adverse_events", "TEXT"),
            ("patient_vaccines", "refusal_reason", "VARCHAR(200)"),
            ("patients", "qr_token", "VARCHAR(32)"),
            ("vaccines", "is_discontinued", "BOOLEAN DEFAULT 0"),
            ("vaccines", "replaced_by_id", "INTEGER"),
            ("vaccine_brands", "is_discontinued", "BOOLEAN DEFAULT 0"),
            ("rx_print_templates", "page_size", "VARCHAR(4) DEFAULT 'A4'"),
            ("rx_print_templates", "show_investigations", "BOOLEAN DEFAULT 1"),
            ("rx_print_templates", "margin_top_mm", "INTEGER"),
            ("rx_print_templates", "margin_right_mm", "INTEGER"),
            ("rx_print_templates", "margin_bottom_mm", "INTEGER"),
            ("rx_print_templates", "margin_left_mm", "INTEGER"),
            ("drugs", "dose_per_kg", "FLOAT"),
            ("drugs", "max_per_kg", "FLOAT"),
            ("drugs", "conc_mg_per_ml", "FLOAT"),
            ("prescriptions", "diagnosis_code", "VARCHAR(20)"),
            ("invoices", "discount_id", "INTEGER"),
            ("invoices", "discount_name", "VARCHAR(120)"),
            ("parents", "nationality", "VARCHAR(60)"),
            ("users", "print_title_ar", "TEXT"),
            ("users", "print_title_en", "TEXT"),
        ]
        existing_tables = set(inspector.get_table_names())
        applied = 0
        for table, column, ddl in additions:
            if table not in existing_tables:
                continue
            cols = {c["name"] for c in inspector.get_columns(table)}
            if column not in cols:
                db.session.execute(
                    text(f'ALTER TABLE {table} ADD COLUMN {column} {ddl}')
                )
                applied += 1
                click.echo(f"  + {table}.{column}")
        _ensure_default_settings()
        _ensure_default_roles()
        _seed_drugs_safe()
        try:  # keep the vaccine catalogue current (idempotent)
            from app.utils.vaccines import seed_vaccines
            seed_vaccines()
        except Exception:  # noqa: BLE001
            pass
        db.session.commit()
        click.secho(f"Database upgraded ({applied} column(s) added).", fg="green")

    @app.cli.command("seed-demo")
    def seed_demo_cmd():
        """Populate a realistic demo dataset for presentations."""
        from app.utils.demo import seed_demo
        db.create_all()
        result = seed_demo()
        if result.get("skipped"):
            click.secho("Demo data already present (skipped).", fg="yellow")
        else:
            click.secho(f"Demo data seeded: {result}", fg="green")

    @app.cli.command("reset-data")
    def reset_data_cmd():
        """Delete all operational data (keeps users, roles, settings, catalogue)."""
        from app.utils.demo import reset_all
        counts = reset_all()
        click.secho(f"Reset complete: {counts}", fg="green")

    @app.cli.command("seed-vaccines")
    def seed_vaccines_cmd():
        """Load the bundled Egyptian vaccine catalogue into the database."""
        from app.utils.vaccines import seed_vaccines
        db.create_all()
        n = seed_vaccines()
        click.secho(f"Vaccine catalogue seeded ({n} new vaccines).", fg="green")

    @app.cli.command("seed")
    def seed():
        """Create demo users, default settings and the vaccine catalogue."""
        from app.utils.vaccines import seed_vaccines
        db.create_all()
        _ensure_default_settings()
        _ensure_default_roles()
        _seed_drugs_safe()
        seed_vaccines()

        created = 0
        for username, password, name_ar, name_en, role in DEMO_USERS:
            if User.query.filter_by(username=username).first():
                continue
            user = User(
                username=username,
                full_name=name_ar,
                full_name_en=name_en,
                role=role,
                is_active=True,
            )
            user.set_password(password)
            db.session.add(user)
            created += 1

        db.session.commit()
        click.secho(f"Seed complete. {created} user(s) created.", fg="green")
        if created:
            click.secho("Demo credentials (change in production!):", fg="yellow")
            for username, password, *_ in DEMO_USERS:
                click.echo(f"  {username} / {password}")

    @app.cli.command("create-admin")
    @click.option("--username", prompt=True)
    @click.option("--name", prompt="Full name")
    @click.password_option()
    def create_admin(username, name, password):
        """Create a new administrator account."""
        db.create_all()
        if User.query.filter_by(username=username).first():
            click.secho("Username already exists.", fg="red")
            return
        user = User(username=username, full_name=name, role="admin", is_active=True)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        click.secho(f"Administrator '{username}' created.", fg="green")


def _ensure_default_settings():
    for key, value in DEFAULT_SETTINGS.items():
        if Setting.query.filter_by(key=key).first() is None:
            db.session.add(Setting(key=key, value=value))


# Labels for the five built-in roles seeded into the editable Role table.
_ROLE_LABELS = {
    "admin": ("مدير النظام", "Administrator"),
    "doctor": ("طبيب", "Doctor"),
    "reception": ("استقبال", "Reception"),
    "accountant": ("محاسب", "Accountant"),
    "pharmacy": ("صيدلية", "Pharmacy"),
}


def _seed_drugs_safe():
    """Seed the common-drugs catalogue (idempotent, best-effort)."""
    try:
        from app.utils.drugs import seed_drugs
        seed_drugs()
    except Exception:  # noqa: BLE001
        pass
    try:
        from app.utils.investigations import seed_investigations
        seed_investigations()
    except Exception:  # noqa: BLE001
        pass
    _seed_crm_templates_safe()


# Friendly default names for the seeded CRM templates.
_CRM_TPL_NAMES = {
    "appointment_confirm": "تأكيد موعد",
    "doctor_schedule": "جدول الطبيب اليومي",
    "vaccine_given": "إشعار تطعيم",
    "birthday": "تهنئة عيد ميلاد",
}


def _seed_crm_templates_safe():
    """Seed the unified message-template registry (idempotent, best-effort)."""
    try:
        from app.models import TEMPLATE_DEFAULTS, MessageTemplate
        for occ, body in TEMPLATE_DEFAULTS.items():
            if MessageTemplate.query.filter_by(occasion=occ).first() is None:
                db.session.add(MessageTemplate(
                    name=_CRM_TPL_NAMES.get(occ, occ), occasion=occ,
                    body=body, is_active=True))
    except Exception:  # noqa: BLE001
        pass


def _ensure_default_roles():
    """Seed the built-in roles into the editable Role table (idempotent)."""
    from app.models import ROLE_PERMISSIONS, Role

    for name, modules in ROLE_PERMISSIONS.items():
        if Role.query.filter_by(name=name).first() is not None:
            continue
        label_ar, label_en = _ROLE_LABELS.get(name, (name, name))
        db.session.add(Role(
            name=name, label_ar=label_ar, label_en=label_en,
            modules="" if name == "admin" else ",".join(modules),
            is_system=True, is_admin=(name == "admin"),
        ))
