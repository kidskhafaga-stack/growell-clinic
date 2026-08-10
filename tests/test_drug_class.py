"""The column the catalogue was dropping, and why it was worth going back for.

The clinic sent the Egyptian drug register again, saying some data was missing
from the bundled catalogue. They were right, and not in the way it first looked:
the file holds **the same 25,065 trade names** — zero new, zero lost. What it
holds that the bundled copy did not is ``drug_class``, the register's own
classification, present on 24,634 of them and dropped entirely when the
catalogue was first compressed.

So this was never "add more drugs". It was a column that had been thrown away,
which is why nobody could ask the catalogue for the antibiotics: 25,000 trade
names behind a single search box can only be searched, and a search only finds
what you already knew the name of.

**The field is not clean, and pretending otherwise would be the bug.** The
register writes a classification in that column most of the time and,
occasionally, a product description that ran into the wrong place — up to 300
characters of ingredient list. Length is what separates them: a classification
name is short, a description is not. Digits are *not*, which was checked —
"OMEGA 3" and "H2 ANTAGONIST" are real classes.

The cut costs 494 drugs out of 24,634 their class. They stay in the catalogue
and stay searchable; they merely do not appear under a category, which is the
honest outcome for a drug whose "class" was a paragraph.
"""
import gzip
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CATALOGUE = os.path.join(ROOT, "app", "data", "egypt_drugs.json.gz")


def _rows():
    with gzip.open(CATALOGUE, "rt", encoding="utf-8") as fh:
        return json.load(fh)


def test_the_bundled_catalogue_carries_the_class():
    """It ships with the program, so every install has it without a download.

    The clinic asked for exactly this: the catalogue present with any
    installation, not fetched later from somewhere that might be unreachable.
    """
    rows = _rows()
    assert len(rows) == 25065
    with_class = [r for r in rows if len(r) > 6 and r[6]]
    assert len(with_class) > 24000
    # The row is still positional, and the class is the seventh field.
    first = rows[0]
    assert first[0] == "1 2 3 (ONE TWO THREE) 20 F.C.TABS."
    assert first[6] == "COLD PRODUCTS"


def test_a_description_in_the_class_column_is_not_a_class():
    """The register occasionally puts a paragraph where a category belongs.

    Three hundred characters of ingredient list is not something to offer in a
    filter, and truncating it to fit the column would store a sentence
    fragment as though it named a category.
    """
    from app.utils.egypt_drugs import clean_class

    assert clean_class("ANTIBIOTICS") == "ANTIBIOTICS"
    assert clean_class("  COLD PRODUCTS  ") == "COLD PRODUCTS"
    assert clean_class("") is None
    assert clean_class(None) is None
    assert clean_class(
        "CHOCOLATE-FLAVORED CANDY FORTIFIED WITH IRON  ZINC  COPPER AND "
        "VITAMINS AND MORE WORDS THAT KEEP GOING") is None


def test_a_number_in_a_class_is_not_a_reason_to_drop_it():
    """Checked, because the obvious filter would have been wrong.

    Rejecting anything containing a digit was the first idea and would have
    thrown away 215 genuine classifications covering 1,270 drugs.
    """
    from app.utils.egypt_drugs import clean_class

    assert clean_class("OMEGA 3") == "OMEGA 3"
    assert clean_class("H2 ANTAGONIST") == "H2 ANTAGONIST"
    assert clean_class("LEUKOTRIENE D4 AND E4 ANTAGONIST") == \
        "LEUKOTRIENE D4 AND E4 ANTAGONIST"


def test_seeding_puts_the_class_on_the_drug(clinic):
    """End to end: the file holds it, so the register in the database does."""
    with clinic["app"].app_context():
        from app.models import Drug
        from app.utils.egypt_drugs import seed_register

        seed_register(limit=400)
        classed = Drug.query.filter(Drug.drug_class.isnot(None)).count()
        total = Drug.query.count()
        # ``limit`` caps the rows *read*, not the rows written: the cosmetic
        # ones inside that slice are skipped, so 400 in is fewer than 400 out.
        # Asserting exactly 400 was asserting the pre-cosmetics catalogue.
        assert 300 < total <= 400
        assert classed > total * 0.9
        one = Drug.query.filter_by(
            trade_name="1 2 3 (ONE TWO THREE) 20 F.C.TABS.").first()
        assert one.drug_class == "COLD PRODUCTS"


def test_an_older_data_file_does_not_break_the_upgrade(clinic):
    """A clinic upgrading the program before its data file catches up.

    The rows grew a seventh field. Unpacking by position count would meet a
    six-field row with a ValueError in the middle of a seed — so it is read
    defensively and simply yields no class.
    """
    with clinic["app"].app_context():
        from app.models import Drug
        from app.utils import egypt_drugs

        original = egypt_drugs._load
        egypt_drugs._load = lambda: [
            ["OLDFORMAT 500 MG", "قديم", "PARACETAMOL", "MAKER", "ORAL", 5.0],
        ]
        try:
            added = egypt_drugs.seed_register()
        finally:
            egypt_drugs._load = original
        assert added == 1
        row = Drug.query.filter_by(trade_name="OLDFORMAT 500 MG").first()
        assert row is not None
        assert row.drug_class is None


def test_the_column_is_in_the_additive_migration():
    """A new column on an existing table, so an installed clinic gets it.

    ``drugs`` is not a new table — every clinic already has one, full of their
    own edits. Without this line the upgrade brings a model that names a
    column the database does not have.
    """
    from app.utils.schema import ADDITIONS

    assert ("drugs", "drug_class", "VARCHAR(80)") in ADDITIONS


# --------------------------------------------- onto the clinic's shelves ----
# The register's labels are a supplier's inventory categories. The program
# already had better ones: the fourteen classes the drug reference is
# organised by, named in both languages and ordered the way a paediatrician
# thinks. The first version of the catalogue filter exposed the raw labels
# instead — a 683-entry dropdown with "5-HT3 ANTAGONIST.ANTI-EMETIC" beside
# "HAIR CARE" — which is what "the reference looked better" was pointing at.

def test_the_registers_words_map_onto_the_clinics_classes():
    """Matched on the register's own vocabulary for a therapeutic group."""
    from app.utils.drug_classing import map_label

    assert map_label("ANTIBIOTIC.CEPHALOSPORIN.THIRD-GENERATION") == "Antibiotics"
    assert map_label("ANTIBIOTIC.QUINOLONE") == "Antibiotics"
    assert map_label("MUCOLYTIC") == "Respiratory"
    assert map_label("ANTI-HISTAMINE.ANTI-ALLERGY") == "Antihistamines & allergy"
    assert map_label("IRON SUPPLEMENT") == "Vitamins & minerals"
    assert map_label("ANTHELMINTIC") == "Antiparasitics"


def test_the_words_a_childrens_clinic_runs_on():
    """A second pass, after reading what had been left behind.

    The first set of rules was written from the biggest labels and missed the
    everyday paediatric ones — a clinic runs on cough syrup, saline nose
    drops, nappy cream and metronidazole for giardia, and the register files
    those under words the first pass did not know. 1,051 more drugs found a
    shelf, and the shelves that gained most are the paediatric ones:
    respiratory 705 → 1,065, antiparasitics 74 → 177.
    """
    from app.utils.drug_classing import map_label

    assert map_label("COUGH PRODUCTS") == "Respiratory"
    assert map_label("ANTI-COUGH.NON-PRODUCTIVE") == "Respiratory"
    assert map_label("NASAL CONGESTION.ADRENERGIC ALPHA-AGONIST") == "Respiratory"
    assert map_label("DIAPER RASH") == "Topical preparations"
    assert map_label("BABY CARE") == "Topical preparations"
    assert map_label("ANTISEPTIC") == "Topical preparations"
    assert map_label("ANTIPROTOZOAL.NITROIMIDAZOLE") == "Antiparasitics"
    assert map_label("SCABICIDE") == "Antiparasitics"
    assert map_label("ORS") == "Rehydration & diarrhoea"
    assert map_label("OMEGA 3") == "Vitamins & minerals"


def test_infant_formula_gets_a_shelf_rather_than_somebody_elses():
    """147 products, the most paediatric group in the register, homeless.

    Milk is not a drug and does not belong under vitamins, and a clinic that
    recommends a formula looks for it where formula is. Forcing it onto an
    existing shelf would have been exactly the silent guess this module
    avoids everywhere else — so it got the fifteenth shelf.
    """
    from app.utils.drug_classing import map_label

    assert map_label("MILK PRODUCTS.FIRST STAGE (AGE 0-6 MONTHS)") == "Infant formula"
    assert map_label("HYPO-ALLERGENIC MILK") == "Infant formula"
    assert map_label("LACTOSE FREE MILK") == "Infant formula"
    assert map_label("MILK PRODUCTS.ANTI-REGURGITATION MILK") == "Infant formula"
    # …and not a formula that is only called one.
    assert map_label("MALE HEALTH FORMULA") is None


def test_the_milk_shelf_exists_to_be_filed_onto(clinic):
    """Mapping to a class name that no class has is mapping to nothing.

    Caught by deleting the ``DrugClass`` row and watching the string tests
    stay green: ``map_label`` still answered "Infant formula", ``class_id_for``
    found no such class, and every milk product silently went unfiled. The
    name and the shelf have to be checked together.
    """
    with clinic["app"].app_context():
        from app.models import Drug, DrugClass
        from app.utils.drug_classing import class_id_for
        from app.utils.drugbook_seed import seed_drugbook
        from app.utils.egypt_drugs import seed_register

        seed_drugbook()
        milk = DrugClass.query.filter_by(name_en="Infant formula").first()
        assert milk is not None, "there is no shelf for infant formula"
        assert milk.name_ar == "ألبان الأطفال"
        assert class_id_for("HYPO-ALLERGENIC MILK") == milk.id

        seed_register()
        assert Drug.query.filter_by(class_id=milk.id).count() > 100


def test_what_does_not_belong_in_a_childrens_clinic_stays_unshelved():
    """``None`` is a real answer, and it is the honest one here.

    Roughly half the register does not map, and the half that does not is
    hair care, oncology, massage cream, sun block, statins. A paediatric
    clinic has no shelf for those and should not grow one to make a
    percentage look better — they stay in the catalogue and stay searchable
    by name, under no category.
    """
    from app.utils.drug_classing import map_label

    assert map_label("HAIR CARE") is None
    assert map_label("MASSAGE CREAM") is None
    assert map_label("WEIGHT LOSS") is None
    assert map_label("ANTI-DIABETIC.SECRETAGOGUES.DPP-4 INHIBITORS") is None
    assert map_label("ANTINEOPLASTIC") is None
    assert map_label("SUN BLOCK") is None
    assert map_label("ANTIHYPERLIPIDEMIC.STATINS") is None
    assert map_label(None) is None
    assert map_label("") is None


def test_seeding_puts_drugs_on_the_clinics_shelves(clinic):
    """End to end, and the number is the point: 12,506 of 25,065."""
    with clinic["app"].app_context():
        from app.models import Drug, DrugClass
        from app.utils.drugbook_seed import seed_drugbook
        from app.utils.egypt_drugs import seed_register

        seed_drugbook()
        seed_register(limit=3000)
        classed = Drug.query.filter(Drug.class_id.isnot(None)).count()
        assert classed > 1000
        antibiotics = DrugClass.query.filter_by(name_en="Antibiotics").first()
        assert Drug.query.filter_by(class_id=antibiotics.id).count() > 50


def test_a_catalogue_seeded_before_this_is_classified_in_place(clinic):
    """Re-seeding cannot fix it, so the mapping is applied to what is there.

    The seeder skips trade names it already has — deliberately, so it never
    overwrites a clinic's own edits. Without a backfill, a clinic that seeded
    last month would have 25,000 uncategorised drugs and no way forward.
    """
    with clinic["app"].app_context():
        from app.models import Drug
        from app.utils.drug_classing import backfill
        from app.utils.drugbook_seed import seed_drugbook
        db = clinic["db"]

        seed_drugbook()
        db.session.add_all([
            Drug(trade_name="OLD ONE", drug_class="ANTIBIOTIC.QUINOLONE",
                 is_active=True),
            Drug(trade_name="OLD TWO", drug_class="HAIR CARE", is_active=True),
        ])
        db.session.commit()

        assert backfill() == 1
        assert Drug.query.filter_by(trade_name="OLD ONE").first().class_id
        assert Drug.query.filter_by(trade_name="OLD TWO").first().class_id is None


def test_a_hand_filed_drug_outranks_the_pattern(clinic):
    """Somebody who filed a drug themselves has made a decision.

    The backfill touches only rows with no class, so re-running it — which
    happens on every seed — never undoes that.
    """
    with clinic["app"].app_context():
        from app.models import Drug, DrugClass
        from app.utils.drug_classing import backfill
        from app.utils.drugbook_seed import seed_drugbook
        db = clinic["db"]

        seed_drugbook()
        topical = DrugClass.query.filter_by(name_en="Topical preparations").first()
        db.session.add(Drug(trade_name="FILED BY HAND",
                            drug_class="ANTIBIOTIC.QUINOLONE",
                            class_id=topical.id, is_active=True))
        db.session.commit()

        backfill()
        row = Drug.query.filter_by(trade_name="FILED BY HAND").first()
        assert row.class_id == topical.id


def test_the_catalogue_shows_the_same_shelves_as_the_reference(clinic):
    """One vocabulary across both screens, with counts, as the reference has.

    The catalogue holds trade names and the reference holds ingredients, so
    the numbers differ; what must not differ is what the categories are
    called.
    """
    with clinic["app"].app_context():
        from app.models import Drug, DrugClass
        from app.utils.drugbook_seed import seed_drugbook
        db = clinic["db"]

        seed_drugbook()
        antibiotics = DrugClass.query.filter_by(name_en="Antibiotics").first()
        db.session.add_all([
            Drug(trade_name="AAA", class_id=antibiotics.id, is_active=True),
            Drug(trade_name="BBB", class_id=antibiotics.id, is_active=True),
        ])
        db.session.commit()
        antibiotics_id = antibiotics.id

    body = (clinic["sign_in"]("boss").get("/prescriptions/drugs")
            .get_data(as_text=True))
    assert "المضادات الحيوية" in body
    assert f"class_id={antibiotics_id}" in body
    # The raw supplier labels are no longer offered as categories.
    assert 'name="drug_class"' not in body


def test_an_empty_shelf_is_not_offered(clinic):
    """A children's clinic browsing an oncology category finds nothing."""
    with clinic["app"].app_context():
        from app.models import Drug, DrugClass
        from app.utils.drugbook_seed import seed_drugbook
        db = clinic["db"]

        seed_drugbook()
        antibiotics = DrugClass.query.filter_by(name_en="Antibiotics").first()
        db.session.add(Drug(trade_name="AAA", class_id=antibiotics.id,
                            is_active=True))
        db.session.commit()

    body = (clinic["sign_in"]("boss").get("/prescriptions/drugs")
            .get_data(as_text=True))
    assert "المضادات الحيوية" in body
    assert "مضادات الفطريات" not in body      # nothing in it


def test_the_class_link_is_in_the_additive_migration():
    """A new column on ``drugs``, which every installed clinic already has."""
    from app.utils.schema import ADDITIONS

    assert ("drugs", "class_id", "INTEGER") in ADDITIONS
