"""The laboratory's sections — a fixed list, like a medicine's family.

Asked as *«ونصنفها كده زي الأدوية؟»*. A test's ``category`` stays what it
has always been: the clinic's own words for the doctor, free text. The
section is the bench a test belongs to, from one list every hospital shares,
so a report, a filter or a worklist can say «chemistry» and mean the same
thing everywhere.

**A section is suggested, then a person sorts.** The suggestion comes from
what the program can tell without guessing:

* a test whose make-up is known (`utils/lab_parts`) carries its section;
* a culture is microbiology; a blood group or a cross-match the blood bank;
  a PCR molecular — read from the name;
* the clinic's own category, where one word says it plainly («تجلط» is
  coagulation, «فيتامينات» vitamins). A category that does not say it —
  «التهابات» holds a CRP (chemistry) and an ESR (haematology) — suggests
  nothing.

Nothing is written until the sorting screen is saved.
"""
import re

#: In display order. ``(key, Arabic, English)``.
SECTIONS = (
    ("hematology", "أمراض الدم", "Haematology"),
    ("coagulation", "التجلط", "Coagulation"),
    ("chemistry", "الكيمياء الحيوية", "Clinical chemistry"),
    ("hormones", "الهرمونات والغدد", "Hormones & endocrinology"),
    ("vitamins", "الفيتامينات والمعادن", "Vitamins & minerals"),
    ("immunology", "المناعة والأمصال", "Immunology & serology"),
    ("urine_stool", "البول والبراز", "Urine & stool"),
    ("microbiology", "الميكروبيولوجي", "Microbiology"),
    ("blood_bank", "بنك الدم", "Blood bank"),
    ("molecular", "البيولوجيا الجزيئية", "Molecular"),
    ("other", "أخرى", "Other"),
)
KEYS = tuple(k for k, _, _ in SECTIONS)
_NAMES = {k: (ar, en) for k, ar, en in SECTIONS}

#: A clinic category that names one section plainly. Compared after
#: ``lab_import.key``.
_CATEGORY = {
    "امراض الدم": "hematology", "دم": "hematology", "hematology": "hematology",
    "haematology": "hematology",
    "تجلط": "coagulation", "coagulation": "coagulation",
    "غدد": "hormones", "هرمونات": "hormones", "hormones": "hormones",
    "endocrinology": "hormones",
    "فيتامينات": "vitamins", "vitamins": "vitamins",
    "مناعه": "immunology", "امصال": "immunology", "immunology": "immunology",
    "serology": "immunology",
    "ميكروبيولوجي": "microbiology", "مزارع": "microbiology",
    "microbiology": "microbiology",
    "كيمياء": "chemistry", "chemistry": "chemistry", "biochemistry": "chemistry",
    "بنك الدم": "blood_bank", "blood bank": "blood_bank",
}
#: Words in a test's name that settle its section.
_NAME_RULES = (
    (r"\b(culture|c ?& ?s)\b|مزرع", "microbiology"),
    (r"\b(blood group|abo|rh typing|cross ?match|coombs)\b|فصيل|توافق", "blood_bank"),
    (r"\bpcr\b|\bgenexpert\b", "molecular"),
)


def name(key, lang="ar"):
    pair = _NAMES.get(key)
    if not pair:
        return ""
    return pair[1] if lang == "en" else pair[0]


def choices(lang="ar"):
    return [(k, name(k, lang)) for k in KEYS]


def clean(value):
    value = (value or "").strip()
    return value if value in KEYS else None


def suggest(test):
    """The section the program can tell, or ``None``."""
    from app.utils import lab_parts
    from app.utils.lab_import import key

    if getattr(test, "kind", "lab") != "lab":
        return None
    if getattr(test, "is_culture", None):
        return "microbiology"
    panel = lab_parts.panel_for(test)
    if panel and panel.get("section"):
        return panel["section"]
    text = " ".join(filter(None, [test.name_en, test.name_ar])).lower()
    for pattern, section in _NAME_RULES:
        if re.search(pattern, text):
            return section
    return _CATEGORY.get(key(test.category or ""))


def from_sheet(text):
    """A section as a sheet writes it — its key, or either of its names."""
    from app.utils.lab_import import key

    wanted = key(text or "")
    if not wanted:
        return None
    for k, ar, en in SECTIONS:
        if wanted in (key(k), key(ar), key(en)):
            return k
    return _CATEGORY.get(wanted)


__all__ = ["KEYS", "SECTIONS", "choices", "clean", "from_sheet", "name", "suggest"]
