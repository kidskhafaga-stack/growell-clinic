"""A work list that remembers what somebody already did about it.

The list is rebuilt from birthdays and doses every time it opens, which is
right and has one consequence: a row worked yesterday comes back this morning
looking exactly like a row nobody has touched. Reception rings a family, the
family says "next month", and tomorrow the list says ring them.

A list that cannot remember is one people stop believing, and it fails
quietly: nobody complains, they just work the top of it and ignore the rest.

Three actions, differing only in how long they last — a call is a fact about
today, a snooze is a decision with a date on it, and a dismissal has no date.

**The dose number is part of the key, and that is the assertion worth having.**
Silencing a reminder about the second dose says nothing about the third.
Keyed on the patient and the vaccine alone, one phone call would take a child
off the list for the rest of their course, and nothing on any screen would
say so.

**Nothing is deleted and nothing hides without a way back.** The screen counts
what it is holding and gives it back on request, for the same reason the
opt-out is asked in one place: the failure that cannot be undone is a child
who silently stops being followed.
"""
import os
import sys
from datetime import timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

from app.utils.clock import local_today  # noqa: E402


@pytest.fixture()
def ward(clinic):
    """A child mid-course: dose 1 given long ago, so 2 and 3 are overdue."""
    from app.extensions import db
    from app.models import Patient, PatientVaccine, Vaccine, VaccineBrand

    from app.utils.vaccines import seed_vaccines

    with clinic["app"].app_context():
        seed_vaccines()
        db.session.commit()
        pcv = Vaccine.query.filter_by(code="PCV").first()
        brand = VaccineBrand.query.filter_by(vaccine_id=pcv.id,
                                             name="Prevenar 13").first()
        kid = Patient(patient_number="RA1", full_name="طفل", gender="male",
                      is_active=True,
                      date_of_birth=local_today() - timedelta(days=900))
        db.session.add(kid)
        db.session.flush()
        db.session.add(PatientVaccine(
            patient_id=kid.id, vaccine_id=pcv.id, brand_id=brand.id,
            dose_number=1, event_type="given",
            given_date=kid.date_of_birth + timedelta(days=60)))
        db.session.commit()
        clinic["kid_id"] = kid.id
        clinic["pcv_id"] = pcv.id
    return clinic


def _due(ward, **kw):
    from app.utils.vaccine_due import due_list

    return due_list(today=local_today(), **kw)


def _act(ward, action, dose_number=2, until=None):
    from app.extensions import db
    from app.models.reminder_action import ReminderAction, default_until

    with ward["app"].app_context():
        db.session.add(ReminderAction(
            patient_id=ward["kid_id"], vaccine_id=ward["pcv_id"],
            dose_number=dose_number, action=action,
            until=default_until(action, until)))
        db.session.commit()


# ------------------------------------------------------------ it remembers

def test_the_row_is_there_before_anybody_touches_it(ward):
    with ward["app"].app_context():
        rows = _due(ward)

    assert any(r["patient"].id == ward["kid_id"] for r in rows), \
        "the fixture is not overdue, so nothing below tests anything"


def test_a_snooze_takes_it_off_the_list(ward):
    _act(ward, "snoozed", until=local_today() + timedelta(days=30))

    with ward["app"].app_context():
        mine = [r for r in _due(ward) if r["patient"].id == ward["kid_id"]]

    assert 2 not in [r["dose_number"] for r in mine]


def test_a_snooze_that_has_run_out_comes_back(ward):
    """The difference between remembering and forgetting."""
    _act(ward, "snoozed", until=local_today() - timedelta(days=1))

    with ward["app"].app_context():
        mine = [r for r in _due(ward) if r["patient"].id == ward["kid_id"]]

    assert 2 in [r["dose_number"] for r in mine]


def test_a_call_goes_quiet_only_for_today(ward):
    """A call is a fact about today, not a decision about next week."""
    from app.models.reminder_action import ReminderAction

    _act(ward, "called")

    with ward["app"].app_context():
        row = ReminderAction.query.first()

        assert row.until == local_today() + timedelta(days=1)
        assert row.is_active() is True
        assert row.is_active(local_today() + timedelta(days=2)) is False


def test_a_dismissal_has_no_date_on_it(ward):
    from app.models.reminder_action import ReminderAction

    _act(ward, "dismissed")

    with ward["app"].app_context():
        assert ReminderAction.query.first().until is None
        mine = [r for r in _due(ward) if r["patient"].id == ward["kid_id"]]

    assert 2 not in [r["dose_number"] for r in mine]


# ------------------------------------------- the assertion this file is for

def test_silencing_one_dose_does_not_silence_the_next(ward):
    """One phone call must not take a child off the list for a whole course.

    Silencing dose 2 does quieten the course while dose 2 is outstanding, and
    that is correct — dose 3 cannot be given before it, so there is nothing
    else to chase. The question is what happens when the course **moves on**:
    once dose 2 is given, dose 3 is the next thing owed, and an action taken
    about dose 2 must have nothing to say about it.

    Keyed on the patient and the vaccine alone, one dismissal would follow the
    child through the rest of the course and no screen would mention it.
    """
    from app.extensions import db
    from app.models import PatientVaccine, VaccineBrand

    _act(ward, "dismissed", dose_number=2)

    with ward["app"].app_context():
        assert not [r for r in _due(ward)
                    if r["patient"].id == ward["kid_id"]], \
            "the silenced dose is still being chased"

        # The course moves on: dose 2 happens.
        brand = VaccineBrand.query.filter_by(vaccine_id=ward["pcv_id"],
                                             name="Prevenar 13").first()
        db.session.add(PatientVaccine(
            patient_id=ward["kid_id"], vaccine_id=ward["pcv_id"],
            brand_id=brand.id, dose_number=2, event_type="given",
            given_date=local_today() - timedelta(days=30)))
        db.session.commit()

        mine = [r for r in _due(ward) if r["patient"].id == ward["kid_id"]]

    assert 3 in [r["dose_number"] for r in mine], \
        f"one dismissal followed the child into the next dose: {mine}"


# ------------------------------------------------------- nothing disappears

def test_what_is_held_back_is_counted(ward):
    """A row that vanishes for good is how a child stops being followed."""
    _act(ward, "dismissed")

    with ward["app"].app_context():
        rows = _due(ward)

    assert getattr(rows, "held_back", 0) >= 1


def test_it_can_be_asked_for_anyway(ward):
    _act(ward, "dismissed")

    with ward["app"].app_context():
        shown = _due(ward, include_silenced=True)
        mine = [r for r in shown if r["patient"].id == ward["kid_id"]]

    assert 2 in [r["dose_number"] for r in mine]


def test_the_screen_says_how_many_it_is_hiding_and_offers_them_back(ward):
    from app.i18n import t

    _act(ward, "dismissed")
    from app.extensions import db
    from app.models.vaccine_plan import VaccinePlanItem
    with ward["app"].app_context():
        db.session.add(VaccinePlanItem(patient_id=ward["kid_id"],
                                       vaccine_id=ward["pcv_id"]))
        db.session.commit()

    client = ward["sign_in"]("doc")
    page = client.get("/vaccinations/plans", follow_redirects=True).data.decode()
    with ward["app"].test_request_context("/"):
        assert t("vact.show_hidden") in page

    shown = client.get("/vaccinations/plans?hidden=1",
                       follow_redirects=True).data.decode()
    with ward["app"].test_request_context("/"):
        assert t("vact.undo") in shown


def test_undoing_puts_it_back(ward):
    from app.models.reminder_action import ReminderAction

    _act(ward, "dismissed")
    with ward["app"].app_context():
        action_id = ReminderAction.query.first().id

    ward["sign_in"]("doc").post(f"/vaccinations/reminder/{action_id}/undo",
                                follow_redirects=True)

    with ward["app"].app_context():
        assert ReminderAction.query.count() == 0
        mine = [r for r in _due(ward) if r["patient"].id == ward["kid_id"]]

    assert 2 in [r["dose_number"] for r in mine]


# ----------------------------------------------------------------- the form

def test_the_desk_can_record_a_call(ward):
    from app.models.reminder_action import ReminderAction

    ward["sign_in"]("doc").post("/vaccinations/reminder/act", data={
        "action": "called", "patient_id": ward["kid_id"],
        "vaccine_id": ward["pcv_id"], "dose_number": 2},
        follow_redirects=True)

    with ward["app"].app_context():
        row = ReminderAction.query.first()
        assert row is not None and row.action == "called"


def test_a_snooze_without_a_date_is_refused(ward):
    """"Later" with no date is how a row goes quiet for ever by accident."""
    from app.models.reminder_action import ReminderAction

    ward["sign_in"]("doc").post("/vaccinations/reminder/act", data={
        "action": "snoozed", "patient_id": ward["kid_id"],
        "vaccine_id": ward["pcv_id"], "dose_number": 2},
        follow_redirects=True)

    with ward["app"].app_context():
        assert ReminderAction.query.count() == 0


def test_a_nonsense_action_is_refused(ward):
    from app.models.reminder_action import ReminderAction

    ward["sign_in"]("doc").post("/vaccinations/reminder/act", data={
        "action": "vanish", "patient_id": ward["kid_id"],
        "vaccine_id": ward["pcv_id"]}, follow_redirects=True)

    with ward["app"].app_context():
        assert ReminderAction.query.count() == 0


def test_the_wording_exists_in_both_languages(ward):
    import json

    here = os.path.dirname(os.path.abspath(__file__))
    keys = ["called", "snoozed", "dismissed", "undone", "bad", "needs_date",
            "call", "snooze", "dismiss", "undo", "hidden_n", "show_hidden"]
    for lang in ("ar", "en"):
        with open(os.path.join(here, "..", "app/i18n/locales", f"{lang}.json"),
                  encoding="utf-8") as fh:
            block = json.load(fh)["vact"]
        for key in keys:
            assert key in block, f"{lang} is missing vact.{key}"
