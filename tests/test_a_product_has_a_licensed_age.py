"""Don't offer somebody a course their vial is not licensed to give them.

The instruction, after the screen that started this: *"ده مش منطقي — أنا عارف
إنه بيحسب صح، بس ميطلعش حاجة مش مناسبة للسن."* Hiding a stale date was not
enough. A woman of twenty-nine was still being offered the infant hexavalent,
the infant pentavalent, paediatric DT and the measles-varicella combination —
nine doses of products that cannot be given to an adult at all.

**Where the number comes from matters more than the number.** The doctor's
other instruction in the same breath was *"واحنا شغالين على المصنع خليه هو
الافتراضي"* — the leaflet is what is actually being quoted across the desk, so
make it the default. That is also what supplies the answer here: the ceiling
is not this program's clinical opinion about when a course is pointless, it is
the licensed age range printed on the product, in the column
`max_age_final_dose_days` that has held exactly that fact since rotavirus was
fixed.

So the ceilings written are the ones the labels state:

  * every DTaP/DTwP-containing paediatric combination — hexavalent,
    pentavalent, Pentaxim, the government DTP booster and paediatric DT —
    stops before the seventh birthday, which is where Tdap and Td take over;
  * Priorix Tetra is licensed to and including twelve years, the same shape
    ProQuad already carried.

**And nothing else.** Varicella, meningococcal ACWY, Bexsero, HPV, typhoid and
influenza have no upper age on their labels, so they keep none here — which is
why an adult is still offered ten doses and every one of them is a dose she
could actually be given. A ceiling invented to tidy a screen would be this
program deciding a clinical question, and it would be wrong in the direction
that costs somebody a vaccine.

A shut course does not vanish. It moves to a shelf of its own, because the
shelf it was landing on is headed *"not yet time"* and these are the opposite
— and it stays on the page so a dose given elsewhere can still be recorded.
"""
import os
import sys
from datetime import timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

from app.utils.clock import local_today  # noqa: E402

# The products whose labels state a paediatric-only range, and the age at
# which each stops. Held here as well as in the catalogue so that a ceiling
# quietly dropped from the JSON fails a test instead of a patient.
PAEDIATRIC_ONLY = ("HEXA", "PENTAXIM", "PENTA", "DTP_B", "DT")


@pytest.fixture()
def seeded(clinic):
    from app.extensions import db

    from app.utils.vaccines import seed_vaccines, seed_vaccine_schedules

    with clinic["app"].app_context():
        seed_vaccines()
        seed_vaccine_schedules()
        db.session.commit()
    return clinic


_COUNTER = [0]


def _offered(seeded, years):
    """{vaccine code: [dose numbers offered]} for somebody of `years`."""
    from app.extensions import db
    from app.models import Patient
    from app.utils.vaccines import GIVEABLE, patient_plan

    _COUNTER[0] += 1
    with seeded["app"].app_context():
        dob = local_today() - timedelta(days=int(years * 365.25))
        person = Patient(patient_number=f"LA{_COUNTER[0]}", full_name="مريض",
                         gender="female", date_of_birth=dob, is_active=True)
        db.session.add(person)
        db.session.commit()
        out = {}
        for item in patient_plan(person):
            owed = [d["dose_number"] for d in item["doses"]
                    if d["status"] in GIVEABLE]
            if owed:
                out[item["vaccine"].code] = owed
        return out


# ------------------------------------------------- the reported screen

def test_an_adult_is_not_offered_an_infant_course(seeded):
    """The nine doses that were left after the dates were hidden."""
    offered = _offered(seeded, 29)

    still_there = [code for code in PAEDIATRIC_ONLY if code in offered]
    assert not still_there, \
        f"a twenty-nine-year-old is being offered {still_there}"
    assert "MMRV" not in offered, \
        "the measles-varicella combination is licensed to twelve, not to adults"


def test_and_is_still_offered_what_she_can_actually_have(seeded):
    """The other half, and the one that keeps this honest.

    An adult can be given varicella, meningococcal ACWY, Bexsero, HPV to
    forty-five, typhoid and influenza — none of those labels carries an upper
    age. A change that quietly emptied the screen would look like a fix and
    would be a clinic no longer offering vaccines it should.
    """
    offered = _offered(seeded, 29)

    for code in ("VARICELLA", "FLU", "MENACWY", "MENB", "HPV", "TYPHOID"):
        assert code in offered, \
            f"{code} has no upper age on its label and stopped being offered"


# ------------------------------------------ and the ordinary child is untouched

@pytest.mark.parametrize("years,code", [
    (0.5, "HEXA"), (0.5, "PENTAXIM"),
    (3, "HEXA"), (3, "PENTAXIM"),
    (6.5, "HEXA"),
    (8, "MMRV"), (11, "MMRV"),
])
def test_the_ceiling_does_not_reach_the_children_it_is_not_about(
        seeded, years, code):
    """Inside the licensed range nothing moved.

    Six and a half years is the edge deliberately: the seventh birthday is the
    ceiling, and a child six months short of it is still inside it. A rule
    that closed a window early would take a catch-up away from exactly the
    children who most need one.
    """
    assert code in _offered(seeded, years), \
        f"a {years}-year-old inside the licensed range lost {code}"


@pytest.mark.parametrize("code", PAEDIATRIC_ONLY)
def test_and_it_does_reach_the_far_side_of_it(seeded, code):
    """Eight years old: past the seventh birthday, so the DTaP-containing
    products are done. Paired with the test above so "the ceiling exists" and
    "the ceiling is in the right place" are two failures, not one."""
    assert code not in _offered(seeded, 8), \
        f"{code} is still being offered past its licensed age"


# --------------------------------------------------- what the shelf now says

def test_a_shut_course_stops_reading_as_not_yet_time(seeded):
    """It was landing under *"لسه بدري عليها"* — too early. For a
    twenty-nine-year-old and the infant hexavalent that is the exact opposite
    of the truth, and a heading that says the opposite of the truth is worse
    than no heading."""
    from app.extensions import db
    from app.models import Patient
    from app.utils.vaccines import PLAN_GROUPS, group_plan, patient_plan

    assert "closed" in PLAN_GROUPS

    with seeded["app"].app_context():
        dob = local_today() - timedelta(days=int(29 * 365.25))
        grown = Patient(patient_number="LAshelf", full_name="مريض",
                        gender="female", date_of_birth=dob, is_active=True)
        db.session.add(grown)
        db.session.commit()
        shelves = dict(group_plan(patient_plan(grown)))

    closed = {item["vaccine"].code for item in shelves.get("closed", [])}
    later = {item["vaccine"].code for item in shelves.get("later", [])}

    assert set(PAEDIATRIC_ONLY) <= closed, \
        f"a shut course is not on the shut shelf: {closed}"
    assert not (set(PAEDIATRIC_ONLY) & later), \
        f"a shut course is still filed under 'not yet': {later}"


def test_the_shut_shelf_is_on_the_page_and_closed(seeded):
    """Kept rather than hidden: the row is what a doctor clicks to record a
    dose given somewhere else, and a course nobody can start is still part of
    a child's history. Collapsed, because it is not a task."""
    import re

    from app.extensions import db
    from app.models import Patient
    from app.utils.vaccines import OPEN_GROUPS

    assert "closed" not in OPEN_GROUPS

    with seeded["app"].app_context():
        dob = local_today() - timedelta(days=int(29 * 365.25))
        grown = Patient(patient_number="LApage", full_name="مريض",
                        gender="female", date_of_birth=dob, is_active=True)
        db.session.add(grown)
        db.session.commit()
        pid = grown.id

    page = seeded["sign_in"]("boss").get(
        f"/vaccinations/{pid}").get_data(as_text=True)

    import json

    with open("app/i18n/locales/ar.json", encoding="utf-8") as fh:
        heading = json.load(fh)["vaccinations"]["group_closed"]
    assert heading in page, "the shut shelf has no heading on the page"
    assert not any(" open" in tag for tag in
                   re.findall(r"<details[^>]*vac-group[^>]*>", page)), \
        "a shelf opened on a patient who has started nothing"


def test_a_dose_already_given_survives_the_window_shutting(seeded):
    """A shut course still has to show what happened. The record is why the
    family carries the certificate at all."""
    from app.extensions import db
    from app.models import Patient, PatientVaccine, Vaccine, VaccineBrand
    from app.utils.vaccines import patient_plan

    with seeded["app"].app_context():
        hexa = Vaccine.query.filter_by(code="HEXA").first()
        brand = (VaccineBrand.query.filter_by(vaccine_id=hexa.id)
                 .order_by(VaccineBrand.id).first())
        dob = local_today() - timedelta(days=int(10 * 365.25))
        kid = Patient(patient_number="LAgiven", full_name="طفل",
                      gender="male", date_of_birth=dob, is_active=True)
        db.session.add(kid)
        db.session.flush()
        db.session.add(PatientVaccine(
            patient_id=kid.id, vaccine_id=hexa.id, brand_id=brand.id,
            dose_number=1, event_type="given",
            given_date=dob + timedelta(days=60)))
        db.session.commit()
        row = next(v for v in patient_plan(kid) if v["vaccine"].code == "HEXA")

    assert [d["dose_number"] for d in row["doses"] if d["status"] == "done"] \
        == [1], f"the dose the child had disappeared with the window: {row}"


# ------------------------------------------ the ceiling is the label's, not ours

def test_every_ceiling_written_is_one_a_label_states(seeded):
    """The guard on the whole change.

    Adding a ceiling is the one edit here that can silently cost somebody a
    vaccine, so the set of products that carry one is pinned. A ceiling
    appearing on a product whose label states none — because it tidied a
    screen — fails this.
    """
    from app.extensions import db
    from app.models import Vaccine, VaccineBrand

    with seeded["app"].app_context():
        capped = set()
        for brand in VaccineBrand.query.all():
            if brand.max_age_final_dose_days:
                vaccine = db.session.get(Vaccine, brand.vaccine_id)
                capped.add(vaccine.code)

    # Rotavirus, hepatitis A, Synflorix, ProQuad, Trumenba and HPV were
    # already capped from their own labels; this branch added the DTaP family
    # and Priorix Tetra.
    expected = {"ROTA", "HAV", "PCV", "MMRV", "MENB", "HPV",
                "HEXA", "PENTAXIM", "PENTA", "DTP_B", "DT"}
    assert capped == expected, \
        f"the set of products carrying a licensed-age ceiling changed: {capped}"


def test_the_seventh_birthday_is_where_the_dtap_family_stops(seeded):
    """And the number itself, so a typo in the catalogue is a failing test
    rather than a child turned away at six."""
    from app.models import Vaccine, VaccineBrand

    seven_years = 2557
    with seeded["app"].app_context():
        for code in PAEDIATRIC_ONLY:
            vaccine = Vaccine.query.filter_by(code=code).first()
            for brand in VaccineBrand.query.filter_by(
                    vaccine_id=vaccine.id).all():
                assert brand.max_age_final_dose_days == seven_years, \
                    (f"{code}/{brand.name} stops at "
                     f"{brand.max_age_final_dose_days} days, not the seventh "
                     f"birthday")


# ------------------------------------------------------------- and the default

def test_switching_off_the_old_default_moves_nothing(seeded):
    """The measurement the new default rests on, kept as a test.

    `egypt` states no schedule outside the national programme, and inside it
    the rows are the leaflet's anyway — so naming the leaflet as the default
    changes what the settings screen honestly says and not one child's dates.
    If that ever stops being true, the two profiles have diverged and somebody
    has to decide which one a clinic should be on, rather than finding out
    from a schedule that moved under them.
    """
    from app.extensions import db
    from app.models import Patient, Setting
    from app.utils.vaccines import patient_plan

    with seeded["app"].app_context():
        kids = []
        for months in (2, 6, 12, 18, 24, 48, 72, 120, 192, 348):
            dob = local_today() - timedelta(days=int(months * 30.44))
            kid = Patient(patient_number=f"LAsw{months}", full_name="طفل",
                          gender="male", date_of_birth=dob, is_active=True)
            db.session.add(kid)
            kids.append((months, kid))
        db.session.commit()

        def snapshot(profile):
            Setting.set("vaccine_guideline_profile", profile)
            db.session.commit()
            return {(months, item["vaccine"].code):
                    tuple((d["dose_number"], d["status"], d["due_date"])
                          for d in item["doses"])
                    for months, kid in kids for item in patient_plan(kid)}

        egypt = snapshot("egypt")
        leaflet = snapshot("manufacturer")

    moved = {key for key in egypt if egypt[key] != leaflet[key]}
    assert egypt, "nothing was compared"
    assert not moved, \
        f"the two profiles have diverged on {len(moved)} course(s): {sorted(moved)[:5]}"
