"""Bringing a database's shape up to the code's, wherever that is needed.

This lived inside the ``upgrade-db`` command, which meant it could only be run
by a person at a terminal — and the one moment it is needed most is a moment
nobody is at a terminal for.

**Restoring a backup.** ``restore_backup`` put an older database and its files
back and stopped there, so newer code went looking for a column that database
has never had. The symptoms scatter — one screen fine, the next raising
``no such column`` — which reads as a corrupt backup rather than a schema a
version behind, and the honest response to a corrupt backup is to give up on it
and re-enter the settings by hand. That is the reported experience, and it was
never a bad backup.

**Schema only, on purpose.** The command also seeds catalogues and backfills
columns; none of that belongs here. A restored backup brings its own content,
and re-running seeders over somebody's restored data would add rows they did
not ask for at the exact moment they are trying to get back to a known state.
What a restore needs is for the *shape* to match the code. Nothing else.

Additive only, and idempotent: new tables, and new nullable columns. It never
drops or rewrites, so running it on a database that is already current does
nothing at all — which is what makes it safe to call on a path where nobody
chose to run it.
"""

# (table, column, column DDL type) introduced by later phases.
ADDITIONS = [
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
    ("payments", "account_id", "INTEGER"),
    ("expenses", "account_id", "INTEGER"),
    ("supplier_payments", "account_id", "INTEGER"),
    ("cashier_shifts", "account_id", "INTEGER"),
    ("cash_accounts", "settles_into_id", "INTEGER"),
    ("cash_accounts", "fee_percent", "FLOAT"),
    ("cash_accounts", "settle_after_days", "INTEGER"),
    ("expenses", "shift_id", "INTEGER"),
    ("supplier_payments", "shift_id", "INTEGER"),
    ("payments", "tendered", "FLOAT"),
    ("invoice_items", "vaccine_brand_id", "INTEGER"),
    ("invoice_items", "vaccine_dose_number", "INTEGER"),
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
    ("users", "sidebar", "VARCHAR(10)"),
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
    ("services", "visit_type", "VARCHAR(30)"),
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
    # Which granularity a period is. Existing rows are months, and the default
    # says so — a clinic that already closed January must not find it
    # unlabelled after an upgrade.
    ("accounting_periods", "kind", "VARCHAR(10) DEFAULT 'month'"),
    # Which import created this vaccination record, so an import can be undone
    # exactly and a doctor can see which doses came from the old program.
    ("patient_vaccines", "import_batch_id", "INTEGER"),
]

def apply_schema(report=None):
    """Create missing tables and add missing columns. Returns the count added.

    ``report`` is an optional callable for progress — the CLI passes
    ``click.echo``; the restore path passes nothing, because there is nobody
    watching a terminal when a restore runs.
    """
    from sqlalchemy import inspect, text

    from app.extensions import db

    db.create_all()                 # brand-new tables
    inspector = inspect(db.engine)
    existing_tables = set(inspector.get_table_names())

    applied = 0
    for table, column, ddl in ADDITIONS:
        if table not in existing_tables:
            continue
        cols = {c["name"] for c in inspector.get_columns(table)}
        if column in cols:
            continue
        db.session.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
        applied += 1
        if report:
            report(f"  + {table}.{column}")
        if (table, column) == ("named_discounts", "auto_apply"):
            # A campaign a clinic already created was always chosen by hand —
            # turning it on for everybody is not an upgrade. New campaigns
            # default to automatic; existing ones do not.
            db.session.execute(text(
                "UPDATE named_discounts SET auto_apply = 0 "
                "WHERE dtype = 'campaign'"))
    db.session.commit()
    return applied
