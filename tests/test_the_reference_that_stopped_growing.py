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


# ------------------------------------------------------ the infant bottles

# (ingredient, the drops that exist, the mg/ml on them, the syrup's mg/ml)
#
# Every one of these is more concentrated than its own syrup — which is what
# drops *are for*, and exactly why a reference that carries only syrups is
# wrong in the dangerous direction for the youngest patients on its books.
DROPS = [
    ("Paracetamol", "Cetal Drops", 100.0, 24.0),
    ("Ibuprofen", "Flabu Drops", 40.0, 20.0),
    ("Amoxicillin", "Unimox Drops", 100.0, 25.0),
    ("Ketotifen", "Zedotefen Drops", 1.0, 0.2),
]


@pytest.mark.parametrize("ingredient,trade,drops_conc,syrup_conc", DROPS)
def test_the_drops_are_there_and_carry_their_own_strength(
        seeded, ingredient, trade, drops_conc, syrup_conc):
    """The bottle an infant is actually given.

    Asked in three words — *"وسيتال شراب سيتال نقط؟"* — and the syrup was
    there twice while the drops were not there at all. The gap is not
    cosmetic: paracetamol drops are 100 mg/ml against the syrup's 24, so the
    same number of millilitres is four times the dose. The program works the
    dose out from the concentration precisely so that cannot happen, and that
    only protects anybody if the bottle in their hand is in the list.
    """
    from app.models import Drug, GenericDrug

    with seeded["app"].app_context():
        g = GenericDrug.query.filter_by(name_en=ingredient).first()
        d = Drug.query.filter_by(generic_id=g.id, trade_name=trade).first()
        assert d is not None, f"{trade} is not in the reference"
        assert d.form == "drops"
        assert d.conc_mg_per_ml == drops_conc
        assert drops_conc > syrup_conc, \
            "a drops presentation weaker than its own syrup is a typo"


def test_the_millilitres_differ_by_the_strength_and_not_by_the_name(seeded):
    """The arithmetic the whole shape of this table exists for: one child, one
    dose in milligrams, three bottles, three different amounts to pour."""
    from app.models import Drug, GenericDrug

    with seeded["app"].app_context():
        g = GenericDrug.query.filter_by(name_en="Paracetamol").first()
        by_name = {(d.trade_name, d.strength): d.conc_mg_per_ml
                   for d in Drug.query.filter_by(generic_id=g.id).all()}
        dose_mg = 15 * 10                       # 15 mg/kg for a 10 kg child

    # Keyed on the *pair*, because the name alone does not identify a bottle
    # — which is the point being tested.
    ml = {key: round(dose_mg / conc, 1)
          for key, conc in by_name.items() if conc}
    assert ml[("Cetal", "120 mg/5 ml")] == 6.2
    assert ml[("Cetal", "250 mg/5 ml")] == 3.0
    assert ml[("Cetal Drops", "100 mg/ml")] == 1.5


def test_both_strengths_of_a_brand_stand_as_their_own_rows(seeded):
    """Cetal is three things on a shelf. One row called "Cetal" would make the
    program answer a question it cannot answer from the name."""
    from app.models import Drug, GenericDrug

    with seeded["app"].app_context():
        g = GenericDrug.query.filter_by(name_en="Paracetamol").first()
        cetal = {(d.strength, d.form) for d in
                 Drug.query.filter_by(generic_id=g.id).all()
                 if d.trade_name.startswith("Cetal")}
    assert ("120 mg/5 ml", "syrup") in cetal
    assert ("250 mg/5 ml", "syrup") in cetal
    assert ("100 mg/ml", "drops") in cetal


def test_no_brand_is_carried_that_the_register_has_never_heard_of(seeded):
    """Found by checking: "Cetal Forte" was in this list and on no Egyptian
    register anywhere — the 250 mg/5 ml suspension is sold as plain Cetal. A
    name nobody can buy is a name a doctor picks and a pharmacy cannot fill.
    """
    import gzip
    import json
    import os

    from app.models import Drug, GenericDrug

    path = os.path.join(os.path.dirname(__file__), "..", "app", "data",
                        "egypt_drugs.json.gz")
    with gzip.open(os.path.abspath(path), "rt", encoding="utf-8") as fh:
        register = " | ".join(row[0].upper() for row in json.load(fh))

    with seeded["app"].app_context():
        g = GenericDrug.query.filter_by(name_en="Paracetamol").first()
        names = {d.trade_name for d in
                 Drug.query.filter_by(generic_id=g.id).all()}

    # Spot-checked on the ingredient the whole thread was about rather than
    # swept over the lot: a sweep would fail on every legitimately renamed
    # product and stop being read.
    unknown = [n for n in names
               if n.replace(" Drops", "").upper() not in register]
    assert unknown == [], f"not on any Egyptian register: {unknown}"


def test_the_two_ibuprofen_drops_are_listed_separately(seeded):
    """They are written differently on the two boxes — 40 mg/ml and
    50 mg/1.25 ml — and a clinic stocking the second while the screen shows
    the first is reading the wrong millilitres off it."""
    from app.models import Drug, GenericDrug

    with seeded["app"].app_context():
        g = GenericDrug.query.filter_by(name_en="Ibuprofen").first()
        drops = {d.strength: d.conc_mg_per_ml for d in
                 Drug.query.filter_by(generic_id=g.id, form="drops").all()}
    assert drops == {"40 mg/ml": 40.0, "50 mg/1.25 ml": 40.0}


# --------------------------------- correcting a figure we shipped wrong

def _abimol(fx):
    from app.models import Drug

    with fx["app"].app_context():
        d = Drug.query.filter_by(trade_name="Abimol", form="syrup").first()
        return (d.strength, d.conc_mg_per_ml) if d else None


def _shipped_the_old_value(fx):
    """Put the row back the way an older version of this program shipped it."""
    from app.models import Drug

    db = fx["db"]
    with fx["app"].app_context():
        d = Drug.query.filter_by(trade_name="Abimol", form="syrup").first()
        d.strength, d.conc_mg_per_ml = "120 mg/5 ml", 24.0
        db.session.commit()


def _fix(fx):
    from app.utils.drugbook_seed import apply_shipped_fixes

    with fx["app"].app_context():
        out = apply_shipped_fixes()
        fx["db"].session.commit()
    return out


def test_a_figure_we_shipped_wrong_is_put_right_on_update(seeded):
    """The gap the add-only rule leaves open, and the reason this exists.

    The seed never overwrites, which is what makes it safe on a working
    clinic — a dose somebody corrected must not come back as ours next
    Tuesday. The cost is that when *we* ship a wrong figure it stays wrong,
    and Abimol's syrup is 150 mg/5 ml while this file shipped 120 for a long
    time: a fifth off every millilitre worked out from it.
    """
    _shipped_the_old_value(seeded)
    assert _abimol(seeded) == ("120 mg/5 ml", 24.0)

    assert _fix(seeded) == {"fixed": 1, "left": 0}
    assert _abimol(seeded) == ("150 mg/5 ml", 30.0)


def test_a_figure_the_clinic_changed_is_left_exactly_alone(seeded):
    """The safety of the whole thing, and the half that must never slip.

    A clinic that had already noticed, or that carries its own protocol
    figure, does not match what we shipped — so nothing of theirs is touched,
    and the update says how many it did not dare touch rather than going
    quiet about them.
    """
    from app.models import Drug

    db = seeded["db"]
    with seeded["app"].app_context():
        d = Drug.query.filter_by(trade_name="Abimol", form="syrup").first()
        d.strength, d.conc_mg_per_ml = "١٥٠ مج/٥ مل (بروتوكولنا)", 31.0
        db.session.commit()

    assert _fix(seeded) == {"fixed": 0, "left": 1}
    assert _abimol(seeded) == ("١٥٠ مج/٥ مل (بروتوكولنا)", 31.0)


def test_a_clinic_already_carrying_the_right_figure_is_not_counted(seeded):
    """A fresh install, or one already corrected. Nothing to do and nothing to
    warn about — a line saying "1 left alone" every single update is a line
    people stop reading."""
    assert _abimol(seeded) == ("150 mg/5 ml", 30.0)
    assert _fix(seeded) == {"fixed": 0, "left": 0}


def test_running_it_twice_changes_nothing_the_second_time(seeded):
    """It runs on every update. A correction that re-applied would be a second
    write over a row the clinic may have edited in between."""
    _shipped_the_old_value(seeded)
    assert _fix(seeded)["fixed"] == 1
    assert _fix(seeded) == {"fixed": 0, "left": 0}


def test_a_correction_only_touches_the_product_it_names(seeded):
    """Same ingredient, same strength on the label, different brand. A fix
    written for one product must not walk along the shelf."""
    from app.models import Drug

    _shipped_the_old_value(seeded)
    before = _abimol(seeded)
    del before

    with seeded["app"].app_context():
        others = {(d.trade_name, d.strength, d.conc_mg_per_ml)
                  for d in Drug.query.filter(Drug.trade_name != "Abimol").all()}
    _fix(seeded)
    with seeded["app"].app_context():
        after = {(d.trade_name, d.strength, d.conc_mg_per_ml)
                 for d in Drug.query.filter(Drug.trade_name != "Abimol").all()}
    assert others == after


def test_a_correction_says_which_value_it_expects_to_find(seeded):
    """Written out rather than worked out. It is what makes the change
    reviewable in a diff, and it forces whoever adds one to say what they
    believe the clinic is holding."""
    from app.utils.drugbook_seed import SHIPPED_FIXES

    for fix in SHIPPED_FIXES:
        assert fix.get("was"), "a correction with no expected value would overwrite"
        assert fix.get("now"), "a correction with nothing to write"
        assert fix.get("why"), "a clinical figure changed with no reason recorded"
        assert set(fix["was"]) & set(fix["now"]), \
            "the value checked and the value written are unrelated"


def test_the_update_actually_runs_it_and_says_so(seeded):
    """Driven through ``upgrade-db`` itself rather than by reading the source.

    Written the other way first and two deliberate breakages walked past it:
    a scan for the function's name matched the *import* after the call had
    been replaced, and a scan for the word "corrected" matched a comment after
    the message had been deleted. A test that greps for its own vocabulary
    passes on a program that does nothing.

    And the message is half the point. A clinical number changing quietly
    under a clinic is exactly what an update may not do without telling them.
    """
    from app.models import Drug

    _shipped_the_old_value(seeded)

    result = seeded["app"].test_cli_runner().invoke(args=["upgrade-db"])
    assert result.exit_code == 0
    assert "corrected" in result.output, "the update went quiet about it"

    with seeded["app"].app_context():
        d = Drug.query.filter_by(trade_name="Abimol", form="syrup").first()
        assert (d.strength, d.conc_mg_per_ml) == ("150 mg/5 ml", 30.0)


def test_the_update_names_what_it_did_not_dare_touch(seeded):
    """The other half of telling them: a clinic whose own figure was left
    alone should be told, not left to find out."""
    from app.models import Drug

    db = seeded["db"]
    with seeded["app"].app_context():
        d = Drug.query.filter_by(trade_name="Abimol", form="syrup").first()
        d.strength, d.conc_mg_per_ml = "بروتوكولنا", 31.0
        db.session.commit()

    result = seeded["app"].test_cli_runner().invoke(args=["upgrade-db"])
    assert "left alone" in result.output

    with seeded["app"].app_context():
        d = Drug.query.filter_by(trade_name="Abimol", form="syrup").first()
        assert d.conc_mg_per_ml == 31.0


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
