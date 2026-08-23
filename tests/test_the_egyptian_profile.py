"""`egypt` is a reference in its own right, not another one wearing a name.

The clinic this program is written for is Egyptian, so the reference it
follows out of the box is the Egyptian programme rather than a leaflet chosen
because it was the safest thing to default to.

The rule that matters more than the default, and the reason this file exists
apart from the profile's own tests: **a profile must be the source of its own
rules.** It would have been easy to add `egypt` to a settings picker and have
the engine quietly read the CDC's rows whenever it was chosen — the screens
would look right, the schedules would be right, and the sentence the clinic
reads in its settings would be false. A clinic that is told it follows the
Egyptian programme and is in fact being scheduled by the CDC cannot audit its
own practice, and cannot correct a rule it cannot see.

So the tests below are mostly about what `egypt` does **not** get. Where the
Egyptian programme says nothing — every vaccine outside the national schedule,
which is most of the optional shelf — the leaflet answers, exactly as it does
for any other profile with a gap. That is the documented fallback, not a
back door: the leaflet is a statement about the product and is available to
everybody, and no other *guideline's* rows are ever read for a clinic
following this one.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


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


def _sources_in_play(seeded):
    """Every `source` the banded engine actually loaded, for this clinic."""
    from app.utils.vaccines import _banded_templates

    with seeded["app"].app_context():
        loaded = _banded_templates()
        return {band["source"] for bands in loaded.values() for band in bands}


def test_it_is_one_of_the_references_a_clinic_can_follow(seeded):
    from app.models import VaccineScheduleTemplate

    assert "egypt" in VaccineScheduleTemplate.GUIDELINE_PROFILES
    assert "egypt" in VaccineScheduleTemplate.SOURCES


def test_following_it_never_reads_another_guideline_s_rows(seeded):
    """The anti-alias test. Nothing tagged `cdc` or `who` may reach a clinic
    that follows the Egyptian programme.

    A CDC band is planted where the engine cannot miss it, and the engine is
    then asked what it loaded. If `egypt` were ever implemented as "read the
    CDC's rows", this is the assertion that would go red.
    """
    from app.extensions import db
    from app.models import (Vaccine, VaccineScheduleDose,
                            VaccineScheduleTemplate)

    with seeded["app"].app_context():
        pcv = Vaccine.query.filter_by(code="PCV").first()
        tpl = VaccineScheduleTemplate(
            vaccine_id=pcv.id, code="PLANTED-CDC", source="cdc",
            label="planted", is_active=True, is_catch_up=False,
            start_age_min_months=0, start_age_max_months=None,
            match_age_on="today")
        db.session.add(tpl)
        db.session.flush()
        db.session.add(VaccineScheduleDose(
            template_id=tpl.id, dose_number=1, recommended_age_months=0))
        db.session.commit()

    _follow(seeded, "egypt")
    assert "cdc" not in _sources_in_play(seeded), \
        "a clinic following the Egyptian programme was handed a CDC schedule"

    # And the control: the same planted row *is* read once the clinic says it
    # follows the CDC — so the assertion above is about the profile and not
    # about the row being unreachable.
    _follow(seeded, "cdc")
    assert "cdc" in _sources_in_play(seeded)


# ------------------------------- pneumococcal: the leaflet, and it says so

def _pcv(seeded, age_months, dose_ages=()):
    """Returns ``(review, [(number, status)], the band's label)``."""
    from datetime import timedelta

    from app.extensions import db
    from app.models import Patient, PatientVaccine, Vaccine, VaccineBrand
    from app.utils.clock import local_today
    from app.utils.vaccines import patient_plan

    _EG[0] += 1
    with seeded["app"].app_context():
        pcv = Vaccine.query.filter_by(code="PCV").first()
        brand = VaccineBrand.query.filter_by(vaccine_id=pcv.id,
                                             name="Prevenar 13").first()
        dob = local_today() - timedelta(days=int(age_months * 30.44))
        kid = Patient(patient_number=f"EG{_EG[0]}", full_name="طفل",
                      gender="male", date_of_birth=dob, is_active=True)
        db.session.add(kid)
        db.session.flush()
        for number, age in enumerate(dose_ages, start=1):
            db.session.add(PatientVaccine(
                patient_id=kid.id, vaccine_id=pcv.id, brand_id=brand.id,
                dose_number=number, event_type="given",
                given_date=dob + timedelta(days=int(age * 30.44))))
        db.session.commit()
        row = next(v for v in patient_plan(kid) if v["vaccine"].code == "PCV")
        return (row.get("review"),
                [(d["dose_number"], d["status"]) for d in row["doses"]],
                row.get("rule"))


_EG = [0]


def test_it_states_no_pneumococcal_schedule_of_its_own(seeded):
    """Pneumococcal is not in the national programme and no Egyptian clinical
    reference states a catch-up. The Drug Authority's assessment of a
    marketing application is not one: it carries the manufacturer's table,
    reviewed and approved — the leaflet with a different letterhead.

    So the profile has no rows here. It neither invents a schedule nor borrows
    another body's under its own name.
    """
    from app.models import Vaccine, VaccineScheduleTemplate

    with seeded["app"].app_context():
        pcv = Vaccine.query.filter_by(code="PCV").first()
        mine = VaccineScheduleTemplate.query.filter_by(
            vaccine_id=pcv.id, source="egypt", is_active=True).count()

    assert mine == 0, \
        "the Egyptian profile is asserting a pneumococcal schedule again"


def test_the_leaflet_answers_and_the_child_still_gets_a_schedule(seeded):
    """Saying nothing is not the same as computing nothing. The loader's
    ordinary fallback hands the question to the product's leaflet, which is
    what an Egyptian paediatrician is working from in any case."""
    from app.utils.vaccines import GIVEABLE

    review, doses, _label = _pcv(seeded, 2)

    assert review is None, f"a two-month-old was handed a question: {review}"
    assert len(doses) == 4, f"not the leaflet's infant series: {doses}"
    assert [n for n, status in doses if status in GIVEABLE], \
        "nothing is offerable for a child due their first dose"


def test_the_answer_says_whose_it_is(seeded):
    """The line worth being careful about: a fallback the doctor cannot see is
    a number from nowhere.

    It was not visible at all until this was written. The engine knew which
    band produced a child's dates and said nothing, so "3 doses" looked the
    same whether it came from the reference the clinic follows, from the
    vial's leaflet because the reference is silent about the product, or from
    the brand's raw rows because nothing banded applies. Three different
    degrees of authority, one identical number.

    An earlier version of this file put ACIP's numbers under a bare Egyptian
    label, and a settings screen reading "you follow the Egyptian programme"
    over another body's rules leaves a clinic unable to audit its own
    practice. Naming the rule is what makes a borrowing a statement rather
    than a disguise.
    """
    _review, _doses, rule = _pcv(seeded, 36)

    assert rule, "the plan does not say which rule produced these dates"
    assert "Prevenar" in rule, \
        f"the schedule does not say which product it came from: {rule!r}"


def test_the_screen_shows_it_too(seeded):
    """In the plan is not on the card. This is the screen a doctor works from.

    Asserted against the rule's **own text**, not against the product name:
    the first version of this looked for "Prevenar" and passed with the badge
    deleted, because the trade name is already on the card as the brand. A
    check that cannot fail is not a check.
    """
    from datetime import timedelta

    from app.extensions import db
    from app.models import Patient
    from app.utils.clock import local_today
    from app.utils.vaccines import patient_plan

    with seeded["app"].app_context():
        kid = Patient(patient_number="EGscreen", full_name="طفل",
                      gender="male", is_active=True,
                      date_of_birth=local_today() - timedelta(days=1100))
        db.session.add(kid)
        db.session.commit()
        kid_id = kid.id
        rule = next(v for v in patient_plan(kid)
                    if v["vaccine"].code == "PCV")["rule"]

    assert rule, "there is no rule to show"
    page = seeded["sign_in"]("boss").get(
        f"/vaccinations/{kid_id}").get_data(as_text=True)

    # The dash the labels are built with survives templating; the rest of the
    # sentence is what identifies the rule.
    fragment = rule.split("—")[-1].strip()[:24]
    assert fragment and fragment in page, (
        f"the vaccination screen does not carry the rule that produced these "
        f"dates: {rule!r}")


def test_the_old_egyptian_rows_are_retired_on_a_clinic_that_has_them(seeded):
    """Seeding only ever adds — it keys on (vaccine, code, source) — so
    deleting rows from the catalogue does nothing to an install that already
    has them. A clinic created last month would go on being scheduled by rows
    a clinic created tomorrow never gets: same program, same settings, two
    answers depending on the install date."""
    from app.utils.vaccines import _RETAGGED_BANDS

    for code in ("PCV-EG-CU7", "PCV-EG-CU12", "PCV-EG-CU2Y",
                 "PCV-EG-END", "PCV-EG-INF"):
        assert _RETAGGED_BANDS.get(code, "absent") is None, \
            f"{code} is not retired by the upgrade"
