"""Safety checks for a list of medicines — used by the visit and the rx writer.

Three questions get asked every time a doctor writes a drug for a child:

* **is the child allergic to it?** — the allergies already on the file, matched
  against the ingredient, the brand and the drug family;

* **is this dose right for this child?** — the paediatric rules on the active
  ingredient, run against the patient's own weight and age;
* **do these drugs fight each other?** — interactions between the ingredients
  already on the list, with a severity and, where we know one, the alternative
  to use instead;
* **and does this course ever stop?** — a topical corticosteroid written with
  no end date on it is the one that gets repeated at the pharmacy for months,
  and it is the harm this file was extended for. Where a printed course limit
  exists it is checked too; where none does, the missing end date is still
  worth saying.

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
        entry = {
            "name": getattr(it, "name", None) or getattr(it, "drug_name", ""),
            "drug": getattr(it, "drug", None),
            "generic": getattr(it, "generic", None),
            "dose": getattr(it, "dose", None),
        }
        # **Only when the caller knows about durations at all.** An empty
        # duration and a caller that has never heard of the field are two
        # different facts, and the whole course check turns on the first one.
        # Conflating them would put "no end date written" on every screen that
        # simply does not pass durations — which is the same empty-list-means-
        # two-things fault this program keeps finding.
        if hasattr(it, "duration"):
            entry["duration"] = it.duration
        out.append(entry)
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


# Topical corticosteroids and topical antifungals, named by the code the
# reference already carries. ATC's D07 and D01 are exactly these two families,
# so no list of ingredients has to be kept in step with the seed — an
# ingredient added next year is covered the day it is added.
STEROID_ATC = "D07"
ANTIFUNGAL_ATC = "D01"


def _atc_family(generic, prefix):
    return bool(generic is not None
                and (generic.atc_code or "").upper().startswith(prefix))


def course_warnings(generic, duration):
    """What is wrong with the length of this course, if anything.

    Two different findings and they are deliberately separate:

    ``no_end_date`` — a topical corticosteroid with nothing written in the
    duration box. This needs no number from anybody: the concern is not that
    the course is too long, it is that **nothing says when it stops**, and the
    tube then gets repeated for months on a child's face or nappy area. The
    family is read off the ATC code the reference already holds.

    ``course_too_long`` — past the printed limit, and only for the ingredients
    where a printed limit exists. Hydrocortisone's carton says seven days;
    almost nothing else says anything, and this file does not invent the rest.
    """
    from app.utils.rx_shorthand import duration_days

    out = []
    if generic is None:
        return out
    days = duration_days(duration)
    if days is None and _atc_family(generic, STEROID_ATC):
        out.append("no_end_date")
    ceiling = getattr(generic, "max_course_days", None)
    if ceiling and days is not None and days > ceiling:
        out.append("course_too_long")
    return out


def steroid_with_antifungal(generics):
    """True when a topical steroid and a topical antifungal are written
    together.

    Not a forbidden combination and not treated as one — it is prescribed
    every day and often rightly. What it is, is the shape in which a steroid
    quietly becomes permanent: the rash improves, comes back, and the tube
    that has no end date on it is the steroid. Said once for the whole
    prescription rather than per line, because it is a fact about the pair.
    """
    rows = [g for g in generics if g is not None]
    return (any(_atc_family(g, STEROID_ATC) for g in rows)
            and any(_atc_family(g, ANTIFUNGAL_ATC) for g in rows))


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
        if "duration" in it:
            entry["warnings"] += course_warnings(generic, it["duration"])
        lines.append(entry)

    # What the child is *already* on, added before the interactions are
    # paired. Without this the check could only see the drugs being written in
    # this room: a child on carbamazepine for epilepsy, handed a macrolide for
    # a chest infection, produced no warning at all — the carbamazepine was
    # prescribed months ago by somebody else and was never in the list.
    from app.utils.patient_meds import ingredient_ids

    ongoing = ingredient_ids(patient) if patient is not None else []
    pairs = interaction_pairs(generic_ids + ongoing)
    together = steroid_with_antifungal([l["generic"] for l in lines])

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
        "steroid_with_antifungal": together,
        "has_warnings": (any(l["warnings"] or l["allergy"] for l in lines)
                         or bool(pairs) or together),
        "allergies": [l for l in lines if l["allergy"]],
    }


def as_json(result, lang="ar"):
    """The same result shaped for the browser (live checks while typing)."""
    return {
        "weight": result["weight"],
        "age_months": result["age_months"],
        "steroid_with_antifungal": result.get("steroid_with_antifungal", False),
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
