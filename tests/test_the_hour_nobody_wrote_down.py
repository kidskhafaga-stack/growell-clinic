"""The hour of birth, and the refusal to invent one.

Jaundice thresholds in the first days of life move **by the hour**.
``Patient.date_of_birth`` is a ``Date``, so without a time the program is
working up to twenty-four hours out — and at 48 hours of age that gap is the
whole distance between "go home" and "start phototherapy".

The field is optional, because most of what a clinic is told about a birth is
a parent's memory rather than a discharge summary. What it must never be is
*assumed*: a stored midnight is indistinguishable from a baby actually born at
midnight, and a computed age built on one would be silently wrong for half the
register with nothing on the screen to say so.
"""
from datetime import time, timedelta

import pytest


@pytest.fixture
def baby(clinic):
    """A newborn, with the hour recorded."""
    from app.models import Patient
    from app.utils.clock import local_now

    with clinic["app"].app_context():
        now = local_now().replace(tzinfo=None)
        born = now - timedelta(hours=30)
        row = Patient(patient_number="NB1", full_name="مولود", gender="male",
                      date_of_birth=born.date(), birth_time=time(born.hour,
                                                                 born.minute),
                      gestation_weeks=36, gestation_days=4, is_active=True)
        clinic["db"].session.add(row)
        clinic["db"].session.commit()
        yield row


def test_it_counts_the_hours(clinic, baby):
    with clinic["app"].app_context():
        assert 29.5 < baby.age_hours < 30.5


def test_no_hour_recorded_is_none_and_never_a_number(clinic, baby):
    """The whole point. A number here would be a guess wearing a
    measurement's clothes."""
    with clinic["app"].app_context():
        baby.birth_time = None
        clinic["db"].session.commit()
        assert baby.age_hours is None


def test_midnight_is_a_real_hour_and_not_a_blank(clinic, baby):
    """A baby born at 00:00 has an hour recorded. If blank were stored as
    midnight the two would be the same row, and this is the test that says
    they are not."""
    from app.utils.clock import local_now

    with clinic["app"].app_context():
        today = local_now().replace(tzinfo=None).date()
        baby.date_of_birth = today
        baby.birth_time = time(0, 0)
        clinic["db"].session.commit()
        assert baby.age_hours is not None
        assert baby.age_hours >= 0


def test_it_runs_on_the_clinic_s_clock(clinic, baby, monkeypatch):
    """The birth date and hour were written down by somebody standing in the
    clinic, so the "now" they are subtracted from has to be the same clock.
    `datetime.now()` here would be out by the whole offset, all day, on any
    install whose server sits in another zone — the bug already found once
    across thirty-one test files."""
    import app.models.patient as patient_module

    calls = []
    real = patient_module.local_now

    def spy(*args, **kwargs):
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(patient_module, "local_now", spy)
    with clinic["app"].app_context():
        baby.age_hours
    assert calls, "age_hours read a clock that is not the clinic's"


# ------------------------------------------------------------ the form ------
def test_the_form_takes_it(clinic):
    page = clinic["sign_in"]("boss").get(
        "/patients/new").get_data(as_text=True)
    assert 'name="birth_time"' in page
    assert 'type="time"' in page
    assert "patients.birth_time" not in page, "untranslated key on the screen"


def test_saving_it_keeps_it(clinic):
    from app.models import Patient

    boss = clinic["sign_in"]("boss")
    boss.post("/patients/new", data={
        "full_name": "مولود جديد", "gender": "male",
        "date_of_birth": "2026-08-30", "birth_time": "14:30",
        "gestation_weeks": "36", "gestation_days": "4", "is_active": "1",
    }, follow_redirects=True)
    with clinic["app"].app_context():
        row = Patient.query.filter_by(full_name="مولود جديد").first()
        assert row is not None
        assert row.birth_time == time(14, 30)


def test_leaving_it_blank_stores_nothing(clinic):
    from app.models import Patient

    boss = clinic["sign_in"]("boss")
    boss.post("/patients/new", data={
        "full_name": "طفل بدون ساعة", "gender": "female",
        "date_of_birth": "2026-08-30", "birth_time": "", "is_active": "1",
    }, follow_redirects=True)
    with clinic["app"].app_context():
        row = Patient.query.filter_by(full_name="طفل بدون ساعة").first()
        assert row is not None
        assert row.birth_time is None, "a blank hour became a stored one"


def test_the_edit_form_shows_it_back(clinic, baby):
    with clinic["app"].app_context():
        baby.birth_time = time(9, 5)
        clinic["db"].session.commit()
        patient_id = baby.id
    page = clinic["sign_in"]("boss").get(
        f"/patients/{patient_id}/edit").get_data(as_text=True)
    assert 'value="09:05"' in page


def test_an_unreadable_time_is_refused_not_swallowed(clinic):
    from app.models import Patient

    boss = clinic["sign_in"]("boss")
    boss.post("/patients/new", data={
        "full_name": "ساعة غلط", "gender": "male",
        "date_of_birth": "2026-08-30", "birth_time": "not-a-time",
        "is_active": "1",
    }, follow_redirects=True)
    with clinic["app"].app_context():
        assert Patient.query.filter_by(full_name="ساعة غلط").first() is None


def test_the_column_is_in_the_upgrade_list(clinic):
    """Clinics upgrade in place; a column added only to the model arrives on
    a running install as "no such column"."""
    from app.utils.schema import ADDITIONS

    assert any(table == "patients" and column == "birth_time"
               for table, column, _type in ADDITIONS)
