"""A single-doctor clinic must not be shown a ward.

Reported in the clinic's own words:

    «لو البرنامج شغال في عيادة، الملف يبقى متظبط على العيادة. لو شغال في
    مركز، يبقى متظبط على إنه مركز أو مستشفى. ولو عيادة دكتورين متخصصة برده
    كده — يعني الأقسام الداخلي في الملف متبقاش ظاهرة، علشان ما لغبطش
    الدكتور ويبص يلاقي حاجات هو مش محتاجها في عيادة.»

**The program already had the machinery**, and this suite is mostly here to
keep it honest. ``app/utils/facility.py`` is three layers — an administrative
*type* that only presets defaults, the *capabilities* a place actually offers,
and the *modules* those switch on — and ``beds``, ``theatres``, ``observations``
and the rest are in ``OPT_IN_MODULES``: off until somebody asks for them.

So the answer to «شكّل الملف حسب المنشأة» is not a fourth mechanism keyed on
the facility type. It is that **every inpatient surface on the file already
asks ``module_enabled``**, and the type only decides what the wizard ticks on
the way in. A two-doctor specialist clinic that *does* admit ticks day-care
and gets the ward; one that does not, never sees it. Keying the file on the
type instead would take that choice away from the place that has it.

What this suite pins is the *iff*, in both directions:

* a facility whose ward is off is served a file with **no trace** of one —
  not a hidden panel, not a heading, not a dead link;
* and a facility whose ward is on **does** get it, so nothing here can be
  satisfied by deleting the feature.

The second half matters as much as the first. A guard that only checked for
absence would pass on a program that had quietly stopped showing a hospital
its own admissions.
"""
import os
import sys
from datetime import timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

# **One known-equivalent gate, written down so nobody "tidies" it away.**
#
# The admit button in `profile.html` is wrapped in `module_enabled('beds')`,
# and mutation testing says that check cannot be observed: `_ward_context`
# already returns an empty `free_beds` and `has_beds=False` for a place whose
# ward is off, so the button's body never renders either way. It stays.
# Deleting it would leave the template correct only *because* of what the
# route happens to do, and a screen that reads a switch is easier to trust
# than one that trusts a caller.

#: What an inpatient department looks like **on the patient's file**. Each is
#: a mark the page only carries when that department exists.
WARD_MARKS = ('data-tab="stays"', "bi-hospital", "/beds/")
THEATRE_MARKS = ("data-operations", "/theatres/")
OBSERVATION_MARKS = ("/observations/",)


@pytest.fixture()
def build():
    """Stand a facility up exactly as the setup wizard would, and sign in."""
    from app import create_app
    from app.extensions import db

    made = {}

    def _build(kind, extra_caps=()):
        app = create_app("testing")
        with app.app_context():
            db.create_all()
            from app.models import Patient, User
            from app.utils import facility
            from app.utils.clock import local_today

            caps = list(facility.FACILITY_TYPES[kind]["caps"]) + list(extra_caps)
            modules = set(facility.BASE_MODULES)
            for cap in caps:
                modules |= facility.CAPABILITY_MODULES.get(cap, set())
            facility.apply_facility(kind, "منشأة", caps, sorted(modules))
            db.session.commit()

            boss = User(username="doc", full_name="د. أحمد", role="admin",
                        is_active=True)
            boss.set_password("secret")
            db.session.add(boss)
            db.session.flush()
            kid = Patient(patient_number="P1", full_name="طفل", gender="male",
                          is_active=True,
                          date_of_birth=local_today() - timedelta(days=900))
            db.session.add(kid)
            db.session.commit()
            client = app.test_client()
            client.post("/login", data={"username": "doc", "password": "secret"},
                        follow_redirects=True)
            made["app"], made["db"] = app, db
            return {"app": app, "db": db, "client": client, "kid": kid.id,
                    "on": facility.module_enabled}

    yield _build

    if made:
        with made["app"].app_context():
            made["db"].session.remove()


def _give_it_a_history(place):
    """A real stay and a real operation on this child's file.

    **Without this the whole suite is hollow.** A facility with no admissions
    serves a file with no stays tab whatever the gates say, so "the ward does
    not show" would pass on a program that had no gates at all — which is
    exactly what mutation testing said about the first draft of this file.

    The dangerous case is also this one: a clinic that ran a ward for a year
    and switched it off still *has* the rows.
    """
    from app.models import Patient
    from app.models.place import Bed, Space, Unit
    from app.models.theatre import Operation, Theatre
    from app.utils import beds as ward
    from app.utils.clock import local_today

    db = place["db"]
    unit = Unit(name="العنبر", kind="ward")
    room = Theatre(name="غرفة ١")
    db.session.add_all([unit, room])
    db.session.flush()
    space = Space(unit_id=unit.id, name="أوضة ١")
    db.session.add(space)
    db.session.flush()
    bed = Bed(space_id=space.id, name="سرير ١")
    db.session.add(bed)
    db.session.flush()

    child = db.session.get(Patient, place["kid"])
    stay = ward.admit(child, bed, reason="التهاب رئوي")
    db.session.commit()
    ward.discharge(stay, "home")
    db.session.add(Operation(patient_id=child.id, theatre_id=room.id,
                             procedure="استئصال لوز", on_date=local_today(),
                             admission_id=stay.id, status="done"))
    db.session.commit()
    return stay


def _file(place):
    return place["client"].get(
        "/patients/%s" % place["kid"]).get_data(as_text=True)


def _report(place):
    return place["client"].get(
        "/patients/%s/report" % place["kid"]).get_data(as_text=True)


# ------------------------------------------- every type the wizard offers --
@pytest.mark.parametrize("kind", [
    "single_doctor", "multi_doctor", "polyclinic", "medical_center",
    "pediatric_center", "specialized_center", "diagnostic_center",
])
def test_a_place_with_no_ward_is_served_a_file_with_no_ward_in_it(build, kind):
    """**The report, in the clinic's words.** Not hidden by a stylesheet and
    not one click away — absent from the page that was served."""
    place = build(kind)
    with place["app"].app_context():
        assert place["on"]("beds") is False
        html = _file(place)
        for mark in WARD_MARKS:
            assert mark not in html, "%s leaked %r" % (kind, mark)
        # And the observation chart with them: a place that does not watch
        # children hour by hour has no use for the button either.
        assert place["on"]("observations") is False
        for mark in OBSERVATION_MARKS:
            assert mark not in html, "%s leaked %r" % (kind, mark)


@pytest.mark.parametrize("kind", [
    "single_doctor", "multi_doctor", "polyclinic", "medical_center",
    "pediatric_center", "specialized_center", "diagnostic_center",
])
def test_a_place_that_does_not_operate_is_served_a_file_with_no_theatre(
        build, kind):
    place = build(kind)
    with place["app"].app_context():
        assert place["on"]("theatres") is False
        html = _file(place)
        for mark in THEATRE_MARKS:
            assert mark not in html, "%s leaked %r" % (kind, mark)


@pytest.mark.parametrize("kind", ["single_doctor", "multi_doctor",
                                  "medical_center"])
def test_the_printed_report_carries_no_department_the_place_does_not_have(
        build, kind):
    """The sheet that leaves the building. A heading over an empty table is
    the same confusion on paper, and harder to explain to a family."""
    from app.i18n import translate as t

    place = build(kind)
    with place["app"].app_context():
        html = _report(place)
        assert t("report.stays") not in html
        assert t("report.operations") not in html


# ----------------------------------------- and the other direction --------
def test_a_hospital_is_shown_all_of_it(build):
    """**The half that stops this being satisfied by deletion.** A guard that
    only looked for absence would pass on a program that had quietly stopped
    showing a hospital its own admissions — and with no stay on the file to
    show, it would pass on one that had no gates at all."""
    place = build("hospital")
    with place["app"].app_context():
        assert place["on"]("beds") is True
        assert place["on"]("theatres") is True
        stay = _give_it_a_history(place)
        html = _file(place)
        for mark in WARD_MARKS:
            assert mark in html, "a hospital lost %r" % mark
        for mark in THEATRE_MARKS:
            assert mark in html, "a hospital lost %r" % mark
        # The stay itself and the case in it, not merely the furniture.
        assert "التهاب رئوي" in html
        assert "استئصال لوز" in html
        assert "/beds/admission/%s" % stay.id in html


def test_a_two_doctor_clinic_that_does_admit_gets_the_ward(build):
    """**The type presets; the capability decides.** Keying the file on the
    facility type would take this choice away from the place that has it: a
    small specialist clinic that keeps children for the day is a clinic with
    a ward, whatever the word on its licence says."""
    place = build("multi_doctor", extra_caps=["day_care"])
    with place["app"].app_context():
        assert place["on"]("beds") is True
        assert "/beds/" in _file(place)


def test_the_same_clinic_without_that_capability_does_not(build):
    """The pair to the test above — one tick apart, and that is the whole
    design."""
    place = build("multi_doctor")
    with place["app"].app_context():
        assert place["on"]("beds") is False
        assert "/beds/" not in _file(place)


def test_a_place_that_stops_admitting_stops_seeing_its_old_admissions(build):
    """**The case that actually needs the gate.** A clinic with no ward has no
    admissions either, so hiding them is easy; a clinic that ran a ward for a
    year and switched it off still has every row. The file reads the switch
    each time it is drawn, so those rows go quiet — and they are not deleted,
    which is why switching back on brings them straight back."""
    from app.models import Setting

    place = build("hospital")
    with place["app"].app_context():
        _give_it_a_history(place)
        assert "التهاب رئوي" in _file(place)

        Setting.set("mod_enabled:beds", "0")
        Setting.set("mod_enabled:theatres", "0")
        place["db"].session.commit()
        html = _file(place)
        for mark in WARD_MARKS + THEATRE_MARKS:
            assert mark not in html, "a switched-off ward kept %r" % mark
        assert "التهاب رئوي" not in html
        assert "استئصال لوز" not in html

        # And nothing was thrown away: switched back on, it is all there.
        Setting.set("mod_enabled:beds", "1")
        Setting.set("mod_enabled:theatres", "1")
        place["db"].session.commit()
        assert "التهاب رئوي" in _file(place)


def test_a_clinic_that_only_watches_gets_the_chart_and_no_beds(build):
    """Observation is not admission — «a group of its own rather than a line
    inside inpatient» is already the code's own distinction, and the file has
    to keep it: a clinic that watches a child for four hours has somewhere to
    write the readings and still has no ward."""
    place = build("single_doctor", extra_caps=["observation"])
    with place["app"].app_context():
        assert place["on"]("observations") is True
        assert place["on"]("beds") is False
        html = _file(place)
        for mark in OBSERVATION_MARKS:
            assert mark in html
        for mark in WARD_MARKS:
            assert mark not in html
