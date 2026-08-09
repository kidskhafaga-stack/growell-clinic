"""Putting the Egyptian register's 2,497 labels into the clinic's 14 shelves.

The drug reference screen was already right: fourteen classes, named in both
languages, ordered the way a paediatrician thinks, each with a count. The
catalogue of 25,065 trade names had nothing — and the first attempt at fixing
that simply exposed the register's own class field as a dropdown, which is how
a clean screen ended up offering "5-HT3 ANTAGONIST.ANTI-EMETIC" next to
"HAIR CARE" in a list 683 entries long. The register's labels are a supplier's
inventory categories, not a clinic's.

So the register is mapped onto the shelves the clinic already has.

**It maps about half, and the half it does not map is the point.** 12,506 of
the 25,065 land in a class. What is left over is, overwhelmingly, not
paediatric: hair care (928), oncology (410), massage cream, sun block,
statins, antipsychotics. A children's clinic has no shelf for those and should
not grow one to make a percentage look better — they stay in the catalogue,
stay searchable by name, and simply sit under no category.

**Matched on the register's words, not on drug names.** Each rule looks for
the vocabulary the register itself uses for a therapeutic group
("CEPHALOSPORIN", "MUCOLYTIC", "ANTHELMINTIC"). Nothing here reads a trade
name or an ingredient to guess at what a drug does — that is what the curated
reference is for, and a guess there would attach a dosing rule to the wrong
medicine.
"""
import re

# (class name_en, pattern over the register's own class label).
#
# Order matters where two could match: a "STEROID.TOPICAL" is reached by the
# corticosteroid rule first because that is the more clinically specific fact
# about it. Everything is matched against the label upper-cased.
RULES = [
    ("Antibiotics",
     r"ANTIBIOTIC|CEPHALOSPORIN|PENICILLIN|QUINOLONE|MACROLIDE"
     r"|AMINOGLYCOSID|SULFONAMIDE|TETRACYCLIN|CARBAPENEM"),
    ("Antifungals", r"ANTIFUNGAL|ANTI-FUNGAL|\bFUNGAL\b"),
    ("Antivirals", r"ANTIVIRAL|ANTI-VIRAL"),
    ("Antiparasitics",
     r"ANTHELMINTIC|ANTI-HELMINTIC|ANTIPARASIT|ANTI-PARASIT"
     r"|SCABIES|AMOEB|ANTIMALARIAL"
     # Metronidazole for giardia is an everyday paediatric prescription here,
     # and the register calls it ANTIPROTOZOAL.
     r"|SCABICIDE|ANTIPROTOZOAL|\bLICE\b|PEDICULOSIS"),
    ("Antihistamines & allergy", r"ANTI-?HISTAMINE|ANTI-?ALLERG"),
    ("Respiratory",
     r"MUCOLYTIC|EXPECTORANT|BRONCHODILATOR|ANTITUSSIVE|ANTI-?ASTHMA"
     r"|\bASTHMA\b|DECONGESTANT|COLD PRODUCT"
     # A children's clinic runs on cough syrup and saline nose drops, and the
     # register files them under words the first pass did not know.
     r"|COUGH|NASAL|SORE THROAT"),
    ("Corticosteroids", r"CORTICOSTEROID|\bSTEROID\b|GLUCOCORTICOID"),
    ("Antipyretics & analgesics",
     r"ANALGESIC|ANTIPYRETIC|\bNSAID\b|ANTI-?INFLAMMATORY|\bPAIN\b"),
    ("Gastrointestinal",
     r"PEPTIC ULCER|ANTACID|LAXATIVE|ANTI-?EMETIC|ANTI-?SPASMODIC"
     r"|PROTON PUMP|PROKINETIC|\bGIT\b|CONSTIPATION|FLATULENCE"),
    ("Rehydration & diarrhoea", r"DIARRH|REHYDRAT|PROBIOTIC|\bORS\b"),
    ("Vitamins & minerals",
     r"VITAMIN|MINERAL|IRON SUPPLEMENT|CALCIUM SUPPLEMENT|ZINC"
     r"|FOLIC|SUPPLEMENT|OMEGA 3|IMMUNITY BOOSTER|APPETITE"),
    ("Eye & ear drops", r"OPHTHALM|\bEYE\b|\bOTIC\b|\bEAR\b"),
    ("Neurology & anticonvulsants",
     r"ANTICONVULS|ANTI-?EPILEPTIC|\bEPILEP\b|NEUROLOG"),
    ("Topical preparations",
     r"TOPICAL|SKIN CARE|DERMATOLOG|EMOLLIENT|\bACNE\b"
     # Nappy cream, baby care and the antiseptics a clinic dresses a graze
     # with. "DIAPER RASH" is 52 products and about as paediatric as the
     # register gets; it was going nowhere.
     r"|DIAPER|NAPPY|BABY CARE|ANTISEPTIC"),
    # Milk, on its own shelf rather than forced onto somebody else's.
    ("Infant formula",
     r"MILK PRODUCT|INFANT FORMULA|FOLLOW UP FORMULA|GROWING FORMULA"
     r"|HYPO-?ALLERGENIC MILK|LACTOSE FREE MILK|EXTRA CARE MILK|SOY MILK"),
]

_COMPILED = [(name, re.compile(pattern)) for name, pattern in RULES]


def map_label(raw):
    """The clinic's class for one of the register's labels, or ``None``.

    ``None`` is a real answer and the common one for adult and cosmetic
    products. It means "this belongs on no shelf here", not "look harder".
    """
    if not raw:
        return None
    label = raw.upper()
    for name, pattern in _COMPILED:
        if pattern.search(label):
            return name
    return None


def class_index():
    """The clinic's classes by English name, for looking a mapping up.

    Empty when the reference has never been seeded, which is a state the
    caller has to cope with rather than crash on: the trade-name catalogue is
    usable without the curated reference behind it.
    """
    from app.models import DrugClass

    return {(c.name_en or "").strip(): c
            for c in DrugClass.query.all() if c.name_en}


def class_id_for(raw, index=None):
    """The clinic's class *id* for a register label, or ``None``."""
    name = map_label(raw)
    if not name:
        return None
    index = class_index() if index is None else index
    found = index.get(name)
    return found.id if found else None


def backfill(batch=2000):
    """Classify the trade names a clinic already has.

    A clinic that seeded its catalogue before this existed has 25,000 drugs
    with a raw register label and no class. Re-seeding would not help — the
    seeder skips names already present, deliberately, so it never overwrites a
    clinic's own edits. So the mapping is applied in place.

    Only rows that have no class yet are touched. Somebody who filed a drug
    under a class by hand outranks a regular expression.
    """
    from app.extensions import db
    from app.models import Drug

    index = class_index()
    if not index:
        return 0
    rows = (Drug.query
            .filter(Drug.class_id.is_(None), Drug.drug_class.isnot(None))
            .all())
    changed = 0
    for drug in rows:
        found = class_id_for(drug.drug_class, index)
        if found:
            drug.class_id = found
            changed += 1
            if changed % batch == 0:
                db.session.commit()
    db.session.commit()
    return changed
