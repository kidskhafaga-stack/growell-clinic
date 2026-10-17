"""إنستجرام من غير صفحة فيسبوك — Instagram API with Instagram Login.

* **الربط**: ``instagram.com/oauth/authorize`` بـ ``state``، والكود (من غير
  ``#_``) بيتبدل بمفتاح قصير وبعده بمفتاح ٦٠ يوم؛
* **التجديد**: لما يفضل أقل من ١٠ أيام والمفتاح عدّى عليه يوم؛
* **الرد**: ``graph.instagram.com/<ver>/<IG_ID>/messages`` بـ Bearer، والرد
  الخاص على التعليق بنفس القاعدة.
"""
import json
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def igl(clinic, monkeypatch):
    from app.models import Setting
    from app.utils import channels, social

    with clinic["app"].app_context():
        for k, v in (("ig_mode", "login"), ("ig_app_id", "990602627938098"),
                     ("ig_app_secret", "IGSECRET"), ("meta_app_secret", "META"),
                     ("meta_verify_token", "v")):
            Setting.set(k, v)
        channels.set_enabled(["whatsapp", "instagram"])
        clinic["db"].session.commit()
    calls = []

    def fake_form(url, fields):
        calls.append(("form", url, fields))
        return 200, {"data": [{"access_token": "SHORT", "user_id": "1755847768034402",
                               "permissions": "instagram_business_basic"}]}

    def fake_get(url):
        calls.append(("get", url, None))
        if "refresh_access_token" in url:
            return 200, {"access_token": "LONG2", "token_type": "bearer", "expires_in": 5183944}
        return 200, {"access_token": "LONG", "token_type": "bearer", "expires_in": 5183944}

    def fake_post(url, payload, headers=None, timeout=10):
        calls.append(("post", url, (payload, headers or {})))
        if "subscribed_apps" in url:
            return 200, json.dumps({"success": True})
        return 200, json.dumps({"recipient_id": "x", "message_id": "aWdf"})
    monkeypatch.setattr(social, "_post_form", fake_form)
    monkeypatch.setattr(social, "_get_json", fake_get)
    monkeypatch.setattr(social, "_post", fake_post)
    clinic["calls"] = calls
    return clinic


def test_business_login_gives_a_sixty_day_key(igl):
    from app.models import Setting

    boss = igl["sign_in"]()
    page = boss.get("/messages/channels").get_data(as_text=True)
    assert "data-ig-fields" in page and "IGSECRET" not in page and "data-ig-start" in page
    start = boss.get("/messages/channels/instagram/start")
    loc = start.headers["Location"]
    assert loc.startswith("https://www.instagram.com/oauth/authorize?client_id=990602627938098")
    assert "instagram_business_manage_messages" in loc and "state=" in loc
    with boss.session_transaction() as sess:
        state = sess["ig_oauth_state"]
    boss.get(f"/messages/channels/instagram/callback?code=AQBx%23_&state=forged")
    with igl["app"].app_context():
        assert not Setting.get("ig_token")
    boss.get("/messages/channels/instagram/start")
    with boss.session_transaction() as sess:
        state = sess["ig_oauth_state"]
    boss.get(f"/messages/channels/instagram/callback?code=AQBx%23_&state={state}")
    form = [c for c in igl["calls"] if c[0] == "form"][-1]
    assert form[1] == "https://api.instagram.com/oauth/access_token"
    assert form[2]["code"] == "AQBx" and form[2]["grant_type"] == "authorization_code"
    exchange = [c for c in igl["calls"] if c[0] == "get"][-1][1]
    assert "grant_type=ig_exchange_token" in exchange and "access_token=SHORT" in exchange
    with igl["app"].app_context():
        assert Setting.get("ig_token") == "LONG" and Setting.get("ig_user_id") == "1755847768034402"
        until = datetime.fromisoformat(Setting.get("ig_token_until"))
        assert timedelta(days=59) < until - datetime.utcnow() < timedelta(days=61)
    boss.post("/messages/channels/instagram/subscribe")
    sub = [c for c in igl["calls"] if c[0] == "post"][-1][1]
    assert "/1755847768034402/subscribed_apps?" in sub and "subscribed_fields=messages%2Ccomments" in sub


def test_replies_go_through_graph_instagram_and_the_key_renews(igl):
    from app.models import Setting
    from app.utils import social, social_inbound

    with igl["app"].app_context():
        Setting.set("ig_user_id", "1755847768034402")
        Setting.set("ig_token", "LONG")
        Setting.set("ig_token_issued", (datetime.utcnow() - timedelta(days=55)).isoformat())
        Setting.set("ig_token_until", (datetime.utcnow() + timedelta(days=5)).isoformat())
        res = social_inbound.receive(social.Inbound(
            channel="instagram", kind="message", sender_id="IGSID9", msg_id="ig.l1",
            text="الدكتور موجود؟", at=datetime.utcnow()))
        igl["db"].session.commit()
        key = res["key"]
    igl["sign_in"]("desk").post(f"/messages/inbox/{key}/send", data={"body": "أيوه"})
    post = [c for c in igl["calls"] if c[0] == "post"][-1]
    assert post[1] == "https://graph.instagram.com/v25.0/1755847768034402/messages"
    assert post[2][0] == {"recipient": {"id": "IGSID9"}, "message": {"text": "أيوه"}}
    assert post[2][1]["Authorization"] == "Bearer LONG2", "renewed before it ran out"
    with igl["app"].app_context():
        assert Setting.get("ig_token") == "LONG2"
