"""The desk was the one screen that got slower as the clinic filled up.

Measured on a seeded clinic, before and after, median of seven runs:

    2,000 patients   desk   230 queries  445 ms  ->  30 queries  125 ms
                     list    18 queries  127 ms  ->  18 queries   96 ms

Every other screen in the program was already flat — the patient list, the
appointments board, the reports all cost the same at 400 patients as at 2,000,
because they page. The desk did not, for two separate reasons.

**One query per conversation.** `inbox.conversations` read the newest message
per thread and then touched `.patient` while building each row, which is a
lazy load apiece: 134 of the desk's 164 queries were the identical
`SELECT patients WHERE id = ?`.

**A full scan for a five-row card.** The birthday card and the work list each
read *every active patient* and decided in Python who had a birthday coming.
Three scans of the whole register per page view, to show about five names.

These tests do not assert a millisecond count — that would fail on a busy
machine and teach everybody to ignore it. They assert the **shape**: that
adding patients does not add queries. A stopwatch measures the machine; the
query count measures the code.
"""
import os
import sys
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

from app.utils.clock import local_today  # noqa: E402


@pytest.fixture()
def counting(clinic):
    """Counts SQL statements while a page is built."""
    from sqlalchemy import event

    from app.extensions import db

    with clinic["app"].app_context():
        engine = db.engine

    state = {"n": 0, "on": False}

    def _count(conn, cur, statement, params, context, many):
        if state["on"]:
            state["n"] += 1

    event.listen(engine, "after_cursor_execute", _count)
    clinic["count"] = state
    yield clinic
    event.remove(engine, "after_cursor_execute", _count)


def _crowd(clinic, n, offset=0):
    """`n` more patients, each with a birthday this week and a conversation.

    Both halves matter: the conversation exercises the inbox's per-row patient
    load, the birthday exercises the scan.
    """
    from app.extensions import db
    from app.models import MessageLog, Patient

    today = local_today()
    for i in range(n):
        when = today + timedelta(days=i % 5)
        kid = Patient(patient_number=f"F{offset + i:05d}",
                      full_name=f"طفل {offset + i}", gender="male",
                      date_of_birth=date(2020, when.month, when.day),
                      own_phone=f"0111{offset + i:07d}", is_active=True)
        db.session.add(kid)
        db.session.flush()
        db.session.add(MessageLog(
            patient_id=kid.id, to_phone=kid.own_phone, direction="in",
            body="سؤال", status="sent",
            created_at=datetime.utcnow() - timedelta(hours=i % 20)))
    db.session.commit()


@pytest.fixture()
def loading(clinic):
    """Counts the Patient rows a page actually turns into objects.

    Queries alone cannot see the second problem. Reading every active patient
    and filtering in Python is **one** query — the same single query as reading
    only the handful with a birthday this week — so a query counter says the
    full scan and the filtered lookup are identical. They are not: one builds
    five objects and the other builds the whole register.

    Found by mutation testing. Putting the scan back passed every assertion in
    this file until this fixture existed.
    """
    from sqlalchemy import event

    from app.models import Patient

    state = {"n": 0, "on": False}

    def _loaded(target, context):
        if state["on"]:
            state["n"] += 1

    event.listen(Patient, "load", _loaded)
    clinic["loaded"] = state
    yield clinic
    event.remove(Patient, "load", _loaded)


def _patients_loaded_by(loading, url):
    client = loading["sign_in"]("desk")
    client.get(url)
    loading["loaded"]["n"] = 0
    loading["loaded"]["on"] = True
    answer = client.get(url)
    loading["loaded"]["on"] = False
    assert answer.status_code == 200
    return loading["loaded"]["n"]


def _queries_for(counting, url):
    client = counting["sign_in"]("desk")
    client.get(url)                      # warm: first-touch costs are not the page
    counting["count"]["n"] = 0
    counting["count"]["on"] = True
    answer = client.get(url)
    counting["count"]["on"] = False
    assert answer.status_code == 200
    return counting["count"]["n"]


# ------------------------------------------------------------- the invariant

@pytest.mark.parametrize("url", ["/messages/desk", "/messages/today"])
def test_more_patients_does_not_mean_more_queries(counting, url):
    """The property that actually matters, and the one that was broken.

    Not "is it fast" — "does it get slower". A screen whose query count grows
    with the register is one that works in testing and stops working in the
    third year, which is the worst possible time to find out.
    """
    with counting["app"].app_context():
        _crowd(counting, 10)
    small = _queries_for(counting, url)

    with counting["app"].app_context():
        _crowd(counting, 60, offset=1000)
    large = _queries_for(counting, url)

    assert large <= small + 3, (
        f"{url} went from {small} to {large} queries when 60 patients were "
        f"added — the cost grows with the clinic")


def test_the_desk_does_not_ask_once_per_conversation(counting):
    """The N+1 by name: 134 of 164 queries were this one lazy load."""
    with counting["app"].app_context():
        _crowd(counting, 40)

    assert _queries_for(counting, "/messages/desk") < 60, \
        "the desk is querying per conversation again"


@pytest.mark.parametrize("url", ["/messages/desk", "/messages/today"])
def test_a_page_does_not_build_the_whole_register(loading, url):
    """The cost a query counter cannot see.

    Patients with a birthday far away are added; none of them has any reason
    to be read. If the page turns them into objects anyway, it is scanning.
    """
    from app.extensions import db
    from app.models import Patient, User, Visit

    with loading["app"].app_context():
        _crowd(loading, 5)
        doctor = User.query.filter_by(username="doc").first()
        for i in range(50):
            far = Patient(patient_number=f"Z{i:05d}", full_name=f"بعيد {i}",
                          gender="female", date_of_birth=date(2019, 1, 1),
                          own_phone=f"0133{i:07d}", is_active=True)
            db.session.add(far)
            db.session.flush()
            # Seen last week, so they are not lapsed either. Without a visit
            # the recall source has nothing to look at and would scan the
            # register unnoticed — which is exactly what it did, and what a
            # mutation of its query slipped past until these visits existed.
            db.session.add(Visit(patient_id=far.id, doctor_id=doctor.id,
                                 visit_date=local_today() - timedelta(days=7),
                                 status="completed",
                                 created_at=datetime.utcnow()))
        db.session.commit()
        total = Patient.query.filter_by(is_active=True).count()

    built = _patients_loaded_by(loading, url)

    assert built < total, (
        f"{url} built {built} patient objects out of {total} active files — "
        "it is reading the whole register to show a handful of rows")


def test_the_birthday_card_does_not_read_the_whole_register(counting):
    """A card with five rows on it must not load ten thousand patients."""
    from app.utils.worklist import birthday_candidates

    with counting["app"].app_context():
        _crowd(counting, 30)
        # Nobody below has a birthday this week; none of them should be read.
        from app.extensions import db
        from app.models import Patient
        for i in range(40):
            db.session.add(Patient(
                patient_number=f"X{i:05d}", full_name=f"بعيد {i}",
                gender="female", date_of_birth=date(2019, 1, 1),
                own_phone=f"0122{i:07d}", is_active=True))
        db.session.commit()

        today = local_today()
        loaded = birthday_candidates(today, 7)
        everybody = Patient.query.filter_by(is_active=True).count()

    assert len(loaded) < everybody, \
        "the birthday query returns every active patient — it is still a scan"
    assert all(p.date_of_birth.month != 1 or p.date_of_birth.day != 1
               for p in loaded), "patients with no birthday this week were loaded"


def test_asking_twice_in_one_request_only_costs_once(counting):
    """The desk asks for the birthdays up to three times to draw one page."""
    from app.blueprints.messages.routes import _upcoming_birthdays

    with counting["app"].app_context():
        _crowd(counting, 5)

    with counting["app"].test_request_context("/"):
        counting["count"]["n"] = 0
        counting["count"]["on"] = True
        first = _upcoming_birthdays()
        after_first = counting["count"]["n"]
        second = _upcoming_birthdays()
        after_second = counting["count"]["n"]
        counting["count"]["on"] = False

    assert after_second == after_first, \
        "the second ask went back to the database inside the same request"
    assert len(first) == len(second)


# ------------------------------------------------ behaviour is not changed

def test_the_same_children_are_still_listed(counting):
    """A faster query that returns different people is not an optimisation."""
    from app.utils.worklist import birthday_candidates

    with counting["app"].app_context():
        _crowd(counting, 12)
        today = local_today()

        fast = {p.id for p in birthday_candidates(today, 7)}

        # The old way, kept here as the thing being compared against.
        from app.models import Patient
        from app.utils.worklist import _next_birthday
        slow = set()
        for p in Patient.query.filter_by(is_active=True).all():
            if not p.date_of_birth:
                continue
            when = _next_birthday(p.date_of_birth, today)
            if today <= when <= today + timedelta(days=7):
                slow.add(p.id)

    assert fast == slow, (
        "the indexed query and the full scan disagree about who has a "
        f"birthday this week: only-fast={fast - slow} only-slow={slow - fast}")


def test_a_leap_day_child_is_not_lost(counting):
    """29 February has no anniversary in a common year.

    The old scan moved those birthdays to the 28th in Python. Filtering on
    (month, day) in SQL would drop them unless the filter is told, so this is
    the case most likely to be quietly broken by the change.
    """
    from app.extensions import db
    from app.models import Patient
    from app.utils.worklist import birthday_candidates

    with counting["app"].app_context():
        db.session.add(Patient(
            patient_number="LEAP1", full_name="طفل ٢٩ فبراير", gender="male",
            date_of_birth=date(2020, 2, 29), own_phone="01099999999",
            is_active=True))
        db.session.commit()

        # Asked from the 27th of February, the 29th is inside a 7-day window
        # in a leap year and the 28th stands in for it otherwise.
        found = birthday_candidates(date(2027, 2, 27), 7)

    assert any(p.patient_number == "LEAP1" for p in found), \
        "the 29 February child fell out of the window entirely"


def test_the_gate_still_refuses_an_opted_out_family(counting):
    """The rule that must never be lost to a refactor of the query around it."""
    from app.extensions import db
    from app.models import Patient
    from app.utils import worklist

    with counting["app"].app_context():
        _crowd(counting, 3)
        kid = Patient.query.filter(Patient.patient_number.like("F%")).first()
        kid.wa_opt_out = True
        db.session.commit()
        opted_out = kid.id

        rows = worklist.today_list()

    assert all(r["patient"].id != opted_out for r in rows), \
        "an opted-out family is on the work list after the query changed"
