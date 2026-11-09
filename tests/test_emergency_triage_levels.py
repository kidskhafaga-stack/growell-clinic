"""Emergency triage on the hospital's own levels (DOCTOR_EASE_PLAN ٤-أ ط-٤).

* The hospital writes its levels once — name, colour, urgent or not, the most
  minutes to the doctor. The program ships none; with none, triage is typed
  by hand exactly as before.
* Triage is then one press on a level; the vitals at the door are kept as a
  reading, and one outside the age band raises «urgent» — never lowers it.
* A child past their level's minutes and not yet seen is said on the register.
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tests.test_emergency_treatment_on_the_bill import er  # noqa: E402,F401


def _arrive(er):
    from app.models import Patient
    from app.utils import emergency as util

    with er["app"].app_context():
        row = util.arrive(er["db"].session.get(Patient, er["ids"]["child"]))
        er["db"].session.commit()
        return row.id


def _levels(er):
    er["sign_in"]("boss").post("/emergency/levels", data={
        "rows": "3",
        "name_0": "أحمر", "color_0": "#dc2626", "urgent_0": "1", "minutes_0": "0",
        "name_1": "أصفر", "color_1": "#eab308", "minutes_1": "10",
        "name_2": "أخضر", "color_2": "#16a34a", "minutes_2": ""})
    from app.utils import er_triage

    with er["app"].app_context():
        return {l["name"]: l["key"] for l in er_triage.levels()}


def _row(er, att):
    from app.models import EmergencyVisit

    with er["app"].app_context():
        row = er["db"].session.get(EmergencyVisit, att)
        return {"level": row.level, "urgent": row.urgent, "triaged_at": row.triaged_at}


def test_with_no_levels_triage_is_typed_by_hand_as_before(er):
    _arrive(er)
    page = er["sign_in"]("nurse").get("/emergency/register").get_data(as_text=True)
    assert "data-triage-level " in page or "data-triage-level>" in page
    assert "data-triage-level-pick" not in page
    assert "data-triage-vitals" in page


def test_triage_is_one_press_on_the_hospital_s_level(er):
    keys = _levels(er)
    assert list(keys) == ["أحمر", "أصفر", "أخضر"]
    att = _arrive(er)
    page = er["sign_in"]("nurse").get("/emergency/register").get_data(as_text=True)
    assert "data-triage-level-pick" in page and "أصفر" in page
    er["sign_in"]("nurse").post(f"/emergency/triage/{att}", data={"level_key": keys["أحمر"]})
    assert _row(er, att)["level"] == "أحمر" and _row(er, att)["urgent"] is True
    att2 = _arrive(er)
    er["sign_in"]("nurse").post(f"/emergency/triage/{att2}", data={"level_key": keys["أخضر"]})
    assert _row(er, att2)["urgent"] is False


def test_a_reading_outside_the_age_band_raises_urgent_and_is_kept(er):
    from app.models import GrowthRecord
    from app.models.observation import Observation

    keys = _levels(er)
    att = _arrive(er)
    page = er["sign_in"]("nurse").post(f"/emergency/triage/{att}", data={
        "level_key": keys["أخضر"], "spo2": "84", "temperature_c": "37",
        "weight_kg": "11.5"}, follow_redirects=True).get_data(as_text=True)
    assert _row(er, att)["urgent"] is True, "raised by the SpO2"
    assert "أكسجين" in page and "84" in page
    with er["app"].app_context():
        obs = Observation.query.one()
        assert obs.spo2 == 84 and obs.temperature_c == 37
        assert GrowthRecord.query.filter_by(source="emergency").one().weight_kg == 11.5


def test_normal_readings_never_lower_what_the_nurse_decided(er):
    keys = _levels(er)
    att = _arrive(er)
    er["sign_in"]("nurse").post(f"/emergency/triage/{att}", data={
        "level_key": keys["أحمر"], "spo2": "99"})
    assert _row(er, att)["urgent"] is True
    att2 = _arrive(er)
    er["sign_in"]("nurse").post(f"/emergency/triage/{att2}", data={
        "level_key": keys["أخضر"], "spo2": "99"})
    assert _row(er, att2)["urgent"] is False


def test_a_child_past_their_level_s_minutes_is_said(er):
    from app.models import EmergencyVisit

    keys = _levels(er)
    att = _arrive(er)
    er["sign_in"]("nurse").post(f"/emergency/triage/{att}", data={"level_key": keys["أصفر"]})
    page = er["sign_in"]("nurse").get("/emergency/register").get_data(as_text=True)
    assert f'data-triage-late="{att}"' not in page
    with er["app"].app_context():
        row = er["db"].session.get(EmergencyVisit, att)
        row.triaged_at = datetime.utcnow() - timedelta(minutes=25)
        er["db"].session.commit()
    page = er["sign_in"]("nurse").get("/emergency/register").get_data(as_text=True)
    assert f'data-triage-late="{att}"' in page
    late = page.split(f'data-triage-late="{att}"', 1)[1][:200]
    assert "15" in late or "14" in late


def test_only_an_admin_writes_the_levels_and_the_minutes_are_checked(er):
    assert er["sign_in"]("nurse").get("/emergency/levels").status_code == 403
    page = er["sign_in"]("boss").get("/emergency/register").get_data(as_text=True)
    assert "data-to-triage-levels" in page, "the door"
    page = er["sign_in"]("boss").get("/emergency/levels").get_data(as_text=True)
    assert "data-no-levels" in page
    er["sign_in"]("boss").post("/emergency/levels", data={
        "rows": "1", "name_0": "أحمر", "minutes_0": "abc"})
    from app.utils import er_triage

    with er["app"].app_context():
        assert er_triage.levels() == []
