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
import json
from datetime import datetime

from app.extensions import db
from app.models import Drug, DrugClass, GenericDrug
from app.utils.drugbook_parse import (clean_manufacturer, parse_conc,
                                      parse_form, parse_pack, parse_route,
                                      parse_strength, split_ingredients)

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
    # The Egyptian register's own column names (the open EDA dataset), so the
    # file downloads and imports without anyone editing a header first.
    "commercial_name_en": "trade_name", "commercial_name_ar": "trade_name_ar",
    "trade_name_ar": "trade_name_ar", "الاسم التجاري بالعربي": "trade_name_ar",
    "scientific_name": "generic_en", "scientific name": "generic_en",
    "drug_class": "class", "drug class": "class",
    "route": "route", "طريقة الاستخدام": "route",
    "price_egp": "price", "price egp": "price", "السعر بالجنيه": "price",
}

# The fields a mapping screen offers, in the order they are asked for.
# (key, required, example)
FIELDS = [
    ("trade_name", True, "AUGMENTIN 1 GM 14 F.C. TABS."),
    ("trade_name_ar", False, "أوجمنتين"),
    ("generic_en", False, "AMOXICILLIN+CLAVULANIC ACID"),
    ("generic_ar", False, "أموكسيسيللين"),
    ("class", False, "المضادات الحيوية"),
    ("form", False, "tablet"),
    ("strength", False, "1 GM"),
    ("conc", False, "25"),
    ("route", False, "ORAL.SOLID"),
    ("manufacturer", False, "GSK"),
    ("price", False, "210"),
    ("pack_size", False, "14 tabs"),
    ("barcode", False, ""),
]
REQUIRED_FIELDS = [key for key, required, _ in FIELDS if required]


def guess_mapping(headers):
    """Which column looks like which field → ``{field: column index}``.

    A file whose headers we already know is mapped without anyone being asked;
    the screen exists for the files we don't know, and even those arrive with
    most of the work done.
    """
    out = {}
    for idx, raw in enumerate(headers or []):
        field = COLUMNS.get(str(raw or "").strip().lower())
        if field and field not in out:
            out[field] = idx
    return out


def rows_from_matrix(headers, data_rows, mapping):
    """Turn a raw sheet plus the user's column choices into row dicts."""
    rows, errors = [], []
    for i, raw in enumerate(data_rows or [], start=2):
        row = {}
        for field, idx in (mapping or {}).items():
            if 0 <= idx < len(raw):
                value = raw[idx]
                row[field] = _clean("" if value is None else str(value))
        if not row.get("trade_name"):
            errors.append(f"line {i}: no trade name")
            continue
        rows.append(row)
    return rows, errors


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


# The column the name is stored in. Keys are built from the *stored* form, so
# a name the database truncates still matches itself on the next import —
# otherwise re-running the same file quietly grows a second copy of every long
# ingredient name.
GENERIC_NAME_MAX = 140


def _gen_name(name):
    """The exact text an ingredient name is stored as.

    Trimmed *after* truncation as well as before: a cut that lands on a space
    would otherwise store a name whose own key doesn't match it, and the next
    import of the same file would create a second copy of it.
    """
    return " ".join((name or "").split())[:GENERIC_NAME_MAX].strip()


def _gen_key(name):
    return _gen_name(name).lower()


def _brand_key(trade_name, strength):
    """How a product is recognised as one we already have.

    Built through the same normaliser the name is *stored* with, on both
    sides — otherwise a name with a double space is written one way and looked
    up another, and every re-import adds the whole file again."""
    return (_gen_name(trade_name)[:160].lower(),
            " ".join((strength or "").split()).lower())


def _clean(value):
    return (value or "").strip()


def _number(value):
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def parse(stream_bytes):
    """Read the uploaded file into normalised row dicts.

    Accepts CSV and JSON — the published drug datasets ship both, and asking a
    clinic to convert one into the other before it can use its own data is a
    step that exists only for our convenience.

    Returns ``(rows, errors)``. A row missing a trade name is reported rather
    than guessed at — an unnamed product is not importable.
    """
    text = stream_bytes.decode("utf-8-sig", errors="replace") \
        if isinstance(stream_bytes, bytes) else stream_bytes
    if text.lstrip()[:1] in ("[", "{"):
        return _parse_json(text)
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


def _parse_json(text):
    """A JSON array of objects (or ``{"drugs": [...]}``) → the same row dicts."""
    try:
        data = json.loads(text)
    except ValueError as exc:
        return [], [f"invalid JSON: {exc}"]
    if isinstance(data, dict):
        data = next((v for v in data.values() if isinstance(v, list)), [])
    rows, errors = [], []
    for i, raw in enumerate(data, start=1):
        if not isinstance(raw, dict):
            continue
        row = {}
        for key, value in raw.items():
            field = COLUMNS.get(str(key).strip().lower())
            if field:
                row[field] = _clean(str(value) if value is not None else "")
        if not row.get("trade_name"):
            errors.append(f"item {i}: no trade name")
            continue
        rows.append(row)
    if not rows and not errors:
        errors.append("no trade-name field")
    return rows, errors


def enrich(row):
    """Fill in what the register buries inside its own strings.

    A commercial list writes ``AUGMENTIN 1 GM 14 F.C. TABS.`` and expects you
    to read the strength, the pack and the form out of it. Columns the file
    supplies explicitly always win — this only fills blanks.
    """
    name = row.get("trade_name") or ""
    scientific = row.get("generic_en") or ""
    if not row.get("strength"):
        row["strength"] = parse_strength(name, scientific)
    if not row.get("form"):
        row["form"] = parse_form(name)
    if not row.get("pack_size"):
        row["pack_size"] = parse_pack(name)
    if not row.get("conc"):
        row["conc"] = parse_conc(row.get("strength"))
    if row.get("route"):
        row["route"] = parse_route(row["route"])
    if row.get("manufacturer"):
        row["manufacturer"] = clean_manufacturer(row["manufacturer"])
    row["ingredients"] = split_ingredients(scientific) or (
        [row["generic_ar"]] if row.get("generic_ar") else [])
    return row


def import_rows(rows, dry_run=False, create_classes=False, batch=500):
    """Create/update classes, ingredients and products from parsed rows.

    Returns a summary dict. With ``dry_run`` nothing is written — the caller
    shows the numbers first, which is the only honest way to import 25,000 rows
    into a live catalogue.

    ``create_classes`` is off by default, and that is deliberate. The market
    register carries thousands of commercial groupings ("COLD PRODUCTS",
    "VITAMIN C   ANTIOXIDANT"); turning each into a class would bury the
    clinic's own twelve-branch tree under a list nobody can browse. Ingredients
    and products come in; the tree stays the clinic's.
    """
    summary = {"rows": len(rows), "classes": 0, "generics": 0, "brands": 0,
               "updated": 0, "skipped": 0, "links": 0}
    classes = {(c.name_ar or "").strip().lower(): c for c in DrugClass.query.all()}
    generics = {}
    for gen in GenericDrug.query.all():
        for key in (gen.name_en, gen.name_ar):
            if key:
                generics.setdefault(_gen_key(key), gen)
    brands = {}
    for d in Drug.query.all():
        brands[_brand_key(d.trade_name, d.strength)] = d

    pending = 0
    for row in rows:
        row = enrich(row)
        cls = _class_for(row, classes, summary, create_classes, dry_run)
        found = _ingredients_for(row, generics, cls, summary, dry_run)
        gen = found[0] if found else None

        key = _brand_key(row["trade_name"], row.get("strength"))
        drug = brands.get(key)
        conc = _number(row.get("conc"))
        price = _number(row.get("price"))
        if drug is None:
            drug = Drug(price_updated_at=datetime.utcnow() if price else None,
                        trade_name=_gen_name(row["trade_name"])[:160],
                        trade_name_ar=(row.get("trade_name_ar") or None),
                        generic_name=(gen.name_en or gen.name_ar) if gen else None,
                        generic_id=(gen.id if gen is not None and not dry_run else None),
                        form=row.get("form") or None,
                        route=row.get("route") or None,
                        strength=row.get("strength") or None,
                        conc_mg_per_ml=conc, price=price,
                        manufacturer=row.get("manufacturer") or None,
                        barcode=row.get("barcode") or None,
                        pack_size=row.get("pack_size") or None,
                        is_active=True)
            if not dry_run:
                db.session.add(drug)
                pending += 1
                if pending >= batch:
                    db.session.flush()
                    pending = 0
            brands[key] = drug
            summary["brands"] += 1
            summary["links"] += _link_ingredients(drug, found, dry_run)
            continue

        # Existing product: refresh the commercial fields only — never
        # overwrite a clinic's own dosing edits with a supplier file.
        changed = False
        for field, value in (("price", price), ("barcode", row.get("barcode")),
                             ("manufacturer", row.get("manufacturer")),
                             ("pack_size", row.get("pack_size")),
                             ("trade_name_ar", row.get("trade_name_ar")),
                             ("route", row.get("route")),
                             ("form", row.get("form")),
                             ("conc_mg_per_ml", conc)):
            if value in (None, "") or getattr(drug, field) == value:
                continue
            if not dry_run:
                setattr(drug, field, value)
                if field == "price":
                    drug.price_updated_at = datetime.utcnow()
            changed = True
        if gen is not None and drug.generic_id is None:
            if not dry_run:
                drug.generic_id = gen.id
            changed = True
        added = _link_ingredients(drug, found, dry_run)
        summary["links"] += added
        summary["updated" if (changed or added) else "skipped"] += 1

    if dry_run:
        db.session.rollback()
    elif pending:
        db.session.flush()
    return summary


def _class_for(row, classes, summary, create_classes, dry_run):
    """The row's drug class — looked up always, created only if asked."""
    name = (row.get("class") or "").strip()
    if not name:
        return None
    cls = classes.get(name.lower())
    if cls is not None or not create_classes:
        return cls
    cls = DrugClass(name_ar=name[:120], is_active=True)
    if not dry_run:
        db.session.add(cls)
        db.session.flush()
    classes[name.lower()] = cls
    summary["classes"] += 1
    return cls


def _ingredients_for(row, generics, cls, summary, dry_run):
    """Every ingredient this row names, creating the ones we've not seen.

    The first is the one the product's dosing is read from; the rest exist so
    the allergy and interaction checks can see the whole product.
    """
    names = row.get("ingredients") or []
    if not names and row.get("generic_en"):
        names = [row["generic_en"]]
    out = []
    for name in names:
        gen = generics.get(_gen_key(name))
        if gen is None:
            gen = GenericDrug(
                name_ar=_gen_name(row.get("generic_ar") or name),
                name_en=_gen_name(name),
                class_id=(cls.id if cls is not None and not dry_run else None),
                is_active=True)
            if not dry_run:
                db.session.add(gen)
                db.session.flush()
            generics[_gen_key(name)] = gen
            summary["generics"] += 1
        elif cls is not None and gen.class_id is None and not dry_run:
            gen.class_id = cls.id
        out.append(gen)
    return out


def _link_ingredients(drug, found, dry_run):
    """Attach every ingredient to the product. Returns how many were new."""
    if dry_run or not found:
        return 0
    existing = {g.id for g in (drug.ingredients or []) if g.id}
    added = 0
    for gen in found:
        if gen.id is None or gen.id in existing:
            continue
        drug.ingredients.append(gen)
        existing.add(gen.id)
        added += 1
    return added
