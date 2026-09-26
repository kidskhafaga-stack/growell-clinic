"""One slot, one child — when several desks book the same doctor at once.

Asked in these words: *«والناس اللي بتحجز في نفس الوقت لنفس الطبيب؟»*

Measured before it was answered: six desks sending the same doctor, the same
day and the same nine o'clock to a real server at the same instant made
**five appointments at nine o'clock**, and ten slots in a row were each
booked more than once. Every desk had asked "is it free?" and been told yes,
correctly — nobody had written yet.

Now the doctor's diary is held (``appointments.hold_the_diary``) before the
slot is asked about, so the second desk waits the few milliseconds until the
first booking is saved and is then told the time is gone. The same for
moving an appointment into a slot, and for walk-ins, where two families
arriving together were both given the same next slot.

What is kept as it was: a walk-in when the doctor has nothing left today is
still seen, at the current time, beside whoever else is — that overbooking is
the clinic's choice, not a clash.

These run over a real SQLite file with a thread per desk, and the moment
between "is it free?" and "write it" is held open on purpose, so that the
tests would book twice if the diary were not held.
"""
import os
import sys
import threading
import time as _time
from datetime import date, datetime, time, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

DESKS = 4


@pytest.fixture()
def diary(tmp_path, monkeypatch):
    """A doctor with a working day, four desks, and a child for each."""
    from app import create_app
    from app.extensions import db

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/diary.db")
    app = create_app("testing")
    with app.app_context():
        db.create_all()
        from app.models import DoctorSchedule, Patient, Service, User

        # Every clinic that vaccinates has it; the booking form files one if
        # it is missing, which is a write of its own.
        db.session.add(Service(code="SVC-VACFEE", name="رسم تطعيم", price=0,
                               category="vaccination_fee", is_active=True,
                               commission_type="none", commission_value=0,
                               visit_type="vaccination"))

        doctor = User(username="doc", full_name="د. منى", role="doctor",
                      is_active=True)
        doctor.set_password("secret")
        db.session.add(doctor)
        for n in range(DESKS):
            desk = User(username=f"desk{n}", full_name=f"استقبال {n}",
                        role="reception", is_active=True)
            desk.set_password("secret")
            db.session.add(desk)
        db.session.flush()
        for weekday in range(7):
            db.session.add(DoctorSchedule(
                doctor_id=doctor.id, weekday=weekday, start_time=time(9, 0),
                end_time=time(17, 0), slot_minutes=15, is_active=True))
        kids = []
        for n in range(DESKS * 2):
            kid = Patient(patient_number=f"K{n}", full_name=f"طفل {n}",
                          gender="male", date_of_birth=date(2023, 1, 1),
                          is_active=True)
            db.session.add(kid)
            db.session.flush()
            kids.append(kid.id)
        db.session.commit()
        doctor_id = doctor.id

    def sign_in(username):
        client = app.test_client()
        client.post("/login", data={"username": username,
                                    "password": "secret"})
        return client

    return {"app": app, "doctor": doctor_id, "kids": kids,
            "sign_in": sign_in,
            "tomorrow": date.today() + timedelta(days=2)}


@pytest.fixture()
def slow_to_answer(monkeypatch):
    """Hold open the moment between "which times are taken?" and the save.

    Without it the desks could happen to arrive one after another and a
    missing lock would go unnoticed; with it, every desk that is allowed to
    ask at the same time does, and would book the same slot."""
    from app.utils import appointments

    real = appointments.taken_times

    def taken_times(*args, **kwargs):
        answer = real(*args, **kwargs)
        _time.sleep(0.3)
        return answer

    monkeypatch.setattr(appointments, "taken_times", taken_times)
    # And where the status button asks it, which imported it by name.
    from app.blueprints.appointments import routes
    monkeypatch.setattr(routes, "taken_times", taken_times)


def _together(n, work):
    """Run ``work(i)`` for ``n`` desks, released at the same instant."""
    gate = threading.Barrier(n)
    replies, errors = [None] * n, []

    def one(i):
        try:
            gate.wait()
            replies[i] = work(i)
        except Exception as exc:  # noqa: BLE001 - reported below
            errors.append(exc)

    threads = [threading.Thread(target=one, args=(i,)) for i in range(n)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(60)
    assert not errors, errors
    return replies


def _at(diary, on_date, hhmm=None):
    from app.models import Appointment
    from app.models.appointment import ACTIVE_STATUSES

    with diary["app"].app_context():
        rows = Appointment.query.filter(
            Appointment.doctor_id == diary["doctor"],
            Appointment.appt_date == on_date,
            Appointment.status.in_(ACTIVE_STATUSES)).all()
        return [a.appt_time.strftime("%H:%M") for a in rows
                if hhmm is None or a.appt_time.strftime("%H:%M") == hhmm]


def _slot_taken(diary):
    from app.i18n import t

    with diary["app"].test_request_context():
        return t("appointments.slot_taken")


# ------------------------------------------------------------ booking ----
def test_four_desks_one_slot_one_booking(diary, slow_to_answer):
    desks = [diary["sign_in"](f"desk{i}") for i in range(DESKS)]

    def book(i):
        return desks[i].post("/appointments/new", data={
            "patient_id": diary["kids"][i], "doctor_id": diary["doctor"],
            "appt_date": diary["tomorrow"].isoformat(), "appt_time": "10:00",
            "appt_type": "followup"})

    replies = _together(DESKS, book)
    assert _at(diary, diary["tomorrow"], "10:00") == ["10:00"]
    saved = [r for r in replies if r.status_code == 302]
    refused = [r for r in replies if r.status_code == 200]
    assert len(saved) == 1 and len(refused) == DESKS - 1
    # And each desk that lost was told why, on the form it filled in.
    for reply in refused:
        assert _slot_taken(diary) in reply.get_data(as_text=True)


def test_a_refused_desk_can_book_the_next_slot_at_once(diary, slow_to_answer):
    """The diary is let go of when a booking is refused — the desk that lost
    is not left waiting on itself."""
    desks = [diary["sign_in"](f"desk{i}") for i in range(2)]

    def book(i):
        return desks[i].post("/appointments/new", data={
            "patient_id": diary["kids"][i], "doctor_id": diary["doctor"],
            "appt_date": diary["tomorrow"].isoformat(), "appt_time": "11:00",
            "appt_type": "followup"})

    replies = _together(2, book)
    loser = desks[[r.status_code for r in replies].index(200)]
    started = _time.monotonic()
    again = loser.post("/appointments/new", data={
        "patient_id": diary["kids"][5], "doctor_id": diary["doctor"],
        "appt_date": diary["tomorrow"].isoformat(), "appt_time": "11:15",
        "appt_type": "followup"})
    assert again.status_code == 302
    assert _time.monotonic() - started < 5
    assert sorted(_at(diary, diary["tomorrow"])) == ["11:00", "11:15"]


def test_different_slots_at_once_are_all_booked(diary):
    """Holding the diary makes desks take turns; it does not turn anybody
    away who asked for a free time."""
    desks = [diary["sign_in"](f"desk{i}") for i in range(DESKS)]
    times = ["09:00", "09:15", "09:30", "09:45"]

    def book(i):
        return desks[i].post("/appointments/new", data={
            "patient_id": diary["kids"][i], "doctor_id": diary["doctor"],
            "appt_date": diary["tomorrow"].isoformat(), "appt_time": times[i],
            "appt_type": "followup"})

    replies = _together(DESKS, book)
    assert [r.status_code for r in replies] == [302] * DESKS
    assert sorted(_at(diary, diary["tomorrow"])) == times


# ------------------------------------------------------------ moving ----
def test_two_appointments_moved_into_one_slot(diary, slow_to_answer):
    from app.extensions import db
    from app.models import Appointment

    with diary["app"].app_context():
        ids = []
        for i, hour in enumerate((9, 10)):
            appt = Appointment(patient_id=diary["kids"][i],
                               doctor_id=diary["doctor"],
                               appt_date=diary["tomorrow"],
                               appt_time=time(hour, 0), appt_type="followup",
                               status="scheduled")
            db.session.add(appt)
            db.session.flush()
            ids.append(appt.id)
        db.session.commit()

    desks = [diary["sign_in"](f"desk{i}") for i in range(2)]

    def move(i):
        return desks[i].post(f"/appointments/{ids[i]}/reschedule", data={
            "doctor_id": diary["doctor"],
            "appt_date": diary["tomorrow"].isoformat(), "appt_time": "12:00"})

    _together(2, move)
    assert _at(diary, diary["tomorrow"], "12:00") == ["12:00"]
    # The one that was not moved is still where it was.
    assert len(_at(diary, diary["tomorrow"])) == 2


# ------------------------------------------------------------ walk-ins ----
@pytest.fixture()
def morning(diary, monkeypatch):
    """Eight in the morning in the clinic, today, whatever the real clock
    says — so there are free slots left for a walk-in to be given."""
    from app.blueprints.appointments import routes
    from app.utils import appointments

    today = date.today()
    eight = datetime.combine(today, time(8, 0))
    monkeypatch.setattr(appointments, "to_local", lambda *_a, **_k: eight)
    monkeypatch.setattr(routes, "local_today", lambda *_a, **_k: today)
    diary["today"] = today
    return diary


def test_walk_ins_together_are_given_different_slots(morning, slow_to_answer):
    desks = [morning["sign_in"](f"desk{i}") for i in range(DESKS)]

    def walk_in(i):
        return desks[i].post("/appointments/walk-in", data={
            "patient_id": morning["kids"][i], "doctor_id": morning["doctor"]})

    _together(DESKS, walk_in)
    times = sorted(_at(morning, morning["today"]))
    assert times == ["09:00", "09:15", "09:30", "09:45"]


def test_a_full_day_still_takes_the_walk_in(morning, monkeypatch):
    """Overbooking when nothing is left is the clinic's choice and stays."""
    from app.blueprints.appointments import routes

    monkeypatch.setattr(routes, "next_available", lambda *_a, **_k: None)
    desks = [morning["sign_in"](f"desk{i}") for i in range(2)]

    def walk_in(i):
        return desks[i].post("/appointments/walk-in", data={
            "patient_id": morning["kids"][i], "doctor_id": morning["doctor"]})

    _together(2, walk_in)
    assert len(_at(morning, morning["today"])) == 2


def test_a_refused_booking_does_not_hold_up_the_other_desks(diary, monkeypatch):
    """While the refused form is being drawn again, another desk can save.
    Nothing was written, so there is nothing to keep the diary for."""
    import sqlite3

    from app.blueprints.appointments import routes

    path = diary["app"].config["SQLALCHEMY_DATABASE_URI"].split("///", 1)[1]
    client = diary["sign_in"]("desk0")
    others = []
    real = routes.render_template

    def render_template(*args, **kwargs):
        # Another desk, its own connection, a tenth of a second's patience.
        con = sqlite3.connect(path, timeout=0.1)
        try:
            con.execute("UPDATE settings SET value = value WHERE 0")
            con.execute("INSERT INTO settings (key, value) VALUES ('probe', '1')")
            con.commit()
            others.append("saved")
        except sqlite3.OperationalError as exc:
            others.append(str(exc))
        finally:
            con.close()
        return real(*args, **kwargs)

    monkeypatch.setattr(routes, "render_template", render_template)
    reply = client.post("/appointments/new", data={
        "patient_id": diary["kids"][0], "doctor_id": diary["doctor"],
        "appt_date": diary["tomorrow"].isoformat(), "appt_time": "08:00",
        "appt_type": "followup"})               # before the doctor starts
    assert reply.status_code == 200
    assert others == ["saved"]


# ------------------------------------------------------------ bringing back ----
def _book_row(diary, kid, on_date, hhmm, status="scheduled"):
    from app.extensions import db
    from app.models import Appointment

    hour, minute = (int(x) for x in hhmm.split(":"))
    with diary["app"].app_context():
        appt = Appointment(patient_id=diary["kids"][kid],
                           doctor_id=diary["doctor"], appt_date=on_date,
                           appt_time=time(hour, minute), appt_type="followup",
                           status=status)
        db.session.add(appt)
        db.session.commit()
        return appt.id


def _status(diary, appt_id):
    from app.extensions import db
    from app.models import Appointment

    with diary["app"].app_context():
        return db.session.get(Appointment, appt_id).status


def _bring_back(client, appt_id):
    return client.post(f"/appointments/{appt_id}/status",
                       data={"status": "scheduled"}, follow_redirects=True)


def _reopen_refused(diary):
    from app.i18n import t

    with diary["app"].test_request_context():
        return t("appointments.reopen_slot_taken")


def test_a_cancelled_booking_whose_time_was_given_away_stays_cancelled(diary):
    """Cancelled at ten; somebody else was booked at ten; bringing the first
    one back would have put two children in one slot."""
    day = diary["tomorrow"]
    first = _book_row(diary, 0, day, "10:00", status="cancelled")
    _book_row(diary, 1, day, "10:00")
    client = diary["sign_in"]("desk0")
    page = _bring_back(client, first).get_data(as_text=True)
    assert _status(diary, first) == "cancelled"
    assert _reopen_refused(diary) in page
    assert _at(diary, day, "10:00") == ["10:00"]


def test_a_missed_booking_whose_time_was_given_away_stays_missed(diary):
    day = diary["tomorrow"]
    missed = _book_row(diary, 0, day, "11:00", status="no_show")
    _book_row(diary, 1, day, "11:00")
    _bring_back(diary["sign_in"]("desk0"), missed)
    assert _status(diary, missed) == "no_show"


def test_a_cancelled_booking_whose_time_is_still_free_comes_back(diary):
    day = diary["tomorrow"]
    first = _book_row(diary, 0, day, "10:00", status="cancelled")
    _book_row(diary, 1, day, "10:15")                 # next door, not a clash
    _bring_back(diary["sign_in"]("desk0"), first)
    assert _status(diary, first) == "scheduled"


def test_a_missed_booking_comes_back_after_its_hour(diary):
    """Marked absent at nine, walks in at ten: the hour having gone is not a
    reason to refuse — only another child in the slot is."""
    from app.utils.clock import local_today

    today = local_today()
    missed = _book_row(diary, 0, today, "00:00", status="no_show")
    _bring_back(diary["sign_in"]("desk0"), missed)
    assert _status(diary, missed) == "scheduled"


def test_two_cancelled_bookings_brought_back_at_once(diary, slow_to_answer):
    """Two cancelled at the same ten o'clock, brought back by two desks in
    the same instant: one of them."""
    day = diary["tomorrow"]
    ids = [_book_row(diary, i, day, "10:00", status="cancelled")
           for i in range(2)]
    desks = [diary["sign_in"](f"desk{i}") for i in range(2)]

    def bring_back(i):
        return desks[i].post(f"/appointments/{ids[i]}/status",
                             data={"status": "scheduled"})

    _together(2, bring_back)
    assert sorted(_status(diary, i) for i in ids) == ["cancelled", "scheduled"]
