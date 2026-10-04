"""A child received in emergency before registration — GAHAR ACT.03 (و).

«المستشفى مش هتستقبل حالة قبل التسجيل وساعات بيبقى مطلوب تدخل سريع». So:

* one form on the emergency screen receives a child **now**: a sex, an
  estimated age, the name if anybody knows it; the file is opened and the
  child arrives on it in the same press;
* with no name the file is provisional, under a name that says so; the
  birth date is worked out from the estimated age and marked estimated —
  never made up by the program;
* the desk has a list of files to complete, and completes them on the same
  file, saying in so many words that the identity is now known;
* nothing changes for a child who is already registered.
"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def er(clinic):
    from app.models import Setting

    with clinic["app"].app_context():
        Setting.set("mod_enabled:emergency", "1")
        clinic["db"].session.commit()
    return clinic


def _arrive(c, **form):
    data = {"gender": "male", "age_value": "4", "age_unit": "years", **form}
    return c["sign_in"]("boss").post("/emergency/arrive-now", data=data)


def test_a_child_with_no_name_is_received_at_once(er):
    from app.models import EmergencyVisit, Patient

    page = er["sign_in"]("boss").get("/emergency/register").get_data(as_text=True)
    assert "data-arrive-now" in page
    answer = _arrive(er)
    with er["app"].app_context():
        child = Patient.query.filter(Patient.identity_provisional.is_(True)).one()
        assert child.full_name.startswith("مجهول") and child.dob_estimated is True
        assert child.patient_number
        today = date.today()
        assert child.date_of_birth.year == today.year - 4
        visit = EmergencyVisit.query.filter_by(patient_id=child.id).one()
    assert f"/emergency/attendance/{visit.id}" in answer.headers["Location"]


def test_a_name_known_is_not_provisional_but_the_age_is_still_an_estimate(er):
    from app.models import Patient

    _arrive(er, full_name="يوسف أحمد", gender="male", age_value="8", age_unit="months")
    with er["app"].app_context():
        child = Patient.query.filter_by(full_name="يوسف أحمد").one()
        assert child.identity_provisional is None and child.dob_estimated is True


def test_a_sex_and_an_age_are_asked_and_never_invented(er):
    from app.models import Patient

    with er["app"].app_context():
        before = Patient.query.count()
    _arrive(er, gender="")
    _arrive(er, age_value="")
    _arrive(er, age_value="40", age_unit="years")
    with er["app"].app_context():
        assert Patient.query.count() == before


def test_the_desk_completes_the_file_on_the_same_file(er):
    from app.models import Patient

    _arrive(er)
    boss = er["sign_in"]("boss")
    with er["app"].app_context():
        child = Patient.query.filter(Patient.identity_provisional.is_(True)).one()
        cid, number = child.id, child.patient_number
    listing = boss.get("/patients/provisional").get_data(as_text=True)
    assert f'data-provisional-row="{cid}"' in listing
    profile = boss.get(f"/patients/{cid}").get_data(as_text=True)
    assert "data-provisional-banner" in profile
    form = boss.get(f"/patients/{cid}/edit").get_data(as_text=True)
    assert "data-identity-confirm" in form and "data-dob-confirm" in form
    boss.post(f"/patients/{cid}/edit", data={
        "patient_number": number, "full_name": "مالك محمود", "gender": "male",
        "date_of_birth": "2022-03-09", "identity_confirmed": "1", "is_active": "1"})
    with er["app"].app_context():
        child = er["db"].session.get(Patient, cid)
        assert (child.full_name, child.identity_provisional, child.dob_estimated) == (
            "مالك محمود", None, None)
        assert child.date_of_birth == date(2022, 3, 9)
    assert f'data-provisional-row="{cid}"' not in boss.get("/patients/provisional").get_data(as_text=True)


def test_the_search_says_provisional_and_estimated(er):
    _arrive(er)
    rows = er["sign_in"]("boss").get("/emergency/patient-search?q=مجهول").get_json()
    assert rows and rows[0]["hint"].startswith("ملف مؤقت") and "~" in rows[0]["hint"]
