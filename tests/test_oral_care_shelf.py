"""190 oral-care products with no shelf — and 28 of them worth finding.

The register files 190 products under ``ORAL CARE`` and this program filed them
nowhere: no class, no shelf, invisible to anyone browsing the reference.

**No trade-name research was needed, and that is a finding rather than a
shortcut.** The obvious way to classify them is to look each name up. It turned
out the register answers itself: of the 35 that list no active ingredient — the
ones a lookup would have been *for* — 33 name their own form in the trade name
(MOUTH WASH, ORAL GEL, ORAL SPRAY, TOOTHPASTE) and the other two are settled by
the route column sitting beside it. Both facts are already in the file, and
both are better evidence than a search result for a brand name.

**Why a children's clinic needs the shelf at all.** Not tidiness: 28 of the 190
contain a local anaesthetic or a salicylate, and several are sold as teething
gels — DENTINOX, KAMISTAD, MUNDISAL, PANSORAL are all on Egyptian shelves.
Choline salicylate is restricted to 16+ in the UK over Reye's syndrome;
benzocaine teething gels were pulled for under-2s in the US over
methaemoglobinaemia. Neither ingredient had an entry in this reference.

**And one honest limit is asserted here too.** The new entries do *not* attach
to those products, because almost all of them are combinations and the
combination guard refuses to hang a single ingredient's dose on a mixture.
A doctor can look the ingredient up; the warning does not fire by itself. That
is written down as a test so nobody reads the shelf and assumes otherwise.
"""
import gzip
import json
import os
import re
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

DATA = os.path.join(os.path.dirname(__file__), "..", "app", "data",
                    "egypt_drugs.json.gz")

# What a product is, in its own name.
SAYS_WHAT_IT_IS = re.compile(
    r"MOUTH ?WASH|MOUTHWASH|MOUTH SOLN|ORAL GEL|ORAL SPRAY|MOUTH SPRAY"
    r"|TOOTH ?PASTE|ORAL SOLN|ORAL SOLUTION|ORAL OINT|GARGLE|PAINT|DENT")

# …and where the name alone does not, the register's own route column does.
ORAL_ROUTES = {"MOUTH", "SPRAY", "TOPICAL", "ORAL.LIQUID"}


def _register():
    with gzip.open(DATA, "rt", encoding="utf-8") as fh:
        return json.load(fh)


def _oral_care():
    return [r for r in _register() if (r[6] or "").upper() == "ORAL CARE"]


# --- the classification ----------------------------------------------------

def test_the_register_says_what_each_one_is_without_being_asked():
    """The reason no trade name had to be looked up anywhere.

    Of the 35 with **no listed ingredient** — the ones a lookup would have
    been for — 33 name their own form and the last two are settled by the
    route column. If that ever stops being true the shortcut stops being safe,
    and this test is where it shows.
    """
    nameless = [r for r in _oral_care() if not (r[2] or "").strip()]
    assert len(nameless) >= 30, "the sample this rests on has changed"

    by_name = [r for r in nameless if SAYS_WHAT_IT_IS.search(r[0].upper())]
    assert len(by_name) >= 33, (
        f"only {len(by_name)} of {len(nameless)} name their own form")

    # The remainder are settled by the route column, still without leaving the
    # file. Written this way because the first version claimed *all* of them
    # named their form and two did not — the claim was rounded up before it
    # was checked.
    unclear = [r[0] for r in nameless
               if r not in by_name and (r[4] or "").upper() not in ORAL_ROUTES]
    assert unclear == [], f"these say nothing, so guessing starts: {unclear}"


def test_oral_care_maps_to_the_new_shelf():
    from app.utils.drug_classing import map_label

    for label in ("ORAL CARE", "MOUTH WASH", "TOOTHPASTE", "DENTAL CARE"):
        assert map_label(label) == "Oral & dental care", label


def test_the_shelf_exists_and_the_products_land_on_it(clinic):
    """End to end through the real seed."""
    with clinic["app"].app_context():
        from app.models import Drug, DrugClass
        from app.utils.drugbook_seed import seed_drugbook
        from app.utils.egypt_drugs import seed_register

        seed_drugbook()
        seed_register()

        shelf = DrugClass.query.filter_by(code="ORAL").first()
        assert shelf is not None, "no oral & dental shelf was created"
        assert shelf.name_ar == "العناية بالفم والأسنان"

        on_shelf = Drug.query.filter_by(class_id=shelf.id).count()
        assert on_shelf >= 190, (
            f"only {on_shelf} products reached the shelf; the register has 190 "
            "under ORAL CARE alone")


# --- the 28 that made it worth doing ---------------------------------------

def test_the_hazardous_ones_are_a_real_share_not_a_rounding_error():
    """The number that justifies the shelf in a paediatric clinic.

    If this drops to a handful the argument changes, and somebody should know.
    """
    risky = re.compile(r"LIDOCAINE|LIGNOCAINE|BENZOCAINE|SALICYLATE")
    hits = [r for r in _oral_care() if risky.search((r[2] or "").upper())]
    assert len(hits) >= 25, (
        f"only {len(hits)} oral-care products carry an anaesthetic or a "
        "salicylate")


@pytest.mark.parametrize("name,must_say,reference", [
    ("Choline salicylate (oral gel)", "راي", "MHRA"),
    ("Benzocaine (oral gel)", "ميتهيموجلوبين", "FDA"),
])
def test_each_new_entry_carries_its_hazard_and_its_source(name, must_say,
                                                          reference):
    """A warning nobody can check is a warning nobody should act on."""
    from app.utils.drugbook_seed import GENERICS

    entry = next((g for g in GENERICS if g["name_en"] == name), None)
    assert entry is not None, f"{name} is not in the reference"
    text = (entry.get("black_box") or "") + (entry.get("contraindications") or "")
    assert must_say in text
    assert reference in (entry.get("ref") or "")


def test_the_age_limits_are_the_ones_the_regulators_set(clinic):
    """Not "use with care in children" — the actual numbers.

    16 for choline salicylate (MHRA), 2 for benzocaine (FDA). A vague warning
    is one a busy clinic rounds down to nothing.
    """
    with clinic["app"].app_context():
        from app.models import GenericDrug
        from app.utils.drugbook_seed import seed_drugbook

        seed_drugbook()
        choline = GenericDrug.query.filter_by(
            name_en="Choline salicylate (oral gel)").first()
        benzo = GenericDrug.query.filter_by(
            name_en="Benzocaine (oral gel)").first()

        assert "١٦" in (choline.black_box or "") + (choline.contraindications or "")
        assert "سنتين" in (benzo.black_box or "") + (benzo.contraindications or "")


def test_the_warning_does_not_fire_by_itself_and_that_is_written_down(clinic):
    """The honest limit, and where it now stops.

    Almost every one of these products is a combination — chlorhexidine plus
    lidocaine plus clove oil — and the combination guard refuses to hang one
    ingredient's dose on a mixture. **Nothing the register imports attaches by
    itself**, and asserting that keeps somebody from reading the shelf and
    assuming a doctor gets warned automatically.

    What changed is the other half. The shelf used to link *nothing at all*,
    which meant a teething gel with a salicylate in it carried the warning
    nowhere. A handful of these are now named by hand in the seed — Mundisal,
    Pansoral, Dentocaine — and those do attach, because a person read the box
    and wrote which ingredient the warning belongs to. Guessing that over
    25,000 imported rows and writing it three times are not the same act, and
    the difference is exactly what this test holds apart.
    """
    with clinic["app"].app_context():
        from app.models import Drug, GenericDrug
        from app.utils.drugbook_seed import seed_drugbook
        from app.utils.egypt_drugs import seed_register

        seed_drugbook()
        seed_register()
        for name in ("Choline salicylate (oral gel)", "Benzocaine (oral gel)"):
            generic = GenericDrug.query.filter_by(name_en=name).first()
            assert generic is not None
            linked = Drug.query.filter_by(generic_id=generic.id).all()
            assert linked, f"{name} carries the warning and reaches nothing"
            # Every imported row carries the register's Arabic name; the ones
            # written into the seed by hand do not. So this is "did the import
            # guess?", not "how many rows are there".
            guessed = [d.trade_name for d in linked if d.trade_name_ar]
            assert guessed == [], (
                f"{name} picked up {guessed} from the register — if the "
                "combination guard has changed, this limit is worth "
                "re-reading rather than the number being edited")
