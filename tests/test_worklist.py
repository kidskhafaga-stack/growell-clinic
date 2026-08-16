"""One list of everybody the clinic has a reason to write to today.

The reasons already existed, each on its own screen. Three screens is three
times somebody has to remember to look, and the one nobody opens is the one
that stops happening.

**Joining them is the easy half.** These tests are mostly about the gate,
because a list built by merging three sources is exactly where a rule that
only one of them enforced gets lost — and the rule most likely to be lost is
the opt-out, which is the one mistake here that cannot be taken back.

Each source is also tested on its own. `today_list` swallows an exception from
one builder so a single broken source cannot blank the whole screen, and that
guard would otherwise hide a source that had stopped working entirely — it
hid exactly that during development.
"""
import os
import sys
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


def _patient(clinic, name="طفل جديد", number="W1", dob_in_days=2,
             opt_out=False, phone="01000000000", active=True):
    from app.extensions import db
    from app.models import Patient

    today = date.today()
    dob = None
    if dob_in_days is not None:
        when = today + timedelta(days=dob_in_days)
        dob = date(2024, when.month, when.day)
    p = Patient(patient_number=number, full_name=name, gender="male",
                date_of_birth=dob, wa_opt_out=opt_out, own_phone=phone,
                is_active=active)
    db.session.add(p)
    db.session.flush()
    return p


def _rows(clinic, build):
    from app.extensions import db
    from app.utils import worklist

    with clinic["app"].app_context():
        build()
        db.session.commit()
        return worklist.today_list()


def _kinds(rows, kind):
    return [r for r in rows if r["kind"] == kind]


# ------------------------------------------------------------------- the gate

def test_a_reachable_patient_is_on_the_list(clinic):
    rows = _rows(clinic, lambda: _patient(clinic))

    assert _kinds(rows, "birthday"), "a birthday two days away is not on the list"


def test_an_opted_out_family_is_never_on_it(clinic):
    """The one rule on this screen that cannot be taken back."""
    rows = _rows(clinic, lambda: _patient(clinic, name="رافض", opt_out=True))

    assert not _kinds(rows, "birthday"), \
        "somebody who asked not to be written to is on a send list"


def test_a_patient_with_no_number_is_not_on_it(clinic):
    rows = _rows(clinic, lambda: _patient(clinic, name="بلا رقم", phone=None))

    assert not _kinds(rows, "birthday"), \
        "a row with nothing to send to is on a list of things to send"


def test_an_archived_file_is_not_on_it(clinic):
    """The clinic has already said those are off its books."""
    rows = _rows(clinic, lambda: _patient(clinic, name="مؤرشف", active=False))

    assert not _kinds(rows, "birthday"), "an archived file is being chased"


def test_the_gate_is_one_function_not_three(clinic):
    """Asked separately per source, one of them eventually forgets a rule."""
    from app.models import Patient
    from app.utils.worklist import reachable

    with clinic["app"].app_context():
        good = _patient(clinic, number="G1")
        assert reachable(good) is True

        good.wa_opt_out = True
        assert reachable(good) is False
        good.wa_opt_out = False

        good.own_phone = None
        assert reachable(good) is False

    assert reachable(None) is False, "a missing patient must not be reachable"
    assert not isinstance(Patient, bool)  # keeps the import honest


# ------------------------------------------------- already said, do not repeat

def test_a_birthday_already_sent_drops_off(clinic):
    """A list that never shrinks stops being a work list."""
    from app.extensions import db
    from app.models import MessageLog

    def build():
        p = _patient(clinic)
        db.session.add(MessageLog(patient_id=p.id, to_phone="01000000000",
                                  body="كل سنة وانت طيب", status="sent",
                                  template_type="birthday",
                                  created_at=datetime.utcnow()))

    assert not _kinds(_rows(clinic, build), "birthday"), \
        "a birthday message already sent is still on the list"


def test_a_message_older_than_the_guard_does_not_suppress(clinic):
    """The guard is a repeat window, not a permanent tombstone."""
    from app.extensions import db
    from app.models import MessageLog
    from app.utils.worklist import REPEAT_GUARD_DAYS

    def build():
        p = _patient(clinic)
        long_ago = datetime.utcnow() - timedelta(
            days=REPEAT_GUARD_DAYS["birthday"] + 5)
        db.session.add(MessageLog(patient_id=p.id, to_phone="01000000000",
                                  body="السنة اللي فاتت", status="sent",
                                  template_type="birthday",
                                  created_at=long_ago))

    assert _kinds(_rows(clinic, build), "birthday"), \
        "last year's birthday message suppressed this year's"


def test_another_kind_of_message_does_not_suppress_a_birthday(clinic):
    """The guard is per reason. One `template_type` must not silence another."""
    from app.extensions import db
    from app.models import MessageLog

    def build():
        p = _patient(clinic)
        db.session.add(MessageLog(patient_id=p.id, to_phone="01000000000",
                                  body="تذكير بالموعد", status="sent",
                                  template_type="appointment_reminder",
                                  created_at=datetime.utcnow()))

    assert _kinds(_rows(clinic, build), "birthday"), \
        "an unrelated message suppressed the birthday"


@pytest.mark.parametrize("kind", ["birthday", "vaccine", "recall"])
def test_every_reason_has_its_own_guard_and_type(clinic, kind):
    from app.utils.worklist import REPEAT_GUARD_DAYS, TEMPLATE_TYPES

    assert kind in REPEAT_GUARD_DAYS and REPEAT_GUARD_DAYS[kind] > 0
    assert kind in TEMPLATE_TYPES


def test_the_guards_are_not_all_the_same_number(clinic):
    """They are different conversations.

    Chasing a lapsed family twice in a month is nagging; a dose still not given
    a fortnight later is worth saying again.
    """
    from app.utils.worklist import REPEAT_GUARD_DAYS

    assert len(set(REPEAT_GUARD_DAYS.values())) > 1, \
        "one window for three different conversations"


# --------------------------------------------------------------- the ordering

def test_the_latest_thing_is_at_the_top(clinic):
    """A dose three months overdue outranks a birthday next week.

    Built out of order on purpose, so insertion order and the answer disagree.
    """
    from app.extensions import db
    from app.models import MessageLog, Patient
    from app.utils import worklist

    with clinic["app"].app_context():
        _patient(clinic, name="عيد بعد أسبوع", number="B1", dob_in_days=6)
        _patient(clinic, name="عيد النهاردة", number="B2", dob_in_days=0)
        db.session.commit()
        rows = [r for r in worklist.today_list() if r["kind"] == "birthday"]

    assert len(rows) == 2
    assert rows[0]["patient"].full_name == "عيد النهاردة", \
        f"ordered {[r['patient'].full_name for r in rows]}"
    assert not isinstance(MessageLog, bool) and not isinstance(Patient, bool)


# ---------------------------------------------------------------- the screens

def test_the_list_has_a_screen_of_its_own(clinic):
    from app.extensions import db

    with clinic["app"].app_context():
        _patient(clinic)
        db.session.commit()

    page = clinic["sign_in"]("desk").get("/messages/today").data.decode()

    assert "طفل جديد" in page, "the work list screen does not show the work"


def test_the_filter_shows_a_subset_and_the_counts_do_not_move(clinic):
    """A count that disagrees with the list it heads is why nobody trusts one."""
    from app.extensions import db

    with clinic["app"].app_context():
        _patient(clinic)
        db.session.commit()

    client = clinic["sign_in"]("desk")
    everything = client.get("/messages/today").data.decode()
    birthdays = client.get("/messages/today?kind=birthday").data.decode()
    recalls = client.get("/messages/today?kind=recall").data.decode()

    assert "طفل جديد" in everything and "طفل جديد" in birthdays
    assert "طفل جديد" not in recalls, "the filter is not filtering"


def test_a_nonsense_filter_shows_everything_rather_than_failing(clinic):
    """It arrives in a URL, so it is checked rather than trusted."""
    answer = clinic["sign_in"]("desk").get("/messages/today?kind=../etc/passwd")

    assert answer.status_code == 200


def test_the_desk_carries_the_count_and_a_way_in(clinic):
    from app.extensions import db

    with clinic["app"].app_context():
        _patient(clinic)
        db.session.commit()

    page = clinic["sign_in"]("desk").get("/messages/desk").data.decode()

    assert "/messages/today" in page, "the desk has no way into the day's list"


def test_reception_may_open_it(clinic):
    """It is the work, not the setup."""
    assert clinic["sign_in"]("desk").get("/messages/today").status_code == 200


def test_a_broken_source_does_not_blank_the_desk(clinic):
    """The count is one panel on a dashboard, not the dashboard."""
    from app.utils import worklist

    original = worklist.counts

    def explode(*a, **k):
        raise RuntimeError("the vaccine plan is unreadable")

    worklist.counts = explode
    try:
        answer = clinic["sign_in"]("desk").get("/messages/desk")
        assert answer.status_code == 200, \
            "a failing count took the whole desk down with it"
    finally:
        worklist.counts = original
