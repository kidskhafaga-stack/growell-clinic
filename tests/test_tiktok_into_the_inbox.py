"""تيك توك في نفس الصندوق — من توثيق TikTok Business Messaging API v1.3.

* **التوقيع**: ``Tiktok-Signature: t=…,s=…`` = HMAC-SHA256 لـ ``"t." + body``
  بسر التطبيق، والوقت القديم مرفوض، والحدث لتطبيق تاني مش بتاعنا؛
* **الرسالة** بتوصل بـ ``conversation_id`` والرد بيروح عليه، **١٠ ردود في
  ٤٨ ساعة** بس، والمفتاح بيتجدد لوحده لما يومه يخلص؛
* **الإعلان أو لينك tiktok.me** بيعمل عميل محتمل بمصدره من غير رسالة؛
* **ربط الحساب** OAuth بـ ``state`` بيتأكد في الرجوع.
"""
import hashlib
import hmac
import json
import os
import sys
import time
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

SECRET = "tt-app-secret"
APP = "7043848340043202562"


@pytest.fixture()
def tt(clinic, monkeypatch):
    from app.models import Setting
    from app.utils import channels, social

    with clinic["app"].app_context():
        for k, v in (("tt_app_id", APP), ("tt_app_secret", SECRET),
                     ("tt_auth_url", "https://www.tiktok.com/v2/auth/authorize?client_key=x"),
                     ("tt_business_id", "biz-open-id"), ("tt_refresh_token", "R1"),
                     ("tt_access_token", "A1"),
                     ("tt_access_until", (datetime.utcnow() + timedelta(hours=5)).isoformat())):
            Setting.set(k, v)
        channels.set_enabled(["whatsapp", "tiktok"])
        clinic["db"].session.commit()
    calls = []

    def fake_post(url, payload, headers=None, timeout=10):
        calls.append((url, payload, headers or {}))
        if url.endswith("refresh_token/"):
            return 200, json.dumps({"code": 0, "data": {
                "access_token": "A2", "expires_in": 86400, "open_id": "biz-open-id",
                "refresh_token": "R2", "refresh_token_expires_in": 31536000}})
        if url.endswith("oauth2/token/"):
            return 200, json.dumps({"code": 0, "data": {
                "access_token": "A9", "expires_in": 86400, "open_id": "biz-9",
                "refresh_token": "R9", "refresh_token_expires_in": 31536000}})
        return 200, json.dumps({"code": 0, "message": "OK",
                                "data": {"message": {"message_id": f"out{len(calls)}"}}})
    monkeypatch.setattr(social, "_post", fake_post)
    clinic["calls"] = calls
    return clinic


def _event(event, content, app=APP):
    return {"client_key": app, "event": event, "create_time": int(time.time()),
            "user_openid": "biz-open-id", "content": json.dumps(content)}


def _receive(mid, text, conv="conv-1", who="uid-1", name="mama_omar"):
    return _event("im_receive_msg", {
        "from": name, "to": "clinic", "unique_identifier": who,
        "from_user": {"id": who, "role": "personal_account"},
        "to_user": {"id": "biz-open-id", "role": "business_account"},
        "conversation_id": conv, "message_id": mid,
        "timestamp": int(time.time() * 1000), "type": "text",
        "text": {"body": text}, "scene_type": 0, "is_follower": True})


def _post(client, payload, secret=SECRET, stamp=None):
    raw = json.dumps(payload).encode()
    t = str(stamp if stamp is not None else int(time.time()))
    sig = hmac.new(secret.encode(), t.encode() + b"." + raw, hashlib.sha256).hexdigest()
    return client.post("/wa/webhook/tiktok", data=raw, headers={
        "Content-Type": "application/json", "Tiktok-Signature": f"t={t},s={sig}"})


def test_only_a_fresh_signature_from_tiktok_is_filed(tt):
    from app.models import MessageLog

    out = tt["app"].test_client()
    payload = _receive("m1", "الدكتورة متاحة السبت؟")
    assert out.post("/wa/webhook/tiktok", json=payload).status_code == 403
    assert _post(out, payload, secret="nope").status_code == 403
    assert _post(out, payload, stamp=int(time.time()) - 3600).status_code == 403
    assert _post(out, _receive("m9", "x"), ).status_code == 200
    assert _post(out, {**payload, "client_key": "another-app"}).status_code == 200
    with tt["app"].app_context():
        assert MessageLog.query.filter_by(provider_msg_id="tt:m1").count() == 0
    _post(out, payload)
    _post(out, payload)
    with tt["app"].app_context():
        assert MessageLog.query.filter_by(provider_msg_id="tt:m1").count() == 1


def test_a_reply_goes_to_the_conversation_ten_in_48_hours(tt):
    from app.models import Contact, MessageLog, Setting

    out = tt["app"].test_client()
    _post(out, _receive("m1", "عايزة أحجز"))
    with tt["app"].app_context():
        contact = Contact.query.one()
        assert contact.identity("tiktok").value == "mama_omar"
        assert contact.identity("tiktok_conversation").value == "conv-1"
        key = f"c{contact.id}"
        # The day's access token has run out: it is renewed on its own.
        Setting.set("tt_access_until", (datetime.utcnow() - timedelta(minutes=1)).isoformat())
        tt["db"].session.commit()
    desk = tt["sign_in"]("desk")
    desk.post(f"/messages/inbox/{key}/send", data={"body": "أهلاً، تحبي يوم إيه؟"})
    assert tt["calls"][0][0].endswith("/tt_user/oauth2/refresh_token/")
    url, body, headers = tt["calls"][-1]
    assert url.endswith("/business/message/send/") and headers["Access-Token"] == "A2"
    assert body == {"business_id": "biz-open-id", "recipient_type": "CONVERSATION",
                    "recipient": "conv-1", "message_type": "TEXT",
                    "text": {"body": "أهلاً، تحبي يوم إيه؟"}}
    for i in range(12):
        desk.post(f"/messages/inbox/{key}/send", data={"body": f"رد {i}"})
    with tt["app"].app_context():
        assert MessageLog.query.filter_by(direction="out", channel="tiktok").count() == 10
        row = MessageLog.query.filter_by(direction="in").one()
        row.created_at = datetime.utcnow() - timedelta(hours=49)
        tt["db"].session.commit()
    assert 'data-social-state="window"' in desk.get(f"/messages/inbox/{key}").get_data(as_text=True)


def test_an_ad_or_a_link_opens_a_lead_and_a_comment_is_answered_on_tiktok(tt):
    from app.models import Lead, MessageLog

    out = tt["app"].test_client()
    _post(out, _event("im_referral_msg", {
        "from": "abo_ali", "to": "clinic", "unique_identifier": "uid-7",
        "from_user": {"id": "uid-7", "role": "personal_account"},
        "to_user": {"id": "biz-open-id", "role": "business_account"},
        "conversation_id": "conv-7", "timestamp": int(time.time() * 1000),
        "is_follower": False, "referral": {"source": "ad", "ad": {
            "advertiser_id": "1", "ad_id": "AD7", "ad_name": "Vaccines October",
            "timestamp": 1, "embed_url": ""}}}))
    with tt["app"].app_context():
        lead = Lead.query.one()
        assert (lead.channel, lead.source_kind, lead.campaign) == ("tiktok", "ad", "Vaccines-October")
        assert MessageLog.query.count() == 0, "nothing was said yet"
    _post(out, _event("im_receive_high_intent_comment", {
        "from": "abo_ali", "to": "clinic", "unique_identifier": "uid-7",
        "from_user": {"id": "uid-7", "role": "personal_account"},
        "to_user": {"id": "biz-open-id", "role": "business_account"},
        "comment_id": "CM1", "comment_text": "سعر التطعيم كام؟", "is_follower": False}))
    with tt["app"].app_context():
        log = MessageLog.query.one()
        assert log.event == "comment"
        key = f"c{log.contact_id}"
    desk = tt["sign_in"]("desk")
    before = len(tt["calls"])
    desk.post(f"/messages/inbox/{key}/send", data={"body": "تعالى"})
    assert len(tt["calls"]) == before, "a TikTok comment is not answered from here"


def test_connecting_the_account_checks_the_state(tt):
    from app.models import Setting

    boss = tt["sign_in"]()
    page = boss.get("/messages/channels").get_data(as_text=True)
    assert "data-tt-fields" in page and SECRET not in page and "data-tt-start" in page
    start = boss.get("/messages/channels/tiktok/start")
    assert start.status_code == 302
    loc = start.headers["Location"]
    assert loc.startswith("https://www.tiktok.com/v2/auth/authorize?client_key=x&state=")
    state = loc.split("state=")[1].split("&")[0]
    boss.get("/messages/channels/tiktok/callback?code=C&state=forged")
    with tt["app"].app_context():
        assert Setting.get("tt_business_id") == "biz-open-id"
    boss.get("/messages/channels/tiktok/start")
    state = None
    with boss.session_transaction() as sess:
        state = sess["tt_oauth_state"]
    boss.get(f"/messages/channels/tiktok/callback?code=C&state={state}")
    with tt["app"].app_context():
        assert Setting.get("tt_business_id") == "biz-9"
        assert Setting.get("tt_refresh_token") == "R9"
    sent = [c for c in tt["calls"] if c[0].endswith("oauth2/token/")][-1][1]
    assert sent["grant_type"] == "authorization_code" and sent["auth_code"] == "C"
    assert sent["redirect_uri"].endswith("/messages/channels/tiktok/callback")
    assert tt["sign_in"]("desk").get("/messages/channels/tiktok/start").status_code in (302, 403)
