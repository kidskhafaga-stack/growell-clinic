"""When the program will not answer.

Approved as the last layer of the engine, and the one it cannot reach by being
cleverer: *any case it cannot establish from age, history, intervals, brand,
guideline and eligibility — it will not guess. It returns Clinical Review
Required rather than producing an unverified medical reminder.*

Everything else in the schedule decides **what** to do. This decides when the
honest answer is that nobody here can decide.

It looks only for records the arithmetic cannot run on at all:

    two doses numbered 1     the course is a different length depending
                             which of them is the mistake
    dates out of order       the record contradicts its own numbering
    more doses than doses    more on file than the schedule has room for
    a dose with no date      every interval and ceiling is computed from
                             dates; one missing makes the rest arithmetic
                             on a hole

Deliberately narrow. A flag for anything a doctor might want a second opinion
about would land on everybody, and a warning on every row is one nobody reads.

**And it stops the message, not only the screen.** The file shows the flag; the
reminder sweep skips the course entirely. "It will not guess" has to reach the
message too, or the guess simply travels further — to a family, as a date.
"""
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

from app.utils.clock import local_today  # noqa: E402


@pytest.fixture()
def seeded(clinic):
    from app.extensions import db

    from app.models import Setting

    from app.utils.vaccines import seed_vaccines, seed_vaccine_schedules

    with clinic["app"].app_context():
        seed_vaccines()
        seed_vaccine_schedules()
        # These use pneumococcal as the vehicle for something else — a
        # duplicated dose, an interval rule, a progress bar — and the Egyptian
        # profile deliberately computes no pneumococcal schedule at all, so
        # there would be no course here to measure any of it against. The
        # leaflet is followed instead: the vehicle has to be a course that
        # exists.
        Setting.set("vaccine_guideline_profile", "manufacturer")
        db.session.commit()
    return clinic


def _course(seeded, tag, doses):
    """`doses` as [(dose_number, days_after_birth)] — duplicates allowed."""
    from app.extensions import db
    from app.models import Patient, PatientVaccine, Vaccine, VaccineBrand
    from app.utils.vaccine_due import due_list
    from app.utils.vaccines import patient_plan

    with seeded["app"].app_context():
        pcv = Vaccine.query.filter_by(code="PCV").first()
        brand = VaccineBrand.query.filter_by(vaccine_id=pcv.id,
                                             name="Prevenar 13").first()
        dob = local_today() - timedelta(days=900)
        kid = Patient(patient_number=f"CR{tag}", full_name="طفل",
                      gender="male", date_of_birth=dob, is_active=True)
        db.session.add(kid)
        db.session.flush()
        for number, days in doses:
            db.session.add(PatientVaccine(
                patient_id=kid.id, vaccine_id=pcv.id, brand_id=brand.id,
                dose_number=number, event_type="given",
                given_date=dob + timedelta(days=days)))
        db.session.commit()
        row = next(v for v in patient_plan(kid) if v["vaccine"].code == "PCV")
        chased = any(r["patient"].id == kid.id and r["vaccine"].code == "PCV"
                     for r in due_list())
        return row.get("review"), chased, kid.id


# ------------------------------------------------- what it refuses to answer

def test_a_clean_record_is_scheduled_normally(seeded):
    """The half that keeps the flag meaning something."""
    review, chased, _ = _course(seeded, "ok", [(1, 60), (2, 120)])

    assert review is None
    assert chased is True


def test_two_doses_under_one_number(seeded):
    """Either one is a duplicate or a number is wrong, and the course is a
    different length depending which."""
    review, chased, _ = _course(seeded, "dup", [(1, 60), (1, 120)])

    assert review == "duplicate_dose"
    assert chased is False


def test_dates_that_contradict_their_numbering(seeded):
    review, chased, _ = _course(seeded, "ord", [(1, 200), (2, 60)])

    assert review == "out_of_order"
    assert chased is False


def test_more_doses_than_the_schedule_has_room_for(seeded):
    review, chased, _ = _course(seeded, "many",
                                [(1, 60), (2, 90), (3, 120), (4, 150), (5, 200)])

    assert review == "more_than_scheduled"
    assert chased is False


def test_a_dose_with_no_date(seeded):
    """Checked directly: `given_date` is NOT NULL, so no row can carry this
    today — which is exactly why it is worth pinning. The guard is unreachable
    through the database and would rot unnoticed until somebody relaxes the
    column or builds a row in memory.
    """
    from app.utils.vaccines import needs_clinical_review

    with seeded["app"].app_context():
        assert needs_clinical_review(
            date(2020, 1, 1), [(1, 2), (2, 4)], [(1, None)]) == "undated_dose"


# ----------------------------------------------------- it stops the message

def test_the_sweep_will_not_send_about_a_record_it_cannot_read(seeded):
    """The half that makes it a safeguard rather than a label.

    A date computed from a contradiction is worse on a family's phone than on
    a screen, because nobody can see what it was computed from.
    """
    _review, chased, _ = _course(seeded, "msg", [(1, 200), (2, 60)])

    assert chased is False


def test_the_other_path_will_not_send_about_it_either(seeded):
    """The sweep is not the only way a message is composed.

    `due_list` reads flat columns; `patient_due_reminders` walks one child's
    ORM rows, and the WhatsApp recall for a single patient goes through the
    second. Measured: with the guard removed from the ORM path alone, every
    test here still passed, because they all asked the sweep. Two doors, and
    only one of them was being tried.
    """
    from app.extensions import db
    from app.models import Patient
    from app.utils.vaccines import doses_for, patient_due_reminders

    _review, _chased, patient_id = _course(seeded, "orm", [(1, 200), (2, 60)])

    with seeded["app"].app_context():
        kid = db.session.get(Patient, patient_id)
        sent = patient_due_reminders(
            kid, "ar", local_today(),
            doses=doses_for([patient_id]).get(patient_id, []))

    assert not [r for r in sent if r["vaccine"].code == "PCV"], \
        "the per-patient path still composed a reminder from a record it " \
        "cannot read"


def test_the_file_says_so_where_the_doctor_is_looking(seeded):
    from app.i18n import t

    _review, _chased, patient_id = _course(seeded, "ui", [(1, 200), (2, 60)])

    page = seeded["sign_in"]("boss").get(f"/patients/{patient_id}",
                                         follow_redirects=True).data.decode()

    with seeded["app"].test_request_context("/"):
        assert t("vreview.title") in page


# --------------------------------------------------------- it stays narrow

def test_it_does_not_fire_on_an_ordinary_late_course(seeded):
    """Being behind is not being unreadable. A flag that lands on everybody
    teaches the clinic to ignore it."""
    review, chased, _ = _course(seeded, "late", [(1, 60)])

    assert review is None
    assert chased is True


def test_four_winters_are_not_a_contradiction(seeded):
    """The narrowness promise, measured on the case that broke it.

    Influenza is one dose in the catalogue and a five-year-old has had four.
    Read as "more doses than the schedule has room for" that is a
    contradiction; read as four winters it is an ordinary record, and it is
    four winters. The same is true of rabies and typhoid, which are given
    when something happens rather than as a course of a fixed length.

    This was live before it was caught: **every returning influenza patient in
    the register** read "clinical review required", and because the flag also
    stops the message, their annual recall went quiet. The existing narrowness
    test used PCV — a fixed course — and could not see it.
    """
    from app.extensions import db
    from app.models import Patient, PatientVaccine, Vaccine, VaccineBrand
    from app.utils.vaccine_due import due_list
    from app.utils.vaccines import patient_plan

    with seeded["app"].app_context():
        flu = Vaccine.query.filter_by(code="FLU").first()
        brand = VaccineBrand.query.filter_by(vaccine_id=flu.id).first()
        dob = local_today() - timedelta(days=int(5 * 365.25))
        kid = Patient(patient_number="CRflu", full_name="طفل", gender="male",
                      date_of_birth=dob, is_active=True)
        db.session.add(kid)
        db.session.flush()
        for number, years in ((1, 1.0), (2, 2.0), (3, 3.0)):
            db.session.add(PatientVaccine(
                patient_id=kid.id, vaccine_id=flu.id, brand_id=brand.id,
                dose_number=number, event_type="given",
                given_date=dob + timedelta(days=int(years * 365.25))))
        db.session.commit()

        row = next(v for v in patient_plan(kid) if v["vaccine"].code == "FLU")
        chased = any(r["patient"].id == kid.id and r["vaccine"].code == "FLU"
                     for r in due_list())

    assert row["review"] is None, \
        f"a child with four winters of influenza was flagged: {row['review']}"
    assert chased, "the annual influenza recall went silent"


def test_a_fixed_course_still_counts_its_doses(seeded):
    """The other half — otherwise "repeatable" could quietly be everything."""
    review, _chased, _ = _course(seeded, "fixed", [(1, 60), (2, 120), (3, 180),
                                                   (4, 240), (5, 300)])

    assert review == "more_than_scheduled"


def test_every_reason_it_can_give_has_words(seeded):
    """A flag with no explanation sends somebody hunting for what is wrong."""
    from app.utils.vaccines import REVIEW_REASONS

    assert set(REVIEW_REASONS) == {"undated_dose", "duplicate_dose",
                                   "more_than_scheduled", "out_of_order"}
    for reason, text in REVIEW_REASONS.items():
        assert text and len(text) > 10, reason


def test_the_wording_exists_in_both_languages(seeded):
    import json

    here = os.path.dirname(os.path.abspath(__file__))
    for lang in ("ar", "en"):
        with open(os.path.join(here, "..", "app/i18n/locales", f"{lang}.json"),
                  encoding="utf-8") as fh:
            block = json.load(fh)["vreview"]
        for key in ("title", "hint"):
            assert key in block, f"{lang} is missing vreview.{key}"
