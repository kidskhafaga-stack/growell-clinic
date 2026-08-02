"""One answer to "which drug did you mean", for every screen that asks.

Reported: *"the drug search looks odd and it's hard to choose"*. Three causes,
all of them here or in the picker that renders this:

**Two endpoints had drifted.** The visit room's search returned the Arabic
name, the strength and the ingredient; the prescription writer's returned the
Latin trade name and no strength at all — while its template printed
``'(' + s.strength + ') '``. ``strength`` was never in that payload, so every
row in the list read **"() paracetamol"**. That is the "odd look", and it was
invisible from the server side because the server was not the one printing it.

**Nothing distinguished two rows.** Same brand, three strengths, three
identical lines — the doctor picks one and finds out later. The strength and
form are part of the answer, not decoration.

**And the order was alphabetical**, so typing "بروف" put the exact match
wherever the alphabet happened to place it. Ranked now: what you typed, then
what starts with it, then what merely contains it.
"""
from sqlalchemy import or_

DEFAULT_LIMIT = 15


def _rank(needle, *names):
    """0 = exact, 1 = starts with, 2 = contains, 3 = matched elsewhere.

    Lower sorts first. Every name of the product is tried, because a doctor
    types the Arabic on the box and a pharmacist types the Latin.
    """
    best = 3
    for name in names:
        text = (name or "").strip().lower()
        if not text:
            continue
        if text == needle:
            return 0
        if text.startswith(needle):
            best = min(best, 1)
        elif needle in text:
            best = min(best, 2)
    return best


def search_drugs(q, lang="ar", limit=DEFAULT_LIMIT, include_generics=True):
    """Active products matching ``q``, best match first.

    One payload for every caller: adding a field for one screen and not the
    other is how the two drifted apart in the first place.

    ``include_generics`` appends active ingredients that no brand on file
    carries, so a drug the clinic has never stocked is still prescribable by
    name — the visit room already did this and the prescription writer did
    not, which meant the same search gave two different answers depending on
    which screen you were standing on.
    """
    from app.models import Drug

    q = (q or "").strip()
    if not q:
        return []
    needle = q.lower()
    like = f"%{q}%"
    rows = (Drug.query.filter(Drug.is_active.is_(True))
            .filter(or_(Drug.trade_name.ilike(like),
                        Drug.trade_name_ar.ilike(like),
                        Drug.generic_name.ilike(like)))
            # Fetch wider than we return: the database orders alphabetically
            # and the ranking below is what decides, so cutting at `limit`
            # here would throw away the exact match before it was ranked.
            .order_by(Drug.trade_name).limit(max(limit * 4, 40)).all())

    rows.sort(key=lambda d: (
        _rank(needle, d.trade_name_ar, d.trade_name, d.generic_name),
        (d.trade_name or "").lower()))
    out = [_as_dict(d, lang) for d in rows[:limit]]
    if include_generics:
        out.extend(_loose_generics(like, lang, out))
    return out


def _loose_generics(like, lang, already):
    """Ingredients with no brand in the results — writable by name."""
    from app.models import GenericDrug

    seen = {row["generic_id"] for row in already if row["generic_id"]}
    found = []
    for gen in (GenericDrug.query.filter(GenericDrug.is_active.is_(True))
                .filter(or_(GenericDrug.name_ar.ilike(like),
                            GenericDrug.name_en.ilike(like)))
                .order_by(GenericDrug.name_en).limit(6).all()):
        if gen.id in seen:
            continue
        name = gen.display_name(lang)
        found.append({
            "id": "", "generic_id": gen.id, "trade": name, "alt": "",
            "trade_ar": "", "latin": "", "generic": name, "strength": "",
            "form": "", "name": name, "label": name, "dose": "",
            "frequency": "", "instructions": "", "max": "",
            "dose_per_kg": None, "max_per_kg": None, "conc": None,
            "is_ingredient": True,
        })
    return found


def _as_dict(d, lang):
    generic = d.generic.display_name(lang) if d.generic else (d.generic_name or "")
    return {
        "id": d.id,
        "generic_id": d.generic_id or "",
        # What to show first: the Arabic on the box when we have it.
        "trade": d.display_name(lang),
        # And the other spelling, so a name read off a box in either script is
        # recognisable without searching again.
        "alt": (d.trade_name if d.display_name(lang) != d.trade_name else
                (d.trade_name_ar or "")),
        "trade_ar": d.trade_name_ar or "",
        "latin": d.trade_name,
        "generic": generic,
        "strength": d.strength or "",
        "form": d.form or "",
        # The text a picked row puts in the prescription line — brand plus
        # strength, because "Brufen" alone is not a prescription.
        "name": " ".join(filter(None, [d.display_name(lang), d.strength or ""])),
        "label": d.label(),
        "dose": d.default_dose or "",
        "frequency": d.default_frequency or "",
        "instructions": d.default_instructions or "",
        "max": d.max_daily_dose or "",
        "dose_per_kg": d.dose_per_kg,
        "max_per_kg": d.max_per_kg,
        "conc": d.conc_mg_per_ml,
        "is_ingredient": False,
    }
