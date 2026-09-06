"""Custom Flask CLI commands for database setup and seeding.

    flask --app run init-db         create all tables
    flask --app run seed            create demo users (one per role)
    flask --app run create-admin    interactively create an admin user
"""
import os

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
        _seed_service_types_safe()
        _seed_client_categories_safe()
        _seed_devices_safe()
        _seed_accounts_safe()
        _seed_tills_safe()
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

    @app.cli.command("update-check")
    def update_check():
        """Say whether a newer version exists. Never fetch it.

        Called by ``start.bat`` on the way past. It prints a short notice or
        nothing at all, and it exits 0 either way — a clinic must never be
        stopped from opening the program because a check about the program
        could not be made.

        The distinction from ``update.bat`` is the point. Updating is a
        decision somebody makes, with a snapshot before it and a schema
        upgrade after it. This only knocks on the door.

        What it finds is also written down, because the console it prints to
        scrolls past in a window nobody is looking at. The bell reads what was
        stored, so the notice survives until somebody acts on it — and so that
        showing it costs no request of its own.
        """
        from app.utils.updates import pending, remember

        try:
            found = remember(pending())
        except Exception:  # noqa: BLE001 — a notice never blocks a launch
            return
        if not found:
            return
        click.secho("", err=False)
        click.secho("  " + "-" * 56, fg="yellow")
        click.secho("   There is a newer version of the program.", fg="yellow")
        for line in found["notes"]:
            click.secho(f"     - {line}", fg="yellow")
        click.secho("   Close the clinic and run update.bat when convenient.",
                    fg="yellow")
        click.secho("  " + "-" * 56, fg="yellow")

    @app.cli.command("record-version")
    @click.argument("revision", required=False)
    def record_version(revision):
        """Write down which revision this copy is now running.

        A `git clone` can answer that itself. A copy that was downloaded as a
        ZIP cannot, so the update writes it into the instance folder — the one
        place a file survives being replaced by the next update.
        """
        from app.utils.updates import record_installed

        written = record_installed(revision)
        if written:
            click.secho(f"Recorded version {written[:12]}.", fg="green")
        else:
            click.secho("Could not work out which version this is.", fg="yellow")

    @app.cli.command("sync-db")
    def sync_db():
        """Bring the database's *shape* up to the code's. Nothing else.

        This is what every launch needs and all it needs: the schema has to
        match the code that is about to read it. It is additive and idempotent,
        so on an already-current database it does nothing and says so.

        ``start.bat`` used to run the full ``upgrade-db`` on every start, which
        also re-ran every seeder and — worse — took a **pre-upgrade backup each
        time**. That archive holds the database *and every uploaded file*, so a
        clinic with a few gigabytes of photos wrote a few gigabytes on every
        launch, and nothing pruned them until the next scheduled backup
        happened to come round. Opening the program five times in a morning
        cost five full copies of the clinic. Disks fill quietly, and a full
        disk is what stops a clinic.
        """
        from app.utils.schema import apply_schema

        applied = apply_schema(report=click.echo)
        if applied:
            click.secho(f"Database shape updated ({applied} change(s)).", fg="green")
        else:
            click.secho("Database shape already current.", fg="green")

    @app.cli.command("upgrade-db")
    def upgrade_db():
        """Safely apply additive schema changes to an existing database.

        Creates any new tables and adds new nullable columns that later
        phases introduced, without touching existing data. Idempotent.
        """
        # Safety net: snapshot the DB before touching the schema (skipped
        # silently when there is no database file yet, e.g. first init).
        #
        # Trimmed straight afterwards, like every other automatic snapshot.
        # Retention only ever ran from the *scheduled* backup, so these piled
        # up until that happened to come round — and each one carries every
        # uploaded file in the clinic.
        try:
            from app.utils.backups import _retain, create_backup
            click.echo("  ~ pre-upgrade backup: " + create_backup("preupgrade"))
            _retain()
        except Exception:  # noqa: BLE001
            pass

        # The schema itself lives in app/utils/schema.py, because a restore
        # needs to apply it too and there is nobody at a terminal for that.
        from app.utils.schema import apply_schema

        applied = apply_schema(report=click.echo)
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
        try:  # the credits the program ships with — once, and never over
              # anything the clinic wrote
            from app.utils.project import seed_credits
            credited = seed_credits()
            if any(credited.values()):
                click.echo(f"  + credits: {credited['developer']} field(s), "
                           f"{credited['doctors']} person(s)")
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
            # And the figures this program shipped wrong, corrected only where
            # it still holds what we put there. Said out loud either way: a
            # clinical number changing quietly under a clinic is exactly the
            # thing an update is not allowed to do without telling them.
            from app.utils.drugbook_seed import apply_shipped_fixes

            put_right = apply_shipped_fixes()
            if put_right["fixed"]:
                click.secho(f"  ~ drug reference: {put_right['fixed']} shipped "
                            "figure(s) corrected", fg="green")
            if put_right["left"]:
                click.secho(f"  ! drug reference: {put_right['left']} product(s) "
                            "carry your own figure and were left alone",
                            fg="yellow")
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
        _seed_service_types_safe()
        _seed_client_categories_safe()
        _backfill_service_types_safe()
        _migrate_visit_type_map_safe()
        try:  # every service carries a code (auto-generate for older rows)
            from app.utils.services import backfill_service_codes
            backfill_service_codes()
        except Exception:  # noqa: BLE001
            pass
        _seed_devices_safe()
        _seed_accounts_safe()
        _seed_tills_safe()
        _ensure_owner_safe()
        _unforce_doctor_english_safe()
        db.session.commit()
        click.secho(f"Database upgraded ({applied} column(s) added).", fg="green")

    @app.cli.command("backup-now")
    @click.option("--reason", default="manual",
                  help="What the backup is for (manual / preupgrade / …).")
    def backup_now_cmd(reason):
        """Take a full backup and confirm it can actually be read back.

        The confirmation is the point. A backup nobody has opened is a promise,
        not a safety net, and the moment you find out it was empty is the
        moment you needed it. update.bat refuses to go any further if this
        fails, because an update without a working way back is the thing that
        file exists to prevent.
        """
        from app.utils.backups import backup_path, create_backup

        name = create_backup(reason)
        if not name:
            click.secho("Backup failed.", fg="red")
            raise SystemExit(1)

        path = backup_path(name)
        size = os.path.getsize(path) if path and os.path.isfile(path) else 0
        if size <= 0:
            click.secho(f"Backup {name} is empty — treating as a failure.",
                        fg="red")
            raise SystemExit(1)
        click.secho(f"Backup written: {name} ({size / 1024 / 1024:.1f} MB)",
                    fg="green")

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
        _seed_service_types_safe()
        _seed_client_categories_safe()
        _seed_devices_safe()
        _seed_accounts_safe()
        _seed_tills_safe()
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

    @app.cli.command("vaccine-review")
    @click.option("--out", default="vaccine_brands_review.csv",
                  help="Where to write the file.")
    def vaccine_review_cmd(out):
        """Export every brand in the catalogue against the scheduling rules.

        For the clinical review: one row per trade name, showing what the
        program actually holds for it — the age bands it follows, the ceiling
        on its final dose, whether it is routine or given on indication, which
        source its schedule came from — so a doctor can mark what is missing
        against a leaflet rather than against somebody's memory of the
        catalogue.

        Generated rather than kept in the repository on purpose: a checked-in
        copy is out of date the first time a brand is edited, and a stale
        review table is worse than none because it reads as current.
        """
        import csv

        from app.models import Vaccine, VaccineScheduleTemplate

        bands = {}
        for tpl in VaccineScheduleTemplate.query.filter(
                VaccineScheduleTemplate.start_age_min_months.isnot(None)).all():
            bands.setdefault((tpl.vaccine_id, tpl.brand_id), []).append(tpl)

        three = {True: "yes", False: "no", None: "unknown"}
        rows = []
        for vaccine in Vaccine.query.order_by(Vaccine.is_mandatory.desc(),
                                              Vaccine.sort_order).all():
            has_who = VaccineScheduleTemplate.query.filter_by(
                vaccine_id=vaccine.id, source="who").first() is not None
            for brand in vaccine.brands:
                own = bands.get((vaccine.id, brand.id), [])
                wide = bands.get((vaccine.id, None), [])
                rows.append({
                    "vaccine_code": vaccine.code,
                    "vaccine_ar": vaccine.name_ar,
                    "brand": brand.name,
                    "manufacturer": brand.manufacturer or "",
                    "valency": brand.valency or "",
                    "dose_volume": brand.dose_volume or "",
                    "route": vaccine.route or "",
                    "government": "yes" if vaccine.is_mandatory else "no",
                    "doses": len(brand.doses),
                    # 1. age at the first dose
                    "R1_age_bands": (len(own) if own else
                                     (f"{len(wide)} (vaccine-wide)" if wide else "")),
                    # 2. previous doses — not modelled yet
                    "R2_previous_doses": "",
                    # 3. intervals
                    "R3_min_interval_days": vaccine.min_interval_days or "",
                    # 4. window / cutoff
                    "R4_max_age_final_dose_days": brand.max_age_final_dose_days or "",
                    "R4_vaccine_max_age_months": vaccine.max_age_months or "",
                    # 5. booster
                    "R5_booster": "yes" if vaccine.booster_required else "",
                    # 6. indication
                    "R6_indication": brand.reminder_scope or "",
                    # 7. interchangeability — not modelled yet
                    "R7_interchangeable": "",
                    # 8. WHO kept beside the manufacturer
                    "R8_who_template": "yes" if has_who else "",
                    "doses_change_by_start_age":
                        "yes" if brand.doses_change_by_start_age else "",
                    "registered_eg": three[brand.registered_in_egypt],
                    "available_now": three[brand.available_now],
                    "discontinued": "yes" if brand.is_discontinued else "",
                    "seasonal": "yes" if vaccine.is_seasonal else "",
                    "on_demand": "yes" if vaccine.on_demand else "",
                    "catch_up_note": (brand.catch_up_notes
                                      or vaccine.catch_up_notes
                                      or "").replace("\n", " ")[:300],
                    "source_url": brand.source_url or "",
                })

        if not rows:
            click.secho("The catalogue is empty — seed it first.", fg="yellow")
            return
        # utf-8-sig so Excel opens the Arabic without being told to.
        with open(out, "w", encoding="utf-8-sig", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        gov = sum(1 for r in rows if r["government"] == "yes")
        click.secho(f"{len(rows)} brands -> {out} "
                    f"({gov} government, {len(rows) - gov} optional)", fg="green")

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
        _seed_service_types_safe()
        _seed_client_categories_safe()
        _seed_devices_safe()
        _seed_accounts_safe()
        _seed_tills_safe()
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
    "nursing": ("تمريض", "Nursing"),
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
    "appointment_reminder": "تذكير قبل الموعد",
    "no_show_followup": "متابعة الغياب",
    "patient_recall": "استدعاء مريض غايب",
    "doctor_schedule": "جدول الطبيب اليومي",
    "vaccine_given": "إشعار تطعيم",
    "vaccine_back": "التطعيم بقى متوفر",
    "birthday": "تهنئة عيد ميلاد",
}


def _seed_tills_safe():
    """The cash tills, and the one-off move of history into them.

    Both are idempotent and both stay quiet on failure — an install that can't
    seed a till must still finish upgrading, and the screen says plainly when
    no till exists.
    """
    try:
        from app.utils.treasury import seed_accounts
        made = seed_accounts()
        if made:
            click.secho(f"  + {made} cash till(s)", fg="green")
    except Exception as exc:  # noqa: BLE001
        click.secho(f"  ! cash tills not seeded: {exc}", fg="yellow")
        return
    try:
        from app.utils.treasury_migrate import migrate_history
        moved = migrate_history()
        if moved.get("tagged"):
            click.secho(f"  ~ {moved['tagged']} money movement(s) tagged with "
                        f"a till", fg="green")
        if moved.get("entries"):
            click.secho(f"  ~ {moved['entries']} correction entr(ies) posted "
                        f"to move history out of the main drawer", fg="green")
    except Exception as exc:  # noqa: BLE001
        click.secho(f"  ! till history not migrated: {exc}", fg="yellow")


def _seed_visit_types_safe():
    """Seed the editable visit-type catalogue from the built-in defaults
    (idempotent, best-effort)."""
    try:
        from app.utils.visit_types import ensure_seeded
        ensure_seeded()
    except Exception:  # noqa: BLE001
        pass


def _seed_service_types_safe():
    """Seed the editable service-type catalogue from the built-in list
    (idempotent, best-effort)."""
    try:
        from app.utils.service_types import ensure_seeded
        ensure_seeded()
    except Exception:  # noqa: BLE001
        pass


def _seed_client_categories_safe():
    """Seed the editable client-category catalogue from the built-in list
    (idempotent, best-effort)."""
    try:
        from app.utils.client_categories import ensure_seeded
        ensure_seeded()
    except Exception:  # noqa: BLE001
        pass


# The default medical-device catalogue lives in app/utils/reference.py, which
# is the other place that seeds it. It was written out here as well, and two
# copies of a list are two lists the moment somebody edits the file they happen
# to have open — the seeder a fresh install runs and the seeder an upgrade runs
# would then hand out different catalogues.


def _seed_devices_safe():
    """Seed the default medical-device catalogue (idempotent, best-effort)."""
    try:
        from app.models import MedicalDevice
        from app.utils.reference import DEFAULT_DEVICES

        for name, name_en, manuf, model, dtype, sw in DEFAULT_DEVICES:
            if MedicalDevice.query.filter_by(name=name).first() is None:
                db.session.add(MedicalDevice(
                    name=name, name_en=name_en, manufacturer=manuf, model=model,
                    device_type=dtype, software=sw, connection_type="usb",
                    import_mode="manual", is_active=True, is_system=True))
        db.session.flush()
        # …and the fields each one records, or the device arrives seeded,
        # priced and unusable.
        from app.utils.device_templates import seed_device_measurements

        seed_device_measurements()
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


def _unforce_doctor_english_safe():
    """Give back the interface language that was taken from the doctors.

    Creating a doctor used to set ``language = "en"`` whatever the clinic ran
    in, so a doctor signed in to an English program wrapped around Arabic
    names and Arabic complaints while reception saw Arabic. The default is
    gone; this is for the accounts that already carry it.

    Only ``en``, only doctors, and only once — the flag is what makes it once,
    because a clinic that deliberately puts a doctor back into English must
    not have it undone by the next upgrade.
    """
    from app.models import Setting, User

    try:
        if Setting.get("doctor_language_unforced") == "1":
            return
        changed = 0
        for user in User.query.filter_by(role="doctor", language="en").all():
            user.language = None
            changed += 1
        Setting.set("doctor_language_unforced", "1")
        db.session.commit()
        if changed:
            click.secho(f"  + {changed} doctor(s) returned to the clinic's "
                        "language (they can still choose English)", fg="green")
    except Exception:  # noqa: BLE001
        db.session.rollback()


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


def _migrate_visit_type_map_safe():
    """Move the visit-type→service map out of settings and onto the services
    (idempotent, best-effort). The pricing of a visit now lives with the thing
    being priced."""
    try:
        from app.utils.pricing import migrate_visit_type_map
        moved = migrate_visit_type_map()
        if moved:
            click.echo(f"  ~ {moved} visit-type charge(s) moved onto their service")
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
        role = Role(
            name=name, label_ar=label_ar, label_en=label_en,
            modules="" if name == "admin" else ",".join(modules),
            is_system=True, is_admin=(name == "admin"),
        )
        # Seed the capabilities too, now that a role can hold them. Without
        # this a fresh clinic's nursing role would be a set of screens with no
        # permission to write on any of them — and `can` would fall back to
        # the table in code, which is the thing the column exists to replace.
        from app.models.permissions import ROLE_CAPABILITIES
        role.set_capabilities(ROLE_CAPABILITIES.get(name, []))
        db.session.add(role)
