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


def _bare(text):
    """Drop a leading Arabic definite article.

    The catalogue writes "الخماسي"; the file writes "خماسى خلوى". Without this
    they miss each other entirely, and 'خماسى خلوى-(Quinvaxem (DTwP-HBV-Hib'
    was matched to hepatitis B instead — because the only piece that *did* hit
    anything was the "HBV" buried in its ingredient list.
    """
    return text[2:] if text.startswith("ال") and len(text) > 4 else text


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
    needle, hay = _bare(needle), _bare(hay)
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


def _words(text):
    """A catalogue name and each of its words.

    Catalogue names are phrases — "الخماسي (الثلاثي + كبدي ب + هيموفيلس)" —
    and the file's names are phrases too, so comparing them whole almost never
    fires. Indexing the words as well is what lets "خماسى خلوى" find the
    pentavalent; without it the only piece of
    'خماسى خلوى-(Quinvaxem (DTwP-HBV-Hib' that hit anything was the "HBV"
    buried in its own ingredient list, which pulled it to hepatitis B.
    """
    out = {text}
    for word in re.split(r"[\s+]+", text):
        word = word.strip("()[]،,.")
        if len(word) >= 4:
            out.add(word)
    return out


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
                    keys |= _words(key)
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
    runner_up = top[1]["score"] if len(top) > 1 else 0
    for entry in top:
        # Confidence is relative to the *runner-up*, not to how many candidates
        # exist at all. Indexing the catalogue word by word means many entries
        # score something, so "more than one candidate" stopped telling anyone
        # anything — everything came back medium, and a confidence that is
        # always the same is not a confidence.
        entry["confidence"] = _confidence(entry["score"], best, runner_up,
                                          len(parts))
    return [{k: v for k, v in e.items() if k not in ("keys", "brand_keys")}
            for e in top]


def _confidence(score, best, runner_up, parts):
    """``high`` / ``medium`` / ``low`` for one candidate.

    High means the pieces landed squarely **and** the next candidate is not
    close behind. A near-tie is the case that most needs a person to look, so
    it is never high however well both scored: 'Mencevax - الحمى الشوكية' and
    'Mencevax - الحمى الشوكية - 10' are two rows of the same file, and picking
    between two products for a child is not a decision to take on a margin of
    one point.
    """
    if score < best:
        return "low"
    if score < parts:                    # barely anything was explained
        return "low"
    clear = score >= runner_up + 2       # the runner-up is not breathing on it
    return "high" if (clear and score >= parts * 2) else "medium"


def suggest_all(names):
    """``{name: [candidates]}`` for a whole file, on one pass of the catalogue.

    9,908 rows carry 27 distinct names, so this runs 27 times and the clinic
    confirms 27 rows. Building the catalogue per name would be 27 sets of
    queries for no reason.
    """
    entries = catalogue()
    return {name: suggest(name, entries) for name in names}
