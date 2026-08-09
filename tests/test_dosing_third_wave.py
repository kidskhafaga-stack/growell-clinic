"""Fifteen ingredients the register kept asking for, and why not the others.

The catalogue holds 25,350 trade names and the dose calculator reached almost
none of them. Half the gap was spelling, and that is fixed elsewhere. This is
the other half: ingredients the reference simply did not hold.

They were **chosen by measurement**. After seeding the whole Egyptian
register, these are the single-ingredient names carrying the most trade names
that could not be dosed — then filtered to what a children's clinic actually
gives. 107 ingredients → 122; brands with a dose behind them 1,622 → 1,816.
Povidone-iodine alone accounts for 64 of that, and only after its name
lost a ``(topical)`` qualifier that bought nothing — it is never given
any other way — and the register's ``POVIDONE- IODINE`` spacing was
normalised.

**What was left out matters as much.** Pregabalin (96 products), gabapentin
(69), etoricoxib (66), moxifloxacin (57), meloxicam (35), piroxicam (34),
linezolid (37) and vonoprazan (41) are all large in the register and are not
children's medicines. Ranitidine (45) was withdrawn worldwide over NDMA.
Putting a paediatric dose beside any of them would be inventing a use — the
catalogue can hold a drug perfectly well without pretending to dose it, and
these tests make that a rule rather than an oversight.

**Every number carries its source.** ``reference`` is not decoration here: a
dose on a screen is trusted, and the only way anybody can check one is if the
screen says where it came from.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

# The ones the measurement selected, with the count of trade names each
# reaches in the register.
ADDED = [
    "Cefotaxime", "Ceftazidime", "Cefdinir", "Erythromycin",
    "Phenoxymethylpenicillin", "Terbinafine", "Griseofulvin", "Pantoprazole",
    "Cyproheptadine", "Hydroxyzine", "Adrenaline (epinephrine)",
    "Vitamin C (ascorbic acid)", "Vitamin A", "Povidone-iodine",
    "Lidocaine (topical)",
]

# Large in the register, and deliberately absent.
REFUSED = [
    "Pregabalin", "Gabapentin", "Etoricoxib", "Moxifloxacin", "Meloxicam",
    "Piroxicam", "Linezolid", "Vonoprazan", "Ranitidine",
]


def test_every_ingredient_says_where_its_dose_came_from():
    """A dose on a screen is believed. The source is how it can be checked.

    Applied to all 122, not just the new ones — an ingredient without a
    reference is a number nobody can audit, and one unreferenced entry is
    enough to make the column decorative.
    """
    from app.utils.drugbook_seed import GENERICS

    missing = [g["name_en"] for g in GENERICS if not g.get("ref")]
    assert not missing, f"no reference for: {missing}"


def test_the_measured_additions_are_all_there():
    """Chosen by how many boxes they reach, not by taste."""
    from app.utils.drugbook_seed import GENERICS

    names = {g["name_en"] for g in GENERICS}
    for drug in ADDED:
        assert drug in names, f"{drug} was measured in and is missing"


def test_adult_drugs_are_not_given_a_childs_dose():
    """The refusal, as a rule rather than an oversight.

    Each of these is large in the Egyptian register, so each is a standing
    temptation to raise the coverage percentage. A paediatric dose beside a
    drug children are not given is an invented indication, and it would look
    exactly like a real one.
    """
    from app.utils.drugbook_seed import GENERICS

    names = {g["name_en"] for g in GENERICS}
    for drug in REFUSED:
        assert drug not in names, (
            f"{drug} is not a children's medicine and must not carry a "
            "paediatric dose")


def test_the_one_that_is_not_about_coverage(clinic):
    """Adrenaline reaches five boxes and is the most important of the fifteen.

    A paediatric clinic without an anaphylaxis dose in front of the doctor is
    missing the one number where the delay itself is what kills. It is here
    for that, not for its share of the register.
    """
    with clinic["app"].app_context():
        from app.models import GenericDrug
        from app.utils.drugbook_seed import seed_drugbook

        seed_drugbook()
        adrenaline = GenericDrug.query.filter_by(
            name_en="Adrenaline (epinephrine)").first()
        assert adrenaline is not None
        assert adrenaline.dose_per_kg == 0.01          # of 1:1000, IM
        assert adrenaline.max_single_dose_mg == 0.5
        assert "الأنافيلاكسيس" in (adrenaline.black_box or "")


def test_a_drug_dosed_by_weight_band_carries_the_bands_not_a_fake_per_kg(clinic):
    """Terbinafine is given by weight band, and inventing a per-kg is wrong.

    62.5mg under 20kg, 125mg to 40kg, 250mg above. Dividing that into a
    milligrams-per-kilo would produce a number that is correct at one weight
    and wrong either side of it — so it carries no ``dose_per_kg`` at all and
    states the bands instead.
    """
    with clinic["app"].app_context():
        from app.models import GenericDrug
        from app.utils.drugbook_seed import seed_drugbook

        seed_drugbook()
        terb = GenericDrug.query.filter_by(name_en="Terbinafine").first()
        assert terb.dose_per_kg is None
        assert "62.5" in (terb.dose_note or "")
        assert "250" in (terb.dose_note or "")


@pytest.mark.parametrize("name,warning", [
    ("Erythromycin", "البواب"),          # pyloric stenosis in young infants
    ("Vitamin A", "الجمجمة"),            # raised intracranial pressure
    ("Povidone-iodine", "الدرقية"),   # neonatal thyroid suppression
    ("Lidocaine (topical)", "التسنين"),  # FDA warning on teething gels
])
def test_the_warnings_that_are_the_reason_to_look_it_up(clinic, name, warning):
    """A dose without its hazard is half the entry.

    Each of these is a real, non-obvious harm a paediatrician needs beside the
    number: erythromycin and pyloric stenosis in the first six weeks, vitamin A
    and raised intracranial pressure, iodine absorbed through newborn skin,
    and lidocaine teething gel — which the FDA warns against under two and
    which is sold over the counter here.
    """
    with clinic["app"].app_context():
        from app.models import GenericDrug
        from app.utils.drugbook_seed import seed_drugbook

        seed_drugbook()
        drug = GenericDrug.query.filter_by(name_en=name).first()
        text = (drug.black_box or "") + (drug.precautions or "")
        assert warning in text


def test_the_additions_reach_the_catalogue(clinic):
    """End to end, and the number is the justification.

    Brands with a dose behind them: 1,622 → 1,816. Not a large share of
    25,350, and saying so is the point — most of that catalogue is adult and
    cosmetic products a children's clinic will never dose.
    """
    with clinic["app"].app_context():
        from app.models import Drug, GenericDrug
        from app.utils.drugbook_seed import seed_drugbook
        from app.utils.egypt_drugs import seed_register
        db = clinic["db"]

        seed_drugbook()
        seed_register()
        with_dose = (db.session.query(Drug.id)
                     .join(GenericDrug, Drug.generic_id == GenericDrug.id)
                     .filter(GenericDrug.dose_per_kg.isnot(None)).count())
        assert with_dose > 1750

        cefotaxime = GenericDrug.query.filter_by(name_en="Cefotaxime").first()
        assert Drug.query.filter_by(generic_id=cefotaxime.id).count() >= 40


def test_no_entry_carries_a_field_the_seeder_ignores():
    """A key the seeder does not read is clinical data thrown away in silence.

    Caught while writing these, and it found something older than the new
    entries: **vancomycin** had carried ``monitoring="trough levels…"`` since
    it was written, the seeder never read the key, and the reference screen
    has been rendering that row empty ever since — on the one drug where the
    levels *are* the safety of the drug. The seeder reads it now.
    """
    import re

    from app.utils import drugbook_seed
    from app.utils.drugbook_seed import GENERICS

    source = open(drugbook_seed.__file__, encoding="utf-8").read()
    read = set(re.findall(r'row\.get\("([a-z_]+)"', source))
    read |= {"name_ar", "name_en"}
    for entry in GENERICS:
        unread = set(entry) - read
        assert not unread, (
            f"{entry['name_en']} sets {sorted(unread)}, which the seeder "
            "never reads")


def test_vancomycin_shows_the_levels_it_is_dosed_by(clinic):
    """The pre-existing casualty of the key the seeder ignored.

    Vancomycin's trough level is not an extra: it is how the drug is dosed
    safely. It was written into the reference and silently discarded on the
    way to the database, so the screen's monitoring row rendered empty for it.
    """
    with clinic["app"].app_context():
        from app.models import GenericDrug
        from app.utils.drugbook_seed import seed_drugbook

        seed_drugbook()
        vanc = GenericDrug.query.filter_by(name_en="Vancomycin").first()
        assert vanc is not None
        assert vanc.monitoring, "vancomycin has no monitoring advice on screen"
