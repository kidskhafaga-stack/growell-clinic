"""Recognising a vaccine in whatever the old program called it.

The real export writes a vaccine as one free-text field with the brand, the
Arabic name and the abbreviation run together — and not always in the same
order:

    'Synflorix - مكورات رئوية - PCV 10'
    'BEXSERO - meningitis B - الحمى الشوكية B'
    'الحمى الشوكية B - BEXSERO - meningitis B'      ← the same thing, reordered
    'HAV-rix - كبدي (أ)'  /  'HAV-rix - كبدي (أ) [جديد]'
    'Mencevax - الحمى الشوكية'  /  'Mencevax - الحمى الشوكية - 10'
    'Prevenar - مكورات رؤية - PCV 13'               ← "رؤية" is a typo

Order therefore carries no information, so the name is split into pieces and
each piece is scored on its own against the catalogue. The scoring itself lives
in :mod:`app.utils.name_match`, because the services and the doctors in the
same file need exactly the same treatment; what is specific to vaccines is
here: the brand is what the clinic actually stocks and bills, so a brand hit
outranks a vaccine hit.

**Nothing here decides anything.** It proposes, with a confidence, and the
clinic confirms on a screen of 27 rows rather than 9,908. A matcher that wrote
its own guesses into ten years of vaccination records would be a matcher nobody
could trust, and the one case it gets wrong is a child recorded as having had a
vaccine they did not.
"""
from app.utils.name_match import (keys_for, pieces, rank,  # noqa: F401
                                  rank_all, score as _score)

__all__ = ["pieces", "catalogue", "suggest", "suggest_all"]


def _brand_names(brand):
    yield brand.name
    yield brand.name_en
    # "Rota-rix" and "Rotarix" are the same word with a hyphen in it, and the
    # hyphen is also a separator — so the pieces are compared against the
    # de-hyphenated form as well.
    yield (brand.name or "").replace("-", "")


def catalogue():
    """Everything a name can be matched to, loaded in one pass.

    ``[{brand_id, vaccine_id, label, keys}]`` — built once per screen rather
    than queried per name, which is the same rule the rest of the import runs
    on.
    """
    from app.models import Vaccine, VaccineBrand

    entries = []
    vaccines = {v.id: v for v in Vaccine.query.all()}
    for brand in VaccineBrand.query.all():
        vaccine = vaccines.get(brand.vaccine_id)
        brand_keys = keys_for(*_brand_names(brand), whole_only=True)
        keys = set(brand_keys)
        if vaccine is not None:
            keys |= keys_for(vaccine.name_ar, vaccine.name_en, vaccine.code)
        entries.append({
            "brand_id": brand.id,
            "vaccine_id": brand.vaccine_id,
            "strong_keys": brand_keys,
            "keys": keys,
            "label": f"{vaccine.name_ar} — {brand.name}" if vaccine else brand.name,
        })
    return entries


def suggest(name, entries=None, limit=3):
    """Ranked candidates for one free-text name.

    Returns ``[{brand_id, vaccine_id, label, score, confidence}]``, best first
    and empty when nothing scored at all.

    A hit on the **brand** counts double, because the brand is the thing the
    clinic stocks and bills: 'Synflorix' and 'Prevenar' are both pneumococcal,
    and matching only the vaccine would offer them interchangeably when they
    are different products at different prices.
    """
    entries = catalogue() if entries is None else entries
    return rank(name, entries, limit)


def suggest_all(names):
    """``{name: [candidates]}`` for a whole file, on one pass of the catalogue.

    9,908 rows carry 27 distinct names, so this runs 27 times and the clinic
    confirms 27 rows. Building the catalogue per name would be 27 sets of
    queries for no reason.
    """
    return rank_all(names, catalogue())
