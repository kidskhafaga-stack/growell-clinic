"""The Egyptian register is a pharmacy's list. This clinic sees children.

Measured: 2,945 products across 145 label spellings — 12% of the catalogue —
that a paediatrician never prescribes. Hair care alone is 928, larger than the
whole antibiotic shelf, and every one of them sits between the doctor and the
drug they are looking for.

**The register file is not edited.** These are skipped at seed time, so the
bundled data stays exactly as the authority published it and the decision is
one reviewable list in one file rather than a deletion nobody can audit.

**Two things this file exists to hold still.**

*The exceptions.* Head lice is a schoolyard illness treated with a shampoo;
saline nasal wash is filed under a label containing "VAGINAL"; a multivitamin
sold for hair and nails is still a multivitamin. A sweep for cosmetics takes
all three unless it is told not to.

*The order.* Cosmetic is checked **before** the class rules, not after —
several of these already matched a clinical shelf by accident. 130
skin-whitening creams were sitting under "Topical preparations" because the
label began "SKIN CARE", and an anti-wrinkle eye cream had landed under "Eye &
ear drops".
"""
import gzip
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

DATA = os.path.join(os.path.dirname(__file__), "..", "app", "data",
                    "egypt_drugs.json.gz")


def _register():
    with gzip.open(DATA, "rt", encoding="utf-8") as fh:
        return json.load(fh)


# --- what goes ------------------------------------------------------------

@pytest.mark.parametrize("label", [
    "HAIR CARE", "MASSAGE CREAM", "SUN BLOCK", "SEXUAL TONIC", "WEIGHT LOSS",
    "VAGINAL CARE", "SWEETENER", "SCAR THERAPY", "DEODORANT", "NAIL CARE",
    "ANTI-DANDRUFF SHAMPOO", "WHITENING CREAM", "ANTI-AGING SERUM",
])
def test_the_retail_shelf_is_not_a_paediatric_one(label):
    from app.utils.drug_classing import is_cosmetic

    assert is_cosmetic(label) is True, f"{label} is still seeded"


def test_a_whitening_cream_does_not_hide_on_the_topical_shelf():
    """The reason cosmetic is checked before the class rules.

    "SKIN CARE.WHITENING" matched the topical rule on the word "SKIN CARE",
    so 130 skin-lightening creams were sitting on a clinical shelf. Checking
    afterwards would have left every one of them there.
    """
    from app.utils.drug_classing import is_cosmetic, map_label

    assert map_label("SKIN CARE.WHITENING") is not None, (
        "the premise has changed — this used to match a clinical shelf")
    assert is_cosmetic("SKIN CARE.WHITENING") is True


# --- what stays -----------------------------------------------------------

@pytest.mark.parametrize("label", [
    "ANTI-LICE SHAMPOO",                    # a schoolyard illness
    "NASAL/VAGINAL WASH",                   # saline, for a blocked nose
    "ANTISEPTIC SHAMPOO",
    "MULTIVITAMIN FOR SKIN  HAIR AND NAILS",
])
def test_the_clinical_ones_the_sweep_would_have_taken(label):
    """Each of these matches the cosmetic pattern and is still a medicine."""
    from app.utils.drug_classing import is_cosmetic

    assert is_cosmetic(label) is False, f"{label} was swept out"


@pytest.mark.parametrize("label", [
    "ANTIBIOTIC", "COLD PRODUCTS", "ORAL CARE", "DIAPER RASH",
    "ANTIPYRETIC", "MILK PRODUCTS", "VITAMIN",
])
def test_nothing_a_clinic_prescribes_is_caught(label):
    from app.utils.drug_classing import is_cosmetic

    assert is_cosmetic(label) is False


# --- end to end -----------------------------------------------------------

def test_the_catalogue_actually_shrinks(clinic):
    """The number, through the real seed rather than the pattern alone."""
    with clinic["app"].app_context():
        from app.models import Drug
        from app.utils.drugbook_seed import seed_drugbook
        from app.utils.egypt_drugs import seed_register

        seed_drugbook()
        seed_register()

        total = Drug.query.count()
        assert 21500 < total < 23000, (
            f"{total} products seeded; about 22,100 was expected after the "
            "cosmetics came out of 25,065")


def test_not_one_hair_care_product_reaches_the_doctor(clinic):
    """The biggest block, checked in the database rather than in the regex."""
    with clinic["app"].app_context():
        from app.models import Drug
        from app.utils.drugbook_seed import seed_drugbook
        from app.utils.egypt_drugs import seed_register

        seed_drugbook()
        seed_register()
        assert Drug.query.filter(Drug.drug_class.ilike("%HAIR CARE%")).count() == 0


def test_the_shipped_register_is_left_exactly_as_published(clinic):
    """Skipped at seed time, never deleted from the file.

    A clinic attached to a pharmacy can be given these back by changing one
    list; a file with the rows cut out of it cannot give anything back, and
    nobody could review what was removed.
    """
    rows = _register()
    assert len(rows) > 25000, "the bundled register has been edited"
    hair = [r for r in rows if "HAIR CARE" in (r[6] or "").upper()]
    assert len(hair) > 900, "hair care was removed from the data file itself"
