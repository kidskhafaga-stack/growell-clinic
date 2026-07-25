"""The patient inbox: who wrote, who is waiting, and how long they waited.

Receiving the message was never the hard part — knowing that one arrived, and
that nobody has answered it, is. These tests pin the customer-service side:
matching the sender, the "needs a reply" state, the waiting-time numbers, and
adopting a number the system couldn't place.

Runs on the in-memory testing config; nothing here touches a real database.
"""
import os
import sys
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def clinic():
    """A family with a guardian's phone, a teenager with their own, and a
    conversation from a number belonging to neither."""
    from app import create_app
    from app.extensions import db

    app = create_app("testing")
    with app.app_context():
        db.create_all()
        from app.models import Family, Parent, Patient

        fam = Family(family_name="عائلة الاختبار")
        db.session.add(fam)
        db.session.flush()
        db.session.add(Parent(family_id=fam.id, full_name="الأم",
                              relation="mother", phone="01000000001"))
        child = Patient(patient_number="I1", full_name="طفل", gender="male",
                        date_of_birth=date(2019, 1, 1), family_id=fam.id)
        teen = Patient(patient_number="I2", full_name="مراهق", gender="female",
                       date_of_birth=date(2008, 1, 1),
                       own_phone="01000000002")
        db.session.add_all([child, teen])
        db.session.commit()
        yield {"app": app, "db": db, "child": child, "teen": teen, "fam": fam}


def _log(env, *, direction, body, phone, patient=None, minutes_ago=0,
         status=None):
    from app.models import MessageLog

    row = MessageLog(
        direction=direction, body=body, to_phone=phone,
        patient_id=(patient.id if patient else None),
        status=status or ("received" if direction == "in" else "sent"),
        created_at=datetime.utcnow() - timedelta(minutes=minutes_ago))
    env["db"].session.add(row)
    env["db"].session.flush()
    return row


def test_a_guardians_number_finds_the_children(clinic):
    from app.utils.inbox import match_patients

    with clinic["app"].app_context():
        found = match_patients("01000000001")
        assert [p.patient_number for p in found] == ["I1"]


def test_a_patients_own_number_finds_them(clinic):
    """A teenager writing from their own phone used to match nobody and land
    as an unknown caller beside their own file."""
    from app.utils.inbox import match_patients

    with clinic["app"].app_context():
        found = match_patients("01000000002")
        assert [p.patient_number for p in found] == ["I2"]


def test_an_unknown_number_matches_nobody(clinic):
    from app.utils.inbox import match_patients

    with clinic["app"].app_context():
        assert match_patients("01099999999") == []


def test_the_bell_counts_messages_nobody_opened(clinic):
    from app.utils.inbox import unread_count

    with clinic["app"].app_context():
        _log(clinic, direction="in", body="سؤال", phone="01000000001",
             patient=clinic["child"])
        _log(clinic, direction="in", body="تاني", phone="01000000001",
             patient=clinic["child"], status="read")
        _log(clinic, direction="out", body="رد", phone="01000000001",
             patient=clinic["child"])
        assert unread_count() == 1


def test_the_last_word_decides_whether_a_thread_is_open(clinic):
    from app.utils.inbox import conversations

    with clinic["app"].app_context():
        _log(clinic, direction="in", body="سؤال", phone="01000000001",
             patient=clinic["child"], minutes_ago=30)
        assert conversations()[0]["open"] is True
        _log(clinic, direction="out", body="أهلاً", phone="01000000001",
             patient=clinic["child"], minutes_ago=5)
        convs = conversations()
        assert convs[0]["open"] is False
        assert conversations(only_open=True) == []


def test_an_old_quiet_conversation_is_not_lost(clinic):
    """Conversations are grouped over the whole log, not the newest few rows,
    so a thread that went quiet a year ago is still findable."""
    from app.utils.inbox import conversations

    with clinic["app"].app_context():
        _log(clinic, direction="in", body="قديمة", phone="01000000002",
             patient=clinic["teen"], minutes_ago=60 * 24 * 400)
        for i in range(30):
            _log(clinic, direction="out", body=f"حديثة {i}",
                 phone="01000000001", patient=clinic["child"], minutes_ago=i)
        keys = {c["key"] for c in conversations()}
        assert f"p{clinic['teen'].id}" in keys
        assert len(keys) == 2


def test_waiting_time_is_measured_to_the_first_reply(clinic):
    from app.utils.inbox import response_stats

    with clinic["app"].app_context():
        _log(clinic, direction="in", body="سؤال", phone="01000000001",
             patient=clinic["child"], minutes_ago=120)
        _log(clinic, direction="out", body="رد", phone="01000000001",
             patient=clinic["child"], minutes_ago=60)
        # A second question with no answer: counted as waiting, never averaged
        # — an unanswered question must not flatter the average by vanishing.
        _log(clinic, direction="in", body="وسؤال تاني", phone="01000000002",
             patient=clinic["teen"], minutes_ago=10)
        stats = response_stats()
        assert stats["asked"] == 2
        assert stats["answered"] == 1
        assert stats["waiting"] == 1
        assert stats["avg_minutes"] == 60.0


def test_search_finds_a_conversation_by_name_or_number(clinic):
    from app.utils.inbox import conversations

    with clinic["app"].app_context():
        _log(clinic, direction="in", body="سؤال", phone="01000000001",
             patient=clinic["child"])
        _log(clinic, direction="in", body="آخر", phone="01000000002",
             patient=clinic["teen"])
        assert len(conversations(search="مراهق")) == 1
        assert len(conversations(search="0000001")) == 1
        assert conversations(search="لا أحد") == []


def test_naming_an_unknown_caller_moves_the_whole_conversation(clinic):
    """And makes the decision stick for everything that arrives afterwards."""
    from app.utils.inbound import handle_inbound
    from app.utils.inbox import (conversations, known_patient_for_phone,
                                 link_phone_to_patient)

    with clinic["app"].app_context():
        _log(clinic, direction="in", body="أنا جدة الطفل",
             phone="01099999999", minutes_ago=20)
        _log(clinic, direction="in", body="عايزة موعد",
             phone="01099999999", minutes_ago=15)
        assert conversations()[0]["orphan"] is True

        moved = link_phone_to_patient("01099999999", clinic["child"])
        clinic["db"].session.commit()
        assert moved == 2
        assert known_patient_for_phone("01099999999").id == clinic["child"].id

        # The next message from that number arrives on the child's file.
        handle_inbound({"from_phone": "01099999999", "text": "شكراً"}, "test")
        clinic["db"].session.commit()
        convs = conversations()
        assert len(convs) == 1
        assert convs[0]["key"] == f"p{clinic['child'].id}"
        assert convs[0]["count"] == 3


def test_one_spelling_per_number_so_one_conversation_per_family(clinic):
    """Older rows kept the local ``01…`` form while newer ones are stored
    internationally, which showed the same person twice."""
    from app.models import MessageLog
    from app.utils.inbox import conversations, normalize_logged_phones

    with clinic["app"].app_context():
        _log(clinic, direction="out", body="قديم", phone="01099999999",
             minutes_ago=100)
        _log(clinic, direction="in", body="جديد", phone="201099999999",
             minutes_ago=5)
        assert len(conversations()) == 2          # the same person, twice

        moved = normalize_logged_phones()
        clinic["db"].session.commit()
        assert moved == 1
        assert len(conversations()) == 1
        assert {m.to_phone for m in MessageLog.query.all()} == {"201099999999"}
        assert normalize_logged_phones() == 0     # idempotent


def test_an_inbound_message_reaches_the_right_file(clinic):
    from app.utils.inbound import handle_inbound

    with clinic["app"].app_context():
        res = handle_inbound({"from_phone": "01000000002", "text": "مرحبا"},
                             "test")
        clinic["db"].session.commit()
        assert res["matched"] is True
        from app.models import MessageLog
        row = MessageLog.query.filter_by(direction="in").one()
        assert row.patient_id == clinic["teen"].id
