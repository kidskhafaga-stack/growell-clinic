"""The vaccination tab on a child's file, and the question it should answer.

It listed the doses already given as a row of chips and stopped there —
"Doses recorded: 1", and one badge. Everything on it was true and none of it
was what somebody has the file open to find out.

**The certificate and this tab do different jobs.** A certificate is a record
handed to a family: what the child *had*, and it is right for it to look
backwards. This is read while a doctor or the desk is deciding something, so
it has to answer *where does this child stand* — what is owed, when, and
whether each course is finished.

So it is built from the plan rather than from the dose rows. The rows can only
say what happened; the plan knows what is coming, which is the half that was
missing.

The shape borrows from the certificate's cards, and the reason those exist
applies here too: a flat list in date order puts the three doses of one course
pages apart, so "has this child finished the pneumococcal?" can only be
answered by reading everything and counting. The card carries its own ``2/4``,
which is that question in three characters.
"""
import os
import sys
from datetime import timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

from app.utils.clock import local_today  # noqa: E402


@pytest.fixture()
def child(clinic):
    """A child part-way through one course: two doses given, two owed."""
    from app.extensions import db
    from app.models import Patient, PatientVaccine, Vaccine, VaccineBrand

    from app.utils.vaccines import seed_vaccines, seed_vaccine_schedules

    with clinic["app"].app_context():
        seed_vaccines()
        seed_vaccine_schedules()
        db.session.commit()
        pcv = Vaccine.query.filter_by(code="PCV").first()
        brand = VaccineBrand.query.filter_by(vaccine_id=pcv.id,
                                             name="Prevenar 13").first()
        kid = Patient(patient_number="VT1", full_name="طفل", gender="female",
                      # Under two, so the course is the infant series and this
                      # file measures the *display* rather than the schedule.
                      # At two and a half the pneumococcal catch-up applies and
                      # "2/4" becomes "2/3" — a true change that has nothing to
                      # do with what this test is about.
                      date_of_birth=local_today() - timedelta(days=400),
                      is_active=True)
        db.session.add(kid)
        db.session.flush()
        for number in (1, 2):
            db.session.add(PatientVaccine(
                patient_id=kid.id, vaccine_id=pcv.id, brand_id=brand.id,
                dose_number=number, event_type="given",
                given_date=kid.date_of_birth + timedelta(days=60 * number)))
        db.session.commit()
        clinic["kid_id"] = kid.id
    return clinic


def _page(child, patient_id=None):
    return child["sign_in"]("boss").get(
        f"/patients/{patient_id or child['kid_id']}",
        follow_redirects=True).data.decode()


# ------------------------------------------------- what is owed, and when

def test_it_says_what_is_due_next(child):
    """The question the tab exists for, and the one it could not answer."""
    from app.i18n import t

    page = _page(child)

    with child["app"].test_request_context("/"):
        assert t("vaccinations.next_due") in page


def test_the_next_dose_carries_a_date_and_a_state(child):
    """"Something is due" without a date is a feeling, not a next step."""
    import re

    page = _page(child)
    block = re.search(r"calendar-event.*?</div>\s*</div>\s*</div>", page, re.S)

    assert block, "the next-due card is not rendered"
    assert re.search(r"\d{4}-\d{2}-\d{2}", block.group(0)), \
        "the next dose is announced with no date"


def test_a_child_who_owes_nothing_is_not_told_they_do(child):
    """A card that always shows is one nobody reads."""
    from app.extensions import db
    from app.models import Patient

    with child["app"].app_context():
        # A newborn: everything is upcoming, nothing due or overdue yet.
        kid = Patient(patient_number="VT2", full_name="رضيع", gender="male",
                      date_of_birth=local_today(), is_active=True)
        db.session.add(kid)
        db.session.commit()
        kid_id = kid.id

    assert "calendar-event" not in _page(child, kid_id)


# ------------------------------------------------- has the course finished

def test_each_course_says_how_far_along_it_is(child):
    """Two of four, in three characters, instead of counting rows."""
    page = _page(child)

    assert "2/4" in page, "the course does not say how far along it is"


def test_the_doses_given_are_still_listed_under_their_course(child):
    """Grouped, not lost. The record is still the record."""
    page = _page(child)

    assert page.count("bi-check-circle") >= 2


def test_a_child_with_nothing_recorded_reads_as_empty(child):
    from app.extensions import db
    from app.i18n import t
    from app.models import Patient

    with child["app"].app_context():
        kid = Patient(patient_number="VT3", full_name="جديد", gender="male",
                      date_of_birth=local_today() - timedelta(days=20),
                      is_active=True)
        db.session.add(kid)
        db.session.commit()
        kid_id = kid.id

    page = _page(child, kid_id)
    with child["app"].test_request_context("/"):
        assert t("vaccinations.none_recorded") in page


# --------------------------------------------------- it is still a summary

def test_the_full_record_is_still_one_press_away(child):
    """The tab is a glance; the screen that owns the doing is elsewhere."""
    page = _page(child)

    assert f"/vaccinations/{child['kid_id']}" in page


def test_it_does_not_redraw_the_whole_schedule(child):
    """Every vaccine the catalogue knows would be forty cards on a tab.

    Only courses with a dose recorded get a card — the same rule the
    certificate follows, and the reason it reads as a record rather than a
    catalogue.
    """
    page = _page(child)
    panel = page[page.index("tab==='vaccinations'"):]
    panel = panel[:panel.index("gc-tab-panel", 40)] if "gc-tab-panel" in panel[40:] else panel

    assert panel.count("bi-box") <= 4, \
        "the tab is drawing the whole catalogue rather than the child's record"
