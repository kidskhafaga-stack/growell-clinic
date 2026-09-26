"""A request is not a booking — ``BOOKING_APPROVAL_PLAN.md``, stage one.

A family asks for an appointment; a person books it or declines it. What is
held here:

* a request names a child on file or somebody to call back, never nobody;
* it holds **no slot** — the time the family asked for stays bookable by
  anybody, and the request is on no appointment list, the child's file
  included;
* booking it goes through the ordinary booking screen, and saving that
  booking is what answers the request;
* it is answered once: a second booking or decline changes nothing;
* a decline says why;
* every step is in the audit log;
* only somebody who can book can take, book or decline one.
"""
import os
import sys
from datetime import time, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def desk(clinic):
    """A doctor with a schedule, so there are slots to book into."""
    from app.extensions import db
    from app.models import DoctorSchedule, Visit
    from app.utils.clock import local_today

    with clinic["app"].app_context():
        doctor_id = db.session.get(Visit, clinic["ids"]["visit"]).doctor_id
        for weekday in range(7):
            db.session.add(DoctorSchedule(
                doctor_id=doctor_id, weekday=weekday, start_time=time(9, 0),
                end_time=time(17, 0), slot_minutes=30, is_active=True))
        db.session.commit()
    clinic["doctor_id"] = doctor_id
    clinic["tomorrow"] = local_today() + timedelta(days=1)
    return clinic


def _take(desk, who="desk", **fields):
    data = {"doctor_id": desk["doctor_id"],
            "wanted_date": desk["tomorrow"].isoformat(),
            "appt_type": "followup", "message": "عايزة أقرب موعد"}
    data.update(fields)
    return desk["sign_in"](who).post("/appointments/requests", data=data)


def _rows(desk):
    from app.models import BookingRequest

    with desk["app"].app_context():
        return [(r.id, r.status, r.patient_id, r.appointment_id,
                 r.decline_reason) for r in BookingRequest.query.all()]


def _appointments(desk):
    from app.models import Appointment

    with desk["app"].app_context():
        return Appointment.query.count()


def _log(desk, action):
    from app.models import ActivityLog

    with desk["app"].app_context():
        return [(r.entity_id, r.detail) for r in
                ActivityLog.query.filter_by(action=action).all()]


def _book(desk, request_id, patient_id=None, slot="10:00"):
    return desk["sign_in"]("desk").post("/appointments/new", data={
        "patient_id": patient_id or desk["ids"]["child"],
        "doctor_id": desk["doctor_id"],
        "appt_date": desk["tomorrow"].isoformat(), "appt_time": slot,
        "appt_type": "followup", "from_request": request_id,
    })


# ------------------------------------------------------------ taking ----
def test_a_request_for_a_child_on_file(desk):
    _take(desk, patient_id=desk["ids"]["child"])
    [(rid, status, patient, appt, _)] = _rows(desk)
    assert status == "pending" and patient == desk["ids"]["child"]
    assert appt is None
    assert _log(desk, "booking_request.take") == [(rid, None)]


def test_a_family_not_on_file_leaves_a_name_and_a_number(desk):
    from app.models import BookingRequest

    _take(desk, contact_name="أم يوسف", contact_phone="01000000009")
    with desk["app"].app_context():
        row = BookingRequest.query.one()
        assert row.patient_id is None
        assert (row.contact_name, row.contact_phone) == ("أم يوسف",
                                                         "01000000009")
        assert row.who() == "أم يوسف"


@pytest.mark.parametrize("fields", [
    {},                                        # nobody at all
    {"contact_name": "أم يوسف"},               # nobody to call back
    {"contact_phone": "01000000009"},          # nobody to ask for
])
def test_a_request_that_names_nobody_is_refused(desk, fields):
    _take(desk, **fields)
    assert _rows(desk) == []


# ------------------------------------------------------------ no slot ----
def test_a_request_holds_no_slot(desk):
    """The family asked for tomorrow at ten; until somebody books it, ten
    o'clock is anybody's — and the request is on no appointment list."""
    from app.utils.appointments import available_slots

    _take(desk, patient_id=desk["ids"]["child"])
    with desk["app"].app_context():
        assert "10:00" in available_slots(desk["doctor_id"], desk["tomorrow"])
    assert _appointments(desk) == 0
    page = desk["sign_in"]("desk").get(
        f"/patients/{desk['ids']['child']}").get_data(as_text=True)
    assert "عايزة أقرب موعد" not in page


# ------------------------------------------------------------ booking ----
def test_booking_opens_the_booking_screen_with_the_request(desk):
    _take(desk, patient_id=desk["ids"]["child"])
    [(rid, *_)] = _rows(desk)
    client = desk["sign_in"]("desk")
    reply = client.get(f"/appointments/requests/{rid}/book")
    assert reply.status_code == 302
    target = reply.headers["Location"]
    assert f"from_request={rid}" in target
    assert f"date={desk['tomorrow'].isoformat()}" in target
    assert "appt_type=followup" in target
    form = client.get(target).get_data(as_text=True)
    assert f'data-booking-request="{rid}"' in form
    assert f'name="from_request" value="{rid}"' in form
    assert "عايزة أقرب موعد" in form


def test_saving_the_booking_answers_the_request(desk):
    _take(desk, contact_name="أم يوسف", contact_phone="01000000009")
    [(rid, *_)] = _rows(desk)
    _book(desk, rid)
    from app.models import Appointment

    with desk["app"].app_context():
        appt = Appointment.query.one()
    [(_, status, patient, appt_id, _)] = _rows(desk)
    assert (status, appt_id) == ("booked", appt.id)
    # The child the desk chose is who the request was about.
    assert patient == desk["ids"]["child"]
    assert _log(desk, "booking_request.book") == [(rid, f"appointment {appt.id}")]


def test_a_request_is_answered_once(desk):
    _take(desk, patient_id=desk["ids"]["child"])
    [(rid, *_)] = _rows(desk)
    _book(desk, rid, slot="10:00")
    first = _rows(desk)[0][3]
    _book(desk, rid, slot="11:00")          # the same form, sent again
    assert _rows(desk)[0][3] == first       # still the first appointment
    desk["sign_in"]("desk").post(f"/appointments/requests/{rid}/decline",
                                 data={"reason": "متأخر"})
    assert _rows(desk)[0][1] == "booked"
    assert len(_log(desk, "booking_request.book")) == 1
    # And the button no longer leads to a booking.
    reply = desk["sign_in"]("desk").get(f"/appointments/requests/{rid}/book")
    assert "from_request" not in reply.headers["Location"]
    # Nor does an old link to the booking screen bring it back.
    form = desk["sign_in"]("desk").get(
        f"/appointments/new?from_request={rid}").get_data(as_text=True)
    assert "data-booking-request" not in form
    assert 'name="from_request"' not in form


def test_a_booking_that_fails_keeps_the_request_waiting(desk):
    from app.utils.clock import local_today

    _take(desk, patient_id=desk["ids"]["child"])
    [(rid, *_)] = _rows(desk)
    reply = desk["sign_in"]("desk").post("/appointments/new", data={
        "patient_id": desk["ids"]["child"], "doctor_id": desk["doctor_id"],
        "appt_date": (local_today() - timedelta(days=1)).isoformat(),
        "appt_time": "10:00", "from_request": rid})
    assert _appointments(desk) == 0
    assert _rows(desk)[0][1] == "pending"
    # The form comes back with the request still attached.
    assert f'name="from_request" value="{rid}"' in reply.get_data(as_text=True)


# ------------------------------------------------------------ declining ----
def test_a_decline_says_why(desk):
    _take(desk, patient_id=desk["ids"]["child"])
    [(rid, *_)] = _rows(desk)
    client = desk["sign_in"]("desk")
    client.post(f"/appointments/requests/{rid}/decline", data={"reason": " "})
    assert _rows(desk)[0][1] == "pending"
    client.post(f"/appointments/requests/{rid}/decline",
                data={"reason": "الدكتور مسافر الأسبوع ده"})
    assert _rows(desk)[0][1:] == ("declined", desk["ids"]["child"], None,
                                  "الدكتور مسافر الأسبوع ده")
    assert _log(desk, "booking_request.decline") == [
        (rid, "الدكتور مسافر الأسبوع ده")]
    client.post(f"/appointments/requests/{rid}/decline",
                data={"reason": "سبب تاني"})
    assert _rows(desk)[0][4] == "الدكتور مسافر الأسبوع ده"


# ------------------------------------------------------------ the desk ----
def test_the_board_says_how_many_are_waiting(desk):
    board = desk["sign_in"]("desk").get("/appointments/").get_data(as_text=True)
    assert "data-requests-link" in board and "data-requests-waiting" not in board
    _take(desk, patient_id=desk["ids"]["child"])
    _take(desk, contact_name="أم يوسف", contact_phone="01000000009",
          doctor_id="")
    board = desk["sign_in"]("desk").get("/appointments/").get_data(as_text=True)
    assert 'data-requests-waiting="2"' in board


def test_the_requests_page_lists_the_oldest_first(desk):
    _take(desk, contact_name="الأولى", contact_phone="01000000001")
    _take(desk, contact_name="التانية", contact_phone="01000000002")
    page = desk["sign_in"]("desk").get("/appointments/requests").get_data(
        as_text=True)
    assert 'data-requests-waiting="2"' in page
    assert page.index("الأولى") < page.index("التانية")


def test_a_doctors_list_holds_their_requests_and_any_doctors(desk):
    from app.utils import booking_requests

    _take(desk, contact_name="له", contact_phone="01000000001")
    _take(desk, contact_name="لأي دكتور", contact_phone="01000000002",
          doctor_id="")
    with desk["app"].app_context():
        mine = booking_requests.pending(desk["doctor_id"])
        other = booking_requests.pending(desk["doctor_id"] + 999)
        assert {r.contact_name for r in mine} == {"له", "لأي دكتور"}
        assert {r.contact_name for r in other} == {"لأي دكتور"}


def test_only_somebody_who_books_can_take_one(desk):
    from app.models import User

    with desk["app"].app_context():
        role = User.query.filter_by(username="acct").one().role
    reply = _take(desk, who="acct", patient_id=desk["ids"]["child"])
    if reply.status_code in (302, 403) and _rows(desk) == []:
        return
    pytest.fail(f"the {role} role reached the desk's requests")
