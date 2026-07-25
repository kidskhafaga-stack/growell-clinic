"""Reading a real market drug list — the names as the register actually writes them.

The Egyptian register is a commercial list, not a clean reference. One row says
``AUGMENTIN 1 GM 14 F.C. TABS.`` with the ingredient written as
``AMOXICILLIN+CLAVULANIC ACID``, the class as ``ANTIBIOTICS  BROAD SPECTRUM``
and the route as ``ORAL.SOLID``. Everything a prescriber needs is in there; none
of it is in its own column.

This module turns those strings into the shape the reference expects, and — as
importantly — refuses to invent structure that isn't there. Splitting an
ingredient on ``+`` produces genuine components most of the time and produces
nonsense the rest of the time (``(10 INGREDIENTS) EUCALYPTUS OIL-CAMPHOR…``),
so anything that doesn't look like an ingredient name is dropped rather than
becoming a row in the reference that a doctor will one day search.
"""
import re

# Dosage forms, longest first so "F.C. TABS" doesn't match "TABS" first.
FORMS = [
    ("f.c. tab", "tablet"), ("fc tab", "tablet"), ("e.c. tab", "tablet"),
    ("chewable tab", "tablet"), ("eff. tab", "effervescent"),
    ("eff tab", "effervescent"), ("effervescent", "effervescent"),
    ("tab", "tablet"), ("cap", "capsule"), ("susp", "suspension"),
    ("syrup", "syrup"), ("syr", "syrup"), ("drops", "drops"), ("drop", "drops"),
    ("amp", "ampoule"), ("vial", "vial"), ("i.v. inf", "infusion"),
    ("inj", "injection"), ("sachet", "sachet"), ("supp", "suppository"),
    ("cream", "cream"), ("oint", "ointment"), ("gel", "gel"),
    ("lotion", "lotion"), ("spray", "spray"), ("emulsion", "emulsion"),
    ("solution", "solution"),
    ("sol", "solution"), ("powder", "powder"), ("shampoo", "shampoo"),
    ("soap", "soap"), ("patch", "patch"), ("granules", "granules"),
]

# The register's route codes → what a prescriber calls it.
ROUTES = {
    "oral.solid": "oral", "oral.liquid": "oral", "oral": "oral",
    "eff": "oral", "injection": "injection", "topical": "topical",
    "eye": "ophthalmic", "ear": "otic", "nose": "nasal", "spray": "inhalation",
    "inhalation": "inhalation", "rectal": "rectal", "vaginal": "vaginal",
    "mouth": "oromucosal", "soap": "topical", "unknown": None,
}

# A strength is a dose unit — never a bare volume. "SHAMPOO 250 ML" is how big
# the bottle is, not how strong it is, and calling it a strength puts a
# meaningless number on the prescription.
_STRENGTH_RE = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(mg\s*/\s*\d*\s*ml|mcg\s*/\s*\d*\s*ml|"
    r"iu\s*/\s*\d*\s*ml|mg|mcg|gm|g|iu|%)(?![a-z])", re.I)
# Grams this large are a tube or a jar, not a dose.
_GRAM_PACK_MIN = 5
# The count and its unit are often split by the form: "30 F.C. TABS.".
_PACK_RE = re.compile(
    r"\b(\d{1,4})\s*(?:[a-z]\.?\s*){0,4}?"
    r"(tabs?|caps?|amps?|vials?|sachets?|supps?|pieces?|pcs)\b", re.I)
_VOLUME_RE = re.compile(r"\b(\d{1,4}(?:\.\d+)?)\s*(ml|gm|g)\b", re.I)

# A component has to look like a substance name to become one.
_JUNK_START = re.compile(r"^[^A-Za-z؀-ۿ]")
_HAS_LETTERS = re.compile(r"[A-Za-z؀-ۿ]{3}")
MAX_COMPONENTS = 6
MAX_INGREDIENT_LEN = 120


def clean_ingredient(raw):
    """One component name, or None when the text isn't an ingredient.

    ``PARACETAMOL(ACETAMINOPHEN)`` → ``Paracetamol``; a parenthesised synonym
    is the same substance under another name, and keeping both would split one
    ingredient's dosing rules across two rows.
    """
    text = (raw or "").strip()
    if not text:
        return None
    text = re.sub(r"\([^)]*\)", " ", text)          # drop synonyms/notes
    text = re.sub(r"\s+", " ", text).strip(" .,-;:/")
    if not text or len(text) > MAX_INGREDIENT_LEN:
        return None
    # A strength trailing the name ("VITAMIN C 1 GM") belongs to the product.
    text = _STRENGTH_RE.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip(" .,-;:/")
    if not text or _JUNK_START.match(text) or not _HAS_LETTERS.search(text):
        return None
    if re.search(r"\d\s*(ingredients?|%)", text, re.I):
        return None
    return text.title() if text.isupper() else text


def split_ingredients(raw):
    """Every active ingredient in one ``scientific_name`` cell.

    A combination product is genuinely several substances, and a safety check
    that only knows the first one will happily let a child allergic to
    clavulanic acid be given Augmentin. So all of them are returned — the
    first is the one dosing is read from.
    """
    text = (raw or "").strip()
    if not text:
        return []
    parts = re.split(r"[+/]|\s+&\s+", text)
    out = []
    for part in parts:
        name = clean_ingredient(part)
        if name and name.lower() not in {n.lower() for n in out}:
            out.append(name)
        if len(out) >= MAX_COMPONENTS:
            break
    # Nothing survived the cleaning but there *was* text: keep the whole cell
    # as one ingredient rather than losing the product's identity entirely.
    if not out:
        whole = clean_ingredient(text.replace("+", " "))
        if whole:
            out.append(whole)
    return out


def parse_form(name):
    """The dosage form hiding at the end of a commercial name."""
    low = (name or "").lower()
    for token, form in FORMS:
        if re.search(r"\b" + re.escape(token), low):
            return form
    return None


def parse_strength(name, scientific=None):
    """The strength printed in the product name (``1 GM``, ``125 MG/5 ML``).

    Read from the commercial name first — that is where the register puts it —
    and from the ingredient cell only as a fallback (``VITAMIN C 1 GM``).
    """
    for source in (name, scientific):
        for match in _STRENGTH_RE.finditer(source or ""):
            unit = match.group(2).lower()
            if unit in ("g", "gm"):
                try:
                    if float(match.group(1).replace(",", ".")) >= _GRAM_PACK_MIN:
                        continue          # a 20 GM tube, not a 20 gram dose
                except ValueError:
                    continue
            return re.sub(r"\s+", " ", match.group(0)).strip().upper()
    return None


def parse_pack(name):
    """How many are in the box, or how much liquid is in the bottle."""
    match = _PACK_RE.search(name or "")
    if match is not None:
        return f"{match.group(1)} {match.group(2).lower()}"
    # A liquid's pack is its volume — but not when that number is the strength.
    for match in _VOLUME_RE.finditer(name or ""):
        value = float(match.group(1))
        if match.group(2).lower() == "ml" and value >= 15:
            return f"{match.group(1)} ml"
    return None


def parse_conc(strength):
    """mg per ml, when the strength says so — what converts a dose into a spoon."""
    if not strength:
        return None
    match = re.search(r"(\d+(?:\.\d+)?)\s*mg\s*/\s*(\d+(?:\.\d+)?)?\s*ml",
                      strength, re.I)
    if match is None:
        return None
    try:
        mg = float(match.group(1))
        ml = float(match.group(2)) if match.group(2) else 1.0
        return round(mg / ml, 4) if ml > 0 else None
    except (TypeError, ValueError):
        return None


def parse_route(raw):
    """``ORAL.SOLID`` → ``oral``. Unknown stays unknown rather than guessed."""
    key = (raw or "").strip().lower()
    if key in ROUTES:
        return ROUTES[key]
    head = key.split(".")[0]
    return ROUTES.get(head)


def clean_manufacturer(raw, limit=120):
    """``ORGANIX > NOVACURE`` — the register names holder and marketer. The
    company on the box is the one a pharmacist is asked about."""
    text = (raw or "").strip()
    if not text:
        return None
    text = text.split(">")[-1].strip() or text
    return text[:limit]
