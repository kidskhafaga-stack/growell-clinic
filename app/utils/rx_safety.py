"""Safety checks for a list of medicines — used by the visit and the rx writer.

Three questions get asked every time a doctor writes a drug for a child:

* **is the child allergic to it?** — the allergies already on the file, matched
  against the ingredient, the brand and the drug family;

* **is this dose right for this child?** — the paediatric rules on the active
  ingredient, run against the patient's own weight and age;
* **do these drugs fight each other?** — interactions between the ingredients
  already on the list, with a severity and, where we know one, the alternative
  to use instead.

Both are answered from the drug reference, matched on the **active
ingredient**, so every brand of an interacting ingredient is caught. Nothing
here blocks the doctor: it returns warnings for the screen to show.
"""
from app.extensions import db
from app.models import Drug, DrugInteraction, GenericDrug
from app.utils.allergy import check_drug
from app.utils.dosing import age_months_of, calculate, latest_weight


def _generic_of(item):
    """The active ingredient behind one written line (or None)."""
    drug = item.get("drug") if isinstance(item, dict) else None
    generic = item.get("generic") if isinstance(item, dict) else None
    if generic is not None:
        return generic
    if drug is not None and drug.generic_id:
        return drug.generic
    name = (item.get("name") or "").strip().lower() if isinstance(item, dict) else ""
    if not name:
        return None
    # A hand-typed line still matches when it names the ingredient or a brand.
    row = (GenericDrug.query
           .filter(db.or_(db.func.lower(GenericDrug.name_en) == name,
                          db.func.lower(GenericDrug.name_ar) == name)).first())
    if row is not None:
        return row
    brand = (Drug.query
             .filter(db.func.lower(Drug.trade_name) == name,
                     Drug.generic_id.isnot(None)).first())
    return brand.generic if brand is not None else None


def _norm(items):
    """Accept model rows (VisitMedication / PrescriptionItem) or plain dicts."""
    out = []
    for it in items or []:
        if isinstance(it, dict):
            out.append(it)
            continue
        out.append({
            "name": getattr(it, "name", None) or getattr(it, "drug_name", ""),
            "drug": getattr(it, "drug", None),
            "generic": getattr(it, "generic", None),
            "dose": getattr(it, "dose", None),
        })
    return out


def interaction_pairs(generic_ids):
    """Active interaction rules among these ingredients (deduplicated)."""
    ids = {int(i) for i in generic_ids if i}
    if len(ids) < 2:
        return []
    rows = (DrugInteraction.query
            .filter(DrugInteraction.is_active.is_(True),
                    DrugInteraction.generic_a_id.in_(ids),
                    DrugInteraction.generic_b_id.in_(ids)).all())
    seen, out = set(), []
    for r in rows:
        if r.generic_a_id == r.generic_b_id:
            continue
        key = tuple(sorted((r.generic_a_id, r.generic_b_id)))
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def check(items, patient=None, weight_kg=None, age_months=None, lang="ar"):
    """Dose + interaction warnings for a list of written medicines.

    Returns ``{"lines": [...], "interactions": [...], "weight": …, "age_months": …}``
    where each line carries the ingredient it resolved to, the computed dose
    for this child and its warning codes.
    """
    items = _norm(items)
    if patient is not None:
        if weight_kg is None:
            weight_kg = latest_weight(patient)
        if age_months is None:
            age_months = age_months_of(patient)

    lines, generic_ids = [], []
    for it in items:
        generic = _generic_of(it)
        entry = {
            "name": it.get("name") or "",
            "generic": generic,
            "generic_name": generic.display_name(lang) if generic else "",
            "result": None,
            "warnings": [],
            # The allergy check runs even when the ingredient is unknown — a
            # hand-typed brand the reference has never seen still gets matched
            # against what the parent told us.
            "allergy": check_drug(patient, generic=generic, drug=it.get("drug"),
                                  name=it.get("name") or ""),
        }
        product = it.get("drug")
        # A combination product interacts through every ingredient it carries,
        # not just the one its dose is read from.
        if product is not None:
            generic_ids += [g.id for g in product.all_ingredients()]
        if generic is not None:
            generic_ids.append(generic.id)
            res = calculate(generic, weight_kg=weight_kg, age_months=age_months,
                            product=product)
            entry["result"] = res
            # "no weight recorded" is noise on a list — the dose panel says it
            # once; per line we only surface the real safety flags.
            entry["warnings"] = [w for w in res["warnings"]
                                 if w not in ("no_weight", "no_rule")]
        lines.append(entry)

    # What the child is *already* on, added before the interactions are
    # paired. Without this the check could only see the drugs being written in
    # this room: a child on carbamazepine for epilepsy, handed a macrolide for
    # a chest infection, produced no warning at all — the carbamazepine was
    # prescribed months ago by somebody else and was never in the list.
    from app.utils.patient_meds import ingredient_ids

    ongoing = ingredient_ids(patient) if patient is not None else []
    pairs = interaction_pairs(generic_ids + ongoing)

    return {
        "lines": lines,
        "interactions": pairs,
        # Named separately so the screen can say *why* a drug it cannot see on
        # the page is in the warning. "Interacts with something" is a warning
        # a doctor dismisses; "interacts with the carbamazepine he is on" is
        # one they act on.
        "ongoing_ids": ongoing,
        "weight": weight_kg,
        "age_months": age_months,
        "has_warnings": (any(l["warnings"] or l["allergy"] for l in lines)
                         or bool(pairs)),
        "allergies": [l for l in lines if l["allergy"]],
    }


def as_json(result, lang="ar"):
    """The same result shaped for the browser (live checks while typing)."""
    return {
        "weight": result["weight"],
        "age_months": result["age_months"],
        "lines": [{
            "name": l["name"],
            "generic": l["generic_name"],
            "dose_mg": (l["result"] or {}).get("dose_mg"),
            "dose_mg_max": (l["result"] or {}).get("dose_mg_max"),
            "ml": (l["result"] or {}).get("ml"),
            "doses_per_day": (l["result"] or {}).get("doses_per_day"),
            "warnings": l["warnings"],
            "allergy": l["allergy"],
        } for l in result["lines"]],
        "interactions": [{
            "a": r.pair_names(lang)[0],
            "b": r.pair_names(lang)[1],
            "severity": r.severity or "moderate",
            "note": r.note or "",
            "alternative": r.alternative or "",
        } for r in result["interactions"]],
    }
