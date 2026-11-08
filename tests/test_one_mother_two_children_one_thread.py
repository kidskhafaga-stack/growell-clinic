"""One mother, two children, one conversation (SERVICE_DESK_PLAN «تجميع الإخوة»).

A mother writes from one number about two children. Her messages were filed
on the first child the number matched and each child's reminders on its own
thread, so she was two conversations: answered twice, or once while the
other sat waiting. A thread is still the child's (routing, the record and the
file read ``p<id>``); siblings of one family on one number are now shown as
one — one row, one chat with each message's child named, one «answered».
"""
import os
import sys
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

PHONE = "201001112223"


@pytest.fixture()
def family(clinic):
    from app.models import Family, MessageLog, Patient

    with clinic["app"].app_context():
        db = clinic["db"]
        fam = Family(family_name="عائلة سامي")
        db.session.add(fam)
        db.session.flush()
        older = db.session.get(Patient, clinic["ids"]["child"])
        older.family_id = fam.id
        younger = Patient(patient_number="P2", full_name="مريم سامي", gender="female",
                          date_of_birth=date(2024, 5, 1), is_active=True, family_id=fam.id)
        cousin = Patient(patient_number="P3", full_name="ابن خالة", gender="male",
                         date_of_birth=date(2023, 1, 1), is_active=True)
        db.session.add_all([younger, cousin])
        db.session.flush()
        now = datetime.utcnow()
        rows = [
            MessageLog(direction="out", to_phone=PHONE, patient_id=younger.id, status="sent",
                       body="ميعاد تطعيم مريم بكرة", created_at=now - timedelta(hours=3)),
            MessageLog(direction="in", to_phone=PHONE, patient_id=older.id, status="received",
                       body="تمام، وكمان يوسف عنده كحة", created_at=now - timedelta(hours=2)),
            # Another family on another number: never folded in.
            MessageLog(direction="in", to_phone="201009998887", patient_id=cousin.id,
                       status="received", body="سلام", created_at=now - timedelta(hours=1)),
        ]
        db.session.add_all(rows)
        db.session.commit()
        clinic["ids"].update(older=older.id, younger=younger.id, cousin=cousin.id)
    return clinic


def test_one_row_for_the_mother_in_the_inbox(family):
    from app.utils.inbox import conversations

    with family["app"].app_context():
        rows = conversations()
        keys = {r["key"] for r in rows}
        assert f"p{family['ids']['cousin']}" in keys
        mine = [r for r in rows if r.get("siblings")]
        assert len(mine) == 1, "one row for the two children on one number"
        assert {p.id for p in mine[0]["siblings"]} == {family["ids"]["older"], family["ids"]["younger"]}
        assert mine[0]["open"], "her last message is waiting"
        assert len(rows) == 2
    page = family["sign_in"]("desk").get("/messages/inbox").get_data(as_text=True)
    assert "data-siblings-row" in page and "مريم سامي" in page


def test_one_chat_with_each_child_named(family):
    page = family["sign_in"]("desk").get(
        f"/messages/inbox/p{family['ids']['older']}").get_data(as_text=True)
    assert "data-siblings-thread" in page
    assert "ميعاد تطعيم مريم بكرة" in page and "تمام، وكمان يوسف عنده كحة" in page
    assert f'data-bubble-child="{family["ids"]["younger"]}"' in page
    assert "سلام" not in page, "another family's number is not folded in"


def test_answered_once_for_both(family):
    from app.utils.inbox import conversation_for

    family["sign_in"]("desk").post(f"/messages/inbox/p{family['ids']['older']}/resolve")
    with family["app"].app_context():
        for kid in ("older", "younger"):
            assert conversation_for(f"p{family['ids'][kid]}", create=False).resolved_at is not None


def test_one_child_alone_is_unchanged(clinic):
    from app.models import MessageLog
    from app.utils.inbox import conversations

    with clinic["app"].app_context():
        clinic["db"].session.add(MessageLog(direction="in", to_phone=PHONE,
                                            patient_id=clinic["ids"]["child"],
                                            status="received", body="سؤال"))
        clinic["db"].session.commit()
        rows = conversations()
        assert len(rows) == 1 and "siblings" not in rows[0]
    page = clinic["sign_in"]("desk").get(f"/messages/inbox/p{clinic['ids']['child']}").get_data(as_text=True)
    assert "data-siblings-thread" not in page
