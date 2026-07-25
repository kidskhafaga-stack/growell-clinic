"""Checking a written medicine against what the child is allergic to.

The clinic already records allergies — free text on the patient's file, shown
in a red banner on every clinical screen. What was missing is the only moment
that matters: **when the drug is being written**, nothing compared the two.

This matches a written line against the recorded allergies three ways, in
descending order of certainty:

1. the **active ingredient** itself ("أموكسيسيللين" written, "أموكسيسيللين"
   recorded) — a definite match;
2. the **brand name** ("Augmentin" recorded as the allergy);
3. the **drug family** — a child allergic to penicillin must not be handed a
   different penicillin, and a cephalosporin deserves a caution rather than a
   block (cross-reactivity is real but partial).

Free text is messy on purpose: parents say "بنسلين", "حساسية من البنسلين",
"Augmentin". So matching is done on normalised words, and it errs toward
warning. It never blocks a prescription — the doctor decides.
"""
import re
import unicodedata

# Families whose members cross-react. ``sure`` = same family (treat as a real
# allergy), ``caution`` = related family (flag, don't claim).
FAMILIES = {
    "penicillin": {
        "words": ["penicillin", "بنسلين", "بنسيلين", "amoxicillin", "أموكسيسيللين",
                  "اموكسيسيللين", "ampicillin", "أمبيسيللين", "flucloxacillin",
                  "augmentin", "clavulanate", "كلافولانيك"],
        "caution": "cephalosporin",
        "note_ar": "حساسية من عائلة البنسلين",
    },
    "cephalosporin": {
        "words": ["cephalosporin", "سيفالوسبورين", "cefixime", "سيفيكسيم",
                  "ceftriaxone", "سيفترياكسون", "cefuroxime", "سيفوروكسيم",
                  "cephalexin", "سيفاليكسين", "cefaclor", "سيفاكلور",
                  "cefadroxil", "سيفادروكسيل", "cefpodoxime", "سيفبودوكسيم"],
        "caution": "penicillin",
        "note_ar": "حساسية من عائلة السيفالوسبورين",
    },
    "macrolide": {
        "words": ["macrolide", "ماكروليد", "azithromycin", "أزيثروميسين",
                  "clarithromycin", "كلاريثروميسين", "erythromycin", "إريثروميسين"],
        "note_ar": "حساسية من عائلة الماكروليد",
    },
    "sulfa": {
        "words": ["sulfa", "سلفا", "سالفا", "co-trimoxazole", "cotrimoxazole",
                  "sulfamethoxazole", "trimethoprim", "septrin", "سبترين"],
        "note_ar": "حساسية من مركبات السلفا",
    },
    "nsaid": {
        "words": ["nsaid", "مضادات الالتهاب", "ibuprofen", "إيبوبروفين",
                  "ايبوبروفين", "diclofenac", "ديكلوفيناك", "aspirin", "أسبرين",
                  "mefenamic", "ميفيناميك"],
        "note_ar": "حساسية من مضادات الالتهاب غير الستيرويدية",
    },
    "paracetamol": {
        "words": ["paracetamol", "باراسيتامول", "acetaminophen", "بنادول", "cetal"],
        "note_ar": "حساسية من الباراسيتامول",
    },
}

_AR_DIACRITICS = re.compile(r"[ً-ْٰ]")


def normalise(text):
    """Lowercase, strip Arabic diacritics and unify alef/ya/ta-marbuta so
    "أموكسيسيللين" and "اموكسيسيلين" meet in the middle."""
    if not text:
        return ""
    out = unicodedata.normalize("NFKD", str(text))
    out = _AR_DIACRITICS.sub("", out)
    out = (out.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
              .replace("ى", "ي").replace("ة", "ه").replace("ـ", ""))
    out = " ".join(out.lower().split())
    # Transliterations double letters at random — "اموكسيسيلين" and
    # "أموكسيسيللين" are the same drug, and "penicilline" is "penicillin".
    # Collapsing runs on both sides makes them meet.
    return re.sub(r"(.)\1+", r"\1", out)


def recorded_allergies(patient):
    """The patient's allergies as normalised phrases (free text, split on the
    separators people actually type)."""
    raw = (getattr(patient, "allergies", "") or "") if patient is not None else ""
    parts = re.split(r"[,،;\n/|+]| و ", raw)
    return [normalise(p) for p in parts if normalise(p)]


def _families_of(text):
    """Which drug families a phrase names."""
    norm = normalise(text)
    hits = set()
    for family, spec in FAMILIES.items():
        for word in spec["words"]:
            if normalise(word) and normalise(word) in norm:
                hits.add(family)
                break
    return hits


def check_drug(patient, generic=None, drug=None, name=""):
    """Is this medicine a problem for this child?

    Returns ``None`` when nothing matches, else a dict with ``level``
    (``match`` = the drug itself / its family, ``caution`` = a cross-reacting
    family), the ``allergy`` phrase that triggered it and a ``reason``.
    """
    phrases = recorded_allergies(patient)
    if not phrases:
        return None

    # Everything this line is known by: ingredient (both languages) + brand.
    names = [name or ""]
    if generic is not None:
        names += [generic.name_ar or "", generic.name_en or ""]
    if drug is not None:
        names += [drug.trade_name or "", drug.generic_name or ""]
    names = [n for n in names if n and n.strip()]
    norm_names = [normalise(n) for n in names]

    drug_families = set()
    for n in names:
        drug_families |= _families_of(n)

    for phrase in phrases:
        # 1) the ingredient or the brand is named in the allergy itself
        for n in norm_names:
            if not n:
                continue
            if n in phrase or phrase in n:
                return {"level": "match", "allergy": phrase,
                        "reason": "same_drug", "family": None}
        # 2) same family
        allergy_families = _families_of(phrase)
        same = allergy_families & drug_families
        if same:
            family = sorted(same)[0]
            return {"level": "match", "allergy": phrase, "reason": "same_family",
                    "family": family}
        # 3) a family that cross-reacts with it
        for fam in allergy_families:
            cross = FAMILIES.get(fam, {}).get("caution")
            if cross and cross in drug_families:
                return {"level": "caution", "allergy": phrase,
                        "reason": "cross_family", "family": cross}
    return None
