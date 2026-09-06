"""The drug reference froze on the day a clinic first ran it.

Reported as a question: *"ازاي الادوية دي مش موجودة عندنا"* — over a list of
the most ordinary paediatric drugs there are. Paracetamol, ibuprofen,
cetirizine, ondansetron, ORS, vitamin D, salbutamol, albendazole.

**Every one of them was already written.** They are in ``drugbook_seed`` with
their brands and their doses, and the Egyptian register beside it carries
25,000 products including all nine Cetal presentations. Nothing was missing
from the program. What was missing was a way for any of it to reach a clinic
that had already started.

The seeder opened with *"a fresh install only"*:

    if not force and GenericDrug.query.first() is not None:
        return zeros

So the reference was whatever the clinic's very first run produced, for ever.
The list in the source has roughly doubled since; none of it arrived. A doctor
searched for ondansetron and found nothing, while the name sat in two files on
the same disk.

**A top-up is safe here and an update would not be**, which is the whole
reason this could be fixed by deleting four lines. Every step of the seed is
add-only: it skips a row that already exists and never writes over it. So a
clinic that corrected a dose, renamed a brand or switched an ingredient off
keeps every one of those decisions and gains only what it never had — which
is exactly what an update to a working clinic is allowed to do.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

# The list as it was asked about, and it is a fair one: this is what a
# paediatric clinic reaches for on an ordinary morning.
ASKED_FOR = [
    "Paracetamol", "Ibuprofen", "Cetirizine", "Loratadine", "Desloratadine",
    "Ondansetron", "Albendazole", "Mebendazole", "Amoxicillin",
    "Amoxicillin/Clavulanate", "Azithromycin", "Salbutamol", "Simethicone",
    "Oral rehydration salts (ORS)", "Vitamin D (cholecalciferol)",
    "Elemental iron", "Saline nasal drops",
]


@pytest.fixture()
def seeded(clinic):
    from app.utils.drugbook_seed import seed_drugbook

    with clinic["app"].app_context():
        seed_drugbook()
        clinic["db"].session.commit()
    return clinic


def _generics(fx):
    from app.models import GenericDrug

    with fx["app"].app_context():
        return {g.name_en for g in GenericDrug.query.all()}


# ------------------------------------------------------------ what is in it

def test_everything_that_was_asked_about_is_in_the_reference(seeded):
    """The answer to the question, as an assertion: all of it was already
    written, and the only thing wrong was that it never arrived."""
    have = _generics(seeded)
    missing = [name for name in ASKED_FOR if name not in have]
    assert missing == [], f"not in the reference: {missing}"


def test_the_ones_dosed_by_weight_carry_their_figure(seeded):
    """A name with no dose behind it is a list, not a reference."""
    from app.models import GenericDrug

    with seeded["app"].app_context():
        for name in ("Paracetamol", "Ibuprofen", "Amoxicillin", "Ondansetron",
                     "Azithromycin", "Salbutamol"):
            g = GenericDrug.query.filter_by(name_en=name).first()
            assert g.dose_per_kg, f"{name} has no mg/kg"
            assert g.doses_per_day, f"{name} has no frequency"


def test_the_ones_dosed_by_age_carry_bands_instead(seeded):
    """Cetirizine is not milligrams per kilogram — it is 2.5mg at six months
    and 5mg at two years. A reference that forced everything into one shape
    would be inventing a figure for half of it."""
    from app.models import GenericDoseBand, GenericDrug

    with seeded["app"].app_context():
        for name in ("Cetirizine", "Loratadine", "Albendazole", "Simethicone",
                     "Oral rehydration salts (ORS)",
                     "Vitamin D (cholecalciferol)"):
            g = GenericDrug.query.filter_by(name_en=name).first()
            bands = GenericDoseBand.query.filter_by(generic_id=g.id).count()
            assert bands, f"{name} has neither a per-kg dose nor an age band"


def test_the_trade_names_hang_off_the_ingredient(seeded):
    """Cetal is paracetamol. The brand is how a family says it and the
    ingredient is what the dose is worked out from — and 250mg/5mL and
    120mg/5mL are not the same number of millilitres."""
    from app.models import Drug, GenericDrug

    with seeded["app"].app_context():
        para = GenericDrug.query.filter_by(name_en="Paracetamol").first()
        brands = {d.trade_name for d in
                  Drug.query.filter_by(generic_id=para.id).all()}
        assert "Cetal" in brands
        assert len(brands) > 2, "one ingredient, one brand — that is a list"


# ------------------------------------------------- and why it never arrived

def test_a_clinic_that_already_has_one_ingredient_still_gets_the_rest(clinic):
    """The bug itself. One row in the table used to stop the whole seed, so a
    clinic that had typed a single drug by hand — or run an older, shorter
    version of this list — never received another ingredient again."""
    from app.models import GenericDrug
    from app.utils.drugbook_seed import seed_drugbook

    db = clinic["db"]
    with clinic["app"].app_context():
        db.session.add(GenericDrug(name_en="Something they typed",
                                   name_ar="حاجة كتبوها", is_active=True))
        db.session.commit()

        made = seed_drugbook()
        db.session.commit()
        assert made["generics"] > 50, \
            "the reference still refuses to grow once anything is in it"
        assert GenericDrug.query.filter_by(
            name_en="Ondansetron").first() is not None


def test_running_it_again_adds_nothing(seeded):
    """Idempotent, or every update would double the reference."""
    from app.utils.drugbook_seed import seed_drugbook

    with seeded["app"].app_context():
        made = seed_drugbook()
        seeded["db"].session.commit()
    assert made == {"classes": 0, "generics": 0, "brands": 0, "linked": 0,
                    "interactions": 0}


def test_what_the_clinic_changed_is_never_written_back_over(seeded):
    """The condition that makes a top-up safe at all. A clinic that corrected
    a dose against its own protocol must not find the correction gone after an
    update — that is worse than the missing drug this fixes."""
    from app.models import Drug, GenericDrug
    from app.utils.drugbook_seed import seed_drugbook

    db = seeded["db"]
    with seeded["app"].app_context():
        para = GenericDrug.query.filter_by(name_en="Paracetamol").first()
        para.dose_per_kg = 12.5                 # their own figure
        para.is_active = False                  # and they switched it off
        cetal = Drug.query.filter_by(trade_name="Cetal").first()
        cetal.trade_name = "Cetal (شراب الأطفال)"
        db.session.commit()

        seed_drugbook()
        db.session.commit()

        para = GenericDrug.query.filter_by(name_en="Paracetamol").first()
        assert para.dose_per_kg == 12.5
        assert para.is_active is False
        assert Drug.query.filter_by(
            trade_name="Cetal (شراب الأطفال)").first() is not None


def test_a_missing_ingredient_comes_back_with_its_brands(seeded):
    """What a real update looks like: the rows added to the source since the
    clinic's version, and nothing else."""
    from app.models import Drug, GenericDrug
    from app.utils.drugbook_seed import seed_drugbook

    db = seeded["db"]
    with seeded["app"].app_context():
        gone = GenericDrug.query.filter_by(name_en="Ondansetron").first()
        Drug.query.filter_by(generic_id=gone.id).delete()
        db.session.delete(gone)
        db.session.commit()
        before = GenericDrug.query.count()

        made = seed_drugbook()
        db.session.commit()

        assert made["generics"] == 1
        assert made["brands"] >= 1
        assert GenericDrug.query.count() == before + 1
        back = GenericDrug.query.filter_by(name_en="Ondansetron").first()
        assert Drug.query.filter_by(generic_id=back.id).count() >= 1


# ------------------------------------------------ the register beside it

def test_the_egyptian_register_carries_the_presentations(seeded):
    """The reference is the clinic's working set; the register is the market.
    Cetal is three different things on a shelf and the dose in millilitres is
    not the same for any two of them, which is exactly why the program works
    from the ingredient and the strength rather than from the name."""
    import gzip
    import json
    import os

    path = os.path.join(os.path.dirname(__file__), "..", "app", "data",
                        "egypt_drugs.json.gz")
    with gzip.open(os.path.abspath(path), "rt", encoding="utf-8") as fh:
        register = json.load(fh)

    cetal = [row[0].upper() for row in register
             if row[0].upper().startswith("CETAL")]
    assert any("250MG/5ML" in name for name in cetal)
    assert any("100MG/ML" in name for name in cetal)
    assert any("SUPP" in name for name in cetal)
