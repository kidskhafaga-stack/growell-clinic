"""The two lists a child's file is filled in from: allergies and long illnesses.

Asked for as a convenience — *"نحط الحساسية المشهورة عند الأطفال يقدر يدوس
عليها والأمراض المزمنة برده"* — and it is one. But for allergies it is more
than that, and the difference decides how this file is written.

**An allergy chip is not a shortcut. It is what makes the safety check fire.**

``app/utils/allergy.py`` already compares every medicine as it is written
against what the file records, three ways: the ingredient, the brand, and the
**drug family** — so a child recorded as allergic to penicillin is caught when
amoxicillin is prescribed, and a cephalosporin raises a caution rather than a
claim. That matcher normalises hard, because parents say "بنسلين" and
"حساسية من البنسلين" and "Augmentin". It is good; it is not a mind reader.

A mother says *"حساسيه من البنسلن"*. A chip says exactly what the matcher
knows. So the drug chips are **generated from the families themselves** rather
than typed into a list here: a chip whose words the matcher does not recognise
would be worse than free text, because it looks like the allergy was recorded
properly and then no prescription is ever checked against it.

**The rest are foods and the environment, and they are honestly different.**
Nobody prescribes egg. Those chips are only ever a spelling everybody shares,
which still matters — a file that says "لبن بقري" in one place and "حساسية
ألبان" in another cannot be searched, counted or handed to a locum.

**And one long illness is really a drug rule wearing a diagnosis.** أنيميا الفول
— G6PD — is on the list because in Egypt it is common and it is a
contraindication list, not a label. Recording it as a coded phrase is what
makes it possible to act on later; recording it as prose is a note on a screen.

Stored as text, one per line, in the same ``code|ar|en`` shape the visit
phrases use, and parsed by the same module — so a clinic that edits one of
these learns nothing new to edit the other.
"""
from app.models import Setting
from app.utils import phrases

FIELDS = ("allergy", "chronic")


def key_for(field):
    """The Setting key holding this list."""
    return f"patient_{field}_chips"


# Foods, environment and materials — everything an allergy can be that is not
# a medicine. No drug names here on purpose: those come from the matcher.
NON_DRUG_ALLERGIES = [
    ("بروتين لبن البقر", "Cow's milk protein"),
    ("البيض", "Egg"),
    ("الفول السوداني", "Peanut"),
    ("المكسرات", "Tree nuts"),
    ("السمك والمأكولات البحرية", "Fish and seafood"),
    ("القمح / الجلوتين", "Wheat / gluten"),
    ("الصويا", "Soy"),
    ("الفراولة", "Strawberry"),
    ("لدغ الحشرات", "Insect stings"),
    ("اللاتكس", "Latex"),
    ("عث المنزل", "House dust mite"),
    ("حبوب اللقاح", "Pollen"),
    ("وبر الحيوانات", "Animal dander"),
]

# The long illnesses a paediatric clinic actually writes down.
CHRONIC = [
    ("الربو", "Asthma"),
    ("حساسية الصدر", "Reactive airway disease"),
    ("حساسية الأنف", "Allergic rhinitis"),
    ("الأكزيما", "Atopic dermatitis"),
    # In Egypt this is common and it is a *contraindication list*, not a
    # label: fava beans and a named set of drugs. Coded here so the program
    # can act on it later; as prose it is a note nobody can act on.
    ("أنيميا الفول (نقص G6PD)", "G6PD deficiency"),
    ("أنيميا البحر المتوسط", "Thalassaemia"),
    ("أنيميا الخلايا المنجلية", "Sickle cell disease"),
    ("أنيميا نقص الحديد", "Iron deficiency anaemia"),
    ("السكري النوع الأول", "Type 1 diabetes"),
    ("قصور الغدة الدرقية", "Hypothyroidism"),
    ("الصرع", "Epilepsy"),
    ("الشلل الدماغي", "Cerebral palsy"),
    ("عيب خلقي بالقلب", "Congenital heart disease"),
    ("الارتجاع البولي", "Vesicoureteric reflux"),
    ("قصور كلوي مزمن", "Chronic kidney disease"),
    ("التليف الكيسي", "Cystic fibrosis"),
    ("اضطراب طيف التوحد", "Autism spectrum disorder"),
    ("فرط الحركة وتشتت الانتباه", "ADHD"),
]


def drug_allergy_chips():
    """One chip per drug family, in the family's own words.

    Read from :data:`app.utils.allergy.FAMILIES` rather than repeated here.
    The whole value of an allergy chip is that the matcher recognises what it
    writes, and two lists that have to agree eventually do not.
    """
    from app.utils.allergy import FAMILIES

    return [(spec["chip_ar"], spec.get("chip_en", ""))
            for spec in FAMILIES.values() if spec.get("chip_ar")]


# What a clinic owns and may rewrite. The drug chips are deliberately not in
# here — see :func:`editable`.
EDITABLE_DEFAULTS = {
    "allergy": NON_DRUG_ALLERGIES,
    "chronic": CHRONIC,
}


def editable(field):
    """The half of a list the clinic may rewrite, as ``[{code, ar, en}]``.

    **The drug chips are not in it, and that is the point.** A settings editor
    saves back whatever it was shown, so an editor that displayed them would
    freeze a copy into a ``Setting`` the first time anybody pressed save — and
    from then on the screen's chips and the matcher's families would be two
    lists that have to agree. They would not for long: a new family added by an
    update would never reach that clinic's form, and a clinic that tidied
    "بنسلين" into "بنسلين ج" would have built exactly the thing this module
    exists to prevent — a chip that looks like it recorded an allergy and
    writes words no prescription is ever checked against.

    Foods and long illnesses have no such tie. Nothing is matched against them,
    so the clinic's own list is simply better than ours.

    A name this module does not know has no defaults, so it answers with
    nothing without needing a guard of its own — :func:`save` refuses to store
    one, so the key cannot exist either.
    """
    return phrases.parse(Setting.get(key_for(field)),
                         EDITABLE_DEFAULTS.get(field, ()))


def chips(field):
    """``[{code, ar, en}]`` — everything the patient form offers for a field.

    The clinic's own list, plus, for allergies, the drug chips derived from the
    matcher. Same shape and same parser as the visit phrases, so a clinic that
    has edited one of those has nothing new to learn here.
    """
    rows = editable(field)
    if field == "allergy":
        # `checked` is what the screen draws differently. A peanut chip and a
        # penicillin chip are not the same kind of button — one is a shared
        # spelling, the other is what makes a prescription warning fire — and
        # drawing them identically hides the difference that matters.
        derived = [{"code": "", "ar": ar, "en": en, "checked": True}
                   for ar, en in drug_allergy_chips()]
        # Medicines first: they are the ones a prescription is checked against,
        # and the ones somebody is looking for when a child reacted to a drug.
        return derived + rows
    return rows


def save(field, rows):
    """Store an edited list. Blank puts the defaults back.

    Writes the clinic's half only — :func:`chips` adds the derived drug chips
    back on the way out, so a clinic cannot save its way out of having them.

    The guard is the one that matters: without it a typo in a caller would
    write a ``Setting`` no screen ever reads, and the clinic's edit would
    vanish into a key nobody looks at.
    """
    if field not in FIELDS:
        return
    Setting.set(key_for(field), phrases.serialise(rows))
