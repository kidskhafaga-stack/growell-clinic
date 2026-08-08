"""Every drug registered in Egypt, so the doctor can find the box they mean.

The program shipped with 292 trade names. They are the good ones — each is
tied to an ingredient, so it carries paediatric dosing and the safety flags —
but a clinic writes from the whole Egyptian market, and a doctor who types
*Ketofan* and gets nothing does not conclude the catalogue is short. They type
it as free text, and a free-text prescription is one nothing can check for
interactions, allergies or a dose.

So the register goes in too: **25,065 trade names** with their Arabic name,
their active ingredient, the manufacturer and the price, shipped compressed at
under a megabyte and seeded on first run.

**The two layers stay distinct, and that matters clinically.** A seeded
register entry knows what it contains but not how to dose it; a curated brand
knows both. So the register is attached to an ingredient *only where the
scientific name genuinely matches one we hold* — never guessed. A brand that
finds no match is still findable, still prints, and simply has no dose
calculator behind it, which is the honest state rather than a confident number
derived from a name that happened to look similar.

**Prices are a starting point, not a truth.** They are what the register said
when the file was published; Egyptian prices move. They are seeded because a
clinic with a rough price is better off than one with none, and every one of
them is editable.
"""
import gzip
import json
import os

_PATH = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "data", "egypt_drugs.json.gz"))

# Route codes as the register writes them, mapped to the program's own words.
_ROUTES = {
    "ORAL.SOLID": "oral", "ORAL.LIQUID": "oral", "ORAL": "oral",
    "EFF": "oral", "TOPICAL": "topical", "OPHTHALMIC": "eye",
    "OTIC": "ear", "NASAL": "nasal", "RECTAL": "rectal",
    "VAGINAL": "vaginal", "PARENTERAL": "injection", "INHALATION": "inhaled",
}


def _load():
    if not os.path.exists(_PATH):
        return []
    with gzip.open(_PATH, "rt", encoding="utf-8") as fh:
        return json.load(fh)


def available():
    """How many entries the bundled register holds — for the setup screen."""
    return len(_load())


def _clean_maker(value):
    """The register writes "OLD NAME > NEW NAME"; keep the one in use now."""
    return (value or "").split(">")[-1].strip()[:120] or None


def seed_register(limit=None):
    """Insert the register's trade names that the clinic does not already have.

    Idempotent by trade name, and it never touches a drug that is already
    there — a clinic's own edits to a price or a dose outrank a bundled file,
    and re-running this on an upgrade must not quietly undo them.
    """
    from app.extensions import db
    from app.models import Drug, GenericDrug

    rows = _load()
    if limit:
        rows = rows[:limit]
    if not rows:
        return 0

    have = {name.upper() for (name,) in
            db.session.query(Drug.trade_name).all()}
    # Ingredients we can dose, by both names, so a register entry whose
    # scientific name matches one of ours inherits the paediatric maths.
    generics = {}
    for generic in GenericDrug.query.all():
        for key in (generic.name_en, generic.name_ar):
            if key:
                generics[key.strip().upper()] = generic

    added = 0
    for trade, trade_ar, scientific, maker, route, price in rows:
        if trade.upper() in have:
            continue
        have.add(trade.upper())
        # Only an exact ingredient match links. A combination product like
        # "PARACETAMOL+CAFFEINE" is deliberately left unlinked: dosing it on
        # its first-named ingredient is how a child gets the wrong dose of the
        # second one.
        generic = generics.get(scientific.strip().upper())
        db.session.add(Drug(
            trade_name=trade[:160],
            trade_name_ar=(trade_ar or None) and trade_ar[:160],
            generic_name=(scientific or None) and scientific[:160],
            generic_id=generic.id if generic else None,
            manufacturer=_clean_maker(maker),
            route=_ROUTES.get((route or "").strip().upper()),
            price=price,
            dose_per_kg=(generic.dose_per_kg
                         if generic and generic.dose_basis == "per_dose" else None),
            is_active=True,
        ))
        added += 1
        # Committed in batches: 25,000 pending objects in one session is a
        # lot of memory on a clinic PC, and a half-finished seed that leaves
        # 10,000 usable drugs behind is better than one that rolls back.
        if added % 2000 == 0:
            db.session.commit()
    db.session.commit()
    return added
