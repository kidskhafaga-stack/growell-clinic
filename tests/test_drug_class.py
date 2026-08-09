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
        assert total >= 400
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


def test_the_catalogue_can_be_narrowed_by_class(clinic):
    """The whole point: "show me the antibiotics" now has an answer."""
    with clinic["app"].app_context():
        from app.models import Drug
        db = clinic["db"]
        db.session.add_all([
            Drug(trade_name="AAA", drug_class="ANTIBIOTICS", is_active=True),
            Drug(trade_name="BBB", drug_class="ANTIBIOTICS", is_active=True),
            Drug(trade_name="CCC", drug_class="SKIN CARE", is_active=True),
            Drug(trade_name="DDD", drug_class="SKIN CARE", is_active=True),
        ])
        db.session.commit()

    body = (clinic["sign_in"]("boss")
            .get("/prescriptions/drugs?drug_class=ANTIBIOTICS")
            .get_data(as_text=True))
    assert "AAA" in body and "BBB" in body
    assert "CCC" not in body


def test_a_class_of_one_is_not_offered_as_a_category(clinic):
    """It is not a category — it is that drug, described.

    Left in, a thousand single-drug "classes" bury the four hundred real ones,
    and a filter nobody can find their way down is a filter nobody uses.
    """
    with clinic["app"].app_context():
        from app.models import Drug
        db = clinic["db"]
        db.session.add_all([
            Drug(trade_name="AAA", drug_class="ANTIBIOTICS", is_active=True),
            Drug(trade_name="BBB", drug_class="ANTIBIOTICS", is_active=True),
            Drug(trade_name="LONELY", drug_class="ONE OF A KIND",
                 is_active=True),
        ])
        db.session.commit()

    body = (clinic["sign_in"]("boss").get("/prescriptions/drugs")
            .get_data(as_text=True))
    assert 'value="ANTIBIOTICS"' in body
    assert 'value="ONE OF A KIND"' not in body


def test_a_class_reached_by_link_still_filters(clinic):
    """Not being offered in the list is not the same as not existing.

    Somebody who follows a link, or types the URL, gets the drugs — and the
    dropdown shows what they are actually looking at rather than resetting
    itself to "all" and quietly disagreeing with the rows below it.
    """
    with clinic["app"].app_context():
        from app.models import Drug
        clinic["db"].session.add(
            Drug(trade_name="LONELY", drug_class="ONE OF A KIND",
                 is_active=True))
        clinic["db"].session.commit()

    body = (clinic["sign_in"]("boss")
            .get("/prescriptions/drugs?drug_class=ONE OF A KIND")
            .get_data(as_text=True))
    assert "LONELY" in body
    assert 'value="ONE OF A KIND"' in body


def test_each_category_says_how_many_drugs_are_in_it(clinic):
    """A category name alone does not say whether anything is behind it.

    Asked for after seeing the register's own reference, which lists a count
    against every class — and it is the right call: "ANTIBIOTICS (412)" is
    something to open, "ANTIBIOTICS" is a guess.

    It lives in the dropdown and nowhere else. A first attempt also put the
    twelve biggest classes across the top as chips; it answered the same
    question twice and made a clean screen busy, so it came out again.
    """
    with clinic["app"].app_context():
        from app.models import Drug
        db = clinic["db"]
        db.session.add_all([
            Drug(trade_name="AAA", drug_class="ANTIBIOTICS", is_active=True),
            Drug(trade_name="BBB", drug_class="ANTIBIOTICS", is_active=True),
            Drug(trade_name="CCC", drug_class="ANTIBIOTICS", is_active=True),
            Drug(trade_name="DDD", drug_class="SKIN CARE", is_active=True),
            Drug(trade_name="EEE", drug_class="SKIN CARE", is_active=True),
        ])
        db.session.commit()

    body = (clinic["sign_in"]("boss").get("/prescriptions/drugs")
            .get_data(as_text=True))
    assert "ANTIBIOTICS (3)" in body
    assert "SKIN CARE (2)" in body


def test_the_column_is_in_the_additive_migration():
    """A new column on an existing table, so an installed clinic gets it.

    ``drugs`` is not a new table — every clinic already has one, full of their
    own edits. Without this line the upgrade brings a model that names a
    column the database does not have.
    """
    from app.utils.schema import ADDITIONS

    assert ("drugs", "drug_class", "VARCHAR(80)") in ADDITIONS
