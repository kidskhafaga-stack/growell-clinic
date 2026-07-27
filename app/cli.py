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
    # NOTE: message bodies are NOT settings any more. They live in the
    # MessageTemplate registry, edited on one screen, seeded by
    # ``seed_system_templates`` from ``TEMPLATE_DEFAULTS``. The old
    # ``wa_tpl_*`` keys are still *read* as a fallback for clinics that edited
    # them before the move, but writing them here would keep resurrecting a
    # second place to edit the same text.
    # ETA e-invoicing (demo mode by default so it works without credentials).
    "eta_enabled": "0",
    "eta_mode": "demo",
    "eta_environment": "preprod",
    "eta_default_tax": "exempt",
    "eta_vat_rate": "14",
    "eta_send_gap": "0",
    "eta_default_item_type": "EGS",
    # Login security: lock an account after N failed attempts for M minutes.
    "login_max_attempts": "5",
    "login_lockout_minutes": "15",
}


def register_commands(app):
    @app.cli.command("init-db")
    def init_db():
        """Create all database tables."""
        db.create_all()
        _ensure_default_settings()
        _ensure_default_roles()
        _seed_visit_types_safe()
        _seed_devices_safe()
        _seed_accounts_safe()
        _seed_crm_templates_safe()
        # Every catalogue the clinic needs — and no patients, no demo users.
        from app.utils.reference import reference_counts, seed_reference
        seed_reference()
        db.session.commit()
        counts = reference_counts()
        click.secho("Database initialised.", fg="green")
        click.secho(
            f"  catalogues: {counts['vaccines']} vaccines · "
            f"{counts['services']} services · {counts['drugs']} drugs "
            f"({counts['ingredients']} ingredients) · "
            f"{counts['investigations']} investigations · "
            f"{counts['store_items']} store items", fg="green")

    @app.cli.command("upgrade-db")
    def upgrade_db():
        """Safely apply additive schema changes to an existing database.

        Creates any new tables and adds new nullable columns that later
        phases introduced, without touching existing data. Idempotent.
        """
        from sqlalchemy import inspect, text

        # Safety net: snapshot the DB before touching the schema (skipped
        # silently when there is no database file yet, e.g. first init).
        try:
            from app.utils.backups import create_backup
            click.echo("  ~ pre-upgrade backup: " + create_backup("preupgrade"))
        except Exception:  # noqa: BLE001
            pass

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
            ("patient_vaccines", "given_outside", "BOOLEAN DEFAULT 0"),
            ("appointments", "vaccine_brand_id", "INTEGER"),
            ("appointments", "vaccine_dose", "INTEGER"),
            ("appointments", "extra_service_ids", "VARCHAR(200)"),
            ("stock_movements", "document_id", "INTEGER"),
            ("vaccine_inventory", "document_id", "INTEGER"),
            ("stock_movements", "warehouse_id", "INTEGER"),
            ("vaccine_inventory", "warehouse_id", "INTEGER"),
            ("store_documents", "warehouse_id", "INTEGER"),
            ("store_documents", "to_warehouse_id", "INTEGER"),
            ("cashier_shifts", "shift_number", "VARCHAR(40)"),
            ("doctor_schedules", "start_date", "DATE"),
            ("doctor_schedules", "end_date", "DATE"),
            ("doctor_schedules", "season_label", "VARCHAR(60)"),
            ("doctor_service_commissions", "price_override", "FLOAT"),
            ("parents", "auto_named", "BOOLEAN DEFAULT 0"),
            ("diagnoses", "title_en", "VARCHAR(255)"),
            ("visit_investigations", "name_en", "VARCHAR(200)"),
            ("prescription_investigations", "name_en", "VARCHAR(200)"),
            ("payments", "kind", "VARCHAR(10) DEFAULT 'payment'"),
            ("payments", "tendered", "FLOAT"),
            ("invoice_items", "vaccine_brand_id", "INTEGER"),
            ("named_discounts", "payer_id", "INTEGER"),
            ("named_discounts", "min_siblings", "INTEGER DEFAULT 2"),
            ("drugs", "generic_id", "INTEGER"),
            ("drug_interactions", "generic_a_id", "INTEGER"),
            ("drug_interactions", "generic_b_id", "INTEGER"),
            ("drug_interactions", "alternative", "VARCHAR(200)"),
            ("drug_interactions", "is_active", "BOOLEAN DEFAULT 1"),
            ("drugs", "pack_size", "VARCHAR(60)"),
            ("drugs", "price", "FLOAT"),
            ("drugs", "barcode", "VARCHAR(60)"),
            ("drugs", "manufacturer", "VARCHAR(120)"),
            ("drugs", "price_updated_at", "DATETIME"),
            ("drugs", "image", "VARCHAR(255)"),
            ("drugs", "leaflet", "VARCHAR(255)"),
            ("patient_vaccines", "inventory_id", "INTEGER"),
            ("invoices", "payer_id", "INTEGER"),
            ("invoices", "coverage_card", "VARCHAR(60)"),
            ("invoices", "coverage_expiry", "DATE"),
            ("invoices", "is_tax", "BOOLEAN DEFAULT 0"),
            ("services", "eta_item_type", "VARCHAR(8) DEFAULT 'EGS'"),
            ("vaccines", "route", "VARCHAR(20)"),
            ("vaccines", "on_demand", "BOOLEAN DEFAULT 0"),
            ("vaccines", "vaccine_type", "VARCHAR(40)"),
            ("vaccines", "min_interval_days", "INTEGER"),
            ("vaccines", "catch_up_notes", "TEXT"),
            ("vaccines", "coadministration_notes", "TEXT"),
            ("vaccines", "precautions", "TEXT"),
            ("vaccines", "reference", "VARCHAR(255)"),
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
            ("users", "language", "VARCHAR(5)"),
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
            ("message_templates", "image_url", "VARCHAR(300)"),
            ("message_templates", "send_mode", "VARCHAR(10) DEFAULT 'manual'"),
            ("message_templates", "is_system", "BOOLEAN DEFAULT 0"),
            ("message_logs", "image_url", "VARCHAR(300)"),
            ("message_logs", "template_type", "VARCHAR(30)"),
            ("message_logs", "scheduled_at", "DATETIME"),
            ("message_logs", "sent_at", "DATETIME"),
            ("message_logs", "direction", "VARCHAR(3) DEFAULT 'out'"),
            ("patients", "wa_opt_out", "BOOLEAN DEFAULT 0"),
            ("patients", "own_phone", "VARCHAR(20)"),
            ("visit_services", "invoice_id", "INTEGER"),
            ("payments", "shift_id", "INTEGER"),
            ("vaccine_brands", "barcode", "VARCHAR(60)"),
            ("vaccine_brands", "item_code", "VARCHAR(40)"),
            ("vaccine_brands", "min_stock", "INTEGER"),
            ("vaccine_brands", "purchase_unit", "VARCHAR(30)"),
            ("vaccine_brands", "dispense_unit", "VARCHAR(30)"),
            ("vaccine_inventory", "mfg_date", "DATE"),
            ("vaccine_inventory", "receipt_reason", "VARCHAR(20) DEFAULT 'opening'"),
            ("purchase_order_items", "vaccine_brand_id", "INTEGER"),
            ("services", "service_type", "VARCHAR(20) DEFAULT 'other'"),
            ("services", "duration_minutes", "INTEGER"),
            ("services", "cost", "FLOAT"),
            ("services", "needs_doctor", "BOOLEAN DEFAULT 1"),
            ("services", "needs_device", "BOOLEAN DEFAULT 0"),
            ("services", "needs_report", "BOOLEAN DEFAULT 0"),
            ("services", "needs_consumables", "BOOLEAN DEFAULT 0"),
            ("services", "needs_booking", "BOOLEAN DEFAULT 0"),
            ("services", "needs_approval", "BOOLEAN DEFAULT 0"),
            ("services", "can_standalone", "BOOLEAN DEFAULT 1"),
            ("services", "can_add_during_visit", "BOOLEAN DEFAULT 1"),
            ("services", "device_id", "INTEGER"),
            ("store_items", "purchase_unit", "VARCHAR(40)"),
            ("store_items", "units_per_purchase", "INTEGER DEFAULT 1"),
            ("message_templates", "delay_days", "INTEGER DEFAULT 0"),
            ("message_templates", "delay_hours", "INTEGER DEFAULT 0"),
            ("message_templates", "send_hour", "INTEGER"),
            ("vaccine_schedule_templates", "source", "VARCHAR(20) DEFAULT 'custom'"),
            ("vaccine_schedule_templates", "is_seeded", "BOOLEAN DEFAULT 0"),
            ("patients", "archived_at", "DATETIME"),
            ("patients", "archive_reason", "VARCHAR(20)"),
            ("expenses", "recur_start", "DATE"),
            ("expenses", "recur_end", "DATE"),
            ("users", "is_super_admin", "BOOLEAN DEFAULT 0"),
            ("store_documents", "supplier_ref", "VARCHAR(60)"),
            ("store_documents", "due_date", "DATE"),
            ("store_documents", "payment_terms", "VARCHAR(12)"),
            ("named_discounts", "scope", "VARCHAR(20) DEFAULT 'all'"),
            ("vaccine_brands", "catch_up_notes", "TEXT"),
            ("vaccine_brands", "price_policy", "VARCHAR(10) DEFAULT 'manual'"),
            ("vaccine_brands", "margin_percent", "FLOAT"),
            ("store_items", "price_policy", "VARCHAR(10) DEFAULT 'manual'"),
            ("store_items", "margin_percent", "FLOAT"),
            ("store_items", "item_code", "VARCHAR(40)"),
            ("message_templates", "occasion_date", "DATE"),
            ("message_templates", "repeat_rule", "VARCHAR(10) DEFAULT 'once'"),
            ("message_templates", "last_enqueued_on", "DATE"),
            ("message_logs", "template_id", "INTEGER"),
            ("named_discounts", "service_id", "INTEGER"),
            ("named_discounts", "same_doctor", "BOOLEAN DEFAULT 1"),
            ("named_discounts", "family_wide", "BOOLEAN DEFAULT 1"),
            ("named_discounts", "auto_apply", "BOOLEAN DEFAULT 1"),
            ("vaccine_brand_doses", "is_booster", "BOOLEAN DEFAULT 0"),
            ("patient_vaccines", "outside_place", "VARCHAR(160)"),
            ("patient_attachments", "investigation_id", "INTEGER"),
            ("patient_attachments", "source", "VARCHAR(20) DEFAULT 'upload'"),
            ("patient_attachments", "linked_by", "INTEGER"),
            ("patient_attachments", "linked_at", "DATETIME"),
            ("visits", "channel", "VARCHAR(12) DEFAULT 'clinic'"),
            ("visits", "decision", "VARCHAR(16)"),
            ("visits", "based_on_id", "INTEGER"),
            ("conversations", "topic", "VARCHAR(16)"),
            ("drugs", "trade_name_ar", "VARCHAR(160)"),
            ("drugs", "route", "VARCHAR(20)"),
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
                if (table, column) == ("named_discounts", "auto_apply"):
                    # A campaign a clinic already created was always chosen by
                    # hand — turning it on for everybody is not an upgrade.
                    # New campaigns default to automatic; existing ones don't.
                    db.session.execute(text(
                        "UPDATE named_discounts SET auto_apply = 0 "
                        "WHERE dtype = 'campaign'"))
        _ensure_default_settings()
        _ensure_default_roles()
        _seed_drugs_safe()
        try:  # keep the vaccine catalogue current (idempotent)
            from app.utils.vaccines import seed_vaccine_schedules, seed_vaccines
            seed_vaccines()
            seed_vaccine_schedules()
        except Exception:  # noqa: BLE001
            pass
        try:  # ensure base services + visit-type pricing exist (idempotent)
            from app.utils.services import seed_services
            seed_services()
        except Exception:  # noqa: BLE001
            pass
        try:  # seed default general-store consumables on a fresh store
            from app.utils.store_seed import seed_store_items_if_empty
            seed_store_items_if_empty()
        except Exception:  # noqa: BLE001
            pass
        try:  # internal item codes (ITM-/VAC-) + default barcodes, fill-only
            from app.utils.item_codes import backfill_item_codes
            backfill_item_codes()
        except Exception:  # noqa: BLE001
            pass
        try:  # message log: one spelling per number, so one conversation per
              # family instead of "01…" and "201…" sitting side by side
            from app.utils.inbox import normalize_logged_phones
            moved = normalize_logged_phones()
            if moved:
                click.echo(f"  ~ phone numbers normalised in {moved} message(s)")
        except Exception:  # noqa: BLE001
            pass
        try:  # the front desk's canned answers, on a fresh install only
            from app.utils.service_desk import seed_quick_replies
            made = seed_quick_replies()
            if made:
                click.echo(f"  + {made} quick replies")
        except Exception:  # noqa: BLE001
            pass
        try:  # drug reference: classes/ingredients/brands on a fresh install,
              # and link hand-typed drugs to their ingredient afterwards
            from app.utils.drugbook_seed import (link_existing_drugs,
                                                 seed_drugbook,
                                                 seed_interactions)
            made = seed_drugbook()
            made["linked"] = made.get("linked", 0) + link_existing_drugs()
            made["interactions"] = made.get("interactions", 0) + seed_interactions()
            if any(made.values()):
                click.secho("  + drug reference: "
                            f"{made['generics']} ingredient(s), "
                            f"{made['brands']} product(s), "
                            f"{made['interactions']} interaction(s)", fg="green")
        except Exception as exc:  # noqa: BLE001
            # Loud, not silent: a clinic that opens an empty drug reference
            # needs to see why rather than assume the feature isn't there.
            click.secho(f"  ! drug reference not seeded: {exc}", fg="yellow")
        try:  # unify CRM templates into the registry (migrates legacy settings)
            from app.utils.whatsapp import seed_system_templates
            seed_system_templates()
        except Exception:  # noqa: BLE001
            pass
        _seed_visit_types_safe()
        _backfill_service_types_safe()
        try:  # every service carries a code (auto-generate for older rows)
            from app.utils.services import backfill_service_codes
            backfill_service_codes()
        except Exception:  # noqa: BLE001
            pass
        _seed_devices_safe()
        _seed_accounts_safe()
        _ensure_owner_safe()
        db.session.commit()
        click.secho(f"Database upgraded ({applied} column(s) added).", fg="green")

    @app.cli.command("send-due")
    def send_due_cmd():
        """Dispatch scheduled WhatsApp messages whose time has come."""
        from app.utils.whatsapp import dispatch_due
        res = dispatch_due()
        click.secho(
            f"Dispatched {res['sent']} (skipped {res['skipped']}) "
            f"of {res['considered']} due.", fg="green")

    @app.cli.command("archive-inactive")
    @click.option("--force", is_flag=True,
                  help="Run even when auto-archiving is disabled in settings.")
    def archive_inactive_cmd(force):
        """Archive patient files with no activity for the configured N years."""
        from app.utils.archiving import auto_archive, auto_enabled, inactive_years
        if not force and not auto_enabled():
            click.secho("Auto-archiving is disabled (use --force to run anyway).",
                        fg="yellow")
            return
        n = auto_archive()
        click.secho(f"Archived {n} inactive file(s) "
                    f"(> {inactive_years()} years).", fg="green")

    @app.cli.command("seed-reference")
    def seed_reference_cmd():
        """Load the clinic's catalogues only: vaccines, services, drugs,
        investigations, store items, message templates.

        No users, no patients, no demo cases — this is the data a real clinic
        starts from, and it is safe to re-run at any time."""
        from app.utils.reference import reference_counts, seed_reference

        db.create_all()
        _ensure_default_settings()
        _ensure_default_roles()
        _seed_visit_types_safe()
        _seed_devices_safe()
        _seed_accounts_safe()
        made = seed_reference()
        db.session.commit()
        for key, value in made.items():
            if key == "errors":
                for err in value:
                    click.secho(f"  ! {err}", fg="yellow")
            elif value:
                click.secho(f"  + {key}: {value}", fg="green")
        counts = reference_counts()
        click.secho(
            f"Reference ready: {counts['vaccines']} vaccines · "
            f"{counts['services']} services · {counts['drugs']} drugs "
            f"({counts['ingredients']} ingredients) · "
            f"{counts['investigations']} investigations · "
            f"{counts['store_items']} store items.", fg="green")

    @app.cli.command("seed-drugbook")
    def seed_drugbook_cmd():
        """(Re)load the drug reference: classes, ingredients, products.

        Runs on install and on every upgrade too — this is for when a clinic
        wants it back after clearing it, or after pulling a newer list."""
        from app.utils.drugbook_seed import (link_existing_drugs, seed_drugbook,
                                             seed_interactions)
        db.create_all()
        made = seed_drugbook()
        made["linked"] = made.get("linked", 0) + link_existing_drugs()
        made["interactions"] = made.get("interactions", 0) + seed_interactions()
        db.session.commit()
        from app.models import Drug, DrugClass, GenericDrug
        click.secho(
            f"Drug reference: {DrugClass.query.count()} classes, "
            f"{GenericDrug.query.count()} ingredients, "
            f"{Drug.query.count()} products "
            f"(added {made['generics']} / {made['brands']} now).", fg="green")

    @app.cli.command("import-drugs")
    @click.argument("path", type=click.Path(exists=True, dir_okay=False))
    @click.option("--dry-run", is_flag=True,
                  help="Read and report, write nothing.")
    @click.option("--create-classes", is_flag=True,
                  help="Also create the file's own drug groupings (thousands, "
                       "on a market register — usually not what you want).")
    def import_drugs_cmd(path, dry_run, create_classes):
        """Load a drug list (CSV or JSON) into the reference.

        Built for the real thing: the published Egyptian register is 25,000
        products, which is a long wait in a browser tab and a request that may
        time out halfway. On the command line it runs to completion and says
        what it did.
        """
        from app.utils.drugbook_import import import_rows, parse

        db.create_all()
        with open(path, "rb") as fh:
            rows, errors = parse(fh.read())
        for line in errors[:10]:
            click.secho(f"  ! {line}", fg="yellow")
        if len(errors) > 10:
            click.secho(f"  ! …and {len(errors) - 10} more", fg="yellow")
        if not rows:
            click.secho("Nothing to import.", fg="red")
            return
        click.echo(f"Read {len(rows)} rows. Importing…")
        made = import_rows(rows, dry_run=dry_run,
                           create_classes=create_classes)
        if not dry_run:
            db.session.commit()
        from app.models import Drug, GenericDrug
        click.secho(
            f"{'Would add' if dry_run else 'Added'} {made['brands']} products "
            f"and {made['generics']} ingredients; {made['updated']} updated, "
            f"{made['skipped']} unchanged, {made['links']} ingredient links.",
            fg="green")
        if not dry_run:
            click.echo(f"Reference now holds {Drug.query.count()} products "
                       f"and {GenericDrug.query.count()} ingredients.")

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
        from app.utils.vaccines import seed_vaccine_schedules, seed_vaccines
        db.create_all()
        n = seed_vaccines()
        s = seed_vaccine_schedules()
        click.secho(f"Vaccine catalogue seeded ({n} new vaccines, "
                    f"{s} schedule templates).", fg="green")

    @app.cli.command("seed")
    def seed():
        """First-run setup: the clinic's catalogues + one login per role.

        The catalogues come from ``seed-reference`` (no patients, no cases);
        the only demo part here is the set of starter logins, which exist so
        the first person can get in. Use ``seed-demo`` for sample cases."""
        from app.utils.reference import seed_reference
        db.create_all()
        _ensure_default_settings()
        _ensure_default_roles()
        _seed_visit_types_safe()
        _seed_devices_safe()
        _seed_accounts_safe()
        seed_reference()

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
                # The primary admin is the institution owner (super-admin).
                is_super_admin=(role == "admin"),
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
        user = User(username=username, full_name=name, role="admin",
                    is_active=True, is_super_admin=True)
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
    try:  # the drug reference: classes → ingredients → trade names
        from app.utils.drugbook_seed import (link_existing_drugs, seed_drugbook,
                                             seed_interactions)
        seed_drugbook()
        link_existing_drugs()
        seed_interactions()
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


def _seed_visit_types_safe():
    """Seed the editable visit-type catalogue from the built-in defaults
    (idempotent, best-effort)."""
    try:
        from app.utils.visit_types import ensure_seeded
        ensure_seeded()
    except Exception:  # noqa: BLE001
        pass


# Default medical-device catalogue (from the project's device discussion).
# name, name_en, manufacturer, model, device_type
_DEFAULT_DEVICES = [
    ("جهاز وظائف تنفس", "Spirometer", "MIR", "Spirobank II", "spirometry", "WinSpiroPRO"),
    ("جهاز رسم قلب", "ECG", None, None, "ecg", None),
    ("جهاز إيكو", "Echocardiography", None, None, "echo", None),
    ("جهاز رسم مخ", "EEG", None, None, "eeg", None),
    ("جهاز موجات صوتية", "Ultrasound", None, None, "ultrasound", None),
    ("جهاز سمعيات", "Audiometer", None, None, "audiometry", None),
    ("جهاز ضغط الأذن", "Tympanometer", None, None, "tympanometry", None),
]


def _seed_devices_safe():
    """Seed the default medical-device catalogue (idempotent, best-effort)."""
    try:
        from app.models import MedicalDevice
        for name, name_en, manuf, model, dtype, sw in _DEFAULT_DEVICES:
            if MedicalDevice.query.filter_by(name=name).first() is None:
                db.session.add(MedicalDevice(
                    name=name, name_en=name_en, manufacturer=manuf, model=model,
                    device_type=dtype, software=sw, connection_type="usb",
                    import_mode="manual", is_active=True, is_system=True))
    except Exception:  # noqa: BLE001
        pass


def _seed_accounts_safe():
    """Seed the chart of accounts once (idempotent; silent pre-table)."""
    try:
        from app.utils.accounting import ensure_seeded
        if ensure_seeded():
            click.echo("  + chart of accounts seeded")
    except Exception:  # noqa: BLE001
        pass


def _ensure_owner_safe():
    """Guarantee at least one institution owner exists. On an existing DB the
    new ``is_super_admin`` flag defaults to 0, so promote every current admin to
    owner (no one loses access); only later can owners create plain admins."""
    try:
        if User.query.filter_by(is_super_admin=True).first() is not None:
            return
        promoted = 0
        for u in User.query.all():
            if u.is_admin:
                u.is_super_admin = True
                promoted += 1
        if promoted:
            click.echo(f"  + {promoted} admin(s) promoted to owner")
    except Exception:  # noqa: BLE001
        pass


def _backfill_service_types_safe():
    """Give services created before the Service Engine a sensible service_type
    derived from their accounting category (idempotent, best-effort)."""
    try:
        from app.models import Service, service_type_for_category
        for svc in Service.query.filter(
                (Service.service_type.is_(None)) | (Service.service_type == "other")).all():
            derived = service_type_for_category(svc.category)
            if derived != "other":
                svc.service_type = derived
    except Exception:  # noqa: BLE001
        pass


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
