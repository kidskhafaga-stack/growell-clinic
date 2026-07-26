"""Who owns a conversation, and when it stops needing an answer.

"The patient spoke last" is the right definition of waiting almost always.
Almost: a thread ending in "شكراً" would sit in the work list for ever. So a
human can close it — with a timestamp, not a flag, so the next message from
the patient re-opens it without anyone remembering to.

And the delivery board: "12 failed" is not a fact anyone can act on. "Every
vaccine reminder failed and nothing else did" is.
"""
import os
import sys
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def clinic():
    from app import create_app
    from app.extensions import db

    app = create_app("testing")
    with app.app_context():
        db.create_all()
        from app.models import Patient, User

        sara = User(username="sara", full_name="سارة", role="reception",
                    is_active=True)
        omar = User(username="omar", full_name="عمر", role="reception",
                    is_active=True)
        sara.set_password("x")
        omar.set_password("x")
        child = Patient(patient_number="D1", full_name="طفل", gender="male",
                        date_of_birth=date(2019, 1, 1))
        db.session.add_all([sara, omar, child])
        db.session.commit()
        yield {"app": app, "db": db, "sara": sara, "omar": omar, "child": child}


def _msg(clinic, direction, body, minutes_ago=0, **kw):
    from app.models import MessageLog

    row = MessageLog(direction=direction, body=body, to_phone="201000000001",
                     patient_id=clinic["child"].id,
                     status=kw.pop("status", "received" if direction == "in" else "sent"),
                     created_at=datetime.utcnow() - timedelta(minutes=minutes_ago),
                     **kw)
    clinic["db"].session.add(row)
    clinic["db"].session.flush()
    return row


def _key(clinic):
    return f"p{clinic['child'].id}"


# ------------------------------------------------------------- resolution --
def test_closing_a_thread_takes_it_off_the_work_list(clinic):
    """"شكراً" is not a question, and shouldn't look like one for ever."""
    from app.utils.inbox import conversation_for, conversations

    with clinic["app"].app_context():
        _msg(clinic, "in", "شكراً ليكم", minutes_ago=10)
        assert conversations(only_open=True)

        record = conversation_for(_key(clinic))
        record.resolved_at = datetime.utcnow()
        record.resolved_by = clinic["sara"].id
        clinic["db"].session.commit()

        assert conversations(only_open=True) == []
        assert conversations()[0]["resolved"] is True


def test_a_new_message_reopens_a_closed_thread_by_itself(clinic):
    """Stamped with a time rather than a flag, so nobody has to remember to
    un-close anything."""
    from app.utils.inbox import conversation_for, conversations

    with clinic["app"].app_context():
        _msg(clinic, "in", "شكراً", minutes_ago=60)
        record = conversation_for(_key(clinic))
        record.resolved_at = datetime.utcnow() - timedelta(minutes=30)
        clinic["db"].session.commit()
        assert conversations(only_open=True) == []

        _msg(clinic, "in", "بس عندي سؤال تاني", minutes_ago=1)
        clinic["db"].session.commit()
        assert len(conversations(only_open=True)) == 1


def test_closing_does_not_hide_a_thread_from_the_full_list(clinic):
    from app.utils.inbox import conversation_for, conversations

    with clinic["app"].app_context():
        _msg(clinic, "in", "تمام", minutes_ago=5)
        conversation_for(_key(clinic)).resolved_at = datetime.utcnow()
        clinic["db"].session.commit()
        assert len(conversations()) == 1


# ------------------------------------------------------------- assignment --
def test_a_conversation_can_be_handed_to_a_person(clinic):
    from app.utils.inbox import conversation_for, conversations

    with clinic["app"].app_context():
        _msg(clinic, "in", "سؤال", minutes_ago=5)
        record = conversation_for(_key(clinic))
        record.assigned_to = clinic["sara"].id
        clinic["db"].session.commit()

        conv = conversations()[0]
        assert conv["assignee"].username == "sara"
        # …and the "mine" view really is theirs alone.
        assert len(conversations(assignee=clinic["sara"].id)) == 1
        assert conversations(assignee=clinic["omar"].id) == []


def test_an_unassigned_thread_belongs_to_nobodys_list(clinic):
    from app.utils.inbox import conversations

    with clinic["app"].app_context():
        _msg(clinic, "in", "سؤال", minutes_ago=5)
        clinic["db"].session.commit()
        assert conversations()[0]["assignee"] is None
        assert conversations(assignee=clinic["sara"].id) == []


def test_the_record_is_created_once_and_reused(clinic):
    from app.models import Conversation
    from app.utils.inbox import conversation_for

    with clinic["app"].app_context():
        _msg(clinic, "in", "سؤال")
        first = conversation_for(_key(clinic))
        clinic["db"].session.commit()
        again = conversation_for(_key(clinic))
        assert first.id == again.id
        assert Conversation.query.count() == 1
        # It remembers who the thread is about, for a screen that never
        # loads the messages.
        assert first.patient_id == clinic["child"].id


# ---------------------------------------------------------- delivery board --
def test_the_board_shows_which_kind_of_message_is_failing(clinic):
    from app.blueprints.messages.routes import _delivery_by_type

    with clinic["app"].app_context():
        for _ in range(3):
            _msg(clinic, "out", "تذكير", status="failed",
                 template_type="vaccine_due")
        _msg(clinic, "out", "تذكير", status="sent", template_type="vaccine_due")
        for _ in range(5):
            _msg(clinic, "out", "تأكيد", status="sent",
                 template_type="appointment_confirm")
        clinic["db"].session.commit()

        board = {row["type"]: row for row in _delivery_by_type()}
        assert board["vaccine_due"]["failed"] == 3
        assert board["vaccine_due"]["sent"] == 1
        assert board["vaccine_due"]["fail_rate"] == 75.0
        assert board["appointment_confirm"]["failed"] == 0
        assert board["appointment_confirm"]["fail_rate"] == 0
        # The worst offender is listed first — that is the point of the board.
        assert _delivery_by_type()[0]["type"] == "vaccine_due"


def test_the_board_ignores_what_the_patient_sent_us(clinic):
    """An inbound message is not a delivery result."""
    from app.blueprints.messages.routes import _delivery_by_type

    with clinic["app"].app_context():
        _msg(clinic, "in", "سؤال")
        clinic["db"].session.commit()
        assert _delivery_by_type() == []


def test_old_failures_are_history_not_a_task(clinic):
    from app.blueprints.messages.routes import _delivery_by_type, _recent_failures

    with clinic["app"].app_context():
        _msg(clinic, "out", "قديمة", status="failed", template_type="birthday",
             minutes_ago=60 * 24 * 90)
        clinic["db"].session.commit()
        assert _delivery_by_type() == []
        assert _recent_failures() == []


def test_the_failure_list_says_why(clinic):
    from app.blueprints.messages.routes import _recent_failures

    with clinic["app"].app_context():
        _msg(clinic, "out", "تذكير", status="failed",
             template_type="vaccine_due", error="missing_phone")
        clinic["db"].session.commit()
        rows = _recent_failures()
        assert len(rows) == 1
        assert rows[0].error == "missing_phone"


# ------------------------------------------------------ the 24-hour window --
def test_the_free_reply_window_closes_24h_after_the_patient_wrote(clinic):
    """WhatsApp's own rule, and the one that surprises every clinic that
    switches to the Business API. A reply box that doesn't say so lets a
    receptionist type a careful answer, press send, and never learn it was
    refused."""
    from app.models import Setting
    from app.utils.inbox import session_window

    with clinic["app"].app_context():
        Setting.set("crm_mode", "automatic")
        Setting.set("wa_provider", "wapilot")
        _msg(clinic, "in", "سؤال", minutes_ago=60)
        clinic["db"].session.commit()

        window = session_window(_key(clinic))
        assert window["open"] is True
        assert 22 < window["hours_left"] <= 23


def test_the_window_is_shut_once_a_day_has_passed(clinic):
    from app.models import Setting
    from app.utils.inbox import session_window

    with clinic["app"].app_context():
        Setting.set("crm_mode", "automatic")
        Setting.set("wa_provider", "wapilot")
        _msg(clinic, "in", "سؤال من امبارح", minutes_ago=60 * 30)
        clinic["db"].session.commit()
        window = session_window(_key(clinic))
        assert window["open"] is False
        assert window["hours_left"] == 0


def test_a_patient_who_never_wrote_has_no_window_at_all(clinic):
    from app.models import Setting
    from app.utils.inbox import session_window

    with clinic["app"].app_context():
        Setting.set("crm_mode", "automatic")
        Setting.set("wa_provider", "wapilot")
        _msg(clinic, "out", "تأكيد موعد", minutes_ago=10)
        clinic["db"].session.commit()
        window = session_window(_key(clinic))
        assert window["open"] is False
        assert window["never_wrote"] is True


def test_click_to_send_links_have_no_window(clinic):
    """A wa.me link opens the staff member's own WhatsApp — an ordinary
    conversation, with no 24-hour rule to warn about."""
    from app.models import Setting
    from app.utils.inbox import session_window

    with clinic["app"].app_context():
        Setting.set("crm_mode", "manual")
        clinic["db"].session.commit()
        _msg(clinic, "in", "سؤال", minutes_ago=60 * 48)
        assert session_window(_key(clinic)) is None


# -------------------------------------------------------------- the queue --
def test_the_longest_wait_is_at_the_top(clinic):
    """A work list ordered by "newest" puts the person who has been ignored
    for three days at the bottom of the screen."""
    from app.models import Patient
    from app.utils.inbox import conversations

    with clinic["app"].app_context():
        older = Patient(patient_number="D2", full_name="طفل تاني",
                        gender="female", date_of_birth=date(2020, 1, 1))
        clinic["db"].session.add(older)
        clinic["db"].session.flush()
        from app.models import MessageLog
        clinic["db"].session.add(MessageLog(
            direction="in", body="من ٣ أيام", to_phone="201000000002",
            patient_id=older.id, status="received",
            created_at=datetime.utcnow() - timedelta(days=3)))
        _msg(clinic, "in", "من ٥ دقايق", minutes_ago=5)
        clinic["db"].session.commit()

        rows = conversations(only_open=True)
        assert rows[0]["patient"].patient_number == "D2"
        assert rows[0]["waiting_hours"] > 70
        assert rows[1]["waiting_hours"] < 1


def test_a_thread_that_is_not_waiting_has_no_age(clinic):
    from app.utils.inbox import conversations

    with clinic["app"].app_context():
        _msg(clinic, "in", "سؤال", minutes_ago=120)
        _msg(clinic, "out", "رد", minutes_ago=60)
        clinic["db"].session.commit()
        assert conversations()[0]["waiting_hours"] == 0
