"""Two doses of one vaccine in one visit, and nothing said.

Reported: *"note that when I tried it from inside the visit I added two doses
in the same visit — I don't know how. Shouldn't a warning come up? It has a
schedule it can understand."*

It does have one, and it wasn't reading it at the moment it mattered.
``administer_dose`` refused a repeat of the same dose **number** and checked
nothing else, so dose 1 and then dose 2 on the same day passed every guard it
had: a different number, not yet given, stock on the shelf. Two doses of one
antigen minutes apart, recorded in silence.

The minimum interval was already in the program — the catch-up scheduler reads
it to decide when a dose *falls due*, and it was the subject of an earlier fix.
So the number was being carried and simply never consulted where somebody was
about to put a needle in a child.

**A warning, not a block**, in the same spirit as the brand-mix flag beside it:
a dose given elsewhere and typed in late, or a correction to a mis-entered
record, are both legitimate, and the person entering them knows which it is.
What is not acceptable is silence.

The test that matters most is the one that says nothing happens: two
*different* vaccines in one visit is ordinary paediatric practice, and a guard
that cried wolf on it would be turned off within a week.
"""
import os
import sys
from datetime import timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# `interval_warning` counts from `local_today()`, so a dose backdated with
# `date.today()` is a different number of days old whenever UTC and Cairo
# disagree — which they do from 21:00 UTC. "five days ago" read as six.
from app.utils.clock import local_today  # noqa: E402

import pytest  # noqa: E402


@pytest.fixture()
def room(clinic):
    """The visit room, signed in as the doctor."""
    return clinic["sign_in"]("doc")


def _give(client, visit_id, vaccine_id, brand_id=None, **extra):
    data = {"vaccine_id": vaccine_id}
    if brand_id:
        data["brand_id"] = brand_id
    data.update(extra)
    return client.post(f"/visits/{visit_id}/give-vaccine", data=data,
                       follow_redirects=True)


def _warned(reply):
    """The warning is a flash, so its wording is the only thing the doctor
    sees — checking the record would pass on a guard that fired into a log."""
    from app.i18n import t

    body = reply.get_data(as_text=True)
    marker = t("vaccinations.interval_warn").split("{")[0].strip()
    return marker and marker in body


# ================================================== the reported behaviour ==
def test_a_second_dose_the_same_day_is_flagged(clinic, room):
    """The reported case, reproduced: two doses of one vaccine in one visit."""
    ids = clinic["ids"]
    with clinic["app"].test_request_context("/"):
        first = _give(room, ids["visit"], ids["pcv"], ids["brand"])
        assert first.status_code == 200
        second = _give(room, ids["visit"], ids["pcv"], ids["brand"])
        assert _warned(second), (
            "the second dose went in without a word — this is the bug")


def test_the_dose_is_still_recorded(clinic, room):
    """A warning, not a block. Refusing outright would make a mis-typed record
    unfixable and a dose given elsewhere unenterable."""
    from app.models import PatientVaccine

    ids = clinic["ids"]
    _give(room, ids["visit"], ids["pcv"], ids["brand"])
    _give(room, ids["visit"], ids["pcv"], ids["brand"])
    with clinic["app"].app_context():
        given = PatientVaccine.query.filter_by(
            patient_id=ids["child"], vaccine_id=ids["pcv"],
            event_type="given").count()
        assert given == 2


def test_two_different_vaccines_in_one_visit_say_nothing(clinic, room):
    """The test that keeps the guard usable. Giving a child two vaccines in one
    visit is ordinary practice — a warning here would be noise, and a warning
    everybody learns to click past protects nobody."""
    ids = clinic["ids"]
    with clinic["app"].test_request_context("/"):
        _give(room, ids["visit"], ids["pcv"], ids["brand"])
        other = _give(room, ids["visit"], ids["opv"], ids["gov_brand"])
        assert not _warned(other)


def test_a_first_dose_is_never_flagged(clinic, room):
    ids = clinic["ids"]
    with clinic["app"].test_request_context("/"):
        assert not _warned(_give(room, ids["visit"], ids["pcv"], ids["brand"]))


# ============================================================== the rule ====
def test_the_warning_stops_once_the_interval_has_passed(clinic):
    """Otherwise every second dose of every course would be flagged, which is
    the same as flagging none of them."""
    from app.models import Patient, PatientVaccine, Vaccine
    from app.utils.vaccines import interval_warning

    ids = clinic["ids"]
    with clinic["app"].app_context():
        vaccine = clinic["db"].session.get(Vaccine, ids["pcv"])
        patient = clinic["db"].session.get(Patient, ids["child"])
        clinic["db"].session.add(PatientVaccine(
            patient_id=patient.id, vaccine_id=vaccine.id, brand_id=ids["brand"],
            dose_number=1, given_date=local_today() - timedelta(days=60),
            event_type="given"))
        clinic["db"].session.commit()
        assert interval_warning(patient.id, vaccine) is None


def test_the_warning_fires_inside_the_interval(clinic):
    from app.models import Patient, PatientVaccine, Vaccine
    from app.utils.vaccines import interval_warning

    ids = clinic["ids"]
    with clinic["app"].app_context():
        vaccine = clinic["db"].session.get(Vaccine, ids["pcv"])
        patient = clinic["db"].session.get(Patient, ids["child"])
        clinic["db"].session.add(PatientVaccine(
            patient_id=patient.id, vaccine_id=vaccine.id, brand_id=ids["brand"],
            dose_number=1, given_date=local_today() - timedelta(days=5),
            event_type="given"))
        clinic["db"].session.commit()
        warn = interval_warning(patient.id, vaccine)
        assert warn and warn["days"] == 5
        assert warn["minimum"] >= 28
        assert warn["previous_dose"] == 1


def test_the_vaccines_own_interval_wins_over_the_default(clinic):
    """The default is a floor for the vaccines whose source schedule never
    stated one. Where the catalogue does state it, that is the number."""
    from app.models import Patient, PatientVaccine, Vaccine
    from app.utils.vaccines import interval_warning

    ids = clinic["ids"]
    with clinic["app"].app_context():
        vaccine = clinic["db"].session.get(Vaccine, ids["pcv"])
        vaccine.min_interval_days = 56
        patient = clinic["db"].session.get(Patient, ids["child"])
        clinic["db"].session.add(PatientVaccine(
            patient_id=patient.id, vaccine_id=vaccine.id, brand_id=ids["brand"],
            dose_number=1, given_date=local_today() - timedelta(days=40),
            event_type="given"))
        clinic["db"].session.commit()
        warn = interval_warning(patient.id, vaccine)
        assert warn and warn["minimum"] == 56, "40 days is fine at 28, not at 56"


def test_a_backdated_dose_does_not_cry_wolf(clinic):
    """Typing a child's history off the parent's card enters doses *older* than
    what is on file. Reading that as "too soon" would flag every history a
    clinic ever enters."""
    from app.models import Patient, PatientVaccine, Vaccine
    from app.utils.vaccines import interval_warning

    ids = clinic["ids"]
    with clinic["app"].app_context():
        vaccine = clinic["db"].session.get(Vaccine, ids["pcv"])
        patient = clinic["db"].session.get(Patient, ids["child"])
        clinic["db"].session.add(PatientVaccine(
            patient_id=patient.id, vaccine_id=vaccine.id, brand_id=ids["brand"],
            dose_number=2, given_date=local_today(), event_type="given"))
        clinic["db"].session.commit()
        older = local_today() - timedelta(days=90)
        assert interval_warning(patient.id, vaccine, older) is None


def test_a_child_with_no_doses_at_all_is_fine(clinic):
    from app.models import Patient, Vaccine
    from app.utils.vaccines import interval_warning

    ids = clinic["ids"]
    with clinic["app"].app_context():
        assert interval_warning(
            clinic["db"].session.get(Patient, ids["child"]).id,
            clinic["db"].session.get(Vaccine, ids["pcv"])) is None


# ========================================================== both doorways ===
def test_the_vaccinations_screen_warns_too(clinic):
    """Two ways in, and a guard on one of them is a guard somebody walks
    around — the same shape as the booking pause that covered one door."""
    from app.models import PatientVaccine

    ids = clinic["ids"]
    nurse = clinic["sign_in"]("doc")
    nurse.post(f"/vaccinations/{ids['child']}/record",
               data={"vaccine_id": ids["pcv"], "brand_id": ids["brand"]},
               follow_redirects=True)
    reply = nurse.post(f"/vaccinations/{ids['child']}/record",
                       data={"vaccine_id": ids["pcv"], "brand_id": ids["brand"]},
                       follow_redirects=True)
    with clinic["app"].test_request_context("/"):
        assert _warned(reply)
    with clinic["app"].app_context():
        assert PatientVaccine.query.filter_by(
            patient_id=ids["child"], vaccine_id=ids["pcv"],
            event_type="given").count() == 2


def test_the_warning_names_the_date_and_the_gap(clinic):
    """"Too soon" on its own leaves the doctor to go and look up when the last
    one was — which is the moment they decide it is not worth the trouble."""
    from app.i18n import t

    with clinic["app"].test_request_context("/"):
        text = t("vaccinations.interval_warn")
    for field in ("{vaccine}", "{dose}", "{days}", "{date}", "{min}"):
        assert field in text, field
