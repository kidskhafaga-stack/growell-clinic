"""Importing a drug list (EDA / supplier / pharmacy export) into the reference.

The seeded catalogue is a working set, not the market. A clinic that wants the
full Egyptian list — thousands of items — brings its own file, and this reads
it: one row per **product** (trade name + strength), naming the ingredient and
the class it belongs to. Missing classes and ingredients are created as the
rows are read, so a single file can build the whole tree.

Everything is idempotent and additive: re-importing the same file updates the
commercial fields (price, barcode, pack, manufacturer) and creates nothing
twice. Nothing is ever deleted by an import.
"""
import csv
import io

from app.extensions import db
from app.models import Drug, DrugClass, GenericDrug

# Accepted column names → our field. Arabic headers are accepted too, because
# the files clinics actually have are Arabic.
COLUMNS = {
    "class": "class", "المجموعة": "class", "المجموعة الدوائية": "class",
    "generic": "generic_en", "generic_en": "generic_en",
    "active ingredient": "generic_en", "المادة الفعالة": "generic_ar",
    "generic_ar": "generic_ar",
    "trade_name": "trade_name", "trade name": "trade_name", "brand": "trade_name",
    "الاسم التجاري": "trade_name", "اسم الصنف": "trade_name",
    "form": "form", "الشكل": "form", "شكل الدواء": "form",
    "strength": "strength", "التركيز": "strength",
    "conc_mg_per_ml": "conc", "conc": "conc", "التركيز لكل مل": "conc",
    "manufacturer": "manufacturer", "الشركة": "manufacturer",
    "price": "price", "السعر": "price",
    "barcode": "barcode", "الباركود": "barcode",
    "pack_size": "pack_size", "العبوة": "pack_size",
}

TEMPLATE_HEADER = ["class", "generic_ar", "generic_en", "trade_name", "form",
                   "strength", "conc_mg_per_ml", "manufacturer", "price",
                   "barcode", "pack_size"]

TEMPLATE_SAMPLE = [
    ["خافضات الحرارة ومسكنات الألم", "باراسيتامول", "Paracetamol", "Cetal",
     "syrup", "120 mg/5 ml", "24", "Epico", "27", "", "60 ml"],
    ["المضادات الحيوية", "أموكسيسيللين", "Amoxicillin", "E-Mox",
     "syrup", "125 mg/5 ml", "25", "Epico", "35", "", "60 ml"],
]


def template_csv():
    """The blank file to fill in, with one example row per column meaning."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(TEMPLATE_HEADER)
    for row in TEMPLATE_SAMPLE:
        writer.writerow(row)
    return "﻿" + buf.getvalue()          # BOM so Excel opens it as UTF-8


def _clean(value):
    return (value or "").strip()


def _number(value):
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def parse(stream_bytes):
    """Read the uploaded file into normalised row dicts.

    Returns ``(rows, errors)``. A row missing a trade name is reported rather
    than guessed at — an unnamed product is not importable.
    """
    text = stream_bytes.decode("utf-8-sig", errors="replace") \
        if isinstance(stream_bytes, bytes) else stream_bytes
    sample = text[:2048]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    rows, errors = [], []
    if not reader.fieldnames:
        return rows, ["empty file"]
    mapping = {}
    for raw in reader.fieldnames:
        key = COLUMNS.get((raw or "").strip().lower())
        if key:
            mapping[raw] = key
    if "trade_name" not in mapping.values():
        return rows, ["no trade-name column"]
    for i, raw_row in enumerate(reader, start=2):
        row = {}
        for raw_key, field in mapping.items():
            row[field] = _clean(raw_row.get(raw_key))
        if not row.get("trade_name"):
            errors.append(f"line {i}: no trade name")
            continue
        rows.append(row)
    return rows, errors


def import_rows(rows, dry_run=False):
    """Create/update classes, ingredients and products from parsed rows.

    Returns a summary dict. With ``dry_run`` nothing is written — the caller
    shows the numbers first, which is the only honest way to import 3000 rows
    into a live catalogue.
    """
    summary = {"rows": len(rows), "classes": 0, "generics": 0,
               "brands": 0, "updated": 0, "skipped": 0}
    classes = {(c.name_ar or "").strip().lower(): c for c in DrugClass.query.all()}
    generics = {}
    for gen in GenericDrug.query.all():
        for key in (gen.name_en, gen.name_ar):
            if key:
                generics[key.strip().lower()] = gen
    brands = {}
    for d in Drug.query.all():
        brands[(d.trade_name.strip().lower(), (d.strength or "").strip().lower())] = d

    for row in rows:
        # --- class -----------------------------------------------------
        cls = None
        cls_name = row.get("class")
        if cls_name:
            cls = classes.get(cls_name.lower())
            if cls is None:
                cls = DrugClass(name_ar=cls_name, is_active=True)
                if not dry_run:
                    db.session.add(cls)
                    db.session.flush()
                classes[cls_name.lower()] = cls
                summary["classes"] += 1

        # --- ingredient ------------------------------------------------
        gen = None
        gen_en, gen_ar = row.get("generic_en"), row.get("generic_ar")
        for key in (gen_en, gen_ar):
            if key and key.lower() in generics:
                gen = generics[key.lower()]
                break
        if gen is None and (gen_en or gen_ar):
            gen = GenericDrug(name_ar=gen_ar or gen_en, name_en=gen_en or None,
                              class_id=(cls.id if cls is not None and not dry_run
                                        else None),
                              is_active=True)
            if not dry_run:
                db.session.add(gen)
                db.session.flush()
            for key in (gen_en, gen_ar):
                if key:
                    generics[key.lower()] = gen
            summary["generics"] += 1
        elif gen is not None and cls is not None and gen.class_id is None and not dry_run:
            gen.class_id = cls.id

        # --- product ---------------------------------------------------
        key = (row["trade_name"].strip().lower(),
               (row.get("strength") or "").strip().lower())
        drug = brands.get(key)
        conc = _number(row.get("conc"))
        price = _number(row.get("price"))
        if drug is None:
            drug = Drug(trade_name=row["trade_name"],
                        generic_name=(gen.name_en or gen.name_ar) if gen else None,
                        generic_id=(gen.id if gen is not None and not dry_run else None),
                        form=row.get("form") or None,
                        strength=row.get("strength") or None,
                        conc_mg_per_ml=conc, price=price,
                        manufacturer=row.get("manufacturer") or None,
                        barcode=row.get("barcode") or None,
                        pack_size=row.get("pack_size") or None,
                        is_active=True)
            if not dry_run:
                db.session.add(drug)
                db.session.flush()
            brands[key] = drug
            summary["brands"] += 1
            continue
        # Existing product: refresh the commercial fields only — never
        # overwrite a clinic's own dosing edits with a supplier file.
        changed = False
        for field, value in (("price", price), ("barcode", row.get("barcode")),
                             ("manufacturer", row.get("manufacturer")),
                             ("pack_size", row.get("pack_size")),
                             ("conc_mg_per_ml", conc)):
            if value in (None, "") or getattr(drug, field) == value:
                continue
            if not dry_run:
                setattr(drug, field, value)
            changed = True
        if gen is not None and drug.generic_id is None:
            if not dry_run:
                drug.generic_id = gen.id
            changed = True
        summary["updated" if changed else "skipped"] += 1

    if dry_run:
        db.session.rollback()
    return summary
