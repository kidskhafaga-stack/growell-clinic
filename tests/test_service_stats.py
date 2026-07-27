"""Does this clinic answer people, and how fast.

Everything else in the desk module handles one conversation. This is the
question the person running the clinic actually has, and nothing in the
program could answer it: the send screen counts messages by status, which
says how the *provider* is doing.

The numbers are computed from the message log rather than from a column
filled going forward. A column would read faster and would have started at
zero on the day it shipped — and a manager cannot wait a month to find out
whether the desk is coping.
"""
import os
import sys
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def desk(clinic):
    """Two families, and the manager signed in."""
    from app.models import Family, Parent, Patient

    with clinic["app"].app_context():
        made = {}
        for tag, phone in (("a", "01000000001"), ("b", "01000000002")):
            family = Family(family_name=f"عائلة {tag}")
            clinic["db"].session.add(family)
            clinic["db"].session.flush()
            clinic["db"].session.add(Parent(family_id=family.id, full_name="الأم",
                                            relation="mother", phone=phone))
            child = Patient(patient_number=f"S-{tag}", full_name=f"طفل {tag}",
                            gender="male", date_of_birth=date(2024, 1, 1),
                            family_id=family.id, is_active=True)
            clinic["db"].session.add(child)
            clinic["db"].session.flush()
            made[tag] = child.id
        clinic["db"].session.commit()
    clinic["kids"] = made
    clinic["boss"] = clinic["sign_in"]("boss")
    return clinic


def _msg(desk, tag, direction, hours_ago, body="رسالة"):
    from app.models import MessageLog

    with desk["app"].app_context():
        log = MessageLog(direction=direction, provider="meta",
                         to_phone="2010000000" + ("1" if tag == "a" else "2"),
                         body=body, status="received" if direction == "in" else "sent",
                         patient_id=desk["kids"][tag])
        desk["db"].session.add(log)
        desk["db"].session.flush()
        log.created_at = datetime.utcnow() - timedelta(hours=hours_ago)
        desk["db"].session.commit()


def _summary(desk, **kwargs):
    from app.utils.service_stats import summary

    with desk["app"].app_context():
        return summary(**kwargs)


# --------------------------------------------------------- how long it took --
def test_the_time_to_the_first_answer_is_measured(desk):
    _msg(desk, "a", "in", hours_ago=5)
    _msg(desk, "a", "out", hours_ago=3)

    stats = _summary(desk)
    assert stats["asked"] == 1 and stats["answered"] == 1
    assert stats["median_hours"] == 2.0


def test_a_family_writing_three_lines_asked_once(desk):
    """Counting each line as a question answered in seconds is how a service
    report flatters itself."""
    _msg(desk, "a", "in", hours_ago=5, body="دكتور")
    _msg(desk, "a", "in", hours_ago=4.9, body="الولد تعبان")
    _msg(desk, "a", "in", hours_ago=4.8, body="ممكن أعدي؟")
    _msg(desk, "a", "out", hours_ago=3)

    stats = _summary(desk)
    assert stats["asked"] == 1
    assert stats["median_hours"] == 2.0


def test_the_median_survives_one_terrible_conversation(desk):
    """One answered after three days drags a mean into uselessness. The
    median says what the ordinary family waits — which is the number worth
    printing next to it."""
    for tag, gap in (("a", 1), ("b", 1)):
        _msg(desk, tag, "in", hours_ago=10)
        _msg(desk, tag, "out", hours_ago=10 - gap)
    # …and one that took three days.
    _msg(desk, "a", "in", hours_ago=100)
    _msg(desk, "a", "out", hours_ago=100 - 72)

    stats = _summary(desk, days=90)
    assert stats["median_hours"] == 1.0
    assert stats["mean_hours"] > 20, "the mean should show the damage"


def test_answering_within_the_hour_is_counted(desk):
    _msg(desk, "a", "in", hours_ago=5)
    _msg(desk, "a", "out", hours_ago=4.5)
    assert _summary(desk)["within_hour"] == 1


# ------------------------------------------------------ what went unanswered --
def test_a_question_asked_twenty_minutes_ago_is_not_a_failure(desk):
    """It is a queue. Counting it as missed would make the number noise."""
    _msg(desk, "a", "in", hours_ago=0.3)

    stats = _summary(desk)
    assert stats["missed"] == 0
    assert stats["waiting"] == 1


def test_a_question_that_outlived_the_window_is_a_failure(desk):
    """After 24 hours the reply is no longer free and needs an approved
    template — money and goodwill, both gone quietly."""
    _msg(desk, "a", "in", hours_ago=30)

    stats = _summary(desk)
    assert stats["missed"] == 1
    assert stats["waiting"] == 0
    assert stats["answer_rate"] == 0.0


def test_the_answer_rate_is_answered_over_asked(desk):
    _msg(desk, "a", "in", hours_ago=10)
    _msg(desk, "a", "out", hours_ago=9)
    _msg(desk, "b", "in", hours_ago=30)

    stats = _summary(desk)
    assert stats["asked"] == 2 and stats["answered"] == 1
    assert stats["answer_rate"] == 50.0


def test_the_clinic_speaking_first_is_not_a_reply_to_anything(desk):
    """A reminder the clinic sent is not an answer. Counting it would let a
    clinic that never replies show a perfect record by sending campaigns."""
    _msg(desk, "a", "out", hours_ago=10)
    _msg(desk, "a", "out", hours_ago=9)

    stats = _summary(desk)
    assert stats["asked"] == 0
    assert stats["median_hours"] is None


def test_only_the_first_answer_counts_not_the_conversation(desk):
    """A thread with six exchanges is not six questions. Each answer closes
    the question before it and the next inbound opens a new one."""
    _msg(desk, "a", "in", hours_ago=10)
    _msg(desk, "a", "out", hours_ago=9)
    _msg(desk, "a", "in", hours_ago=8)
    _msg(desk, "a", "out", hours_ago=7)

    stats = _summary(desk)
    assert stats["asked"] == 2 and stats["answered"] == 2


def test_older_than_the_window_asked_for_is_left_out(desk):
    _msg(desk, "a", "in", hours_ago=24 * 60)
    _msg(desk, "a", "out", hours_ago=24 * 60 - 1)

    assert _summary(desk, days=30)["asked"] == 0
    assert _summary(desk, days=90)["asked"] == 1


def test_an_empty_clinic_reports_nothing_rather_than_zero(desk):
    """"Median 0 hours" on a clinic with no messages reads as perfect."""
    stats = _summary(desk)
    assert stats["asked"] == 0
    assert stats["median_hours"] is None
    assert stats["mean_hours"] is None
    assert stats["answer_rate"] is None


# ------------------------------------------------------------- the shape ----
def test_the_open_work_is_counted_per_person(desk):
    """"Someone will answer it" is how a message goes unanswered for two
    days."""
    from app.models import Conversation

    _msg(desk, "a", "in", hours_ago=2)
    with desk["app"].app_context():
        conv = Conversation(thread_key=f"p{desk['kids']['a']}",
                            assigned_to=desk["ids"]["doctor"])
        desk["db"].session.add(conv)
        desk["db"].session.commit()

    rows = _summary(desk)["by_assignee"]
    assert len(rows) == 1
    assert rows[0]["count"] == 1
    assert rows[0]["user"].id == desk["ids"]["doctor"]


def test_what_people_write_in_about_is_counted(desk):
    """The commonest topic is the thing to fix, not the thing to answer
    faster."""
    from app.models import Conversation

    with desk["app"].app_context():
        for tag, topic in (("a", "price"), ("b", "price")):
            desk["db"].session.add(Conversation(
                thread_key=f"p{desk['kids'][tag]}", topic=topic))
        desk["db"].session.commit()

    rows = _summary(desk)["by_topic"]
    assert rows[0]["topic"] == "price" and rows[0]["count"] == 2


# -------------------------------------------------------------- the screen --
def test_the_board_shows_the_numbers(desk):
    _msg(desk, "a", "in", hours_ago=5)
    _msg(desk, "a", "out", hours_ago=3)

    body = desk["boss"].get("/messages/service").get_data(as_text=True)
    assert "قياس خدمة المرضى" in body
    assert "الرد الأول" in body


def test_the_board_opens_on_an_empty_clinic(desk):
    """The day a clinic installs this, there is nothing in it."""
    assert desk["boss"].get("/messages/service").status_code == 200


def test_a_silly_range_falls_back_rather_than_erroring(desk):
    """?days= comes from a URL."""
    for value in ("0", "-5", "abc", "99999"):
        resp = desk["boss"].get(f"/messages/service?days={value}")
        assert resp.status_code == 200


def test_the_inbox_links_to_it(desk):
    body = desk["boss"].get("/messages/inbox").get_data(as_text=True)
    assert "/messages/service" in body
