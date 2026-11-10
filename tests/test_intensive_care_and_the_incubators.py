"""Intensive care and the incubators (DOCTOR_EASE_PLAN ٤-ج).

ع-١ — the breathing support and the blood pressure were written with each
reading and shown nowhere: a child on a ventilator looked like one on room
air from the board and from the stay. Now both are on the stay's readings
and the board says the support.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tests.test_the_chart_nobody_read import _admit, _child, ward  # noqa: E402,F401


def test_the_support_and_the_pressure_show_on_the_stay_and_the_board(ward):
    stay = _admit(ward, _child(ward, "سليم"))
    boss = ward["sign_in"]("boss")
    page = boss.post(f"/beds/admission/{stay}/vitals",
                     data={"spo2": "92", "bp_systolic": "95", "bp_diastolic": "60",
                           "oxygen_support": "ventilator"},
                     follow_redirects=True).get_data(as_text=True)
    row = page.split("data-reading=", 1)[1][:2500]
    assert 'data-o2="ventilator"' in row and "95/60" in row
    board = boss.get("/ward/").get_data(as_text=True)
    assert 'data-o2-support="ventilator"' in board and "95/60" in board


def test_room_air_is_not_a_warning_and_a_support_alone_is_a_reading(ward):
    from app.models.observation import Observation

    stay = _admit(ward, _child(ward, "سليم"))
    ward["sign_in"]("boss").post(f"/beds/admission/{stay}/vitals",
                                 data={"oxygen_support": "room_air"})
    with ward["app"].app_context():
        assert Observation.query.one().oxygen_support == "room_air"
    assert "data-o2-support" not in ward["sign_in"]("boss").get("/ward/").get_data(as_text=True)


# ---------------------------------------------- ع-٢ the ventilator settings --

def _vent(ward, stay, **form):
    return ward["sign_in"]("boss").post(f"/beds/stay/{stay}/vent", data=form,
                                        follow_redirects=True).get_data(as_text=True)


def test_each_change_is_a_row_and_the_latest_is_what_the_machine_is_on(ward):
    from app.models import VentSetting

    stay = _admit(ward, _child(ward, "سليم"))
    _vent(ward, stay, mode="SIMV", fio2="60", peep="6", rate="30", pip="22")
    page = _vent(ward, stay, mode="SIMV", fio2="40", peep="5", rate="24", pip="20")
    assert page.count("data-vent-row=") == 2
    now = page.split("data-vent-now", 1)[1][:400]
    assert "40" in now and "SIMV" in now
    page = _vent(ward, stay, stopped="1")
    assert "data-vent-off" in page and "data-vent-now" not in page
    with ward["app"].app_context():
        assert VentSetting.query.count() == 3


def test_a_setting_no_machine_takes_is_refused_and_a_mode_is_needed(ward):
    from app.models import VentSetting

    stay = _admit(ward, _child(ward, "سليم"))
    _vent(ward, stay, mode="SIMV", fio2="140")
    _vent(ward, stay, fio2="40")
    with ward["app"].app_context():
        assert VentSetting.query.count() == 0


def test_the_card_is_on_intensive_care_and_not_on_an_ordinary_ward_stay(ward):
    stay = _admit(ward, _child(ward, "سليم"))
    page = ward["sign_in"]("boss").get(f"/beds/admission/{stay}").get_data(as_text=True)
    from app.models import Admission

    with ward["app"].app_context():
        kind = ward["db"].session.get(Admission, stay).bed.unit.kind
    assert ("data-vent" in page) == (kind in ("icu", "nicu"))
