"""The queue at each doctor's door: the reception screen, «اللي بعده», and
«قرّب دورك» (asked: «شاشة الاستقبال مع زرار اللي بعده ورسالة قرّب دورك»).

The number is the one the booking confirmation already sent; arriving,
opening the visit and finishing it move the child along as they always did;
«اللي بعده» calls the next child who has arrived. The near-turn message is
off until the clinic turns it on, and goes once per booking.
"""
import os
import sys
from datetime import date, time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

from tests.test_appointment_reminder import _automatic  # noqa: E402


@pytest.fixture()
def day(clinic):
    """Five children booked with the doctor today, 9:00 … 13:00, each with a
    phone; the first three have arrived."""
    from app.models import Appointment, Patient
    from app.utils.clock import local_today

    db = clinic["db"]
    with clinic["app"].app_context():
        today = local_today()
        ids = []
        for i in range(5):
            child = Patient(patient_number=f"Q{i}", full_name=f"طفل {i}", gender="male",
                            date_of_birth=date(2024, 1, 1), is_active=True,
                            own_phone=f"0101234567{i}")
            db.session.add(child)
            db.session.flush()
            appt = Appointment(patient_id=child.id, doctor_id=clinic["ids"]["doctor"],
                               appt_date=today, appt_time=time(9 + i, 0),
                               status="scheduled")
            db.session.add(appt)
            db.session.flush()
            if i < 3:
                appt.apply_status("waiting")
            ids.append(appt.id)
        db.session.commit()
    clinic["appts"] = ids
    return clinic


def _appt(c, i):
    from app.models import Appointment

    return c["db"].session.get(Appointment, c["appts"][i])


def test_the_numbers_are_the_ones_the_confirmation_sent(day):
    from app.blueprints.messages.routes import queue_position
    from app.utils import queue_turns
    from app.utils.clock import local_today

    with day["app"].app_context():
        st = queue_turns.state(day["ids"]["doctor"], local_today())
        assert st["now"] is None
        assert [lbl for lbl, _a in st["next"]] == ["1", "2", "3"]
        assert st["not_arrived"] == 2 and st["left"] == 5
        assert all(lbl == str(queue_position(a)) for lbl, a in st["next"])


def test_next_calls_the_first_who_arrived_and_the_screen_shows_it(day):
    doc = day["sign_in"]("doc")
    page = doc.get("/appointments/queue").get_data(as_text=True)
    assert "data-queue-call" in page and "data-queue-screen-door" in page
    doc.post(f"/appointments/queue/{day['ids']['doctor']}/next")
    with day["app"].app_context():
        assert _appt(day, 0).called_at is not None and _appt(day, 1).called_at is None
    screen = day["sign_in"]("desk").get("/appointments/queue/screen").get_data(as_text=True)
    assert f'data-now="{day["ids"]["doctor"]}:1"' in screen
    assert "طفل" not in screen, "no names on a public screen"
    doc.post(f"/appointments/queue/{day['ids']['doctor']}/next")
    screen = day["sign_in"]("desk").get("/appointments/queue/screen").get_data(as_text=True)
    assert f'data-now="{day["ids"]["doctor"]}:2"' in screen


def test_nobody_waiting_is_said_not_invented(day):
    from app.utils import queue_turns
    from app.utils.clock import local_today

    with day["app"].app_context():
        for i in range(3):
            assert queue_turns.call_next(day["ids"]["doctor"], local_today()) is not None
        assert queue_turns.call_next(day["ids"]["doctor"], local_today()) is None, \
            "a child who has not arrived is never called"
        day["db"].session.rollback()


def test_the_doctor_opening_the_visit_counts_as_calling_them_in(day):
    from app.utils import queue_turns
    from app.utils.clock import local_today

    with day["app"].app_context():
        second = _appt(day, 1)
        second.apply_status("in_progress")
        day["db"].session.commit()
        st = queue_turns.state(day["ids"]["doctor"], local_today())
        assert st["now"][0] == "2"
        assert [lbl for lbl, _a in st["next"]] == ["1", "3"]


def test_the_screen_can_show_the_booked_time_instead(day):
    from app.models import Setting

    with day["app"].app_context():
        Setting.set("queue_mode", "time")
        day["db"].session.commit()
    screen = day["sign_in"]("desk").get("/appointments/queue").get_data(as_text=True)
    assert "09:00" in screen


def test_your_turn_is_near_is_off_until_the_clinic_turns_it_on(day):
    from app.models import MessageLog

    day["sign_in"]("doc").post(f"/appointments/queue/{day['ids']['doctor']}/next")
    with day["app"].app_context():
        assert MessageLog.query.filter_by(template_type="queue_near").count() == 0


def test_your_turn_is_near_goes_once_to_those_close_enough(day):
    from app.models import MessageLog, Setting

    with day["app"].app_context():
        _automatic(day)
        Setting.set("queue_near_notify", "1")
        Setting.set("queue_near_ahead", "1")
        day["db"].session.commit()
    doc = day["sign_in"]("doc")
    doc.post(f"/appointments/queue/{day['ids']['doctor']}/next")      # calls #1
    with day["app"].app_context():
        sent = MessageLog.query.filter_by(template_type="queue_near").all()
        # #2 is next (none before it) and #3 has one before it.
        assert sorted(m.appointment_id for m in sent) == sorted(day["appts"][1:3])
        assert "رقم 2" in [m for m in sent if m.appointment_id == day["appts"][1]][0].body
    doc.post(f"/appointments/queue/{day['ids']['doctor']}/next")      # calls #2
    with day["app"].app_context():
        sent = MessageLog.query.filter_by(template_type="queue_near").all()
        assert sorted(m.appointment_id for m in sent) == sorted(day["appts"][1:4]), \
            "#4 joins; #2 and #3 are not sent twice"


def test_only_the_administrator_changes_the_settings(day):
    from app.models import Setting

    day["sign_in"]("desk").post("/appointments/queue/settings",
                                data={"queue_mode": "time", "notify": "1", "ahead": "3"})
    with day["app"].app_context():
        assert (Setting.get("queue_mode", "number") or "number") == "number"
    page = day["sign_in"]("boss").get("/appointments/queue?all=1").get_data(as_text=True)
    assert "data-queue-settings" in page
    day["sign_in"]("boss").post("/appointments/queue/settings",
                                data={"queue_mode": "time", "notify": "1", "ahead": "3"})
    with day["app"].app_context():
        assert Setting.get("queue_mode") == "time"
        assert Setting.get("queue_near_notify") == "1" and Setting.get("queue_near_ahead") == "3"


def test_the_doors_to_it(day):
    board = day["sign_in"]("desk").get("/appointments/").get_data(as_text=True)
    assert "data-queue-door" in board
