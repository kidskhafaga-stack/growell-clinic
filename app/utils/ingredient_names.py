"""One ingredient, spelled the way whoever typed it spells it.

A brand in the catalogue gets its paediatric dosing by matching its scientific
name against the curated reference. The match was exact, so
``PARACETAMOL(ACETAMINOPHEN)`` — 92 products in the Egyptian register — did
not match ``Paracetamol``, and 92 boxes of the commonest drug in paediatrics
arrived with no dose calculator behind them. ``CHOLECALCIFEROL(VITAMIN D3)``
is another 116. ``ACYCLOVIR`` and ``CEFALEXIN`` are the US and British
spellings of drugs the reference already holds under the other one.

Measured across the whole register, recognising every spelling of a name takes
the brands tied to a dosable ingredient from **2,018 to 2,618** — clinical
data already written and already referenced. That is the cheapest and safest
coverage there is: no new numbers, no new judgement, just reading a name.

It was 595 before the route rule below. The extra 251 came from stripping
brackets off this program's *own* ingredient names, where a bracket usually
means a route rather than a synonym — so 27 systemic ofloxacin products were
being handed the dose of ear drops. Those 251 were coverage bought with a
hazard, and they are gone.

**What this deliberately does not do.** It does not guess. Every rule here is
a known orthographic pair or a synonym the register itself puts in brackets
beside the name it belongs to — never a similarity score, never a prefix
match. ``Cefixime`` and ``Cefuroxime`` are four letters apart and are
different antibiotics; a fuzzy matcher that brought them together would put a
cephalosporin's dose on another cephalosporin, and nothing downstream would
question it. The exact-match rule that caused the 92 was a *safe* failure, and
whatever replaces it has to fail the same way.
"""
import re

# Orthographic pairs, applied in both directions. British and American
# pharmacopoeias differ on these and Egyptian packaging uses both.
# Words that make a bracket a route rather than a synonym — in both
# languages, because the reference names every ingredient twice.
#
# English-only was the first version and it defeated the entire rule: a
# lookup on the Arabic name went straight past it, so "أوفلوكساسين" reached
# "Ofloxacin (otic)", "كيتوكونازول" reached the topical ketoconazole and
# "كلورامفينيكول" reached the eye chloramphenicol. Those are the three route
# confusions this module exists to prevent, and they were all live through
# the Arabic side.
_ROUTE_WORDS = {
    "TOPICAL", "OTIC", "EAR", "EYE", "OPHTHALMIC", "NASAL", "INHALED",
    "INHALATION", "ORAL", "RECTAL", "VAGINAL", "IV", "IM", "INJECTION",
    "SUBLINGUAL", "TRANSDERMAL", "BUCCAL",
    "موضعي", "أنف", "عين", "أذن", "قطرة", "استنشاق", "لبوس", "فموي",
    "شرجي", "مهبلي", "حقن", "وريدي", "عضلي",
}

# A bracket that names the *form* or the *purpose* rather than the substance.
# "Teething gel (chamomile)" is not another way of writing chamomile — and
# treating it as one linked chamomile tea and a skin cream to the teething
# gel's entry. "Lysine (appetite)" has the same shape.
_FORM_WORDS = {
    "GEL", "CREAM", "OINTMENT", "LOTION", "DROPS", "SPRAY", "SUPPOSITORY",
    "APPETITE",
    "جل", "كريم", "مرهم", "لوشن", "بخاخ", "شهية",
}


def _words(text):
    return {w.strip(" .") for w in (text or "").upper().split()}


def _is_route(text):
    """Whether a bracket's contents name a route of administration."""
    return bool(_words(text) & _ROUTE_WORDS)


def _is_form(text):
    """Whether a name is a dosage form or a purpose rather than a substance."""
    return bool(_words(text) & _FORM_WORDS)


_SWAPS = [
    ("ACYCLO", "ACICLO"),        # Acyclovir / Aciclovir
    ("SULPH", "SULF"),           # sulphate / sulfate
    ("CEPHA", "CEFA"),           # Cephalexin / Cefalexin
    ("CEPHR", "CEFR"),
    ("OESTR", "ESTR"),
    ("AMPICILLIN", "AMPICILIN"),
    ("Æ", "AE"),
]


# Every way the register writes "this box holds more than one drug". Only
# "+" was rejected before, so "LIDOCAINE - AESCIN - METHYL SALICYLATE" and
# "MENTHOL & CAMPHOR & LIDOCAINE" were single names as far as the matcher
# could tell.
_SEPARATORS = re.compile(r"[+/&،]|\s-\s")


def variants(name):
    """Every spelling of one ingredient worth trying, most literal first.

    The order matters only for readability — a caller stops at its first hit,
    and each variant names the same substance, so any hit is the right one.
    """
    raw = (name or "").strip().upper()
    if not raw:
        return []

    out = [raw]
    # A bracket means one of two opposite things, and telling them apart is
    # the whole of the safety here.
    #
    # In the register it is a synonym: "PARACETAMOL(ACETAMINOPHEN)" is one
    # drug written twice, and both halves should be tried.
    #
    # In this program's own reference it is often a **route**: "Ofloxacin
    # (otic)" is ear drops, and the plain word "OFLOXACIN" on a box may be
    # oral tablets. Stripping that bracket was measured to link 27 systemic
    # ofloxacin products to an ear-drop entry — and the same for
    # "Chloramphenicol (eye)" (21), whose systemic form causes grey baby
    # syndrome, and "Ketoconazole (topical)" (18), whose oral form is
    # hepatotoxic and restricted. A route qualifier is a fact about the drug,
    # not a spelling of it, so it is never dropped.
    inner = re.findall(r"\(([^)]*)\)", raw)
    outside = " ".join(re.sub(r"\([^)]*\)", " ", raw).split())
    if not any(_is_route(part) or _is_form(part) for part in inner):
        inside = " ".join(" ".join(inner).split())
        # The bracket is a synonym only when what is outside it is a substance.
        # "Teething gel (chamomile)" fails that and keeps its full name alone.
        parts = [outside] if _is_form(outside) else [outside, inside]
        for part in parts:
            if part:
                out.append(part)

    # "POVIDONE- IODINE" and "Povidone-iodine" are the same 64 products typed
    # by two people. Spacing around a hyphen is punctuation, not chemistry.
    spaced = []
    for value in out:
        tidy = " ".join(re.sub(r"\s*-\s*", "-", value).split())
        if tidy != value:
            spaced.append(tidy)
    out += spaced

    swapped = []
    for value in out:
        for a, b in _SWAPS:
            if a in value:
                swapped.append(value.replace(a, b))
            if b in value:
                swapped.append(value.replace(b, a))
    out += swapped

    seen, unique = set(), []
    for value in out:
        if value and value not in seen:
            seen.add(value)
            unique.append(value)
    return unique


def index_of(generics):
    """Look-up table from every spelling to the ingredient that owns it.

    Built once per seed rather than per row: 25,000 brands against 107
    ingredients is 2.7 million comparisons the other way round.

    A spelling already claimed is never reassigned. Two ingredients that
    normalise to the same string would otherwise silently swap depending on
    query order, and the one a brand got would depend on nothing anybody could
    see.
    """
    table = {}
    for generic in generics:
        for name in (generic.name_en, generic.name_ar):
            for key in variants(name):
                table.setdefault(key, generic)
    return table


def match(scientific_name, table):
    """The ingredient a brand's scientific name refers to, or ``None``.

    A combination is never matched. "PARACETAMOL+CAFFEINE" contains a drug the
    reference knows, and dosing the box on it gives a child the right dose of
    the paracetamol and an unexamined dose of everything else — which is the
    exact failure the whole exact-match rule existed to prevent.
    """
    raw = (scientific_name or "").strip()
    if not raw or _SEPARATORS.search(raw):
        return None
    # A bare route word is not a drug. Without this, "موضعي" — the word
    # "topical" on its own — matched the topical clotrimazole.
    if _is_route(raw) or _is_form(raw):
        return None
    for key in variants(raw):
        found = table.get(key)
        if found is not None:
            return found
    return None


def route_agrees(product_route, generic_routes):
    """Whether a box's route is one the reference dosed the ingredient by.

    Measured on the bundled register: **98 products** were taking a dose from
    an ingredient given another way — 20 topical gentamicin drops carrying the
    intravenous mg/kg, 12 domperidone suppositories carrying the oral dose, 11
    vaginal clindamycin, 9 rectal ibuprofen. A milligrams-per-kilo written for
    a vein does not describe an eye drop, and the number looks just as
    confident either way.

    An unknown route on either side is not a disagreement — most of the
    catalogue says nothing about route, and refusing those would throw away
    the coverage this module was built for. Only a **stated** conflict blocks.
    """
    product = (product_route or "").strip().lower()
    known = (generic_routes or "").strip().lower()
    if not product or not known:
        return True
    return product in known
