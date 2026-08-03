"""Recognising one of the clinic's own names in whatever the old program wrote.

The vaccine matcher was built first, against a real export, and everything it
learned there is true of the other two columns as well:

    'كشف'  /  'كشف عيادة'  /  'الكشف'            ← one service, three spellings
    'د/ محمد الخفاجى'  /  'محمد الخفاجي'          ← one doctor, two files

So the scoring lives here once and the three callers differ only in what they
build a catalogue out of. Order carries no information — the old program writes
a name as free text with the parts in whatever sequence somebody typed — so a
name is split into pieces and each piece is scored on its own.

**Nothing here decides anything.** It proposes, with a confidence, and the
clinic confirms on a screen of a few dozen rows rather than ten thousand. The
governing rule of the whole import holds: link to what exists first, and
creating something new is an explicit choice, never a side effect of a guess.
"""
import re

from app.utils.history_import import normalise_arabic

# Splitting on the separators the exports actually use. Brackets are separators
# too: "[جديد]" is a note somebody added, not part of the name.
_SPLIT = re.compile(r"[-–—/|,()\[\]]+")

# Noise that appears beside a name and means nothing on its own. Left in the
# string for display, dropped before scoring. "د" and "dr" are here because a
# title is on almost every doctor row in the file and on none of the clinic's
# own user records — scored, it would make every doctor look like every other.
_NOISE = {"جديد", "new", "قديم", "old", "vaccine", "تطعيم", "لقاح",
          "د", "دكتور", "دكتوره", "dr", "doctor", "prof", "أ", "ا"}


def pieces(name):
    """The scoreable parts of a free-text name, normalised."""
    out = []
    for chunk in _SPLIT.split(name or ""):
        text = normalise_arabic(chunk)
        if not text or text in _NOISE or text.isdigit():
            continue
        out.append(text)
    return out


def bare(text):
    """Drop a leading Arabic definite article.

    The catalogue writes "الخماسي"; the file writes "خماسى خلوى". Without this
    they miss each other entirely. The same applies to services — the clinic
    calls it "كشف" and the file says "الكشف".
    """
    return text[2:] if text.startswith("ال") and len(text) > 4 else text


def score(needle, hay):
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
    needle, hay = bare(needle), bare(hay)
    if needle == hay:
        return 2
    # Containment both ways: the file says "روتا" where the catalogue says
    # "فيروس الروتا", and "Rota-rix" where the catalogue brand is "Rotarix".
    if len(needle) >= 3 and (needle in hay or hay in needle):
        return 1
    return 0


def words(text):
    """A catalogue name and each of its words.

    Catalogue names are phrases — "الخماسي (الثلاثي + كبدي ب + هيموفيلس)" —
    and the file's names are phrases too, so comparing them whole almost never
    fires. Indexing the words as well is what lets "خماسى خلوى" find the
    pentavalent, and what lets a doctor's family name alone find them.
    """
    out = {text}
    for word in re.split(r"[\s+]+", text):
        word = word.strip("()[]،,.")
        if len(word) >= 4:
            out.add(word)
    return out


def keys_for(*names, whole_only=False):
    """The lookup keys for one catalogue row, from however many spellings.

    ``whole_only`` keeps the phrase and drops its words — used for the strong
    keys of a brand, where "Rotarix" is the product and a stray word out of a
    long vaccine name is not.
    """
    out = set()
    for value in names:
        key = normalise_arabic(value)
        if not key:
            continue
        out.add(key) if whole_only else out.update(words(key))
    return out


def confidence(value, best, runner_up, parts):
    """``high`` / ``medium`` / ``low`` for one candidate.

    High means the pieces landed squarely **and** the next candidate is not
    close behind. A near-tie is the case that most needs a person to look, so
    it is never high however well both scored: two doctors sharing a family
    name, or two products of the same vaccine, are exactly the decisions that
    should not be taken on a margin of one point.
    """
    if value < best:
        return "low"
    if value < parts:                    # barely anything was explained
        return "low"
    clear = value >= runner_up + 2       # the runner-up is not breathing on it
    return "high" if (clear and value >= parts * 2) else "medium"


def rank(name, entries, limit=3):
    """Ranked candidates for one free-text name, best first.

    ``entries`` are ``{..., "keys": set, "strong_keys": set}``; a hit on a
    strong key counts double. Everything outside ``keys``/``strong_keys`` is
    carried through untouched, so a caller decides for itself what a candidate
    is called and what it points at.

    Empty when nothing scored at all — which is the honest answer, and is why
    every screen that uses this keeps a "none of these" option.
    """
    parts = pieces(name)
    if not parts:
        return []

    scored = []
    for entry in entries:
        strong_keys = entry.get("strong_keys") or ()
        total = 0
        for part in parts:
            strong = max((score(part, key) for key in strong_keys), default=0)
            any_key = max((score(part, key) for key in entry["keys"]), default=0)
            total += strong * 2 + any_key
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
        entry["confidence"] = confidence(entry["score"], best, runner_up,
                                         len(parts))
    return [{k: v for k, v in e.items() if k not in ("keys", "strong_keys")}
            for e in top]


def rank_all(names, entries, limit=3):
    """``{name: [candidates]}`` for a whole column, on one catalogue.

    9,908 rows carry 27 service names and a handful of doctors, so this runs a
    few dozen times against a catalogue built once. Building it per name would
    be a set of queries per name for no reason.
    """
    return {name: rank(name, entries, limit) for name in names}


# ================================================================= services ==
def service_catalogue():
    """Every active service, as matchable entries.

    ``code`` is a strong key: a clinic that exports its own service codes has
    said exactly which service it means, and that should outrank a name that
    merely shares a word.
    """
    from app.models import Service

    entries = []
    for row in Service.query.filter(Service.is_active.is_(True)).all():
        entries.append({
            "service_id": row.id,
            "label": row.name,
            "keys": keys_for(row.name, row.name_en, row.code),
            "strong_keys": keys_for(row.code, whole_only=True),
        })
    return entries


def suggest_services(names, entries=None):
    """``{name in the file: [service candidates]}``."""
    entries = service_catalogue() if entries is None else entries
    return rank_all(names, entries)


# ================================================================== doctors ==
def doctor_catalogue():
    """Everyone who sees patients, as matchable entries.

    The username is indexed as well as the two names because an old program's
    "doctor" column is sometimes a login rather than a person's name.
    """
    from app.utils.appointments import list_doctors
    from flask import g

    lang = getattr(g, "lang", "ar")
    entries = []
    for user in list_doctors():
        entries.append({
            "user_id": user.id,
            "label": user.display_name(lang),
            "keys": keys_for(user.full_name, user.full_name_en, user.username),
        })
    return entries


def suggest_doctors(names, entries=None):
    """``{name in the file: [doctor candidates]}``.

    Replaces an exact-match index. A clinic's own user is "محمد الخفاجى" and
    the file says "د/ محمد الخفاجي" — the same person, and an exact match found
    neither of them, which left a decade of a doctor's work with no doctor on
    it unless somebody picked from the dropdown by hand for every name.
    """
    entries = doctor_catalogue() if entries is None else entries
    return rank_all(names, entries)
