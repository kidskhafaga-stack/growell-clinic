"""The drugs nobody bothered to add, because everybody knows them.

The reference had 25,000 products behind it and no Sudocrem. No Bepanthen, no
Betadine, no burn cream, no nappy-rash antifungal. Said plainly:

    "لو الطبيب أنا بقوله في 20000 ألف دواء ومَيلاقيش حاجات بديهية ومشهورة في
     السوق بتبقى عدم ثقة ويأس"

That is the failure mode this file is about, and it is not a data-coverage
failure. **A catalogue is judged on the first thing somebody looks up.** Type
the most ordinary name you own, get nothing back, and the other 25,000 rows
stop existing — not because they are wrong, but because nobody types a second
word into a box that failed the first one.

So the tests here are about *arriving*, not about counting. Each name is
searched for the way a doctor would search for it, through the endpoint the
prescription writer actually calls.

Three other things are locked down while they are in reach:

**Nappy rash is four medicines, not one.** A barrier, a yeast, a bacterium,
and an inflamed patch that is none of those. The clinic had half of that. It
has all of it now — as products with their categories, and *not* as a "try
this, then this" ladder, because choosing between them is a clinical decision
and this program does not make those.

**A cream must not inherit a tablet's dose.** Terbinafine by mouth is dosed by
weight band and is not for children under two; terbinafine as a cream is
neither. They are two ingredients here for that reason, and the creams hang
off the topical one.

**And what is not here is stated too.** Every oral erythromycin on the
Egyptian register is marked (N/A), so the ingredient keeps its dose and ships
no brand at all. A name a pharmacy cannot fill is the same wasted trip as a
name that was never written.
"""
import gzip
import json
import os
import re
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

REGISTER = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "app", "data", "egypt_drugs.json.gz"))

# What somebody would actually type. Every one of these was missing.
FAMOUS = [
    "Sudocrem", "Desitin", "Bepanthen", "Betadine", "Dermazin", "MEBO",
    "EMLA", "Nocandida", "Daktarin", "Triactin", "Atarax", "Controloc",
    "Cedenir", "Cefaxim", "Ospen", "Griseovin", "Lamisil", "Mundisal",
]


@pytest.fixture()
def seeded(clinic):
    from app.utils.drugbook_seed import seed_drugbook

    with clinic["app"].app_context():
        seed_drugbook()
        clinic["db"].session.commit()
    return clinic


def _register_rows():
    with gzip.open(REGISTER, "rt", encoding="utf-8") as fh:
        return json.load(fh)


def _wave_four():
    """The (trade, ingredient, form, strength, conc, maker) rows added here."""
    from app.utils import drugbook_seed

    source = open(drugbook_seed.__file__, encoding="utf-8").read()
    block = source.split("# --- fourth wave of trade names")[1].split("\n]\n")[0]
    return re.findall(r'^\s*\("([^"]+)",\s*"([^"]+)",', block, re.M)


# ------------------------------------------------------ does it come back?

@pytest.mark.parametrize("typed", FAMOUS)
def test_the_ordinary_name_comes_back_from_the_search(seeded, typed):
    """The whole complaint as an assertion, one name at a time, through the
    endpoint the prescription writer calls — not through the seed list, which
    is where all of these already were on the day it was reported."""
    page = seeded["sign_in"]("boss").get(
        f"/prescriptions/drugs/search?q={typed}")
    assert page.status_code == 200
    found = [row for row in page.get_json()
             if typed.lower() in (row.get("name") or "").lower()
             or typed.lower() in (row.get("generic") or "").lower()]
    assert found, f"typing {typed!r} into the drug search returns nothing"


@pytest.mark.parametrize("typed", ["Sudocrem", "Betadine", "Dermazin"])
def test_and_the_reference_screen_finds_it_too(seeded, typed):
    """Two doors, and the fault was that both were shut. The reference is
    browsed by ingredient and searched by whatever name comes to mind first —
    a trade name typed here has to reach the ingredient behind it."""
    page = seeded["sign_in"]("boss").get(f"/prescriptions/drugbook?q={typed}")
    assert page.status_code == 200
    assert typed.lower() in page.get_data(as_text=True).lower() or \
        "لا توجد" not in page.get_data(as_text=True)


def test_the_search_ranks_the_exact_name_first(seeded):
    """Coming back somewhere on page three is not coming back. Sudocrem is
    what was typed, so Sudocrem is the first row."""
    page = seeded["sign_in"]("boss").get("/prescriptions/drugs/search?q=Sudocrem")
    rows = page.get_json()
    assert rows and "sudocrem" in (rows[0].get("name") or "").lower()


# --------------------------------------------- nappy rash is four medicines

# (what it is, the ingredient that answers it, the shelf it sits on)
NAPPY_RASH = [
    ("حاجز", "Zinc oxide (topical)", "TOPIC"),
    ("حاجز", "Dexpanthenol (topical)", "TOPIC"),
    ("فطر", "Nystatin (topical)", "ANTIF"),
    ("فطر", "Miconazole (topical)", "ANTIF"),
    ("فطر", "Clotrimazole (topical)", "ANTIF"),
    ("ميكروب", "Mupirocin (topical)", "TOPIC"),
    ("التهاب", "Hydrocortisone (topical)", "TOPIC"),
]


@pytest.mark.parametrize("kind,ingredient,shelf", NAPPY_RASH)
def test_every_kind_of_nappy_rash_has_something_behind_it(
        seeded, kind, ingredient, shelf):
    """One complaint, four different medicines. A clinic that can only offer
    the barrier is a clinic that treats the yeast with a barrier."""
    from app.models import Drug, GenericDrug

    with seeded["app"].app_context():
        g = GenericDrug.query.filter_by(name_en=ingredient).first()
        assert g is not None, f"{ingredient} ({kind}) is not in the reference"
        assert g.drug_class is not None and g.drug_class.code == shelf
        assert Drug.query.filter_by(generic_id=g.id, is_active=True).count(), \
            f"{ingredient} is an ingredient with no product behind it"


def test_the_program_does_not_pick_which_one(seeded):
    """It carries the four and it stops there.

    Ordering them — barrier first, then antifungal, then steroid — would be
    the program prescribing, and it does not: it warns and it computes. So no
    entry here tells the doctor what to reach for *next*, and the check is
    that none of them names another ingredient in its own dosing note.
    """
    from app.models import GenericDrug

    names = [n for _, n, _ in NAPPY_RASH]
    with seeded["app"].app_context():
        for name in names:
            g = GenericDrug.query.filter_by(name_en=name).first()
            note = (g.dose_note or "")
            for other in names:
                if other != name:
                    word = other.split(" (")[0].lower()
                    assert word not in note.lower(), \
                        f"{name} tells the doctor to use {other}"


def test_a_cream_is_never_dosed_by_the_kilo(seeded):
    """A barrier cream with a mg/kg figure would put a millilitre count on a
    screen for something smeared on with a finger."""
    from app.models import GenericDrug

    creams = ["Zinc oxide (topical)", "Dexpanthenol (topical)",
              "Nystatin (topical)", "Miconazole (topical)",
              "Silver sulfadiazine (topical)", "Beta-sitosterol (MEBO)",
              "Terbinafine (topical)", "Chlorhexidine",
              "Lidocaine/prilocaine (topical)"]
    with seeded["app"].app_context():
        for name in creams:
            g = GenericDrug.query.filter_by(name_en=name).first()
            assert g is not None, f"{name} is missing"
            assert g.dose_per_kg is None, f"{name} carries a mg/kg figure"
            assert not g.age_bands, f"{name} carries dose bands"


# ------------------------------------------- the cream and the tablet split

def test_the_cream_does_not_inherit_the_tablets_dose(seeded):
    """Terbinafine by mouth is dosed by weight band and is not given under two
    years. The 1% cream is neither, and it was about to be hung off the oral
    ingredient — which would have printed the tablet's rule over a tube."""
    from app.models import Drug, GenericDrug

    with seeded["app"].app_context():
        oral = GenericDrug.query.filter_by(name_en="Terbinafine").first()
        skin = GenericDrug.query.filter_by(
            name_en="Terbinafine (topical)").first()
        assert oral.min_age_months == 24 and oral.dose_note
        assert skin.min_age_months is None and not skin.dose_note
        forms = {(d.trade_name, d.form) for d in
                 Drug.query.filter_by(generic_id=skin.id).all()}
        assert forms and all("tablet" not in f for _, f in forms)
        assert all(d.form == "tablet" for d in
                   Drug.query.filter_by(generic_id=oral.id).all())


def test_the_same_split_for_nystatin(seeded):
    """The oral one is dosed in millilitres after a feed; the cream is not
    dosed at all. One ingredient carrying both would have shown a baby's
    1 ml four times a day on a tube of cream."""
    from app.models import Drug, GenericDrug

    with seeded["app"].app_context():
        mouth = GenericDrug.query.filter_by(name_en="Nystatin").first()
        skin = GenericDrug.query.filter_by(
            name_en="Nystatin (topical)").first()
        assert mouth.age_bands and not skin.age_bands
        creams = Drug.query.filter_by(generic_id=skin.id).all()
        assert creams and all(d.form == "cream" for d in creams)


# ---------------------------------------------------------------- safety

def test_the_burn_cream_is_kept_away_from_a_newborn(seeded):
    """Silver sulfadiazine is a sulfonamide: it displaces bilirubin and can
    cause kernicterus, so it is not for the first weeks. The reference carries
    that as a number the program can act on, not only as a sentence."""
    from app.models import Drug, GenericDrug
    from app.utils.drug_search import age_fit

    with seeded["app"].app_context():
        g = GenericDrug.query.filter_by(
            name_en="Silver sulfadiazine (topical)").first()
        assert g.min_age_months == 2
        assert g.black_box
        drug = Drug.query.filter_by(generic_id=g.id).first()
        assert age_fit(drug, 1) == 1, "it ranks level for a one-month-old"
        assert age_fit(drug, 8) == 0


def test_the_antiseptic_a_newborn_can_have_is_there_too(seeded):
    """Povidone-iodine is absorbed through newborn skin and suppresses the
    thyroid — the reference already said so and offered nothing else. An
    antiseptic that is contraindicated with no alternative on the shelf is a
    warning the desk has to ignore."""
    from app.models import Drug, GenericDrug

    with seeded["app"].app_context():
        iodine = GenericDrug.query.filter_by(name_en="Povidone-iodine").first()
        other = GenericDrug.query.filter_by(name_en="Chlorhexidine").first()
        assert iodine.black_box and not other.black_box
        assert other.drug_class.code == iodine.drug_class.code
        for g in (iodine, other):
            assert Drug.query.filter_by(generic_id=g.id).count()


# --------------------------------------------- honest about the market

def test_every_name_added_here_is_on_the_egyptian_register(seeded):
    """Swept over this wave rather than spot-checked, and that is affordable
    because every row in it was read off the register in the first place. A
    brand nobody can buy is a brand a doctor picks and a pharmacy cannot fill.
    """
    names = " | ".join(row[0].upper() for row in _register_rows())
    unknown = sorted({trade for trade, _ in _wave_four()
                      if trade.upper() not in names})
    assert unknown == [], f"not on any Egyptian register: {unknown}"


def test_erythromycin_ships_no_brand_and_the_register_says_why(seeded):
    """The one ingredient left with no product behind it, on purpose.

    Both halves are checked against the register, so the day a suspension
    comes back this test is what notices.
    """
    from app.models import Drug, GenericDrug

    oral = [row for row in _register_rows()
            if row[2] == "ERYTHROMYCIN" and row[4].startswith("ORAL")]
    assert oral, "the register no longer lists any oral erythromycin"
    assert all("(N/A)" in row[0] for row in oral), \
        "an oral erythromycin is on the market again — it should be listed"

    with seeded["app"].app_context():
        g = GenericDrug.query.filter_by(name_en="Erythromycin").first()
        assert g.dose_per_kg, "the ingredient lost the dose it was kept for"
        assert Drug.query.filter_by(generic_id=g.id).count() == 0


def test_the_millilitres_come_from_the_amoxicillin_not_from_the_box(seeded):
    """A file-wide invariant, and the exception is the interesting half.

    Where a label reads "N mg/5 ml" the concentration is that arithmetic —
    except co-amoxiclav, where the printed number is amoxicillin *plus*
    clavulanate and the dose is worked out from the amoxicillin alone. 457
    means 400 + 57, and 457/5 = 91.4 would overdose nobody but would make
    every millilitre on the screen wrong by a seventh.
    """
    from app.utils.drugbook_seed import BRANDS

    combined = {"156 mg/5 ml": 25, "312 mg/5 ml": 50, "457 mg/5 ml": 80,
                "642 mg/5 ml": 120}
    checked = 0
    for trade, generic, form, strength, conc, maker in BRANDS:
        label = (strength or "").strip()
        if generic == "Amoxicillin/Clavulanate" and label in combined:
            assert conc == combined[label], \
                f"{trade} {label} is dosed off the combined number"
            checked += 1
            continue
        split = re.fullmatch(r"(\d+(?:\.\d+)?) mg/(\d+(?:\.\d+)?)? ?ml", label)
        if not split:
            continue
        per_ml = float(split.group(1)) / float(split.group(2) or 1)
        assert conc is not None and abs(conc - per_ml) < 0.001, \
            f"{trade} says {label} and carries {conc} mg/ml"
        checked += 1
    assert checked > 100, "the sweep stopped matching labels"


# ------------------------------------------------ and it reaches a clinic

def test_a_clinic_that_already_ran_the_seed_gets_the_new_shelf(seeded):
    """The whole point of the top-up, checked on this wave: a clinic that
    installed before any of these existed gets them on the next update, and
    keeps everything of its own."""
    from app.models import Drug, GenericDrug
    from app.utils.drugbook_seed import seed_drugbook

    db = seeded["db"]
    with seeded["app"].app_context():
        g = GenericDrug.query.filter_by(
            name_en="Dexpanthenol (topical)").first()
        mine = Drug.query.filter_by(trade_name="Sudocrem").first()
        mine.manufacturer = "اللي العيادة كتبته"
        Drug.query.filter_by(generic_id=g.id).delete()
        db.session.delete(g)
        db.session.commit()

        seed_drugbook()
        db.session.commit()

        back = GenericDrug.query.filter_by(
            name_en="Dexpanthenol (topical)").first()
        assert back is not None
        assert {d.trade_name for d in
                Drug.query.filter_by(generic_id=back.id).all()} >= {
                    "Bepanthen", "Adcopantin"}
        assert Drug.query.filter_by(
            trade_name="Sudocrem").first().manufacturer == "اللي العيادة كتبته"
