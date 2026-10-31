"""مين يرد على أنهي محادثة — المرحلة الخامسة من ``CONNECTHUB_PLAN.md``.

صاحب العيادة: *«خليه التحكم فيه ممكن، وخلّي التلقائي أقدر أعدّل عليه»*.

* **مقفول** (الأصل): ولا حاجة بتتغير — نفس الصندوق زي ما كان؛
* **اقتراح**: البرنامج بيقول مين، وحد بيدوس «خده»؛
* **تلقائي**: المحادثة بتروح لحد على طول بقواعد العيادة: الموضوع، ثم القناة،
  ثم المجموعة، ثم كل اللي يوصلوا للصندوق — من غير اللي قال «مش متاح»؛
  بالأقل شغلاً أو بالدور؛ واللي ماسك المحادثة بيفضل ماسكها؛
* **محدش رد**: صاحبها بيتنبّه بعد وقت، والمشرف بعد وقت أطول، ولو العيادة
  طلبت — بتتنقل لحد تاني **مرة واحدة** في كل انتظار؛
* الإعدادات للمدير والمشرفين بس.
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def desk(clinic):
    """Two more people on the desk, so there is somebody to choose between."""
    from app.models import User
    from app.utils import routing

    db = clinic["db"]
    with clinic["app"].app_context():
        for username, name in (("mona", "أ منى"), ("sara", "ب سارة")):
            u = User(username=username, full_name=name, role="reception", is_active=True)
            u.set_password("secret")
            db.session.add(u)
        db.session.commit()
        ids = {u.username: u.id for u in User.query.all()}
    routing.forget()
    yield {**clinic, "uid": ids}
    routing.forget()


def _set(**cfg):
    from app.utils import routing

    base = routing.config()
    base.update(cfg)
    routing._save(base)
    routing.forget()


def _arrive(env, phone, body="مرحبا", channel=None, minutes_ago=0):
    """A message from ``phone``, filed the way the hooks file one, then routed."""
    from app.models import MessageLog
    from app.utils import routing

    row = MessageLog(direction="in", body=body, to_phone=phone, status="received",
                     channel=channel,
                     created_at=datetime.utcnow() - timedelta(minutes=minutes_ago))
    env["db"].session.add(row)
    env["db"].session.flush()
    routing.on_inbound(row)
    env["db"].session.commit()
    return row


def _record(key):
    from app.utils.inbox import conversation_for

    return conversation_for(key, create=False)


def _hold(env, user_id, n, prefix="0155"):
    """Give somebody ``n`` open conversations."""
    from app.models import Conversation

    for i in range(n):
        env["db"].session.add(Conversation(thread_key=f"{prefix}{user_id}{i:04d}",
                                           assigned_to=user_id))
    env["db"].session.commit()


def test_off_changes_nothing(desk):
    from app.utils import routing

    with desk["app"].app_context():
        assert routing.config()["mode"] == "off", "the shipped default"
        _arrive(desk, "01011111111")
        rec = _record("01011111111")
        assert rec is None or (rec.assigned_to is None and rec.suggested_to is None)
        assert routing.sweep() == {"assigned": 0, "moved": 0}


def test_suggest_names_somebody_and_a_person_takes_it(desk):
    with desk["app"].app_context():
        _set(mode="suggest", pool=[desk["uid"]["mona"], desk["uid"]["sara"]])
        _arrive(desk, "01022222222")
        rec = _record("01022222222")
        assert rec.assigned_to is None, "a suggestion, not a hand-over"
        assert rec.suggested_to in (desk["uid"]["mona"], desk["uid"]["sara"])
        chosen = rec.suggested_to

    client = desk["sign_in"]("desk")
    page = client.get("/messages/inbox/01022222222")
    assert page.status_code == 200 and b"data-take-suggestion" in page.data
    client.post("/messages/inbox/01022222222/take")
    with desk["app"].app_context():
        rec = _record("01022222222")
        assert (rec.assigned_to, rec.suggested_to, rec.assigned_by) == (chosen, None, "suggested")


def test_auto_gives_it_to_whoever_holds_least(desk):
    from app.models import ActivityLog

    mona, sara = desk["uid"]["mona"], desk["uid"]["sara"]
    with desk["app"].app_context():
        _set(mode="auto", pool=[mona, sara], method="least_open")
        _hold(desk, mona, 2)
        _arrive(desk, "01033333333")
        rec = _record("01033333333")
        assert (rec.assigned_to, rec.assigned_by) == (sara, "auto")
        assert ActivityLog.query.filter_by(action="inbox.auto_assign").count() == 1


def test_turns_go_round(desk):
    mona, sara = desk["uid"]["mona"], desk["uid"]["sara"]
    with desk["app"].app_context():
        _set(mode="auto", pool=[mona, sara], method="turns", keep_owner=True)
        got = []
        for phone in ("01040000001", "01040000002", "01040000003"):
            _arrive(desk, phone)
            got.append(_record(phone).assigned_to)
        assert got[0] != got[1] and got[0] == got[2]


def test_a_topic_rule_then_a_channel_rule_then_the_pool(desk):
    from app.utils import routing

    boss, mona, sara = desk["uid"]["boss"], desk["uid"]["mona"], desk["uid"]["sara"]
    with desk["app"].app_context():
        _set(mode="auto", pool=[mona], by_topic={"price": [boss]},
             by_channel={"instagram": [sara]})
        assert [u.id for u in routing.candidates("price", "instagram")] == [boss]
        assert [u.id for u in routing.candidates("other", "instagram")] == [sara]
        assert [u.id for u in routing.candidates("other", "whatsapp")] == [mona]

        _arrive(desk, "01050000001", body="السعر كام لو سمحت")
        assert _record("01050000001").assigned_to == boss
        _arrive(desk, "01050000002", body="hello", channel="instagram")
        assert _record("01050000002").assigned_to == sara


def test_away_is_skipped_and_everybody_away_names_nobody(desk):
    from app.utils import routing

    mona, sara = desk["uid"]["mona"], desk["uid"]["sara"]
    client = desk["sign_in"]("mona")
    client.post("/messages/inbox/away", data={"away": "1"})
    with desk["app"].app_context():
        assert mona in routing.config()["away"]
        _set(mode="auto", pool=[mona, sara])
        assert [u.id for u in routing.candidates()] == [sara]
        _set(away=[mona, sara])
        assert routing.candidates() == [], "the pool is away — not everybody else"
        _arrive(desk, "01060000001")
        rec = _record("01060000001")
        assert rec is None or rec.assigned_to is None
    client.post("/messages/inbox/away", data={"away": "0"})
    with desk["app"].app_context():
        assert mona not in routing.config()["away"]


def test_the_one_holding_it_keeps_it_unless_away(desk):
    mona, sara = desk["uid"]["mona"], desk["uid"]["sara"]
    with desk["app"].app_context():
        _set(mode="auto", pool=[mona, sara], keep_owner=True)
        _hold(desk, sara, 3)
        _arrive(desk, "01070000001")
        assert _record("01070000001").assigned_to == mona
        _hold(desk, mona, 5)
        _arrive(desk, "01070000001", body="تاني")
        assert _record("01070000001").assigned_to == mona, "she keeps her family"
        _set(away=[mona])
        _arrive(desk, "01070000001", body="تالت")
        assert _record("01070000001").assigned_to == sara


def test_a_hand_over_by_a_person_replaces_the_rules(desk):
    mona, sara = desk["uid"]["mona"], desk["uid"]["sara"]
    with desk["app"].app_context():
        _set(mode="auto", pool=[mona])
        _arrive(desk, "01080000001")
        assert _record("01080000001").assigned_by == "auto"
    desk["sign_in"]("boss").post("/messages/inbox/01080000001/assign",
                                 data={"assigned_to": sara})
    with desk["app"].app_context():
        rec = _record("01080000001")
        assert (rec.assigned_to, rec.assigned_by, rec.suggested_to) == (sara, None, None)


def test_nobody_replied_the_holder_then_the_supervisor(desk):
    from app.models import User
    from app.utils import routing
    from app.utils.notifications import get_notifications, invalidate

    mona, boss = desk["uid"]["mona"], desk["uid"]["boss"]
    with desk["app"].app_context():
        _set(mode="auto", pool=[mona], alert_minutes=15, escalate_minutes=45,
             supervisors=[boss], open_hours_only=False)
        _arrive(desk, "01090000001", minutes_ago=20)
        assert _record("01090000001").assigned_to == mona
        routing.forget()
        assert routing.mine_late(desk["db"].session.get(User, mona)) == 1
        assert routing.for_supervisor(desk["db"].session.get(User, boss)) == 0, "20 < 45"
        invalidate()
        keys = [n["key"] for n in get_notifications(desk["db"].session.get(User, mona))]
        assert "conversations_mine_late" in keys

        _arrive(desk, "01090000002", minutes_ago=50)
        routing.forget()
        assert routing.for_supervisor(desk["db"].session.get(User, boss)) == 1
        assert routing.for_supervisor(desk["db"].session.get(User, mona)) == 0, "not a supervisor"
        invalidate()
        keys = [n["key"] for n in get_notifications(desk["db"].session.get(User, boss))]
        assert "conversations_escalated" in keys


def test_the_wait_counts_in_opening_hours_only_when_asked(desk, monkeypatch):
    from app.utils import routing, service_desk

    with desk["app"].app_context():
        _set(mode="suggest", alert_minutes=15, open_hours_only=True)
        _arrive(desk, "01091000001", minutes_ago=30)
        monkeypatch.setattr(service_desk, "is_open", lambda *a, **k: False)
        routing.forget()
        assert routing.late() == ([], [])
        _set(open_hours_only=False)
        assert len(routing.late()[0]) == 1


def test_the_sweep_hands_out_and_moves_a_late_one_once(desk):
    from app.models import ActivityLog, Conversation
    from app.utils import routing

    mona, sara = desk["uid"]["mona"], desk["uid"]["sara"]
    db = desk["db"]
    with desk["app"].app_context():
        # Arrived while the routing was off: nobody holds it.
        _arrive(desk, "01092000001", minutes_ago=60)
        _set(mode="auto", pool=[mona, sara], reassign=True, escalate_minutes=45,
             alert_minutes=15, open_hours_only=False)
        now = datetime.utcnow()
        done = routing.sweep(now)
        db.session.commit()
        assert done["assigned"] == 1, "the one nobody held"
        assert done["moved"] == 1, "already an hour late: handed on"
        rec = _record("01092000001")
        assert rec.assigned_to in (mona, sara) and rec.assigned_by == "escalated"
        assert rec.escalated_at is not None
        moved = ActivityLog.query.filter_by(action="inbox.escalated").one()
        before, after = moved.detail.split()[1], moved.detail.split()[-1]
        assert before != after and int(after) == rec.assigned_to, "to somebody else"

        assert routing.sweep(now + timedelta(seconds=5)) == {"assigned": 0, "moved": 0}, \
            "at most once a minute"
        again = routing.sweep(now + timedelta(minutes=2))
        db.session.commit()
        assert again["moved"] == 0, "once per wait"
        assert ActivityLog.query.filter_by(action="inbox.escalated").count() == 1
        assert Conversation.query.filter_by(thread_key="01092000001").count() == 1


def test_the_settings_are_for_the_manager_and_supervisors(desk):
    from app.utils import routing

    mona, sara, doc = desk["uid"]["mona"], desk["uid"]["sara"], desk["uid"]["doc"]
    assert desk["sign_in"]("desk").get("/messages/inbox/routing").status_code == 403

    boss = desk["sign_in"]("boss")
    page = boss.get("/messages/inbox/routing")
    assert page.status_code == 200
    for mark in (b"data-routing-form", b'data-rule-topic="price"',
                 b'data-rule-channel="instagram"', b"data-routing-save"):
        assert mark in page.data
    boss.post("/messages/inbox/routing", data={
        "mode": "auto", "method": "turns", "pool": [str(mona), str(sara), str(doc), "x"],
        "topic_price": [str(sara)], "topic_nonsense": [str(mona)],
        "channel_instagram": [str(mona)], "supervisors": [str(mona)],
        "alert_minutes": "30", "escalate_minutes": "10", "keep_owner": "1"})
    with desk["app"].app_context():
        cfg = routing.config()
        assert cfg["mode"] == "auto" and cfg["method"] == "turns"
        assert cfg["pool"] == [mona, sara], "only people who reach the inbox"
        assert cfg["by_topic"] == {"price": [sara]} and cfg["by_channel"] == {"instagram": [mona]}
        assert (cfg["alert_minutes"], cfg["escalate_minutes"]) == (30, 30)
        assert cfg["keep_owner"] and not cfg["reassign"]

    # A supervisor may open it; the inbox shows the door to whoever may.
    assert desk["sign_in"]("mona").get("/messages/inbox/routing").status_code == 200
    assert b"data-to-routing" in boss.get("/messages/inbox").data
    assert b"data-to-routing" not in desk["sign_in"]("desk").get("/messages/inbox").data


def test_a_bad_setting_falls_back_to_off(desk):
    from app.models import Setting
    from app.utils import routing

    with desk["app"].app_context():
        Setting.set(routing.SETTING, "{not json")
        assert routing.config()["mode"] == "off"
        Setting.set(routing.SETTING, '{"mode": "always", "method": "fastest"}')
        cfg = routing.config()
        assert (cfg["mode"], cfg["method"]) == ("off", "least_open")
