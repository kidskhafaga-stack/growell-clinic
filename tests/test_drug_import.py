"""Loading a real market drug register, safely.

The published Egyptian drug list is 25,000 commercial products written the way
a register writes them: the strength and the pack buried inside the product
name, the ingredient as ``AMOXICILLIN+CLAVULANIC ACID``, thousands of
commercial groupings that are not the clinic's drug tree.

What these tests hold is the difference between "imported" and "usable":
combination products carry *all* their ingredients so the allergy check can see
them, the clinic's own curated ingredients and dosing survive, the class tree
isn't buried, and re-running the same file changes nothing.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

# One row per shape the register actually produces.
EDA_CSV = """commercial_name_en,commercial_name_ar,scientific_name,manufacturer,drug_class,route,price_egp
AUGMENTIN 1 GM 14 F.C. TABS.,أوجمنتين,AMOXICILLIN+CLAVULANIC ACID,GLAXO > SMITHKLINE,ANTIBIOTICS BROAD SPECTRUM,ORAL.SOLID,210.0
BRUFEN 400 MG 30 TABS.,بروفين,IBUPROFEN,KAHIRA PHARM,ANALGESIC,ORAL.SOLID,45.5
CETAL 125 MG/5 ML SUSP. 100 ML,سيتال,PARACETAMOL(ACETAMINOPHEN),EPICO,COLD PRODUCTS,ORAL.LIQUID,27.0
NODY CARE SHAMPOO 250 ML,نودي كير,SEA WATER+GLYCERIN,NILL FACTORY,SOOTHING,UNKNOWN,32.0
"""


@pytest.fixture()
def clinic():
    from app import create_app
    from app.extensions import db

    app = create_app("testing")
    with app.app_context():
        db.create_all()
        from app.models import DrugClass, GenericDrug

        # The clinic's own curated reference, as seeded on install.
        cls = DrugClass(code="ABX", name_ar="المضادات الحيوية",
                        name_en="Antibiotics", is_active=True)
        db.session.add(cls)
        db.session.flush()
        db.session.add(GenericDrug(name_ar="أموكسيسيللين", name_en="Amoxicillin",
                                   class_id=cls.id, dose_per_kg=25.0,
                                   doses_per_day=3, is_active=True))
        db.session.commit()
        yield {"app": app, "db": db}


def _import(clinic, text=EDA_CSV, **kwargs):
    from app.utils.drugbook_import import import_rows, parse

    rows, errors = parse(text.encode("utf-8"))
    assert errors == []
    made = import_rows(rows, **kwargs)
    if not kwargs.get("dry_run"):
        clinic["db"].session.commit()
    return made


def test_the_registers_own_columns_are_understood(clinic):
    """No one should have to rename a header before their data will load."""
    from app.utils.drugbook_import import parse

    with clinic["app"].app_context():
        rows, errors = parse(EDA_CSV.encode("utf-8"))
        assert errors == []
        assert len(rows) == 4
        assert rows[0]["trade_name"].startswith("AUGMENTIN")
        assert rows[0]["trade_name_ar"] == "أوجمنتين"
        assert rows[0]["price"] == "210.0"


def test_what_the_register_buries_in_the_name_comes_out(clinic):
    from app.models import Drug

    with clinic["app"].app_context():
        _import(clinic)
        aug = Drug.query.filter(Drug.trade_name.like("AUGMENTIN%")).one()
        assert (aug.strength, aug.form, aug.pack_size) == ("1 GM", "tablet", "14 tabs")
        assert aug.route == "oral"
        assert aug.trade_name_ar == "أوجمنتين"
        assert aug.price == 210.0
        # "GLAXO > SMITHKLINE" — the company on the box is the second one.
        assert aug.manufacturer == "SMITHKLINE"


def test_a_bottle_size_is_not_a_strength(clinic):
    """"SHAMPOO 250 ML" is how big the bottle is. Calling that a strength puts
    a meaningless number on a prescription."""
    from app.models import Drug

    with clinic["app"].app_context():
        _import(clinic)
        shampoo = Drug.query.filter(Drug.trade_name.like("NODY%")).one()
        assert shampoo.strength is None
        assert shampoo.pack_size == "250 ml"


def test_a_liquids_concentration_is_worked_out(clinic):
    """125 mg/5 ml → 25 mg per ml, which is what turns a dose into a spoon."""
    from app.models import Drug

    with clinic["app"].app_context():
        _import(clinic)
        cetal = Drug.query.filter(Drug.trade_name.like("CETAL%")).one()
        assert cetal.strength == "125 MG/5 ML"
        assert cetal.conc_mg_per_ml == 25.0


def test_a_combination_carries_every_ingredient(clinic):
    """The safety point of the whole exercise."""
    from app.models import Drug

    with clinic["app"].app_context():
        _import(clinic)
        aug = Drug.query.filter(Drug.trade_name.like("AUGMENTIN%")).one()
        names = {g.name_en for g in aug.all_ingredients()}
        assert names == {"Amoxicillin", "Clavulanic Acid"}
        # Dosing is read from the first — the one with the paediatric rule.
        assert aug.generic.name_en == "Amoxicillin"


def test_the_allergy_check_sees_the_second_ingredient(clinic):
    """A child allergic to clavulanic acid must not be cleared for Augmentin
    because the check only looked at its amoxicillin."""
    from app.models import Drug
    from app.utils.allergy import check_drug

    class Child:
        allergies = "حساسية من الكلافولانيك"

    with clinic["app"].app_context():
        _import(clinic)
        aug = Drug.query.filter(Drug.trade_name.like("AUGMENTIN%")).one()
        hit = check_drug(Child(), generic=None, drug=aug, name="")
        assert hit is not None and hit["level"] == "match"


def test_the_clinics_own_ingredient_is_reused_not_duplicated(clinic):
    """Amoxicillin already exists with a paediatric dose. An import must join
    it, not create a second one that carries no dosing."""
    from app.extensions import db
    from app.models import GenericDrug

    with clinic["app"].app_context():
        _import(clinic)
        rows = GenericDrug.query.filter(
            db.func.lower(GenericDrug.name_en) == "amoxicillin").all()
        assert len(rows) == 1
        assert rows[0].dose_per_kg == 25.0        # the clinic's rule survived


def test_a_synonym_in_brackets_is_the_same_substance(clinic):
    """PARACETAMOL(ACETAMINOPHEN) is one ingredient, not two."""
    from app.models import Drug

    with clinic["app"].app_context():
        _import(clinic)
        cetal = Drug.query.filter(Drug.trade_name.like("CETAL%")).one()
        assert [g.name_en for g in cetal.all_ingredients()] == ["Paracetamol"]


def test_the_class_tree_is_not_buried_by_the_file(clinic):
    """A market register has thousands of commercial groupings. Turning each
    into a class makes the clinic's own tree unbrowsable, so it doesn't."""
    from app.models import DrugClass

    with clinic["app"].app_context():
        before = DrugClass.query.count()
        _import(clinic)
        assert DrugClass.query.count() == before
        # …unless the clinic explicitly asks for them.
        made = _import(clinic, create_classes=True)
        assert made["classes"] > 0
        assert DrugClass.query.count() > before


def test_importing_the_same_file_twice_changes_nothing(clinic):
    """Anyone re-running a monthly price file must not double the catalogue."""
    from app.models import Drug, GenericDrug

    with clinic["app"].app_context():
        _import(clinic)
        drugs, generics = Drug.query.count(), GenericDrug.query.count()
        again = _import(clinic)
        assert again["brands"] == 0
        assert again["generics"] == 0
        assert Drug.query.count() == drugs
        assert GenericDrug.query.count() == generics


def test_a_dry_run_writes_nothing(clinic):
    from app.models import Drug

    with clinic["app"].app_context():
        made = _import(clinic, dry_run=True)
        assert made["brands"] == 4
        assert Drug.query.count() == 0


def test_json_is_accepted_too(clinic):
    """The published datasets ship CSV and JSON; converting one to the other
    is a step that would exist only for our convenience."""
    from app.models import Drug

    payload = """[
      {"commercial_name_en": "PANADOL 500 MG 20 TABS.",
       "commercial_name_ar": "بانادول", "scientific_name": "PARACETAMOL",
       "manufacturer": "GSK", "route": "ORAL.SOLID", "price_egp": "35"}
    ]"""
    with clinic["app"].app_context():
        _import(clinic, payload)
        row = Drug.query.filter(Drug.trade_name.like("PANADOL%")).one()
        assert row.trade_name_ar == "بانادول"
        assert row.strength == "500 MG"
        assert row.price == 35.0


def test_a_price_update_never_overwrites_the_clinics_dosing(clinic):
    from app.models import Drug

    updated = EDA_CSV.replace(",210.0", ",240.0")
    with clinic["app"].app_context():
        _import(clinic)
        aug = Drug.query.filter(Drug.trade_name.like("AUGMENTIN%")).one()
        aug.default_dose = "1 قرص كل 12 ساعة"
        aug.notes = "ملاحظة العيادة"
        clinic["db"].session.commit()

        _import(clinic, updated)
        aug = Drug.query.filter(Drug.trade_name.like("AUGMENTIN%")).one()
        assert aug.price == 240.0
        assert aug.default_dose == "1 قرص كل 12 ساعة"
        assert aug.notes == "ملاحظة العيادة"


def test_a_file_with_no_product_names_is_refused_clearly(clinic):
    from app.utils.drugbook_import import parse

    with clinic["app"].app_context():
        rows, errors = parse(b"foo,bar\n1,2\n")
        assert rows == []
        assert errors and "trade" in errors[0]


def test_nonsense_never_becomes_a_row_a_doctor_can_find(clinic):
    """A register's ingredient cell is free text, and some of it is a footnote
    or a stray bracket. Anything that isn't a substance name is dropped rather
    than becoming a reference row someone will one day search and trust."""
    from app.utils.drugbook_parse import clean_ingredient, split_ingredients

    for junk in ("( MAGNESIUM CITRATE", "12345", "---", "%20", "", "   "):
        assert clean_ingredient(junk) is None, junk
    assert split_ingredients("12345 + 678") == []
    assert split_ingredients("") == []

    # A parenthesised note is stripped, and what's left is kept — the
    # substance is real even when the annotation isn't.
    assert clean_ingredient("(10 INGREDIENTS) EUCALYPTUS OIL") == "Eucalyptus Oil"
    assert clean_ingredient("PARACETAMOL(ACETAMINOPHEN)") == "Paracetamol"
    assert clean_ingredient("VITAMIN C 1 GM") == "Vitamin C"
    assert split_ingredients(
        "CHLORPHENIRAMINE+PARACETAMOL(ACETAMINOPHEN)+PSEUDOEPHEDRINE") == [
            "Chlorpheniramine", "Paracetamol", "Pseudoephedrine"]
