"""Drugs & prescriptions (clinic): catalogue, writing, safety alerts, print."""
import os
from datetime import datetime, timedelta

from flask import (
    current_app, flash, g, jsonify, redirect, render_template, request, url_for,
)
from flask_login import current_user
from sqlalchemy import or_

from app.blueprints.prescriptions import prescriptions_bp
from app.extensions import db
from app.i18n import t
from app.models import (
    DRUG_FORMS,
    ActivityLog,
    Drug,
    DrugClass,
    DrugInteraction,
    GenericDrug,
    Investigation,
    Patient,
    Prescription,
    PrescriptionInvestigation,
    PrescriptionItem,
    RxPrintTemplate,
    User,
)
from app.utils.decorators import admin_required, client_ip, module_required
from app.utils.paging import paginate
from app.utils.rx_shorthand import FREQUENCIES, expand_line

MODULE = "prescriptions"


def interaction_warnings(drug_ids):
    """Interaction rows among the given drug ids — matched by GENERIC so every
    brand of an interacting generic is caught (not just the seeded pair)."""
    ids = [int(i) for i in drug_ids if i]
    if len(ids) < 2:
        return []
    drugs = Drug.query.filter(Drug.id.in_(ids)).all()
    generics = {(d.generic_name or "").strip() for d in drugs if d.generic_name}
    if len(generics) < 2:
        return []
    out, seen = [], set()
    for r in DrugInteraction.query.all():
        ga = (r.drug_a.generic_name or "").strip() if r.drug_a else ""
        gb = (r.drug_b.generic_name or "").strip() if r.drug_b else ""
        if ga and gb and ga != gb and ga in generics and gb in generics:
            key = tuple(sorted((ga, gb)))
            if key not in seen:
                seen.add(key)
                out.append(r)
    return out


@prescriptions_bp.route("/interactions/check")
@module_required(MODULE)
def interactions_check():
    """JSON: live safety for what is on the prescription right now — the
    paediatric dose for *this* child per line, plus interactions between the
    ingredients (with severity and the alternative to use instead)."""
    from app.utils.rx_safety import as_json
    from app.utils.rx_safety import check as rx_check

    raw = (request.args.get("ids") or "").split(",")
    ids = [int(x) for x in raw if x.strip().isdigit()]
    names = [n for n in (request.args.get("names") or "").split("|") if n.strip()]
    lang = getattr(g, "lang", "ar")
    patient = (db.session.get(Patient, request.args.get("patient_id", type=int))
               if request.args.get("patient_id", type=int) else None)
    drugs = {d.id: d for d in Drug.query.filter(Drug.id.in_(ids)).all()} if ids else {}
    items = [{"name": drugs[i].label(lang), "drug": drugs[i]}
             for i in ids if i in drugs]
    items += [{"name": n.strip()} for n in names]
    result = rx_check(items, patient=patient,
                      weight_kg=request.args.get("weight", type=float),
                      age_months=request.args.get("age_months", type=int), lang=lang)
    data = as_json(result, lang)
    # Kept for the existing caller: the old shape listed interactions only.
    data["warnings"] = data["interactions"]
    return jsonify(data)


@prescriptions_bp.route("/")
@module_required(MODULE)
def index():
    pagination = paginate(Prescription.query.order_by(Prescription.id.desc()))
    return render_template("prescriptions/index.html", pagination=pagination,
                           prescriptions=pagination.items)


# ================================================ drug reference (المرجع) ===
@prescriptions_bp.route("/drugbook")
@module_required(MODULE)
def drugbook():
    """The drug reference, browsed the way it is organised: class → active
    ingredient → the trade names that carry it. Searching cuts across all
    three, because a doctor types whichever name comes to mind first."""
    q = (request.args.get("q") or "").strip()
    class_id = request.args.get("class_id", type=int)
    classes = (DrugClass.query.filter_by(is_active=True)
               .order_by(DrugClass.sort_order, DrugClass.name_ar).all())
    query = GenericDrug.query.filter_by(is_active=True)
    if class_id:
        query = query.filter(GenericDrug.class_id == class_id)
    if q:
        like = f"%{q}%"
        query = query.outerjoin(Drug, Drug.generic_id == GenericDrug.id).filter(or_(
            GenericDrug.name_ar.ilike(like), GenericDrug.name_en.ilike(like),
            GenericDrug.atc_code.ilike(like), Drug.trade_name.ilike(like)))
    # Paged rather than cut off at 300: the reference holds tens of thousands
    # of ingredients, and a doctor who searches and finds nothing has no way
    # to tell "not on file" from "past the limit".
    pagination = paginate(query.order_by(GenericDrug.name_en).distinct())
    counts = {}
    for c in classes:
        counts[c.id] = GenericDrug.query.filter_by(class_id=c.id,
                                                   is_active=True).count()
    return render_template("prescriptions/drugbook.html", classes=classes,
                           generics=pagination.items, pagination=pagination,
                           counts=counts, q=q, class_id=class_id)


@prescriptions_bp.route("/drugbook/<int:generic_id>")
@module_required(MODULE)
def drugbook_generic(generic_id):
    """One active ingredient: dosing by weight and by age, the safety limits,
    the brands that carry it — and a calculator wired to a real patient when
    one is passed in (?patient_id=), so the weight and age are the child's."""
    from app.utils.dosing import age_months_of, calculate, latest_weight

    generic = db.get_or_404(GenericDrug, generic_id)
    patient = (db.session.get(Patient, request.args.get("patient_id", type=int))
               if request.args.get("patient_id", type=int) else None)
    weight = request.args.get("weight", type=float)
    age_months = request.args.get("age_months", type=int)
    if patient is not None:
        if weight is None:
            weight = latest_weight(patient)
        if age_months is None:
            age_months = age_months_of(patient)
    product = (db.session.get(Drug, request.args.get("product_id", type=int))
               if request.args.get("product_id", type=int) else None)
    result = (calculate(generic, weight_kg=weight, age_months=age_months,
                        product=product)
              if (weight is not None or age_months is not None) else None)
    interactions = (DrugInteraction.query
                    .join(Drug, or_(DrugInteraction.drug_a_id == Drug.id,
                                    DrugInteraction.drug_b_id == Drug.id))
                    .filter(Drug.generic_id == generic.id).distinct().all())
    return render_template("prescriptions/drugbook_generic.html", generic=generic,
                           patient=patient, weight=weight, age_months=age_months,
                           product=product, result=result,
                           interactions=interactions)


@prescriptions_bp.route("/drugbook/import", methods=["GET", "POST"])
@admin_required
def drugbook_import():
    """Bring in a real drug list (EDA export, supplier or pharmacy file).

    The seeded catalogue is a working set; the market is thousands of items.
    A file is read one product per row — trade name + strength — naming its
    ingredient and class, and anything missing is created as it reads, so one
    file can build the whole tree. Preview first, then import: numbers before
    a live catalogue changes.

    A published national register runs to tens of thousands of rows, which is a
    long wait in a browser tab and a request that may time out halfway; for
    those there is ``flask import-drugs <file>``, which does the same work and
    says what it did."""
    from app.utils.drugbook_import import import_rows, parse

    summary = errors = None
    preview = request.form.get("mode") != "import"
    if request.method == "POST":
        file = request.files.get("file")
        if not file or not file.filename:
            flash(t("drugbook.import_need_file"), "danger")
            return redirect(url_for("prescriptions.drugbook_import"))
        raw = file.read()
        rows, errors = parse(raw)
        if not rows and _mappable(file.filename):
            # We don't recognise this file's headers. That is not a reason to
            # refuse it — a pharmacy's own price list is still the clinic's
            # data. Ask which column is which.
            mapped = _offer_mapping(file, raw)
            if mapped is not None:
                return mapped
        if not rows:
            flash(t("drugbook.import_no_rows"), "warning")
        else:
            summary = import_rows(
                rows, dry_run=preview,
                create_classes=bool(request.form.get("create_classes")))
            if preview:
                flash(t("drugbook.import_preview_done"), "info")
            else:
                db.session.commit()
                ActivityLog.record("drugbook.import", user_id=current_user.id,
                                   entity="drug", detail=str(summary["rows"]),
                                   ip_address=client_ip())
                db.session.commit()
                flash(t("drugbook.import_done")
                      .replace("{n}", str(summary["brands"])), "success")
    counts = {
        "classes": DrugClass.query.count(),
        "generics": GenericDrug.query.count(),
        "brands": Drug.query.count(),
    }
    return render_template("prescriptions/drugbook_import.html", summary=summary,
                           errors=errors, preview=preview, counts=counts)


@prescriptions_bp.route("/drugbook/import/template")
@admin_required
def drugbook_template():
    """The blank CSV to fill in (UTF-8 with a BOM so Excel opens it right)."""
    from flask import Response

    from app.utils.drugbook_import import template_csv

    return Response(
        template_csv(), mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=drugbook-template.csv"})


@prescriptions_bp.route("/drugbook/product/<int:drug_id>", methods=["GET", "POST"])
@module_required(MODULE)
def drugbook_product(drug_id):
    """One product: its package photo, its leaflet, its price — and the
    cheaper alternatives carrying the same active ingredient.

    The photo is what a parent recognises on the pharmacy shelf, the leaflet
    is what the doctor checks before prescribing, and the price is the
    question every family asks. Editing needs settings access; reading
    doesn't — the doctor must be able to look, and to answer "is there a
    cheaper one?" without leaving the screen."""
    from datetime import datetime

    from app.utils.uploads import remove_drug_media, save_drug_media

    drug = db.get_or_404(Drug, drug_id)
    if request.method == "POST":
        if not current_user.can_access("settings"):
            from flask import abort
            abort(403)
        action = (request.form.get("action") or "").strip()
        if action == "price":
            price = request.form.get("price", type=float)
            drug.price = price if price and price > 0 else None
            drug.price_updated_at = datetime.utcnow() if drug.price else None
            drug.pack_size = (request.form.get("pack_size") or "").strip() or None
            drug.barcode = (request.form.get("barcode") or "").strip() or None
            drug.manufacturer = (request.form.get("manufacturer") or "").strip() or None
            flash(t("drugbook.price_saved"), "success")
        elif action in ("image", "leaflet"):
            stored = save_drug_media(request.files.get("file"))
            if stored is None:
                flash(t("drugbook.bad_file"), "danger")
            else:
                remove_drug_media(getattr(drug, action))
                setattr(drug, action, stored)
                flash(t("drugbook.file_saved"), "success")
        elif action in ("image_delete", "leaflet_delete"):
            field = action.split("_")[0]
            remove_drug_media(getattr(drug, field))
            setattr(drug, field, None)
            flash(t("drugbook.file_removed"), "info")
        db.session.commit()
        return redirect(url_for("prescriptions.drugbook_product", drug_id=drug.id))

    return render_template("prescriptions/drugbook_product.html", drug=drug,
                           alternatives=drug.alternatives())


def _mappable(filename):
    """Only a sheet can be mapped; a JSON payload names its own fields."""
    return (filename or "").lower().rsplit(".", 1)[-1] in ("csv", "xlsx")


# An upload that was never mapped is abandoned work, and a folder that only
# ever grows is a slow leak on a clinic PC.
STASH_HOURS = 6


def _drug_import_tmp():
    folder = os.path.join(current_app.instance_path, "drug_imports")
    os.makedirs(folder, exist_ok=True)
    _sweep_stashes(folder)
    return folder


def _sweep_stashes(folder, hours=STASH_HOURS):
    import time

    cutoff = time.time() - hours * 3600
    for name in os.listdir(folder):
        path = os.path.join(folder, name)
        try:
            if os.path.isfile(path) and os.path.getmtime(path) < cutoff:
                os.remove(path)
        except OSError:
            pass


def _offer_mapping(file, raw):
    """Show the column-mapping screen for a file we couldn't read blind."""
    import io as _io
    import json as _json
    import uuid as _uuid

    from werkzeug.datastructures import FileStorage

    from app.utils.drugbook_import import FIELDS, guess_mapping
    from app.utils.imports import read_matrix

    headers, data_rows, error = read_matrix(
        FileStorage(stream=_io.BytesIO(raw), filename=file.filename))
    if error or not headers or not data_rows:
        return None

    token = _uuid.uuid4().hex
    with open(os.path.join(_drug_import_tmp(), f"{token}.json"), "w",
              encoding="utf-8") as fh:
        _json.dump({"headers": headers, "rows": data_rows,
                    "filename": file.filename}, fh, ensure_ascii=False,
                   default=str)
    return render_template(
        "prescriptions/drugbook_map.html", token=token, headers=headers,
        filename=file.filename, fields=FIELDS, guess=guess_mapping(headers),
        sample=data_rows[:5], total=len(data_rows))


@prescriptions_bp.route("/drugbook/import/map", methods=["POST"])
@admin_required
def drugbook_import_map():
    """Read the file again through the columns the user just named."""
    import json as _json

    from app.utils.drugbook_import import (FIELDS, REQUIRED_FIELDS,
                                           import_rows, rows_from_matrix)

    token = (request.form.get("token") or "").strip()
    if not token.isalnum():
        flash(t("drugbook.import_expired"), "warning")
        return redirect(url_for("prescriptions.drugbook_import"))
    stash = os.path.join(_drug_import_tmp(), f"{token}.json")
    if not os.path.isfile(stash):
        flash(t("drugbook.import_expired"), "warning")
        return redirect(url_for("prescriptions.drugbook_import"))
    with open(stash, encoding="utf-8") as fh:
        payload = _json.load(fh)

    headers = payload["headers"]
    mapping = {}
    for key, _required, _sample in FIELDS:
        rawval = (request.form.get(f"map_{key}") or "").strip()
        if not rawval:
            continue
        try:
            idx = int(rawval)
        except ValueError:
            continue
        if 0 <= idx < len(headers):
            mapping[key] = idx

    missing = [k for k in REQUIRED_FIELDS if k not in mapping]
    if missing:
        flash(t("drugbook.import_map_required"), "danger")
        return render_template(
            "prescriptions/drugbook_map.html", token=token, headers=headers,
            filename=payload.get("filename", ""), fields=FIELDS,
            guess=mapping, sample=payload["rows"][:5],
            total=len(payload["rows"]), missing=missing)

    rows, errors = rows_from_matrix(headers, payload["rows"], mapping)
    preview = request.form.get("mode") != "import"
    summary = None
    if rows:
        summary = import_rows(
            rows, dry_run=preview,
            create_classes=bool(request.form.get("create_classes")))
        if preview:
            flash(t("drugbook.import_preview_done"), "info")
        else:
            db.session.commit()
            os.remove(stash)
            ActivityLog.record("drugbook.import", user_id=current_user.id,
                               entity="drug", detail=str(summary["rows"]),
                               ip_address=client_ip())
            db.session.commit()
            flash(t("drugbook.import_done")
                  .replace("{n}", str(summary["brands"])), "success")
    counts = {"classes": DrugClass.query.count(),
              "generics": GenericDrug.query.count(),
              "brands": Drug.query.count()}
    return render_template("prescriptions/drugbook_import.html",
                           summary=summary, errors=errors, preview=preview,
                           counts=counts, mapped_token=(token if preview else None),
                           mapping=mapping)


# ------------------------------------------------- saved prescriptions -----
def visible_presets(user=None):
    """The saved sets this doctor may use: theirs, shared, and the clinic's."""
    from app.models import RxPreset

    user = user or current_user
    rows = (RxPreset.query.filter(RxPreset.is_active.is_(True))
            .order_by(RxPreset.use_count.desc(), RxPreset.name).all())
    return [p for p in rows if p.visible_to(user)]


@prescriptions_bp.route("/presets")
@module_required(MODULE)
def presets():
    """Manage the sets — rename, edit the lines, share or delete."""
    return render_template("prescriptions/presets.html",
                           presets=visible_presets())


@prescriptions_bp.route("/presets/save", methods=["POST"])
@module_required(MODULE)
def preset_save():
    """Save the lines currently on the writer as a reusable set."""
    from app.models import RxPreset, RxPresetItem

    name = (request.form.get("name") or "").strip()
    if not name:
        flash(t("common.required") + ": " + t("presets.name"), "danger")
        return redirect(request.referrer or url_for("prescriptions.presets"))

    preset = RxPreset(name=name,
                      note=(request.form.get("note") or "").strip() or None,
                      diagnosis=(request.form.get("diagnosis") or "").strip() or None,
                      doctor_id=current_user.id,
                      is_shared=bool(request.form.get("is_shared")),
                      is_active=True)
    db.session.add(preset)
    db.session.flush()

    names = request.form.getlist("item_name")
    drug_ids = request.form.getlist("item_drug_id")
    doses = request.form.getlist("item_dose")
    freqs = request.form.getlist("item_frequency")
    durs = request.form.getlist("item_duration")
    instrs = request.form.getlist("item_instructions")
    for i, raw in enumerate(names):
        drug_name = (raw or "").strip()
        if not drug_name:
            continue
        try:
            did = int(drug_ids[i]) if i < len(drug_ids) and drug_ids[i] else None
        except (ValueError, TypeError):
            did = None
        written = expand_line({
            "dose": (doses[i].strip() if i < len(doses) else ""),
            "frequency": (freqs[i].strip() if i < len(freqs) else ""),
            "duration": (durs[i].strip() if i < len(durs) else ""),
        })
        preset.items.append(RxPresetItem(
            drug_id=did, drug_name=drug_name,
            dose=written["dose"] or None,
            frequency=written["frequency"] or None,
            duration=written["duration"] or None,
            instructions=(instrs[i].strip() if i < len(instrs) else "") or None))
    if not preset.items:
        db.session.rollback()
        flash(t("presets.need_items"), "warning")
        return redirect(request.referrer or url_for("prescriptions.presets"))
    db.session.commit()
    flash(t("presets.saved", name=preset.name), "success")
    return redirect(request.referrer or url_for("prescriptions.presets"))


@prescriptions_bp.route("/presets/<int:preset_id>/lines")
@module_required(MODULE)
def preset_lines(preset_id):
    """The set's medicines, shaped like the writer's own lines."""
    from app.models import RxPreset

    preset = db.get_or_404(RxPreset, preset_id)
    if not preset.visible_to(current_user):
        return jsonify({"ok": False}), 403
    # Applying it is the only use worth counting: opening the list isn't use.
    preset.use_count = (preset.use_count or 0) + 1
    db.session.commit()
    return jsonify({
        "ok": True, "name": preset.name, "diagnosis": preset.diagnosis or "",
        "lines": [{
            "drug_id": it.drug_id or "", "name": it.drug_name,
            "dose": it.dose or "", "frequency": it.frequency or "",
            "duration": it.duration or "",
            "instructions": it.instructions or "",
        } for it in preset.items],
    })


@prescriptions_bp.route("/presets/<int:preset_id>/edit", methods=["POST"])
@module_required(MODULE)
def preset_edit(preset_id):
    from app.models import RxPreset

    preset = db.get_or_404(RxPreset, preset_id)
    if not _may_edit_preset(preset):
        flash(t("presets.not_yours"), "warning")
        return redirect(url_for("prescriptions.presets"))
    preset.name = (request.form.get("name") or preset.name).strip()
    preset.note = (request.form.get("note") or "").strip() or None
    preset.diagnosis = (request.form.get("diagnosis") or "").strip() or None
    preset.is_shared = bool(request.form.get("is_shared"))
    preset.is_active = bool(request.form.get("is_active"))
    db.session.commit()
    flash(t("presets.updated"), "success")
    return redirect(url_for("prescriptions.presets"))


@prescriptions_bp.route("/presets/<int:preset_id>/delete", methods=["POST"])
@module_required(MODULE)
def preset_delete(preset_id):
    from app.models import RxPreset

    preset = db.get_or_404(RxPreset, preset_id)
    if not _may_edit_preset(preset):
        flash(t("presets.not_yours"), "warning")
        return redirect(url_for("prescriptions.presets"))
    db.session.delete(preset)
    db.session.commit()
    flash(t("presets.deleted"), "info")
    return redirect(url_for("prescriptions.presets"))


def _may_edit_preset(preset):
    """Its owner, or an admin. A shared set is still its author's to change —
    two doctors rarely treat a cold identically, and one quietly overwriting
    the other's habits is worse than a little duplication."""
    return (preset.doctor_id in (None, current_user.id)
            or current_user.role == "admin" or current_user.is_super_admin)


# ----------------------------------------------------- drug catalogue ------
@prescriptions_bp.route("/drugs")
@admin_required
def drugs():
    q = (request.args.get("q") or "").strip()
    query = Drug.query
    if q:
        like = f"%{q}%"
        query = query.filter(or_(Drug.trade_name.ilike(like),
                                 Drug.trade_name_ar.ilike(like),
                                 Drug.generic_name.ilike(like)))
    # The register's own classification, which the bundled catalogue had been
    # dropping. 25,000 trade names with no way to narrow them by kind is a
    # list nobody browses — they search, and only find what they already knew
    # the name of.
    drug_class = (request.args.get("drug_class") or "").strip()
    if drug_class:
        query = query.filter(Drug.drug_class == drug_class)
    # Only classes that group more than one drug. A "class" holding a single
    # trade name is not a category — it is that drug described — and a
    # thousand of them would bury the four hundred real ones.
    #
    # Carried with their counts, because a category name on its own does not
    # say whether there is anything behind it. "ANTIBIOTICS (412)" is a thing
    # to open; "ANTIBIOTICS" is a guess.
    from sqlalchemy import func
    classes = [{"name": name, "count": n} for name, n in
               db.session.query(Drug.drug_class, func.count(Drug.id))
               .filter(Drug.drug_class.isnot(None), Drug.drug_class != "")
               .group_by(Drug.drug_class)
               .having(func.count(Drug.id) > 1)
               .order_by(Drug.drug_class).all()]
    # …but a class arrived at by URL still filters, even if it is not offered.
    if drug_class and not any(c["name"] == drug_class for c in classes):
        here = (Drug.query.filter(Drug.drug_class == drug_class).count())
        classes = sorted(classes + [{"name": drug_class, "count": here}],
                         key=lambda c: c["name"])
    pagination = paginate(query.order_by(Drug.trade_name))
    return render_template("prescriptions/drugs.html", drugs=pagination.items,
                           pagination=pagination, forms=DRUG_FORMS, q=q,
                           drug_classes=classes, drug_class=drug_class)


@prescriptions_bp.route("/drugs/new", methods=["POST"])
@admin_required
def drug_new():
    trade = (request.form.get("trade_name") or "").strip()
    if not trade:
        flash(t("common.required") + ": " + t("rx.trade_name"), "danger")
        return redirect(url_for("prescriptions.drugs"))
    db.session.add(Drug(
        trade_name=trade,
        generic_name=(request.form.get("generic_name") or "").strip() or None,
        form=(request.form.get("form") or "").strip() or None,
        strength=(request.form.get("strength") or "").strip() or None,
        default_dose=(request.form.get("default_dose") or "").strip() or None,
        default_frequency=(request.form.get("default_frequency") or "").strip() or None,
        default_instructions=(request.form.get("default_instructions") or "").strip() or None,
        max_daily_dose=(request.form.get("max_daily_dose") or "").strip() or None,
        dose_per_kg=request.form.get("dose_per_kg", type=float),
        max_per_kg=request.form.get("max_per_kg", type=float),
        conc_mg_per_ml=request.form.get("conc_mg_per_ml", type=float),
    ))
    db.session.commit()
    flash(t("rx.drug_added"), "success")
    return redirect(url_for("prescriptions.drugs"))


@prescriptions_bp.route("/drugs/<int:drug_id>/edit", methods=["POST"])
@admin_required
def drug_edit(drug_id):
    d = db.get_or_404(Drug, drug_id)
    d.trade_name = (request.form.get("trade_name") or d.trade_name).strip()
    d.generic_name = (request.form.get("generic_name") or "").strip() or None
    d.form = (request.form.get("form") or "").strip() or None
    d.strength = (request.form.get("strength") or "").strip() or None
    d.default_dose = (request.form.get("default_dose") or "").strip() or None
    d.default_frequency = (request.form.get("default_frequency") or "").strip() or None
    d.default_instructions = (request.form.get("default_instructions") or "").strip() or None
    d.max_daily_dose = (request.form.get("max_daily_dose") or "").strip() or None
    d.dose_per_kg = request.form.get("dose_per_kg", type=float)
    d.max_per_kg = request.form.get("max_per_kg", type=float)
    d.conc_mg_per_ml = request.form.get("conc_mg_per_ml", type=float)
    d.is_active = bool(request.form.get("is_active"))
    db.session.commit()
    flash(t("rx.drug_updated"), "success")
    return redirect(url_for("prescriptions.drugs"))


@prescriptions_bp.route("/drugs/<int:drug_id>/delete", methods=["POST"])
@admin_required
def drug_delete(drug_id):
    d = db.get_or_404(Drug, drug_id)
    db.session.delete(d)
    db.session.commit()
    flash(t("rx.drug_deleted"), "info")
    return redirect(url_for("prescriptions.drugs"))


@prescriptions_bp.route("/drugs/search")
@module_required(MODULE)
def drug_search():
    """Autocomplete for the prescription writer (trade + generic).

    Shares :func:`app.utils.drug_search.search_drugs` with the visit room.
    They used to be two hand-written queries with two different payloads, and
    this one was missing ``strength`` — which the template printed anyway, so
    every row read "() paracetamol".
    """
    from app.utils.drug_search import search_drugs

    return jsonify(search_drugs(request.args.get("q"),
                                lang=getattr(g, "lang", "ar")))


@prescriptions_bp.route("/ai-dose", methods=["POST"])
@module_required(MODULE)
def ai_dose():
    """Ask the configured AI for a paediatric dose suggestion for one drug.

    Sends only the drug name, the child's weight/age and the diagnosis — no
    patient identifiers. The doctor always verifies before prescribing.
    """
    import json as _json

    from app.utils import ai as ai_utils

    if not ai_utils.is_ready():
        return jsonify({"ok": False, "error": "ai_not_ready"}), 400
    data = request.get_json(silent=True) or {}
    drug = (data.get("drug") or "").strip()
    if not drug:
        return jsonify({"ok": False, "error": "no_drug"}), 400
    weight = (str(data.get("weight") or "")).strip()
    age = (data.get("age") or "").strip()
    diagnosis = (data.get("diagnosis") or "").strip()

    system = (
        "You are a paediatric clinical pharmacology assistant. Given a drug, a "
        "child's weight/age and the diagnosis, suggest a typical paediatric dose. "
        "Be conservative and respect maximum doses. Respond ONLY with compact "
        'JSON: {"dose": "...", "frequency": "...", "duration": "...", "note": "..."}. '
        "Keep values short; put cautions in note. The treating doctor verifies."
    )
    prompt = (f"Drug: {drug}\nWeight: {weight or '—'} kg\nAge: {age or '—'}\n"
              f"Diagnosis: {diagnosis or '—'}")
    result = ai_utils.chat([{"role": "user", "content": prompt}], system=system,
                           feature="rx_review")
    if not result.get("ok"):
        return jsonify({"ok": False, "error": result.get("error", "ai_error")}), 502

    text = (result.get("text") or "").strip()
    parsed = None
    try:  # tolerate code fences / surrounding prose
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            parsed = _json.loads(text[start:end + 1])
    except (ValueError, TypeError):
        parsed = None
    if isinstance(parsed, dict):
        return jsonify({"ok": True, "dose": parsed.get("dose", ""),
                        "frequency": parsed.get("frequency", ""),
                        "duration": parsed.get("duration", ""),
                        "note": parsed.get("note", "")})
    return jsonify({"ok": True, "note": text})


@prescriptions_bp.route("/icd/search")
@module_required(MODULE)
def icd_search():
    """ICD-10 autocomplete for the prescription diagnosis field."""
    from app.utils.icd import search_icd

    return jsonify(search_icd(request.args.get("q"), limit=12))


@prescriptions_bp.route("/investigations/search")
@module_required(MODULE)
def investigation_search():
    """Autocomplete for lab tests / imaging when writing a prescription."""
    q = (request.args.get("q") or "").strip()
    kind = (request.args.get("kind") or "").strip()
    if len(q) < 1:
        return jsonify([])
    like = f"%{q}%"
    query = Investigation.query.filter(Investigation.is_active.is_(True)).filter(
        or_(Investigation.name_ar.ilike(like), Investigation.name_en.ilike(like))
    )
    if kind in ("lab", "imaging"):
        query = query.filter(Investigation.kind == kind)
    rows = query.order_by(Investigation.name_ar).limit(15).all()
    return jsonify([{
        "id": x.id, "name": x.display_name(), "kind": x.kind,
        "category": x.category or "",
    } for x in rows])


# ----------------------------------------------------- writing -------------
def _stage(value):
    """Validate the diagnosis stage, or leave it unsaid.

    Unsaid is a real answer: plenty of prescriptions carry a diagnosis nobody
    wants to grade, and inventing "final" for them would put a certainty on
    paper that the doctor never claimed.
    """
    value = (value or "").strip()
    return value if value in Prescription.DIAGNOSIS_STAGES else None


@prescriptions_bp.route("/new", methods=["GET", "POST"])
@module_required(MODULE)
def new():
    if request.method == "POST":
        patient = db.session.get(Patient, request.form.get("patient_id", type=int))
        if patient is None:
            flash(t("rx.need_patient"), "danger")
            return redirect(url_for("prescriptions.new"))

        rx = Prescription(
            patient_id=patient.id,
            doctor_id=request.form.get("doctor_id", type=int) or (
                current_user.id if current_user.role == "doctor" else None),
            visit_id=request.form.get("visit_id", type=int) or None,
            diagnosis=(request.form.get("diagnosis") or "").strip() or None,
            diagnosis_code=(request.form.get("diagnosis_code") or "").strip() or None,
            diagnosis_stage=_stage(request.form.get("diagnosis_stage")),
            complaint=(request.form.get("complaint") or "").strip() or None,
            notes=(request.form.get("notes") or "").strip() or None,
            created_by=current_user.id,
        )
        db.session.add(rx)
        db.session.flush()

        drug_ids = request.form.getlist("item_drug_id")
        names = request.form.getlist("item_name")
        doses = request.form.getlist("item_dose")
        freqs = request.form.getlist("item_frequency")
        durs = request.form.getlist("item_duration")
        instrs = request.form.getlist("item_instructions")
        # Ticked boxes only report the rows that are on, so the set of indices
        # is what says which lines print — an absent value means "off", and
        # that has to be a deliberate press rather than a default.
        off = {i for i in request.form.getlist("item_hidden", type=int)}
        used_ids, count = [], 0
        for i in range(len(names)):
            name = (names[i] or "").strip()
            if not name:
                continue
            did = None
            try:
                did = int(drug_ids[i]) if i < len(drug_ids) and drug_ids[i] else None
            except (ValueError, TypeError):
                did = None
            # Shorthand is expanded here as well as in the browser, so a
            # prescription reads the same however it was written — including
            # from a screen that never ran the JavaScript.
            written = expand_line({
                "dose": (doses[i].strip() if i < len(doses) else ""),
                "frequency": (freqs[i].strip() if i < len(freqs) else ""),
                "duration": (durs[i].strip() if i < len(durs) else ""),
            })
            rx.items.append(PrescriptionItem(
                drug_id=did, drug_name=name,
                dose=written["dose"] or None,
                frequency=written["frequency"] or None,
                duration=written["duration"] or None,
                instructions=(instrs[i].strip() if i < len(instrs) else "") or None,
                printed=i not in off,
            ))
            used_ids.append(did)
            count += 1

        # Investigations: lab tests + imaging (parallel arrays).
        inv_ids = request.form.getlist("inv_id")
        inv_kinds = request.form.getlist("inv_kind")
        inv_names = request.form.getlist("inv_name")
        inv_notes = request.form.getlist("inv_notes")
        inv_count = 0
        for i in range(len(inv_names)):
            name = (inv_names[i] or "").strip()
            if not name:
                continue
            kind = inv_kinds[i] if i < len(inv_kinds) else "lab"
            if kind not in ("lab", "imaging"):
                kind = "lab"
            iid = None
            try:
                iid = int(inv_ids[i]) if i < len(inv_ids) and inv_ids[i] else None
            except (ValueError, TypeError):
                iid = None
            inv_obj = db.session.get(Investigation, iid) if iid else None
            rx.investigations.append(PrescriptionInvestigation(
                investigation_id=iid, kind=kind, name=name,
                name_en=(inv_obj.name_en if inv_obj else None),
                notes=(inv_notes[i].strip() if i < len(inv_notes) else "") or None,
            ))
            inv_count += 1

        if count == 0 and inv_count == 0:
            db.session.rollback()
            flash(t("rx.need_item"), "warning")
            return redirect(url_for("prescriptions.new", patient_id=patient.id))

        ActivityLog.record("rx.create", user_id=current_user.id, entity="prescription",
                           detail=patient.patient_number, ip_address=client_ip())
        db.session.commit()
        if interaction_warnings(used_ids):
            flash(t("rx.interaction_flash"), "warning")
        return redirect(url_for("prescriptions.view", rx_id=rx.id))

    from app.utils import ai as ai_utils

    pid = request.args.get("patient_id", type=int)
    patient = db.session.get(Patient, pid) if pid else None
    # Pre-fill support when opened from inside a visit ("write prescription"):
    # patient + doctor + weight + the visit's final diagnosis carry over so the
    # doctor doesn't re-enter what they already recorded.
    visit_id = request.args.get("visit_id", type=int)
    prefill = {
        "visit_id": visit_id,
        "doctor_id": request.args.get("doctor_id", type=int),
        "weight": request.args.get("weight", type=float),
        "diagnosis": (request.args.get("diagnosis") or "").strip(),
        "diagnosis_code": (request.args.get("diagnosis_code") or "").strip(),
    }
    # Investigations the doctor already ordered in this visit carry over to the
    # prescription so labs/imaging asked for in the exam actually print on it.
    prefill_invs = []
    if visit_id:
        from app.models import VisitInvestigation
        lang = getattr(g, "lang", "ar")
        for vi in (VisitInvestigation.query.filter_by(visit_id=visit_id)
                   .order_by(VisitInvestigation.created_at).all()):
            prefill_invs.append({
                "id": vi.investigation_id or "",
                "kind": vi.kind or "lab",
                "name": vi.display_name(lang),
                "notes": vi.request_notes or "",
            })
    # Medicines the doctor already wrote in the visit carry over too, so what
    # was decided in the room is what prints (same idea as the investigations).
    prefill_meds = []
    visit_rx = []
    if visit_id:
        from app.models import VisitMedication

        # What this visit already printed. Carrying a medicine over twice is
        # how a patient ends up with two prescriptions for the same drug, so
        # anything already on a prescription for this visit is left out and
        # the existing prescription is linked instead.
        visit_rx = (Prescription.query.filter_by(visit_id=visit_id)
                    .order_by(Prescription.id.desc()).all())
        already = {(" ".join((it.drug_name or "").split())).lower()
                   for rx in visit_rx for it in rx.items}
        for m in (VisitMedication.query.filter_by(visit_id=visit_id)
                  .order_by(VisitMedication.id).all()):
            if (" ".join((m.name or "").split())).lower() in already:
                continue
            prefill_meds.append({
                "drug_id": m.drug_id or "",
                "name": m.name,
                "dose": m.dose or "",
                "frequency": m.frequency or "",
                "duration": m.duration or "",
                "instructions": m.instructions or "",
            })
        if visit_rx and not prefill_meds:
            flash(t("rx.visit_meds_all_prescribed"), "info")
    # Medication reconciliation: the patient's recent meds to review while
    # prescribing (continue / stop / modify).
    recent_meds = []
    if patient is not None:
        from app.utils.meds import recent_medications
        recent_meds = recent_medications(patient.id)
    return render_template(
        "prescriptions/new.html", patient=patient, prefill=prefill,
        prefill_invs=prefill_invs, prefill_meds=prefill_meds,
        visit_rx=visit_rx, recent_meds=recent_meds,
        presets=visible_presets(), frequencies=FREQUENCIES,
        # The doctor the field starts on: the one the visit carried over,
        # else the signed-in user when they see patients. Both the patient
        # list and the doctor list used to be sent whole and picked from a
        # dropdown; both are searches now.
        rx_doctor=(db.session.get(User, prefill["doctor_id"])
                   if prefill["doctor_id"]
                   else (current_user if current_user.is_practitioner else None)),
        ai_ready=ai_utils.is_ready(),
    )


def resolve_template(doctor, override_id=None):
    """Pick the print template: explicit override → doctor's → default → built-in."""
    if override_id:
        tpl = db.session.get(RxPrintTemplate, override_id)
        if tpl:
            return tpl
    if doctor is not None and doctor.rx_template_id:
        tpl = db.session.get(RxPrintTemplate, doctor.rx_template_id)
        if tpl:
            return tpl
    tpl = RxPrintTemplate.query.filter_by(is_default=True).first()
    return tpl or RxPrintTemplate.default_instance()


@prescriptions_bp.route("/<int:rx_id>")
@module_required(MODULE)
def view(rx_id):
    from flask import g as _g

    from app.utils.vaccines import visit_given_summary

    rx = db.get_or_404(Prescription, rx_id)
    warnings = interaction_warnings([it.drug_id for it in rx.items])
    tpl = resolve_template(rx.doctor, request.args.get("template", type=int))
    # The copy that leaves the building has to stand on its own.
    #
    # A "preprinted" template deliberately omits the letterhead, because the
    # paper it prints on already carries it. Send that same layout as a PDF and
    # the family receives a page with no clinic name, no doctor, no licence and
    # no stamp — which is not a prescription, it is a list of drug names. A
    # pharmacy is right to refuse it.
    #
    # So the digital copy is always rendered from a complete white template,
    # whatever the clinic prints on. This is not the doctor's choice to make:
    # the choice is about paper, and there is no paper here.
    digital = request.args.get("digital") == "1"
    if digital:
        tpl = RxPrintTemplate.default_instance()
    # Vaccinations administered in this visit (or on the rx date) print on the
    # prescription with dose X/N and the expected date of the next dose.
    try:
        on_date = rx.visit.visit_date if rx.visit else rx.rx_date
        rx_vaccines = visit_given_summary(rx.patient, on_date,
                                          getattr(_g, "lang", "ar"))
    except Exception:  # noqa: BLE001 - printing must never break on plan maths
        rx_vaccines = []
    return render_template("prescriptions/view.html", rx=rx, warnings=warnings,
                           tpl=tpl, rx_vaccines=rx_vaccines, digital=digital,
                           templates=RxPrintTemplate.query.order_by(RxPrintTemplate.name).all())


# ----------------------------------------------------- print templates -----
@prescriptions_bp.route("/templates")
@admin_required
def templates():
    return render_template("prescriptions/templates.html",
                           templates=RxPrintTemplate.query.order_by(RxPrintTemplate.name).all())


def _save_template(tpl):
    tpl.name = (request.form.get("name") or tpl.name or "قالب").strip()
    tpl.mode = "preprinted" if request.form.get("mode") == "preprinted" else "white"
    ls = request.form.get("logo_source")
    tpl.logo_source = ls if ls in ("clinic", "personal", "none") else "clinic"
    tpl.page_size = "A5" if request.form.get("page_size") == "A5" else "A4"
    tpl.font_size = request.form.get("font_size", type=int) or 14
    tpl.margin_mm = request.form.get("margin_mm", type=int) or 12
    for side in ("top", "right", "bottom", "left"):
        setattr(tpl, f"margin_{side}_mm", request.form.get(f"margin_{side}_mm", type=int))
    tpl.top_offset_mm = request.form.get("top_offset_mm", type=int) or 0
    for b in RxPrintTemplate.BOOLS:
        setattr(tpl, b, bool(request.form.get(b)))


@prescriptions_bp.route("/templates/new", methods=["POST"])
@admin_required
def template_new():
    tpl = RxPrintTemplate()
    _save_template(tpl)
    if not RxPrintTemplate.query.first():
        tpl.is_default = True
    db.session.add(tpl)
    db.session.commit()
    flash(t("rxtpl.added"), "success")
    return redirect(url_for("prescriptions.templates"))


@prescriptions_bp.route("/templates/<int:tpl_id>/edit", methods=["POST"])
@admin_required
def template_edit(tpl_id):
    tpl = db.get_or_404(RxPrintTemplate, tpl_id)
    _save_template(tpl)
    db.session.commit()
    flash(t("rxtpl.updated"), "success")
    return redirect(url_for("prescriptions.templates"))


@prescriptions_bp.route("/templates/<int:tpl_id>/default", methods=["POST"])
@admin_required
def template_default(tpl_id):
    tpl = db.get_or_404(RxPrintTemplate, tpl_id)
    RxPrintTemplate.query.update({RxPrintTemplate.is_default: False})
    tpl.is_default = True
    db.session.commit()
    flash(t("rxtpl.default_set"), "success")
    return redirect(url_for("prescriptions.templates"))


@prescriptions_bp.route("/templates/<int:tpl_id>/delete", methods=["POST"])
@admin_required
def template_delete(tpl_id):
    tpl = db.get_or_404(RxPrintTemplate, tpl_id)
    db.session.delete(tpl)
    db.session.commit()
    flash(t("rxtpl.deleted"), "info")
    return redirect(url_for("prescriptions.templates"))


@prescriptions_bp.route("/<int:rx_id>/delete", methods=["POST"])
@module_required(MODULE)
def delete(rx_id):
    rx = db.get_or_404(Prescription, rx_id)
    pid = rx.patient_id
    db.session.delete(rx)
    db.session.commit()
    flash(t("rx.deleted"), "info")
    return redirect(url_for("patients.view", patient_id=pid))


@prescriptions_bp.route("/patient-search")
@module_required(MODULE)
def patient_search():
    """JSON: find a patient to write a prescription for.

    Replaces a dropdown that was capped at 500 names sorted alphabetically. On
    a clinic with a few hundred files nobody noticed; on one with thousands
    the list simply stopped somewhere in the middle of the alphabet, and a
    doctor looking for a child whose name began with a later letter concluded
    the patient was not in the program. Searching has no such edge.
    """
    from flask import jsonify

    from app.utils.patients import apply_patient_search

    q = (request.args.get("q") or "").strip()
    if len(q) < 2:
        return jsonify([])
    rows = (apply_patient_search(
        Patient.query.filter(Patient.is_active.is_(True)), q)
        .order_by(Patient.full_name).limit(20).all())
    lang = getattr(g, "lang", "ar")
    # A bare array, because that is what the shared picker widget consumes —
    # every other search on these screens answers the same way.
    return jsonify([
        {"id": p.id, "name": p.display_name(lang), "number": p.patient_number,
         "dob": p.date_of_birth.isoformat() if p.date_of_birth else ""}
        for p in rows])


@prescriptions_bp.route("/doctor-search")
@module_required(MODULE)
def doctor_search():
    """JSON: the doctors a prescription can be written for.

    A doctor signing in gets their own name, settled, and no list at all — a
    picker that lets one doctor put another's name on a signed prescription is
    a picker that will eventually be used that way by accident. This answers
    the other case: an administrator or the front desk writing one on a
    doctor's behalf, who has to be able to say which doctor.

    An empty query returns everybody, because a clinic has a handful of
    doctors and making somebody guess the first two letters of a list that
    short is not searching, it is a hurdle.
    """
    from flask import jsonify

    q = (request.args.get("q") or "").strip()
    rows = User.query.filter(User.is_active.is_(True),
                             db.or_(User.role == "doctor",
                                    User.is_practitioner.is_(True)))
    if q:
        like = f"%{q}%"
        rows = rows.filter(db.or_(User.full_name.ilike(like),
                                  User.full_name_en.ilike(like),
                                  User.rx_display_name.ilike(like),
                                  User.username.ilike(like)))
    lang = getattr(g, "lang", "ar")
    return jsonify([
        {"id": u.id, "name": u.doctor_print_name(lang),
         "number": u.job_title or ""}
        for u in rows.order_by(User.full_name).limit(20).all()])


@prescriptions_bp.route("/copy/<token>")
def public_copy(token):
    """The prescription as the family opens it — no login, no staff screen.

    Reached from the link sent over WhatsApp. A picture would have been the
    obvious thing to send and cannot be made: rendering a page to a canvas
    through an SVG ``foreignObject`` taints the canvas in Chromium, which is
    what every clinic uses, so the browser refuses to export it. That is why
    the old "save as image" button silently did nothing.

    A link is the better answer anyway. It carries the letterhead, the stamp
    and the signature; it cannot be edited on the way; it is the clinic's own
    record rather than a photograph of it; and the pharmacy can reach the same
    verification code from it.
    """
    from app.utils.vaccines import visit_given_summary

    rx = Prescription.query.filter_by(share_token=token).first_or_404()
    tpl = RxPrintTemplate.default_instance()
    try:
        on_date = rx.visit.visit_date if rx.visit else rx.rx_date
        rx_vaccines = visit_given_summary(rx.patient, on_date,
                                          getattr(g, "lang", "ar"))
    except Exception:  # noqa: BLE001
        rx_vaccines = []
    return render_template("prescriptions/public.html", rx=rx, tpl=tpl,
                           rx_vaccines=rx_vaccines, digital=True)


@prescriptions_bp.route("/<int:rx_id>/send", methods=["POST"])
@module_required(MODULE)
def send_copy(rx_id):
    """Send the family their copy of the prescription.

    What goes out is a **link** to the clinic's own page, not a picture. The
    obvious thing would have been to render the paper to an image in the
    browser and attach it; it cannot be done. Rasterising a page through an
    SVG ``foreignObject`` taints the canvas in Chromium — every clinic's
    browser — so the export throws, which is exactly why the old "save as
    image" button had been quietly falling back to the print dialogue.

    The link is the better document regardless: it carries the letterhead,
    the stamp and the signature whatever the clinic prints on, it cannot be
    edited between here and the pharmacy, and it is the clinic's record
    rather than a photograph of one.
    """
    rx = db.get_or_404(Prescription, rx_id)
    phone = rx.patient.contact_phone if rx.patient else None

    from app.models import Setting
    from app.utils import whatsapp as wa

    lang = getattr(g, "lang", "ar")
    link = url_for("prescriptions.public_copy",
                   token=rx.share_link_token(), _external=True)
    body = wa.render(wa.template_body("rx_copy"), {
        "patient": rx.patient.display_name(lang) if rx.patient else "",
        "doctor": rx.doctor.doctor_print_name(lang) if rx.doctor else "",
        "clinic": Setting.get("clinic_name_ar") or Setting.get("clinic_name") or "",
        "link": link,
    })
    log = wa.send(body, phone, patient_id=rx.patient_id, user_id=current_user.id,
                  template_type="rx_copy")
    ActivityLog.record("rx.send_copy", user_id=current_user.id,
                       entity="prescription", entity_id=rx.id,
                       ip_address=client_ip())
    db.session.commit()
    return render_template("messages/sent.html", log=log, appt=None,
                           back_url=url_for("prescriptions.view", rx_id=rx.id))


@prescriptions_bp.route("/<int:rx_id>/verify.svg")
def verify_qr(rx_id):
    """A QR the pharmacy can scan to check this prescription is real.

    The digital copy is the point. A signed, stamped PDF sent over WhatsApp is
    a document that can be forwarded, edited and re-used, and the family
    holding it has no way to prove otherwise. The printed page has never
    needed this — it is on the clinic's own paper — but the moment a copy
    leaves as a file, "is this genuine" becomes a question somebody has to be
    able to answer.

    Same approach as the vaccination certificate, deliberately: one habit for
    the clinic, one thing for a pharmacist to learn.
    """
    from flask import Response

    rx = db.get_or_404(Prescription, rx_id)
    # Where the code leads. On a copy the family is holding it must lead to
    # the same page they are holding — the pharmacist scanning it is checking
    # that this page came from the clinic, and the staff-only screen would
    # simply refuse them. No login here either: the picture is a QR of a URL
    # and carries nothing else.
    if rx.share_token:
        target = url_for("prescriptions.public_copy", token=rx.share_token,
                         _external=True)
    else:
        target = url_for("prescriptions.verify", rx_id=rx.id, _external=True)
    svg = _qr_svg(target)
    if svg is None:
        return Response("", mimetype="image/svg+xml")
    return Response(svg, mimetype="image/svg+xml")


@prescriptions_bp.route("/<int:rx_id>/verify")
@module_required(MODULE)
def verify(rx_id):
    """What the scanned code opens: what this prescription actually says.

    Read-only and deliberately thin — enough to check a forwarded file against
    the clinic's own record, and nothing a scan should be able to change.
    """
    rx = db.get_or_404(Prescription, rx_id)
    return render_template("prescriptions/verify.html", rx=rx)


def _qr_svg(url, scale=3):
    """An inline SVG QR for ``url``, or None when the library is missing."""
    import io

    try:
        import segno
    except ImportError:                 # pragma: no cover - segno is required
        return None
    buf = io.BytesIO()
    segno.make(url, error="m").save(buf, kind="svg", scale=scale, border=0)
    return buf.getvalue().decode("utf-8")
