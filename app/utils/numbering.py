"""Where a patient file number's letters come from.

The program shipped ``GC-000123`` and ``PM-2026-0001``. ``GC`` is one
clinic's initials — Growell Clinic — so every copy installed anywhere else
handed out file numbers carrying somebody else's name, and nobody noticed
because a file number is not something you read, it is something you quote
down the phone.

So the letters are **derived from the name of the clinic this copy is
installed for**: «عيادة الأطفال» issues ``AT-2026-0001``, «Sunrise Medical
Centre» issues ``SM-2026-0001``. Latin letters either way — a file number
gets printed on a card, read into a phone and sometimes turned into a
barcode, and a number that changes direction halfway through is the one
thing worse than the wrong letters.

**The one rule everything here bends around: a file number that has been
issued never changes.** It is written on a card the family keeps, on a
folder in a cupboard, on last year's lab results. So the derivation is a
*default*, never a recomputation:

* while no patient has been numbered, the prefix follows the clinic name
* **once one has, the numbers themselves answer the question** — the letters
  the last file number went out under are the letters the next one gets, and
  the clinic's name stops being consulted at all

That second step is deliberately *derived, not stored*. Writing the prefix
into settings on first use would have worked too, but the write would have
landed on a read path — the new-patient form previews the next number before
anybody has typed a name — and this project has already shipped that bug
once. Reading it off the last number issued needs no write anywhere, and the
record is a stronger witness than a settings row: it is the thing that is
actually printed on the cards.

A clinic that renames itself in March therefore keeps the letters it spent
January handing out, and :func:`series` exists so the settings screen can
say so out loud: it lists every prefix that actually appears in the file
numbers on record, because a clinic that has changed its prefix once has
two series and the program reads both.
"""
from app.models import Patient, Setting

SCHEMES = ("yearly", "fixed")
DEFAULT_SCHEME = "yearly"

# Where the letters end up if a clinic name yields nothing at all — a name
# made of digits, or a copy whose name was never filled in. The program's
# own initials, not a customer's.
FALLBACK_PREFIX = "PP"

SETTING_KEYS = {"yearly": "patient_number_prefix",
                "fixed": "patient_number_prefix_fixed"}

# What the program used to hand out. A clinic upgrading into this carries
# these rows already — written by `init-db`, not chosen by anybody — so the
# wizard is allowed to replace them, once, while no number has been issued.
# A clinic that *did* choose one of the two keeps it the moment it has a
# single patient on file, which is the case that matters.
LEGACY_DEFAULTS = {"PM", "GC"}

# Words that say what kind of place this is, not which one. Dropping them is
# what turns «مركز جرو ويل الطبي» into GW rather than MG.
SKIP_WORDS = {
    "عيادة", "عيادات", "مركز", "مركز", "مستشفى", "مستشفي", "مجمع", "مؤسسة",
    "الطبي", "الطبية", "طبي", "طبية", "التخصصي", "التخصصية", "تخصصي",
    "د", "د.", "دكتور", "دكتورة", "الدكتور", "الدكتورة", "دكاترة",
    "clinic", "clinics", "polyclinic", "center", "centre", "hospital",
    "medical", "medicine", "specialised", "specialized", "specialist",
    "dr", "dr.", "doctor", "the", "and", "for", "of", "&",
}

# First letters only. A full transliteration needs two Latin letters for
# half the Arabic alphabet (ث، خ، ش) and a prefix has no room for that, so
# each letter gets the nearest single one — ش and س both land on S, which is
# fine: this names a clinic, it does not have to be reversible.
ARABIC_FIRST = {
    "ا": "A", "أ": "A", "إ": "A", "آ": "A", "ء": "A", "ى": "Y", "ي": "Y",
    "ب": "B", "ت": "T", "ث": "S", "ج": "G", "ح": "H", "خ": "K", "د": "D",
    "ذ": "Z", "ر": "R", "ز": "Z", "س": "S", "ش": "S", "ص": "S", "ض": "D",
    "ط": "T", "ظ": "Z", "ع": "A", "غ": "G", "ف": "F", "ق": "Q", "ك": "K",
    "ل": "L", "م": "M", "ن": "N", "ه": "H", "ة": "T", "و": "W",
}

# What sits in front of an Arabic word without being part of it: the definite
# article, and the «لل» of «مركز النور للأطفال» — which is *for the*, and is in
# the name of half the paediatric clinics in the country. Left in, that clinic
# gets AL instead of NA: two prepositions and nothing of its own name.
ARABIC_PROCLITICS = ("لل", "ال")


def _bare(word):
    """``word`` without a leading article or preposition.

    The one thing it will not do is strip a word to nothing: «ال» on its own
    is all somebody gave us, so it keeps it and lets the caller take a letter
    from it rather than returning an empty string for the prefix to skip.
    """
    for clitic in ARABIC_PROCLITICS:
        if word.startswith(clitic) and len(word) > len(clitic):
            return word[len(clitic):]
    return word


def _letter(word):
    """The one Latin letter that stands for ``word``, or ``""``."""
    for ch in word:
        if ch in ARABIC_FIRST:
            return ARABIC_FIRST[ch]
        if ch.isascii() and ch.isalpha():
            return ch.upper()
    return ""


def _words(name):
    """The parts of ``name`` that a prefix should be built from, in order.

    A word saying what kind of place this is gets dropped — but only where it
    is noise, and **which side it sits on decides that**. Arabic puts the
    generic word first («عيادة الأطفال»), where it carries nothing: those
    initials are ط and أ. English puts it last («Growell Clinic»), where it is
    half of how everybody already writes the place: GC. So a lone surviving
    word borrows back the generic word *after* it, and never the one before.

    Falls back to the dropped words when they are all there is: a clinic
    literally called «عيادة» still deserves letters of its own rather than the
    program's.
    """
    parts = [p.strip("().,-–—«»\"'") for p in (name or "").split()]
    parts = [p for p in parts if p]
    kept = [(i, p) for i, p in enumerate(parts) if p.lower() not in SKIP_WORDS]
    if not kept:
        return parts
    if len(kept) == 1:
        at = kept[0][0]
        after = [p for j, p in enumerate(parts)
                 if j > at and p.lower() in SKIP_WORDS]
        if after:
            return [kept[0][1], after[0]]
    return [p for _, p in kept]


def initials(name, want=3):
    """Up to ``want`` Latin letters standing for ``name``; ``""`` if none.

    One letter per word that names the clinic; a single-word name gives its
    first two letters instead, because ``P-2026-0001`` reads like a typo.
    """
    words = _words(name)
    if not words:
        return ""
    if len(words) == 1:
        word = _bare(words[0])
        # A name written as two words joined up — PediaPro, MedCare, KidsHub —
        # is still two words to the person who chose it, and its capitals say
        # where the join is. PP, not PE.
        humps = [ch for ch in word if ch.isascii() and ch.isupper()]
        if len(humps) >= 2:
            return "".join(humps[:want])
        letters = [_letter(ch) for ch in word]
        letters = [ltr for ltr in letters if ltr][:2]
        return "".join(letters)
    out = []
    for word in words:
        letter = _letter(_bare(word))
        if letter:
            out.append(letter)
        if len(out) == want:
            break
    return "".join(out)


def suggest():
    """The prefix this clinic's name asks for, whatever is stored.

    The Arabic name is asked first and the Latin one second — a clinic that
    filled in both is an Arabic clinic with a transliteration, and the two
    give the same letters anyway when the transliteration is honest.
    """
    for key in ("clinic_name_ar", "clinic_name"):
        letters = initials(Setting.get(key))
        if letters:
            return letters
    return FALLBACK_PREFIX


def in_use():
    """The letters the most recent file number went out under, or ``""``.

    *Most recent*, not commonest: a clinic that changed its letters after
    four hundred patients is using the new ones, and the commonest answer
    would drag it back. A number with no prefix at all — an imported paper
    file like ``1234`` — is not letters and does not answer.
    """
    row = (Patient.query.with_entities(Patient.patient_number)
           .filter(Patient.patient_number.isnot(None),
                   Patient.patient_number != "")
           .order_by(Patient.id.desc()).first())
    if row is None:
        return ""
    number = str(row[0])
    head = number.split("-")[0]
    return head if head and head != number else ""


def prefix_for(scheme=None):
    """The letters this clinic's next file number starts with.

    Three answers in order, and the order is the whole design: what somebody
    chose, then what the clinic is already handing out, then what its name
    asks for. Reads only — nothing here writes, on any path.
    """
    scheme = scheme if scheme in SCHEMES else DEFAULT_SCHEME
    stored = (Setting.get(SETTING_KEYS[scheme]) or "").strip()
    return stored or in_use() or suggest()


def issued():
    """Has this clinic handed out a file number yet?

    The question the whole module turns on: before the first one, the letters
    are the program's business; after it, they are the family's.
    """
    return Patient.query.filter(
        Patient.patient_number.isnot(None),
        Patient.patient_number != "",
    ).first() is not None


def adopt_clinic_name():
    """Re-derive both prefixes from the clinic name, if nothing is at stake.

    The setup wizard asks for the facility's name, and on a fresh copy that
    is the first time the program learns it — later than the settings defaults
    were written. So the wizard calls this: with no file number issued there
    is nothing to protect and the letters follow the new name; with one
    issued this does nothing at all, which is the whole point.

    A prefix somebody typed themselves is left alone even then. The only
    stored values it will overwrite are blank and the two the program used to
    ship (:data:`LEGACY_DEFAULTS`) — neither of which anybody chose.

    Returns the prefix now in force, or ``None`` when it declined to move.
    """
    if issued():
        return None
    chosen = suggest()
    moved = False
    for key in SETTING_KEYS.values():
        stored = (Setting.get(key) or "").strip()
        if stored and stored not in LEGACY_DEFAULTS:
            continue
        Setting.set(key, chosen)
        moved = True
    return chosen if moved else None


def series():
    """Every prefix that appears in the file numbers on record, commonest first.

    ``[("PM", 412), ("GC", 9)]`` is a clinic that changed its letters after
    nine patients — a real state, and one the settings screen should show
    rather than imply that the current prefix is the only one.
    """
    counts = {}
    rows = Patient.query.with_entities(Patient.patient_number).filter(
        Patient.patient_number.isnot(None),
        Patient.patient_number != "",
    ).all()
    for (number,) in rows:
        head = str(number).split("-")[0]
        if head and head != str(number):
            counts[head] = counts.get(head, 0) + 1
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
