"""One ingredient, spelled the way whoever typed it spells it.

A brand in the catalogue gets its paediatric dosing by matching its scientific
name against the curated reference. The match was exact, so
``PARACETAMOL(ACETAMINOPHEN)`` — 92 products in the Egyptian register — did
not match ``Paracetamol``, and 92 boxes of the commonest drug in paediatrics
arrived with no dose calculator behind them. ``CHOLECALCIFEROL(VITAMIN D3)``
is another 116. ``ACYCLOVIR`` and ``CEFALEXIN`` are the US and British
spellings of drugs the reference already holds under the other one.

Measured across the whole register, spelling accounts for **344 brands** that
can be dosed from clinical data already written and already referenced. That
is the cheapest and safest coverage there is: no new numbers, no new
judgement, just recognising a name.

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
# Words that make a bracket a route rather than a synonym.
_ROUTE_WORDS = {
    "TOPICAL", "OTIC", "EAR", "EYE", "OPHTHALMIC", "NASAL", "INHALED",
    "INHALATION", "ORAL", "RECTAL", "VAGINAL", "IV", "IM", "INJECTION",
    "SUBLINGUAL", "TRANSDERMAL", "BUCCAL",
}


def _is_route(text):
    """Whether a bracket's contents name a route of administration."""
    words = {w.strip(" .") for w in (text or "").upper().split()}
    return bool(words & _ROUTE_WORDS)


_SWAPS = [
    ("ACYCLO", "ACICLO"),        # Acyclovir / Aciclovir
    ("SULPH", "SULF"),           # sulphate / sulfate
    ("CEPHA", "CEFA"),           # Cephalexin / Cefalexin
    ("CEPHR", "CEFR"),
    ("OESTR", "ESTR"),
    ("AMPICILLIN", "AMPICILIN"),
    ("Æ", "AE"),
]


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
    if not any(_is_route(part) for part in inner):
        outside = " ".join(re.sub(r"\([^)]*\)", " ", raw).split())
        inside = " ".join(" ".join(inner).split())
        for part in (outside, inside):
            if part:
                out.append(part)

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
    if not raw or "+" in raw:
        return None
    for key in variants(raw):
        found = table.get(key)
        if found is not None:
            return found
    return None
