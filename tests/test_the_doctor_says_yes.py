"""The doctor says yes — ``BOOKING_APPROVAL_PLAN.md`` stage three.

Decided for the clinic: *the desk, and then the doctor.* And decided with it:
**each doctor may change that for themselves**, because the clinics and
hospitals this runs in work differently — one doctor leaves their diary to
the desk, another wants to see every request first.

What is held here:

* the clinic's rule is "the desk, then the doctor" until it says otherwise;
* a doctor's own choice beats the clinic's, either way;
* where the doctor approves, the desk sends the request, the doctor says yes
  (or no, and why), and only then is it booked;
* only the doctor it was sent to can say yes — not another doctor, and not
  the desk on their behalf;
* a yes from one doctor is not a yes to book the family with another;
* the booking screen itself refuses, so the rule holds however the desk got
  to the form;
* a doctor sets their own choice; the admin can set anybody's; nobody else.
"""
import os
import sys
from datetime import time, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def clinic2(clinic):
    """Two doctors with a working week, and nothing said about approval —
    the clinic's default."""
    from app.extensions import db
    from app.models import DoctorSchedule, User
    from app.utils.clock import local_today

    with clinic["app"].app_context():
        other = User(username="doc2", full_name="د. سارة", role="doctor",
                     is_active=True)
        other.set_password("secret")
        db.session.add(other)
        db.session.flush()
        for doctor_id in (clinic["ids"]["doctor"], other.id):
            for weekday in range(7):
                db.session.add(DoctorSchedule(
                    doctor_id=doctor_id, weekday=weekday,
                    start_time=time(9, 0), end_time=time(17, 0),
                    slot_minutes=30, is_active=True))
        db.session.commit()
        clinic["ids"]["doctor2"] = other.id
    clinic["tomorrow"] = local_today() + timedelta(days=1)
    return clinic


def _take(c, doctor="doctor", **extra):
    data = {"patient_id": c["ids"]["child"], "appt_type": "followup",
            "wanted_date": c["tomorrow"].isoformat(),
            "message": "عايزة ميعاد متابعة"}
    if doctor:
        data["doctor_id"] = c["ids"][doctor]
    data.update(extra)
    c["sign_in"]("desk").post("/appointments/requests", data=data)
    from app.models import BookingRequest

    with c["app"].app_context():
        return BookingRequest.query.order_by(BookingRequest.id.desc()).first().id


def _state(c, rid):
    from app.extensions import db
    from app.models import BookingRequest

    with c["app"].app_context():
        r = db.session.get(BookingRequest, rid)
        return {"status": r.status, "doctor": r.doctor_id,
                "approved_by": r.approved_by, "note": r.approval_note,
                "decided_by": r.decided_by, "reason": r.decline_reason,
                "appointment": r.appointment_id}


def _book(c, rid, doctor="doctor", slot="10:00", who="desk"):
    return c["sign_in"](who).post("/appointments/new", data={
        "patient_id": c["ids"]["child"], "doctor_id": c["ids"][doctor],
        "appt_date": c["tomorrow"].isoformat(), "appt_time": slot,
        "appt_type": "followup", "from_request": rid})


def _appointments(c):
    from app.models import Appointment

    with c["app"].app_context():
        return Appointment.query.count()


def _forward(c, rid, who="desk", **data):
    return c["sign_in"](who).post(f"/appointments/requests/{rid}/forward",
                                  data=data)


def _approve(c, rid, who="doc", note=""):
    return c["sign_in"](who).post(f"/appointments/requests/{rid}/approve",
                                  data={"note": note})


def _set_policy(c, doctor, value, who=None):
    return c["sign_in"](who or ("doc" if doctor == "doctor" else "boss")).post(
        f"/appointments/approval/{c['ids'][doctor]}",
        data={"booking_approval": value})


def _log(c, action):
    from app.models import ActivityLog

    with c["app"].app_context():
        return [(r.user_id, r.entity_id, r.detail) for r in
                ActivityLog.query.filter_by(action=action).all()]


# ------------------------------------------------------------ the default ----
def test_the_clinic_default_is_the_desk_then_the_doctor(clinic2):
    from app.utils.booking_requests import clinic_policy, policy_for

    with clinic2["app"].app_context():
        assert clinic_policy() == "both"
        assert policy_for(clinic2["ids"]["doctor"]) == "both"
        assert policy_for(None) == "both"


def test_the_desk_cannot_book_before_the_doctor_says_yes(clinic2):
    rid = _take(clinic2)
    page = clinic2["sign_in"]("desk").get("/appointments/requests") \
        .get_data(as_text=True)
    row = page[page.index(f'data-request="{rid}"'):]
    row = row[:row.index("</tr>")]
    assert "data-forward" in row and "data-book" not in row
    # The book button's address, typed by hand, leads back with the reason.
    reply = clinic2["sign_in"]("desk").get(f"/appointments/requests/{rid}/book")
    assert "from_request" not in reply.headers["Location"]
    # And the booking screen itself refuses — the rule is on the booking.
    form = _book(clinic2, rid).get_data(as_text=True)
    assert _appointments(clinic2) == 0
    assert _state(clinic2, rid)["status"] == "pending"
    assert "د. أحمد" in form


# ------------------------------------------------------------ the path ----
def test_sent_approved_booked(clinic2):
    rid = _take(clinic2)
    _forward(clinic2, rid)
    assert _state(clinic2, rid)["status"] == "with_doctor"
    # The doctor sees it at the top of their screen, theirs to answer.
    page = clinic2["sign_in"]("doc").get("/appointments/requests") \
        .get_data(as_text=True)
    assert f'data-mine="{rid}"' in page
    _approve(clinic2, rid, note="أيوه، الصبح أحسن")
    state = _state(clinic2, rid)
    assert (state["status"], state["approved_by"], state["note"]) == (
        "approved", clinic2["ids"]["doctor"], "أيوه، الصبح أحسن")
    assert _book(clinic2, rid).status_code == 302
    assert _state(clinic2, rid)["status"] == "booked"
    assert _appointments(clinic2) == 1
    # Every step written down, by whom.
    assert _log(clinic2, "booking_request.forward")[0][:2] == (
        clinic2["ids"]["desk"], rid)
    assert _log(clinic2, "booking_request.approve") == [
        (clinic2["ids"]["doctor"], rid, "أيوه، الصبح أحسن")]


def test_only_the_doctor_it_was_sent_to_says_yes(clinic2):
    rid = _take(clinic2)
    _forward(clinic2, rid)
    assert _approve(clinic2, rid, who="desk").status_code == 403
    assert _approve(clinic2, rid, who="doc2").status_code == 403
    assert _approve(clinic2, rid, who="boss").status_code == 403
    assert _state(clinic2, rid)["status"] == "with_doctor"
    page = clinic2["sign_in"]("doc2").get("/appointments/requests") \
        .get_data(as_text=True)
    assert f'data-mine="{rid}"' not in page


def test_a_yes_is_not_a_yes_to_another_doctor(clinic2):
    rid = _take(clinic2)
    _forward(clinic2, rid)
    _approve(clinic2, rid)
    _book(clinic2, rid, doctor="doctor2")
    assert _appointments(clinic2) == 0
    assert _state(clinic2, rid)["status"] == "approved"


def test_nothing_to_approve_before_it_is_sent(clinic2):
    rid = _take(clinic2)
    _approve(clinic2, rid)
    assert _state(clinic2, rid)["status"] == "pending"


def test_the_doctor_says_no_and_why(clinic2):
    rid = _take(clinic2)
    _forward(clinic2, rid)
    clinic2["sign_in"]("doc").post(f"/appointments/requests/{rid}/decline",
                                   data={"reason": "محتاج يشوف أخصائي"})
    state = _state(clinic2, rid)
    assert (state["status"], state["decided_by"], state["reason"]) == (
        "declined", clinic2["ids"]["doctor"], "محتاج يشوف أخصائي")
    # The desk can still book the child as it always could — but not as an
    # answer to this request, which stays declined.
    _book(clinic2, rid)
    state = _state(clinic2, rid)
    assert (state["status"], state["appointment"]) == ("declined", None)


def test_any_doctor_is_sent_to_a_doctor_the_desk_picks(clinic2):
    rid = _take(clinic2, doctor=None)
    _forward(clinic2, rid)                          # nobody chosen
    assert _state(clinic2, rid)["status"] == "pending"
    _forward(clinic2, rid, doctor_id=clinic2["ids"]["doctor2"])
    state = _state(clinic2, rid)
    assert (state["status"], state["doctor"]) == (
        "with_doctor", clinic2["ids"]["doctor2"])


# ------------------------------------------------------------ each doctor ----
def test_a_doctor_who_leaves_it_to_the_desk(clinic2):
    _set_policy(clinic2, "doctor", "reception")
    rid = _take(clinic2)
    assert _book(clinic2, rid).status_code == 302
    assert _state(clinic2, rid)["status"] == "booked"


def test_a_doctor_who_approves_in_a_clinic_that_does_not(clinic2):
    from app.extensions import db
    from app.models import Setting

    with clinic2["app"].app_context():
        Setting.set("booking_approval", "reception")
        db.session.commit()
    _set_policy(clinic2, "doctor", "both")
    rid = _take(clinic2)
    _book(clinic2, rid)
    assert _appointments(clinic2) == 0
    # The other doctor follows the clinic, and the desk books for them.
    rid2 = _take(clinic2, doctor="doctor2")
    assert _book(clinic2, rid2, doctor="doctor2").status_code == 302


def test_who_may_set_a_doctors_choice(clinic2):
    from app.extensions import db
    from app.models import User

    def choice(doctor):
        with clinic2["app"].app_context():
            return db.session.get(User, clinic2["ids"][doctor]).booking_approval

    _set_policy(clinic2, "doctor", "reception")              # their own
    assert choice("doctor") == "reception"
    assert _set_policy(clinic2, "doctor2", "reception",
                       who="doc").status_code == 403        # somebody else's
    assert choice("doctor2") is None
    _set_policy(clinic2, "doctor2", "both", who="boss")      # the admin
    assert choice("doctor2") == "both"
    _set_policy(clinic2, "doctor", "whatever")               # back to the clinic
    assert choice("doctor") is None
    assert _set_policy(clinic2, "doctor", "both",
                       who="desk").status_code == 403


def test_the_clinic_rule_is_set_in_settings(clinic2):
    from app.utils.booking_requests import clinic_policy

    page = clinic2["sign_in"]("boss").get("/settings/").get_data(as_text=True)
    assert "data-booking-approval" in page
    with clinic2["app"].app_context():
        assert clinic_policy() == "both"


def test_the_doctors_own_page_offers_the_choice(clinic2):
    page = clinic2["sign_in"]("doc").get("/profile").get_data(as_text=True)
    assert 'data-approval-policy="clinic"' in page
    _set_policy(clinic2, "doctor", "reception")
    page = clinic2["sign_in"]("doc").get("/profile").get_data(as_text=True)
    assert 'data-approval-policy="reception"' in page


def test_the_rule_is_in_the_rules_not_only_on_the_screen(clinic2):
    """Another screen that one day calls ``approve`` gets the same answer:
    only the doctor it was sent to, and only once it was sent."""
    from app.extensions import db
    from app.models import BookingRequest, User
    from app.utils import booking_requests

    rid = _take(clinic2)
    with clinic2["app"].app_context():
        row = db.session.get(BookingRequest, rid)
        doctor = db.session.get(User, clinic2["ids"]["doctor"])
        other = db.session.get(User, clinic2["ids"]["doctor2"])
        assert booking_requests.approve(row, doctor) is None   # not sent yet
        booking_requests.forward(row, None)
        assert booking_requests.approve(row, other) is None    # not theirs
        assert booking_requests.approve(row, doctor) is row
        assert row.status == "approved"
