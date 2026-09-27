"""The card beside a booking request — ``BOOKING_APPROVAL_PLAN.md`` stage two.

What is held here:

* the card says what the desk would otherwise open the child's file for —
  age, last visit, the dose that is due — from the same functions the file
  reads, not a second opinion;
* a booking the child already holds is said on the card, so a family that
  asks twice is not booked twice;
* the soonest free time is the program's own "next available", with the
  doctor asked for, from the day asked for (or today, once it has passed),
  skipping a time already taken;
* it is a suggestion: the button opens the ordinary booking screen with the
  time filled in, and a request that still needs its doctor's yes offers no
  button — not on the screen, and not by typing the link;
* a request that names its doctor is booked with that doctor, whatever the
  link says; a time carried in a link is checked before it is used;
* nothing on the card is written anywhere.
"""
import os
import sys
from datetime import time, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def desk(clinic):
    """A doctor with a working week; the desk alone approves, unless a test
    says otherwise."""
    from app.extensions import db
    from app.models import DoctorSchedule, Setting, Visit
    from app.utils.clock import local_today

    with clinic["app"].app_context():
        doctor_id = db.session.get(Visit, clinic["ids"]["visit"]).doctor_id
        Setting.set("booking_approval", "reception")
        for weekday in range(7):
            db.session.add(DoctorSchedule(
                doctor_id=doctor_id, weekday=weekday, start_time=time(9, 0),
                end_time=time(17, 0), slot_minutes=30, is_active=True))
        db.session.commit()
    clinic["doctor_id"] = doctor_id
    clinic["tomorrow"] = local_today() + timedelta(days=1)
    return clinic


def _take(desk, **fields):
    data = {"doctor_id": desk["doctor_id"],
            "wanted_date": desk["tomorrow"].isoformat(),
            "appt_type": "followup", "message": "عايزة ميعاد",
            "patient_id": desk["ids"]["child"]}
    data.update(fields)
    desk["sign_in"]("desk").post("/appointments/requests", data=data)
    from app.models import BookingRequest

    with desk["app"].app_context():
        return BookingRequest.query.order_by(BookingRequest.id.desc()).first().id


def _page(desk, who="desk"):
    reply = desk["sign_in"](who).get("/appointments/requests")
    assert reply.status_code == 200
    return reply.get_data(as_text=True)


def _row(page, rid):
    row = page[page.index(f'data-request="{rid}"'):]
    return row[:row.index("</tr>")]


def _appointment(desk, patient_id, on_date, at):
    from app.extensions import db
    from app.models import Appointment

    with desk["app"].app_context():
        db.session.add(Appointment(
            patient_id=patient_id, doctor_id=desk["doctor_id"],
            appt_date=on_date, appt_time=at, appt_type="followup",
            status="scheduled"))
        db.session.commit()


# ------------------------------------------------------------ the child ----
def test_the_card_says_age_and_last_visit(desk):
    from app.extensions import db
    from app.models import Patient
    from app.utils.clock import local_today

    rid = _take(desk)
    row = _row(_page(desk), rid)
    assert f'data-request-card="{rid}"' in row
    assert f'data-card-last-visit="{local_today().isoformat()}"' in row
    assert "د. أحمد" in row
    with desk["app"].app_context():
        child = db.session.get(Patient, desk["ids"]["child"])
        years, _months = child.age_parts
    age = row[row.index("data-card-age>") + len("data-card-age>"):]
    age = age[:age.index("</span>")].strip()
    assert age and str(years) in age


def test_the_dose_is_the_one_the_childs_own_plan_says(desk):
    """A baby of ten weeks, whose first dose is due: the card names the dose
    the file's "next due" card names — not a second opinion."""
    from app.extensions import db
    from app.models import Patient
    from app.utils.clock import local_today
    from app.utils.vaccines import next_due_dose, patient_plan

    from app.utils.vaccines import seed_vaccine_schedules, seed_vaccines

    with desk["app"].app_context():
        seed_vaccines()
        seed_vaccine_schedules()
        baby = Patient(patient_number="P9", full_name="رضيع", gender="male",
                       date_of_birth=local_today() - timedelta(days=70))
        db.session.add(baby)
        db.session.commit()
        baby_id = baby.id
        due = next_due_dose(patient_plan(baby, "ar"))
    assert due is not None, "the national schedule has a dose due by ten weeks"
    rid = _take(desk, patient_id=baby_id)
    row = _row(_page(desk), rid)
    assert f'data-card-dose="{due[3]["status"]}"' in row
    assert due[1].display_name("ar") in row


def test_a_child_with_no_visit_says_so(desk):
    from app.extensions import db
    from app.models import Patient

    with desk["app"].app_context():
        kid = Patient(patient_number="P2", full_name="طفل جديد", gender="female",
                      date_of_birth=desk["tomorrow"] - timedelta(days=400))
        db.session.add(kid)
        db.session.commit()
        kid_id = kid.id
    rid = _take(desk, patient_id=kid_id)
    row = _row(_page(desk), rid)
    assert 'data-card-last-visit=""' in row
    assert "لسه مالوش زيارة" in row


def test_a_booking_already_held_is_on_the_card(desk):
    _appointment(desk, desk["ids"]["child"], desk["tomorrow"], time(11, 0))
    rid = _take(desk)
    row = _row(_page(desk), rid)
    assert "data-card-booked" in row
    assert desk["tomorrow"].isoformat() in row


def test_a_family_not_on_file_has_no_child_card_but_a_time(desk):
    rid = _take(desk, patient_id="", contact_name="أم علي",
                contact_phone="01000000000")
    row = _row(_page(desk), rid)
    assert "data-request-card" not in row
    assert f'data-suggestion="{desk["tomorrow"].isoformat()} 09:00"' in row


# ------------------------------------------------------------ the time ----
def test_the_soonest_time_is_the_programs_own_next_available(desk):
    from app.utils.appointments import next_available

    rid = _take(desk)
    with desk["app"].app_context():
        found = next_available(desk["doctor_id"], desk["tomorrow"])
    row = _row(_page(desk), rid)
    assert f'data-suggestion="{found["date"]} {found["time"]}"' in row


def test_a_time_already_taken_is_skipped(desk):
    from app.extensions import db
    from app.models import Patient

    with desk["app"].app_context():
        other = Patient(patient_number="P3", full_name="أخوه", gender="male",
                        date_of_birth=desk["tomorrow"] - timedelta(days=900))
        db.session.add(other)
        db.session.commit()
        other_id = other.id
    _appointment(desk, other_id, desk["tomorrow"], time(9, 0))
    rid = _take(desk)
    row = _row(_page(desk), rid)
    assert f'data-suggestion="{desk["tomorrow"].isoformat()} 09:30"' in row


def test_a_day_that_has_passed_looks_from_today(desk):
    from app.extensions import db
    from app.models import BookingRequest
    from app.utils.appointments import next_available
    from app.utils.clock import local_today

    rid = _take(desk)
    with desk["app"].app_context():
        row = db.session.get(BookingRequest, rid)
        row.wanted_date = local_today() - timedelta(days=5)
        db.session.commit()
        found = next_available(desk["doctor_id"], local_today())
    page_row = _row(_page(desk), rid)
    assert f'data-suggestion="{found["date"]} {found["time"]}"' in page_row


def test_the_button_opens_the_booking_screen_with_the_time(desk):
    rid = _take(desk)
    row = _row(_page(desk), rid)
    assert "data-book-suggested" in row
    client = desk["sign_in"]("desk")
    reply = client.get(f"/appointments/requests/{rid}/book?"
                       f"doctor_id={desk['doctor_id']}&"
                       f"date={desk['tomorrow'].isoformat()}&time=09:00")
    target = reply.headers["Location"]
    assert "time=09:00" in target and f"from_request={rid}" in target
    form = client.get(target).get_data(as_text=True)
    # The slot list opens with the suggested time chosen.
    assert "', '09:00', '" in form


def test_a_time_in_a_link_is_checked(desk):
    rid = _take(desk)
    reply = desk["sign_in"]("desk").get(
        f"/appointments/requests/{rid}/book?time=9am');alert(1)//")
    assert "time=&" in reply.headers["Location"] or \
        reply.headers["Location"].endswith("time=")
    form = desk["sign_in"]("desk").get(
        "/appointments/new?time=25:99").get_data(as_text=True)
    assert "25:99" not in form


def test_a_named_doctor_is_not_swapped_by_the_link(desk):
    from app.extensions import db
    from app.models import User

    with desk["app"].app_context():
        other = User(username="doc2", full_name="د. سارة", role="doctor",
                     is_active=True)
        other.set_password("secret")
        db.session.add(other)
        db.session.commit()
        other_id = other.id
    rid = _take(desk)
    reply = desk["sign_in"]("desk").get(
        f"/appointments/requests/{rid}/book?doctor_id={other_id}")
    assert f"doctor_id={desk['doctor_id']}" in reply.headers["Location"]


# ------------------------------------------------------------ the doctor ----
def test_no_button_while_the_doctor_has_to_say_yes(desk):
    """The clinic's default: the desk, then the doctor."""
    from app.models import Setting

    with desk["app"].app_context():
        Setting.set("booking_approval", "both")
        desk["db"].session.commit()
    rid = _take(desk)
    row = _row(_page(desk), rid)
    assert "data-suggestion=" in row and "data-book-suggested" not in row
    # And typed by hand, the link goes back to the requests with the reason.
    reply = desk["sign_in"]("desk").get(
        f"/appointments/requests/{rid}/book?doctor_id={desk['doctor_id']}"
        f"&date={desk['tomorrow'].isoformat()}&time=09:00")
    assert "/appointments/requests" in reply.headers["Location"]
    assert "from_request" not in reply.headers["Location"]


def test_any_doctor_names_the_doctor_found_and_their_yes(desk):
    from app.models import Setting

    rid = _take(desk, doctor_id="")
    row = _row(_page(desk), rid)
    assert "د. أحمد" in row and "data-book-suggested" in row
    with desk["app"].app_context():
        Setting.set("booking_approval", "both")
        desk["db"].session.commit()
    row = _row(_page(desk), rid)
    assert "data-needs-ok" in row and "data-book-suggested" not in row
    reply = desk["sign_in"]("desk").get(
        f"/appointments/requests/{rid}/book?doctor_id={desk['doctor_id']}")
    assert "from_request" not in reply.headers["Location"]


# ------------------------------------------------------------ nothing written --
def test_the_card_writes_nothing(desk):
    from app.models import ActivityLog, Appointment, BookingRequest

    rid = _take(desk)
    with desk["app"].app_context():
        # Signing in is logged; opening the requests is not.
        before = (Appointment.query.count(),
                  ActivityLog.query.filter(ActivityLog.action != "login").count(),
                  BookingRequest.query.get(rid).status)
    _page(desk)
    _page(desk)
    with desk["app"].app_context():
        after = (Appointment.query.count(),
                 ActivityLog.query.filter(ActivityLog.action != "login").count(),
                 BookingRequest.query.get(rid).status)
    assert before == after


def test_nothing_free_is_said(desk):
    from app.extensions import db
    from app.models import DoctorSchedule

    rid = _take(desk)
    with desk["app"].app_context():
        DoctorSchedule.query.delete()
        db.session.commit()
    row = _row(_page(desk), rid)
    assert 'data-suggestion=""' in row and "data-nothing-free" in row


def test_the_doctor_asked_to_approve_sees_the_card_too(desk):
    """Their yes is decided on the same facts: the child's age, last visit,
    and what is due."""
    from app.models import Setting

    with desk["app"].app_context():
        Setting.set("booking_approval", "both")
        desk["db"].session.commit()
    rid = _take(desk)
    desk["sign_in"]("desk").post(f"/appointments/requests/{rid}/forward")
    page = _page(desk, who="doc")
    mine = page[page.index(f'data-mine="{rid}"'):]
    mine = mine[:mine.index("</tr>")]
    assert f'data-request-card="{rid}"' in mine
    assert "data-card-last-visit" in mine


def test_a_cancelled_or_past_booking_is_not_held(desk):
    from app.extensions import db
    from app.models import Appointment
    from app.utils.clock import local_today

    _appointment(desk, desk["ids"]["child"], desk["tomorrow"], time(11, 0))
    _appointment(desk, desk["ids"]["child"], local_today() - timedelta(days=3),
                 time(11, 0))
    with desk["app"].app_context():
        upcoming = Appointment.query.filter_by(
            appt_date=desk["tomorrow"]).one()
        upcoming.status = "cancelled"
        db.session.commit()
    rid = _take(desk)
    assert "data-card-booked" not in _row(_page(desk), rid)
