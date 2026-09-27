"""How often the desk keeps the suggested time — stage five's measure.

``BOOKING_APPROVAL_PLAN.md`` stage five is a decision taken after two months
of use, **by the numbers and not by opinion**: can one kind of request be
booked without a person choosing the time? The numbers are what the desk did
with the card's suggestion each time it booked a request. What is held here:

* the suggestion is the program's own, worked out on the server when the
  booking is opened — by either button — not read off the link;
* the booking records it beside what was booked: kept, another time the same
  day, another day, another doctor — or nothing free to suggest;
* a booking not opened from a request, or a value that does not read, records
  nothing rather than a guess; nothing is recorded when the form is merely
  opened;
* the report's shares add up to 100, and "nothing free" is kept apart — there
  was no suggestion to keep;
* it measures and changes nothing about booking.
"""
import os
import sys
from datetime import datetime, time, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def desk(clinic):
    from app.extensions import db
    from app.models import DoctorSchedule, Setting, User, Visit
    from app.utils.clock import local_today

    with clinic["app"].app_context():
        doctor_id = db.session.get(Visit, clinic["ids"]["visit"]).doctor_id
        other = User(username="doc2", full_name="د. سارة", role="doctor",
                     is_active=True)
        other.set_password("secret")
        db.session.add(other)
        db.session.flush()
        Setting.set("booking_approval", "reception")
        for doc in (doctor_id, other.id):
            for weekday in range(7):
                db.session.add(DoctorSchedule(
                    doctor_id=doc, weekday=weekday, start_time=time(9, 0),
                    end_time=time(17, 0), slot_minutes=30, is_active=True))
        db.session.commit()
        clinic["ids"]["doctor2"] = other.id
    clinic["doctor_id"] = doctor_id
    clinic["tomorrow"] = local_today() + timedelta(days=1)
    return clinic


def _take(desk, **fields):
    data = {"patient_id": desk["ids"]["child"], "doctor_id": desk["doctor_id"],
            "wanted_date": desk["tomorrow"].isoformat(), "appt_type": "followup"}
    data.update(fields)
    desk["sign_in"]("desk").post("/appointments/requests", data=data)
    from app.models import BookingRequest

    with desk["app"].app_context():
        return BookingRequest.query.order_by(BookingRequest.id.desc()).first().id


def _open(desk, rid, **args):
    """Open the booking from the request; the form's carried suggestion."""
    client = desk["sign_in"]("desk")
    query = "&".join(f"{k}={v}" for k, v in args.items())
    target = client.get(f"/appointments/requests/{rid}/book?{query}") \
        .headers["Location"]
    form = client.get(target).get_data(as_text=True)
    carried = form[form.index('name="suggested" value="') + 24:]
    return carried[:carried.index('"')]


def _book(desk, rid, suggested, doctor="doctor", on=None, at="09:00",
          appt_type="followup"):
    doctor_id = desk["doctor_id"] if doctor == "doctor" else desk["ids"][doctor]
    return desk["sign_in"]("desk").post("/appointments/new", data={
        "patient_id": desk["ids"]["child"], "doctor_id": doctor_id,
        "appt_date": (on or desk["tomorrow"]).isoformat(), "appt_time": at,
        "appt_type": appt_type, "from_request": rid, "suggested": suggested})


def _row(desk, rid):
    from app.extensions import db
    from app.models import BookingRequest

    with desk["app"].app_context():
        r = db.session.get(BookingRequest, rid)
        return {"status": r.status, "outcome": r.suggestion_outcome,
                "doctor": r.suggested_doctor_id, "date": r.suggested_date,
                "time": r.suggested_time}


# ------------------------------------------------------------ recorded ----
def test_the_suggestion_kept(desk):
    rid = _take(desk)
    carried = _open(desk, rid)
    assert carried == f"{desk['doctor_id']}|{desk['tomorrow'].isoformat()}|09:00"
    _book(desk, rid, carried)
    row = _row(desk, rid)
    assert (row["status"], row["outcome"]) == ("booked", "kept")
    assert (row["doctor"], row["date"], row["time"]) == (
        desk["doctor_id"], desk["tomorrow"], "09:00")


@pytest.mark.parametrize("change, expected", [
    ({"at": "11:30"}, "time"),
    ({"on": "day_after"}, "day"),
    ({"doctor": "doctor2"}, "doctor"),
])
def test_what_the_desk_changed(desk, change, expected):
    rid = _take(desk, doctor_id="")                 # any doctor
    carried = _open(desk, rid)
    assert carried.startswith(f"{desk['doctor_id']}|")
    if change.get("on") == "day_after":
        change = {"on": desk["tomorrow"] + timedelta(days=1)}
    _book(desk, rid, carried, **change)
    assert _row(desk, rid)["outcome"] == expected


def test_the_plain_book_button_carries_it_too(desk):
    """Whichever button opened the booking: the question is what the desk did
    with the suggestion on the card, and the card always shows one."""
    rid = _take(desk)
    assert _open(desk, rid).endswith("|09:00")


def test_the_suggestion_is_the_programs_not_the_links(desk):
    rid = _take(desk)
    carried = _open(desk, rid, doctor_id=desk["doctor_id"],
                    date=(desk["tomorrow"] + timedelta(days=5)).isoformat(),
                    time="15:00")
    assert carried == f"{desk['doctor_id']}|{desk['tomorrow'].isoformat()}|09:00"


def test_nothing_free_is_recorded_as_nothing_free(desk):
    from app.extensions import db
    from app.models import DoctorSchedule

    rid = _take(desk)
    with desk["app"].app_context():
        DoctorSchedule.query.delete()
        db.session.commit()
    assert _open(desk, rid) == "none"
    # Booked anyway — an overbooking the desk decided on; the booking screen
    # is what judges that, and it is not this test's business. Recorded here
    # directly, as the screen would.
    from app.models import Appointment, BookingRequest
    from app.utils import booking_requests

    with desk["app"].app_context():
        appt = Appointment(patient_id=desk["ids"]["child"],
                           doctor_id=desk["doctor_id"],
                           appt_date=desk["tomorrow"], appt_time=time(9, 0),
                           appt_type="followup", status="scheduled")
        db.session.add(appt)
        db.session.flush()
        booking_requests.booked(db.session.get(BookingRequest, rid), appt,
                                None, suggested=())
        db.session.commit()
    assert _row(desk, rid)["outcome"] == "none"


@pytest.mark.parametrize("carried", [
    "9|tomorrow|nine",                  # not a date
    "x|{day}|09:00",                    # not a doctor
    "1|{day}|9am",                      # not a time
    "1|{day}|09:00|extra",              # not three parts
    "",
])
def test_a_value_that_does_not_read_records_nothing(desk, carried):
    rid = _take(desk)
    reply = _book(desk, rid, carried.format(day=desk["tomorrow"].isoformat()))
    assert reply.status_code == 302
    row = _row(desk, rid)
    assert row["status"] == "booked" and row["outcome"] is None


def test_opening_the_form_records_nothing(desk):
    rid = _take(desk)
    _open(desk, rid)
    _open(desk, rid)
    row = _row(desk, rid)
    assert (row["status"], row["outcome"], row["time"]) == ("pending", None, None)


def test_a_booking_not_from_a_request_records_nothing(desk):
    from app.models import BookingRequest

    rid = _take(desk)
    desk["sign_in"]("desk").post("/appointments/new", data={
        "patient_id": desk["ids"]["child"], "doctor_id": desk["doctor_id"],
        "appt_date": desk["tomorrow"].isoformat(), "appt_time": "10:00",
        "appt_type": "followup",
        "suggested": f"{desk['doctor_id']}|{desk['tomorrow']}|10:00"})
    with desk["app"].app_context():
        assert BookingRequest.query.filter(
            BookingRequest.suggestion_outcome.isnot(None)).count() == 0
    assert _row(desk, rid)["status"] == "pending"


# ------------------------------------------------------------ the report ----
def _record(desk, outcomes, appt_type="followup", source="desk", days_ago=0):
    from app.extensions import db
    from app.models import BookingRequest

    with desk["app"].app_context():
        for o in outcomes:
            db.session.add(BookingRequest(
                patient_id=desk["ids"]["child"], status="booked",
                appt_type=appt_type, source=source, suggestion_outcome=o,
                requested_at=datetime.utcnow(),
                decided_at=datetime.utcnow() - timedelta(days=days_ago)))
        db.session.commit()


def test_the_shares_add_up_and_nothing_free_is_apart(desk):
    from app.utils import suggestion_measure

    _record(desk, ["kept", "time", "day", "none", "none"])
    with desk["app"].app_context():
        report = suggestion_measure.report(None)
    assert report["suggested"] == 3 and report["nothing_free"] == 2
    assert sum(pct for _n, pct in report["share"].values()) == 100
    assert {k: n for k, (n, _p) in report["share"].items()} == {
        "kept": 1, "time": 1, "day": 1, "doctor": 0}


def test_by_type_and_by_source(desk):
    from app.utils import suggestion_measure

    _record(desk, ["kept"] * 9 + ["time"], appt_type="vaccination")
    _record(desk, ["kept", "day", "doctor"], appt_type="new", source="whatsapp")
    with desk["app"].app_context():
        report = suggestion_measure.report(None)
    first = report["by_type"][0]
    assert (first["key"], first["total"], first["share"]["kept"]) == (
        "vaccination", 10, (9, 90))
    sources = {line["key"]: line["total"] for line in report["by_source"]}
    assert sources == {"desk": 10, "whatsapp": 3}


def test_the_period_counts_only_its_days(desk):
    from app.utils import suggestion_measure

    _record(desk, ["kept"], days_ago=100)
    _record(desk, ["time"], days_ago=3)
    with desk["app"].app_context():
        recent = suggestion_measure.report(30)
        everything = suggestion_measure.report(None)
    assert recent["suggested"] == 1 and recent["share"]["time"][0] == 1
    assert everything["suggested"] == 2
    # "Since" is when the measure first recorded, whatever the period.
    assert recent["since"] == everything["since"]


def test_a_third_each_still_adds_up_to_a_hundred(desk):
    from app.utils.suggestion_measure import _share

    share, total = _share({"kept": 1, "time": 1, "day": 1})
    assert total == 3 and sum(p for _n, p in share.values()) == 100


# ------------------------------------------------------------ the screen ----
def test_the_screen_empty_then_drawn(desk):
    client = desk["sign_in"]("desk")
    page = client.get("/appointments/requests/measure").get_data(as_text=True)
    assert "data-measure-empty" in page
    _record(desk, ["kept"] * 3 + ["day"], appt_type="vaccination")
    page = client.get("/appointments/requests/measure?days=all") \
        .get_data(as_text=True)
    assert 'data-measure="4"' in page and 'data-kept-pct="75"' in page
    assert 'data-type-line="vaccination"' in page
    assert 'data-seg="kept" data-pct="75"' in page
    box = page[page.index('data-outcome="kept"'):]
    assert '<b data-count="3">3</b>' in box[:box.index("</div>")]
    # A period nobody offers is the default.
    assert client.get("/appointments/requests/measure?days=7").status_code == 200


def test_the_requests_screen_links_to_it(desk):
    page = desk["sign_in"]("desk").get("/appointments/requests") \
        .get_data(as_text=True)
    assert "data-measure-link" in page and "/appointments/requests/measure" in page


def test_only_somebody_who_can_book_sees_it(desk):
    reply = desk["sign_in"]("acct").get("/appointments/requests/measure")
    assert reply.status_code in (302, 403)
