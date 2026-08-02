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
each piece is scored on its own against the catalogue. The brand is what the
clinic actually stocks and bills, so a brand hit outranks a vaccine hit.

**Nothing here decides anything.** It proposes, with a confidence, and the
clinic confirms on a screen of 27 rows rather than 9,908. A matcher that wrote
its own guesses into ten years of vaccination records would be a matcher nobody
could trust, and the one case it gets wrong is a child recorded as having had a
vaccine they did not.
"""
import re

from app.utils.history_import import normalise_arabic

# Splitting on the separators the exports actually use. Brackets are separators
# too: "[جديد]" is a note somebody added, not part of the name.
_SPLIT = re.compile(r"[-–—/|,()\[\]]+")

# Noise that appears beside a name and means nothing on its own. Left in the
# string for display, dropped before scoring.
_NOISE = {"جديد", "new", "قديم", "old", "vaccine", "تطعيم", "لقاح"}


def pieces(name):
    """The scoreable parts of a free-text vaccine name, normalised."""
    out = []
    for chunk in _SPLIT.split(name or ""):
        text = normalise_arabic(chunk)
        if not text or text in _NOISE or text.isdigit():
            continue
        out.append(text)
    return out


def _score(needle, hay):
    """How well one piece matches one catalogue name: 0, 1 or 2.

    Deliberately coarse. A similarity ratio would order the near-misses
    prettily and still be a guess; what matters is only whether the clinic is
    shown the right candidate first, and equality-then-containment does that
    without pretending to a precision it has not got.
    """
    if not needle or not hay:
        return 0
    if needle == hay:
        return 2
    # Containment both ways: the file says "روتا" where the catalogue says
    # "فيروس الروتا", and "Rota-rix" where the catalogue brand is "Rotarix".
    if len(needle) >= 3 and (needle in hay or hay in needle):
        return 1
    return 0


def _brand_names(brand):
    yield normalise_arabic(brand.name)
    if brand.name_en:
        yield normalise_arabic(brand.name_en)
    # "Rota-rix" and "Rotarix" are the same word with a hyphen in it, and the
    # hyphen is also a separator — so the pieces are compared against the
    # de-hyphenated form as well.
    yield normalise_arabic((brand.name or "").replace("-", ""))


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
        keys = set(n for n in _brand_names(brand) if n)
        if vaccine is not None:
            for value in (vaccine.name_ar, vaccine.name_en, vaccine.code):
                key = normalise_arabic(value)
                if key:
                    keys.add(key)
        entries.append({
            "brand_id": brand.id,
            "vaccine_id": brand.vaccine_id,
            "brand_keys": set(n for n in _brand_names(brand) if n),
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
    parts = pieces(name)
    if not parts:
        return []

    scored = []
    for entry in entries:
        total = 0
        for part in parts:
            best_brand = max((_score(part, key) for key in entry["brand_keys"]),
                             default=0)
            best_any = max((_score(part, key) for key in entry["keys"]),
                           default=0)
            total += best_brand * 2 + best_any
        if total:
            scored.append({**entry, "score": total})

    scored.sort(key=lambda e: -e["score"])
    top = scored[:limit]
    best = top[0]["score"] if top else 0
    for entry in top:
        # Confidence is relative to the best candidate and to how much of the
        # name was explained. Shown as a hint on the screen, never used to skip
        # asking — see the module docstring.
        entry["confidence"] = _confidence(entry["score"], best, len(parts),
                                          len(top))
    return [{k: v for k, v in e.items() if k not in ("keys", "brand_keys")}
            for e in top]


def _confidence(score, best, parts, candidates):
    """``high`` / ``medium`` / ``low`` for one candidate.

    High means the pieces landed squarely *and* nothing else came close. Two
    candidates tying is the case that most needs a human, so it is never high
    however well they both scored — 'Mencevax - الحمى الشوكية' and
    'Mencevax - الحمى الشوكية - 10' are two rows in the same file.
    """
    if score < best:
        return "low"
    if candidates > 1:
        return "medium"
    return "high" if score >= parts * 2 else "medium"


def suggest_all(names):
    """``{name: [candidates]}`` for a whole file, on one pass of the catalogue.

    9,908 rows carry 27 distinct names, so this runs 27 times and the clinic
    confirms 27 rows. Building the catalogue per name would be 27 sets of
    queries for no reason.
    """
    entries = catalogue()
    return {name: suggest(name, entries) for name in names}
