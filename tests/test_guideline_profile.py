"""Which published guideline the clinic follows, as a setting.

The same product can carry two positions. Bexsero's course is the European
label's from two months and the CDC's from ten years — one product, two
references, both correct where they are followed. A clinic that changes its
policy must not need a developer, and must not re-enter a single dose.

So the brand stores the reference schedules and the clinic picks the source.
`source` has been on the schedule template since it was built; what changed is
that the engine reads the clinic's choice instead of assuming the leaflet.

**Two rules make the setting safe to change.**

*The leaflet fills the gaps.* No guideline covers every product a clinic
stocks. A profile whose silence left a vaccine unscheduled would turn "we
follow the CDC" into "we stopped scheduling half the fridge", so where the
chosen guideline says nothing about a product, its leaflet still applies.

*But silence about an **age** is an answer.* Where the guideline does speak
about a product and does not schedule a child that age — the CDC and a
three-month-old on Bexsero — the honest result is no course at all. Falling
back to the brand's raw dose rows there would answer with a number from no
guideline, which is worse than either of them.
"""
import os
import sys
from datetime import timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

from app.utils.clock import local_today  # noqa: E402


@pytest.fixture()
def seeded(clinic):
    from app.extensions import db

    from app.utils.vaccines import seed_vaccines, seed_vaccine_schedules

    with clinic["app"].app_context():
        seed_vaccines()
        seed_vaccine_schedules()
        db.session.commit()
    return clinic


def _follow(seeded, profile):
    from app.extensions import db
    from app.models import Setting

    with seeded["app"].app_context():
        Setting.set("vaccine_guideline_profile", profile)
        db.session.commit()


def _bexsero(seeded, tag, start_years, age_years):
    """A child on Bexsero whose first dose was at `start_years`."""
    from app.extensions import db
    from app.models import Patient, PatientVaccine, Vaccine, VaccineBrand
    from app.utils.vaccines import patient_plan

    with seeded["app"].app_context():
        menb = Vaccine.query.filter_by(code="MENB").first()
        brand = VaccineBrand.query.filter_by(vaccine_id=menb.id,
                                             name="Bexsero").first()
        dob = local_today() - timedelta(days=int(age_years * 365.25))
        kid = Patient(patient_number=f"GL{tag}", full_name="طفل",
                      gender="male", date_of_birth=dob, is_active=True)
        db.session.add(kid)
        db.session.flush()
        db.session.add(PatientVaccine(
            patient_id=kid.id, vaccine_id=menb.id, brand_id=brand.id,
            dose_number=1, event_type="given",
            given_date=dob + timedelta(days=int(start_years * 365.25))))
        db.session.commit()
        row = next(v for v in patient_plan(kid) if v["vaccine"].code == "MENB")
        return len(row["doses"])


# ------------------------------------------------------------- the setting

def test_the_default_is_the_egyptian_programme(seeded):
    """Unset, an Egyptian clinic follows the Egyptian programme.

    Not merely "some default": this is the country the program is written for,
    and a clinic should not have to choose a reference before it can read a
    vaccination screen.
    """
    from app.models import VaccineScheduleTemplate
    from app.utils.vaccines import guideline_profile

    with seeded["app"].app_context():
        assert guideline_profile() == "egypt"
        assert (VaccineScheduleTemplate.DEFAULT_GUIDELINE_PROFILE
                in VaccineScheduleTemplate.GUIDELINE_PROFILES), \
            "the default is not one of the references that can be chosen"


def test_nonsense_falls_back_to_the_default(seeded):
    """A typo in a settings row must not leave the engine with no reference."""
    from app.utils.vaccines import guideline_profile

    _follow(seeded, "whatever")
    with seeded["app"].app_context():
        assert guideline_profile() == "egypt"


def test_it_is_set_from_the_settings_screen(seeded):
    from app.models import Setting
    from app.utils.vaccines import guideline_profile

    seeded["sign_in"]("boss").post("/settings/", data={
        "vaccine_guideline_profile": "cdc"}, follow_redirects=True)

    with seeded["app"].app_context():
        assert Setting.get("vaccine_guideline_profile") == "cdc"
        assert guideline_profile() == "cdc"


# --------------------------------------------------- it changes the answer

def test_switching_the_profile_recomputes_the_same_records(seeded):
    """The whole point: one policy change, no data re-entered.

    A sixteen-year-old starting Bexsero is two doses either way — the age the
    references agree on. A three-month-old is where they part.
    """
    _follow(seeded, "manufacturer")
    assert _bexsero(seeded, "a", 0.25, 1.0) == 4

    _follow(seeded, "cdc")
    assert _bexsero(seeded, "b", 0.25, 1.0) == 0, \
        "the CDC does not schedule Bexsero at three months"


def test_where_the_references_agree_nothing_moves(seeded):
    """Otherwise "it changed" would mean nothing — it has to change only where
    the guidelines actually differ.

    Measured at sixteen. It used to be measured at twelve, which was a place
    the two references agreed only because the CDC's row said "from ten
    years" — the age its *risk-based* recommendation begins, not its routine
    one. Its routine position for a healthy adolescent starts at sixteen, and
    that is where the two now meet: the European label's two doses from eleven
    years, and the CDC's two doses from sixteen.
    """
    _follow(seeded, "manufacturer")
    leaflet = _bexsero(seeded, "c", 16.2, 17.0)

    _follow(seeded, "cdc")
    cdc = _bexsero(seeded, "d", 16.2, 17.0)

    assert leaflet == cdc == 2


# ------------------------------------------------------------- the two rules

def test_a_product_the_guideline_ignores_keeps_its_leaflet(seeded):
    """No guideline covers a whole fridge. Silence about a *product* is not a
    decision to stop scheduling it.

    Measured on Menveo rather than on a plain course, deliberately. Its
    leaflet bands give a child starting at nine months **two** doses while the
    brand's own dose rows give one — so dropping the leaflet from the query is
    visible here and invisible anywhere the two agree. An early version of
    this test used such a place and passed under the mutation.

    It used to be measured on Vaxneuvance, and that stopped being a fair
    example the moment the CDC's pneumococcal table was written down: the CDC
    does not ignore pneumococcal any more, so a Vaxneuvance child under the
    CDC now gets the CDC's catch-up, which is the whole point of following it.
    Meningococcal ACWY is the honest example now — every band it has comes
    from a leaflet, and no guideline set in this catalogue speaks about it.
    """
    from app.extensions import db
    from app.models import Patient, PatientVaccine, Vaccine, VaccineBrand
    from app.utils.vaccines import patient_plan

    _follow(seeded, "cdc")
    with seeded["app"].app_context():
        mcv = Vaccine.query.filter_by(code="MENACWY").first()
        brand = VaccineBrand.query.filter_by(vaccine_id=mcv.id,
                                             name="Menveo").first()
        dob = local_today() - timedelta(days=int(1.2 * 365.25))
        kid = Patient(patient_number="GLmen", full_name="طفل", gender="male",
                      date_of_birth=dob, is_active=True)
        db.session.add(kid)
        db.session.flush()
        db.session.add(PatientVaccine(
            patient_id=kid.id, vaccine_id=mcv.id, brand_id=brand.id,
            dose_number=1, event_type="given",
            given_date=dob + timedelta(days=int(9 * 30.4))))
        db.session.commit()
        row = next(v for v in patient_plan(kid)
                   if v["vaccine"].code == "MENACWY")

    assert row["brand"].name == "Menveo"
    assert len(row["doses"]) == 2, \
        "the leaflet's own bands were dropped for a product the CDC ignores"


def test_the_guideline_wins_over_the_leaflet_for_the_same_product(seeded):
    """And the rule that decides between them when both speak.

    Measured, after writing Pfizer's pneumococcal catch-up down where it
    belongs — on the brand — silently replaced the chosen guideline's table
    for every child on that vial, because it is the default one. The five-year
    ceiling vanished and a partial record the reference declines to guess at
    came back with an invented date.

    A trade name's schedule replacing the vaccine's is right *between two
    leaflets*. Between a leaflet and the reference the clinic has chosen, the
    reference wins: a clinic following the CDC wants the CDC's catch-up
    whichever vial is in the fridge.

    `egypt` is not one of the profiles tested here, and that is not an
    oversight. It states no pneumococcal rule at all, so there is no contest
    for this ordering to settle — the leaflet answers because nothing else
    does, which is a different mechanism and is held in
    `test_the_pneumococcal_catch_up.py`.
    """
    from app.extensions import db
    from app.models import Patient, PatientVaccine, Vaccine, VaccineBrand
    from app.utils.vaccines import patient_plan

    def ten_year_old(profile, tag):
        _follow(seeded, profile)
        with seeded["app"].app_context():
            pcv = Vaccine.query.filter_by(code="PCV").first()
            brand = VaccineBrand.query.filter_by(vaccine_id=pcv.id,
                                                 name="Prevenar 13").first()
            dob = local_today() - timedelta(days=int(10 * 365.25))
            kid = Patient(patient_number=f"GLw{tag}", full_name="طفل",
                          gender="male", date_of_birth=dob, is_active=True)
            db.session.add(kid)
            db.session.flush()
            for number, months in ((1, 2), (2, 4), (3, 6)):
                db.session.add(PatientVaccine(
                    patient_id=kid.id, vaccine_id=pcv.id, brand_id=brand.id,
                    dose_number=number, event_type="given",
                    given_date=dob + timedelta(days=int(months * 30.4))))
            db.session.commit()
            row = next(v for v in patient_plan(kid)
                       if v["vaccine"].code == "PCV")
            return [d for d in row["doses"] if d["status"] != "done"]

    # Prevenar 13's own label offers a single dose to a child of this age.
    assert ten_year_old("manufacturer", "m"), \
        "the leaflet stopped answering for a clinic that follows the leaflet"

    # The CDC ends the routine course at five, and says so about pneumococcal
    # rather than about a trade name — so it wins here.
    assert not ten_year_old("cdc", "c"), \
        "a brand's leaflet overruled the guideline the clinic follows"
    assert not ten_year_old("who", "w"), \
        "a brand's leaflet overruled the guideline the clinic follows"


def test_silence_about_an_age_is_an_answer(seeded):
    """And the difference from the rule above. The CDC does speak about
    Bexsero; it does not schedule a three-month-old for it. Answering with the
    brand's raw rows there would be a number from no guideline at all."""
    _follow(seeded, "cdc")

    assert _bexsero(seeded, "e", 0.25, 1.0) == 0


# ------------------------------------------------------- no product in code

def test_the_engine_never_branches_on_a_product_name(seeded):
    """The standing rule this exists for: policy is data.

    Naming a product is fine — the seeded bands carry trade names as *values*,
    and the comments explain which leaflet a rule came from. What must never
    appear is a **comparison**: `if brand.name == "Bexsero"` is the shape that
    turns a guideline change into a code change, and it is what this looks for.

    Parsed rather than grepped, because the first version of this test read
    the file as text and failed on its own documentation.
    """
    import ast

    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, "..", "app/utils/vaccines.py")
    with open(path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())

    products = {"Bexsero", "Vaxneuvance", "Prevenar 13", "Prevenar 20",
                "Synflorix", "Gardasil 9", "RotaRix", "RotaTeq"}
    offences = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            for side in [node.left, *node.comparators]:
                if isinstance(side, ast.Constant) and side.value in products:
                    offences.append((side.value, node.lineno))
        elif isinstance(node, ast.Call):
            for arg in node.args:
                if isinstance(arg, ast.Constant) and arg.value in products:
                    offences.append((arg.value, node.lineno))

    assert not offences, \
        f"the engine branches on a trade name instead of reading data: {offences}"


def test_both_references_are_kept_side_by_side(seeded):
    """Switching back has to be possible, so neither may overwrite the other."""
    from app.models import Vaccine, VaccineScheduleTemplate

    with seeded["app"].app_context():
        menb = Vaccine.query.filter_by(code="MENB").first()
        sources = {t.source for t in VaccineScheduleTemplate.query
                   .filter_by(vaccine_id=menb.id)
                   .filter(VaccineScheduleTemplate.start_age_min_months
                           .isnot(None)).all()}

    assert {"manufacturer", "cdc"} <= sources


def test_the_wording_exists_in_both_languages(seeded):
    import json

    here = os.path.dirname(os.path.abspath(__file__))
    # Read off the list the engine actually uses, so a reference cannot be
    # added to the picker and reach a clinic as a blank line.
    from app.models import VaccineScheduleTemplate

    keys = ["guideline_profile", "guideline_profile_hint"] + [
        f"guideline_{p}" for p in VaccineScheduleTemplate.GUIDELINE_PROFILES]
    for lang in ("ar", "en"):
        with open(os.path.join(here, "..", "app/i18n/locales", f"{lang}.json"),
                  encoding="utf-8") as fh:
            block = json.load(fh)["settings"]
        for key in keys:
            assert key in block, f"{lang} is missing settings.{key}"


def test_every_reference_can_be_picked_and_every_source_can_be_written(seeded):
    """The picker offers what the engine reads, and the editor can write it.

    Both were hand-written lists once. The settings picker named three of the
    references and the schedule editor named four of the sources, and `cdc`
    was in neither — so a clinic could be handed a CDC schedule and had no way
    to correct one.
    """
    from app.models import Vaccine, VaccineScheduleTemplate

    client = seeded["sign_in"]("boss")
    page = client.get("/settings/").get_data(as_text=True)
    for profile in VaccineScheduleTemplate.GUIDELINE_PROFILES:
        assert f'value="{profile}"' in page, \
            f"the settings picker cannot choose {profile}"

    with seeded["app"].app_context():
        vaccine_id = Vaccine.query.first().id
    editor = client.get(
        f"/vaccinations/manage/vaccine/{vaccine_id}/schedules"
    ).get_data(as_text=True)
    for source in VaccineScheduleTemplate.SOURCES:
        assert f'value="{source}"' in editor, \
            f"the schedule editor cannot author a {source} row"
