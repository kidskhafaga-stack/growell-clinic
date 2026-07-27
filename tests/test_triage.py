"""Which message is the one to answer first.

Sorting by who has waited longest is exactly right for a list of questions
about opening hours and prices. It is wrong for one of them: "الولد سخن ٤٠
وبيتنفس بصعوبة" does not wait its turn behind eleven people asking what the
consultation costs, however long they have been waiting.

The flag only ever raises a thread and never lowers one, because the cost of
the two mistakes is not remotely the same: a pricing question read as urgent
wastes a minute, and an emergency read as a pricing question is the reason
the feature exists.
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


# ------------------------------------------------------------ the guessing --
@pytest.mark.parametrize("text", [
    "الولد سخن ٤٠ وبيتنفس بصعوبة",
    "البيبي بيتشنج",
    "ابني بلع حاجة",
    "في نزيف من الجرح",
    "she is not breathing well",
    "طوارئ لو سمحت",
])
def test_an_emergency_reads_as_an_emergency(text):
    from app.utils.triage import suggest_topic

    assert suggest_topic(text) == "urgent"


@pytest.mark.parametrize("text,topic", [
    ("نتيجة الأشعة وصلت", "result"),
    ("عايزة أحجز ميعاد الأربع", "appointment"),
    ("الكشف بكام؟", "price"),
    ("استنيت ساعتين ومحدش رد عليا", "complaint"),
])
def test_the_ordinary_topics_are_recognised(text, topic):
    from app.utils.triage import suggest_topic

    assert suggest_topic(text) == topic


def test_an_emergency_wins_over_the_topic_it_is_also_about(text=None):
    """A message can be about a result *and* be an emergency. When it is
    both, it is an emergency."""
    from app.utils.triage import suggest_topic

    assert suggest_topic("نتيجة التحليل وحشة والولد بيتشنج") == "urgent"


@pytest.mark.parametrize("text", ["ازيك يا دكتور", "شكراً", "", "   ", None])
def test_a_message_about_nothing_in_particular_is_left_alone(text):
    """Guessing a topic for every message would make the label meaningless."""
    from app.utils.triage import suggest_topic

    assert suggest_topic(text) is None


# ------------------------------------------------------------ the ordering --
@pytest.fixture()
def inbox(clinic):
    """Two families writing in, and the desk signed in."""
    from app.models import Family, Parent, Patient

    with clinic["app"].app_context():
        made = {}
        for tag, phone in (("a", "01000000001"), ("b", "01000000002")):
            family = Family(family_name=f"عائلة {tag}")
            clinic["db"].session.add(family)
            clinic["db"].session.flush()
            clinic["db"].session.add(Parent(family_id=family.id,
                                            full_name="الأم", relation="mother",
                                            phone=phone))
            child = Patient(patient_number=f"P-{tag}", full_name=f"طفل {tag}",
                            gender="male", date_of_birth=datetime(2024, 1, 1).date(),
                            family_id=family.id, is_active=True)
            clinic["db"].session.add(child)
            clinic["db"].session.flush()
            made[tag] = child.id
        clinic["db"].session.commit()
    clinic["kids"] = made
    clinic["desk"] = clinic["sign_in"]("boss")
    return clinic


def _wrote(inbox, tag, body, hours_ago=0):
    from app.models import MessageLog

    with inbox["app"].app_context():
        log = MessageLog(direction="in", provider="meta",
                         to_phone="2010000000" + ("1" if tag == "a" else "2"),
                         body=body, status="received",
                         patient_id=inbox["kids"][tag])
        inbox["db"].session.add(log)
        inbox["db"].session.flush()
        log.created_at = datetime.utcnow() - timedelta(hours=hours_ago)
        inbox["db"].session.commit()


def _order(inbox):
    from app.utils.inbox import conversations

    with inbox["app"].app_context():
        return [c["key"] for c in conversations(only_open=True)]


def test_the_emergency_comes_first_however_long_the_others_waited(inbox):
    """The whole point. A child who cannot breathe does not queue behind a
    pricing question from yesterday morning."""
    _wrote(inbox, "a", "الكشف بكام؟", hours_ago=30)
    _wrote(inbox, "b", "الولد سخن ٤٠ وبيتنفس بصعوبة", hours_ago=0)

    order = _order(inbox)
    assert order[0] == f"p{inbox['kids']['b']}"


def test_without_an_emergency_the_longest_wait_still_wins(inbox):
    """Nothing else about the ordering changes."""
    _wrote(inbox, "a", "الكشف بكام؟", hours_ago=30)
    _wrote(inbox, "b", "عايزة أحجز ميعاد", hours_ago=1)

    assert _order(inbox)[0] == f"p{inbox['kids']['a']}"


def test_marking_it_urgent_by_hand_lifts_it_too(inbox):
    """The words are a guess; a person is not. Both raise the thread."""
    _wrote(inbox, "a", "سؤال عادي خالص", hours_ago=30)
    _wrote(inbox, "b", "ممكن حضرتك تشوف الولد النهاردة", hours_ago=1)

    assert _order(inbox)[0] == f"p{inbox['kids']['a']}"

    inbox["desk"].post(f"/messages/inbox/p{inbox['kids']['b']}/topic",
                       data={"topic": "urgent"}, follow_redirects=True)
    assert _order(inbox)[0] == f"p{inbox['kids']['b']}"


def test_a_person_overrules_the_guess(inbox):
    """The program matched some words; the receptionist read the message.
    Once a person has said, the guess stops being made for that thread."""
    from app.utils.inbox import conversations

    _wrote(inbox, "a", "في نزيف بسيط من السرة بعد ما وقعت القسطرة")
    inbox["desk"].post(f"/messages/inbox/p{inbox['kids']['a']}/topic",
                       data={"topic": "other"}, follow_redirects=True)

    with inbox["app"].app_context():
        conv = conversations(only_open=True)[0]
        assert conv["topic"] == "other"
        assert conv["suggested_topic"] is None, "still second-guessing a person"


def test_a_topic_that_is_not_one_is_ignored(inbox):
    from app.models import Conversation

    _wrote(inbox, "a", "سؤال")
    inbox["desk"].post(f"/messages/inbox/p{inbox['kids']['a']}/topic",
                       data={"topic": "extremely-urgent"}, follow_redirects=True)
    with inbox["app"].app_context():
        assert Conversation.query.one().topic is None


def test_clearing_the_topic_brings_the_guess_back(inbox):
    from app.utils.inbox import conversations

    _wrote(inbox, "a", "الولد بيتشنج")
    inbox["desk"].post(f"/messages/inbox/p{inbox['kids']['a']}/topic",
                       data={"topic": "other"}, follow_redirects=True)
    inbox["desk"].post(f"/messages/inbox/p{inbox['kids']['a']}/topic",
                       data={"topic": ""}, follow_redirects=True)

    with inbox["app"].app_context():
        conv = conversations(only_open=True)[0]
        assert conv["topic"] is None
        assert conv["suggested_topic"] == "urgent"


def test_an_answered_thread_stays_at_the_bottom_even_if_urgent(inbox):
    """Dealt with is dealt with. Otherwise every emergency the clinic ever
    answered sits at the top of the list for ever."""
    _wrote(inbox, "a", "الولد بيتشنج", hours_ago=5)
    _wrote(inbox, "b", "الكشف بكام", hours_ago=1)
    inbox["desk"].post(f"/messages/inbox/p{inbox['kids']['a']}/resolve",
                       follow_redirects=True)

    from app.utils.inbox import conversations

    with inbox["app"].app_context():
        keys = [c["key"] for c in conversations()]
        assert keys[-1] == f"p{inbox['kids']['a']}"


# --------------------------------------------------------------- on screen --
def test_the_inbox_shows_the_guess_as_a_guess(inbox):
    """Drawn as a question, not a verdict — the program has not read the
    message, it has matched some words in it."""
    _wrote(inbox, "a", "الولد بيتشنج")
    body = inbox["desk"].get("/messages/inbox").get_data(as_text=True)
    assert "طارئ" in body
    assert "؟" in body


def test_a_confirmed_topic_is_shown_plainly(inbox):
    _wrote(inbox, "a", "سؤال عن الميعاد")
    inbox["desk"].post(f"/messages/inbox/p{inbox['kids']['a']}/topic",
                       data={"topic": "appointment"}, follow_redirects=True)
    body = inbox["desk"].get("/messages/inbox").get_data(as_text=True)
    assert "ميعاد" in body


def test_the_thread_offers_every_topic(inbox):
    _wrote(inbox, "a", "سؤال")
    body = inbox["desk"].get(
        f"/messages/inbox/p{inbox['kids']['a']}").get_data(as_text=True)
    assert 'name="topic"' in body
    for label in ("طارئ", "نتيجة", "ميعاد", "سعر", "شكوى"):
        assert label in body
