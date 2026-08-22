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
