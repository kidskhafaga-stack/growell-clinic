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
