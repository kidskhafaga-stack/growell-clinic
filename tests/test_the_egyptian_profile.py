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


def test_the_leaflet_still_fills_what_the_programme_does_not_run(seeded):
    """PCV is not in the Egyptian national schedule, and that is a fact about
    Egypt rather than a hole in the program.

    A private-market vaccine here is given on its leaflet, which is what the
    catalogue has always said in prose. So `egypt` says nothing about it and
    the manufacturer's rows answer — the same fallback every profile has, not
    a special case written for this one.
    """
    _follow(seeded, "egypt")
    assert "manufacturer" in _sources_in_play(seeded)


# ------------------------------------------ and what it will not invent

def _pcv(seeded, age_months, dose_ages=()):
    """Returns ``(review reason, [(dose number, status)])`` for a child."""
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
        return row.get("review"), [(d["dose_number"], d["status"])
                                   for d in row["doses"]]


_EG = [0]


@pytest.mark.parametrize("age_months,given", [
    (2, ()),            # a newborn, and yes — this one too
    (9, ()),
    (14, (13,)),
    (36, (2, 4, 6)),
    (120, (2, 4, 6)),
])
def test_it_states_no_pneumococcal_schedule_of_its_own(seeded, age_months,
                                                        given):
    """The decision this file's opening paragraph is about, applied.

    This profile carried a pneumococcal table, and the numbers in it were
    sound — they were ACIP's. That was exactly the objection. Writing another
    body's table down and putting `egypt` on it makes the settings screen say
    something untrue, and a clinic told it follows the Egyptian programme
    cannot then audit its own practice.

    The Egyptian Drug Authority's assessment of Prevenar 13 does not fill the
    gap either: a public assessment report is the regulator reading the
    *manufacturer's* dossier, and the schedule inside it is the leaflet's.
    Registration is permission to sell, not a decision about what to give a
    child.

    So it says the true thing — recommended, no schedule this program may
    compute — for every child, including the two-month-old. That is the cost
    and it is deliberate: a profile that answers honestly for the hard cases
    and invents for the easy ones would be worth less than one that does
    neither.
    """
    from app.utils.vaccines import GIVEABLE

    review, doses = _pcv(seeded, age_months, given)

    assert review == "guideline_unsettled", \
        f"the Egyptian profile answered with a schedule it does not have: {doses}"
    assert not [n for n, status in doses if status in GIVEABLE], \
        f"doses were computed anyway: {doses}"


def test_it_still_shows_the_doses_a_child_actually_had(seeded):
    """Not knowing what comes next is no reason to lose what happened."""
    _review, doses = _pcv(seeded, 36, (2, 4, 6))

    assert [n for n, status in doses if status == "done"] == [1, 2, 3]


def test_the_leaflet_answers_for_a_clinic_that_follows_the_leaflet(seeded):
    """And the way out, which is the same one the decision named: a doctor who
    wants Prevenar 13's own numbers follows the leaflet, under its own source.

    Held here rather than left implied — without it, "Egypt states nothing"
    would be the whole story, and a clinic would have no route to a schedule
    at all.
    """
    from app.extensions import db
    from app.models import Setting
    from app.utils.vaccines import GIVEABLE

    with seeded["app"].app_context():
        Setting.set("vaccine_guideline_profile", "manufacturer")
        db.session.commit()

    review, doses = _pcv(seeded, 36, ())

    assert review is None, f"the leaflet stopped answering: {review}"
    assert [n for n, status in doses if status in GIVEABLE] == [1], \
        f"not the label's single dose for a child of three: {doses}"


def test_the_retired_rows_stop_applying_on_a_clinic_that_has_them(seeded):
    """Seeding only ever adds — it keys on (vaccine, code, source) — so
    removing a band from the catalogue does nothing whatever to an install
    that already has it. Five rows have to be retired by the upgrade, or the
    table this decision removed goes on scheduling children for ever."""
    from app.models import VaccineScheduleTemplate
    from app.utils.vaccines import _RETAGGED_BANDS, retag_moved_bands

    for code in ("PCV-EG-CU7", "PCV-EG-CU12", "PCV-EG-CU2Y",
                 "PCV-EG-END", "PCV-EG-INF"):
        assert _RETAGGED_BANDS.get(code, "missing") is None, \
            f"{code} is not retired by the upgrade"

    with seeded["app"].app_context():
        # Nothing seeded them this time, so there is nothing left to retire —
        # which is the idempotence that matters on a clinic that upgrades
        # twice.
        retag_moved_bands()
        assert not VaccineScheduleTemplate.query.filter(
            VaccineScheduleTemplate.code.like("PCV-EG-%"),
            VaccineScheduleTemplate.code != "PCV-EG-UNSET",
            VaccineScheduleTemplate.is_active.is_(True)).count()
