"""The device studies board is never a blank page.

Asked, with a picture of it, as *«الصفحة دي فارغة خالص ليه؟»*. It was a
worklist and nothing else: with no study ordered it said «nothing waiting»
and stopped — no way to start a study for the child in front of the echo,
nothing of what was done, and no hint why nothing arrives. And an echo
added to the tests list as a film before the studies had a room of their
own could not be moved, so its orders went to radiology for ever. Held here:

* a study is started from the board by file number, with no order;
* the studies done lately are listed;
* an empty board says why — no test defined as a device study, or orders
  for a device's test filed under another room;
* a test is moved to the right room, and its open orders move with it.
"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def room(clinic):
    from app.models import Investigation, MedicalDevice, Setting

    with clinic["app"].app_context():
        db = clinic["db"]
        Setting.set("mod_enabled:labs", "1")
        echo = MedicalDevice(name="إيكو", device_type="echo", is_active=True)
        db.session.add(echo)
        db.session.flush()
        # An echo filed as a film, the way catalogues built before the
        # studies had a room of their own have it.
        test = Investigation(name_ar="إيكو قلب", kind="imaging", device_id=echo.id,
                             is_active=True)
        db.session.add(test)
        db.session.commit()
        clinic["ids"].update(echo=echo.id, echo_test=test.id)
    return clinic


def _order(c):
    from app.models import VisitInvestigation

    with c["app"].app_context():
        row = VisitInvestigation(visit_id=c["ids"]["visit"], patient_id=c["ids"]["child"],
                                 investigation_id=c["ids"]["echo_test"], kind="imaging",
                                 name="إيكو قلب", status="requested")
        c["db"].session.add(row)
        c["db"].session.commit()
        return row.id


def test_an_empty_board_says_why(room):
    _order(room)
    page = room["sign_in"]("boss").get("/visits/studies/board").get_data(as_text=True)
    assert "data-board-empty" in page and "data-none-defined" in page
    assert "data-filed-elsewhere" in page
    assert "data-device-start" in page and "data-recent-studies" in page


def test_a_test_moved_to_its_room_takes_its_open_orders(room):
    from app.models import Investigation, VisitInvestigation

    order = _order(room)
    room["sign_in"]("boss").post(f"/labs/tests/{room['ids']['echo_test']}", data={
        "name_ar": "إيكو قلب", "is_active": "1", "in_house": "1",
        "move_kind": "diagnostic"})
    with room["app"].app_context():
        db = room["db"]
        assert db.session.get(Investigation, room["ids"]["echo_test"]).kind == "diagnostic"
        assert db.session.get(VisitInvestigation, order).kind == "diagnostic"
    page = room["sign_in"]("boss").get("/visits/studies/board").get_data(as_text=True)
    assert f'data-device-order="{order}"' in page


def test_a_study_is_started_by_file_number(room):
    boss = room["sign_in"]("boss")
    answer = boss.get("/visits/studies/start?number=P1")
    assert f"/visits/studies/new/{room['ids']['child']}" in answer.headers["Location"]
    answer = boss.get("/visits/studies/start?number=NOPE")
    assert "/visits/studies/board" in answer.headers["Location"]


def test_what_was_done_lately_is_listed(room):
    from app.models import DeviceStudy

    with room["app"].app_context():
        room["db"].session.add(DeviceStudy(patient_id=room["ids"]["child"],
                                           device_id=room["ids"]["echo"],
                                           study_date=date.today(),
                                           performed_by=room["ids"]["doctor"],
                                           conclusion="طبيعي"))
        room["db"].session.commit()
    page = room["sign_in"]("boss").get("/visits/studies/board").get_data(as_text=True)
    assert "data-recent-study" in page and "طبيعي" in page
