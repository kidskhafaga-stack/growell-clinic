"""ماسنجر وإنستجرام وتليجرام في نفس الصندوق — المرحلة ٢ من ``CONNECTHUB_PLAN.md``.

الأشكال هنا منقولة من أمثلة التوثيق الرسمي نفسه (Meta وTelegram)، مش من
الذاكرة:

* **مفيش رسالة من غير إثبات**: توقيع ``X-Hub-Signature-256`` على Meta،
  والسر في ``X-Telegram-Bot-Api-Secret-Token`` على تليجرام؛
* **نفس الإشعار مرتين رسالة واحدة**، والرسالة اللي اتمسحت على إنستجرام
  بتتمسح هنا؛
* **الشخص بالهوية مش بالاسم**، والمحادثة ``c<id>`` لحد ما موظف يربطها
  بملف — وبعدها بتكمل على الملف والرد بيطلع على نفس القناة؛
* **الرد**: جوه ٢٤ ساعة ``RESPONSE``، وبعدها بس بتاج الموظف لو العيادة واخدة
  الموافقة؛ إنستجرام لحد ١٠٠٠ بايت؛ التعليق رد خاص واحد بس؛
* **الإعلان والتعليق** بيعملوا عميل محتمل بمصدره.
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

SECRET = "app-secret-for-tests"
TG_SECRET = "tg_secret_token_long_enough_123"


@pytest.fixture()
def hub(clinic, monkeypatch):
    from app.models import Setting
    from app.utils import channels, social

    with clinic["app"].app_context():
        for k, v in (("meta_page_id", "PAGE1"), ("meta_page_token", "PAGE-TOKEN"),
                     ("meta_app_secret", SECRET), ("meta_verify_token", "verify-me"),
                     ("tg_bot_token", "123:ABC"), ("tg_webhook_secret", TG_SECRET)):
            Setting.set(k, v)
        channels.set_enabled(["whatsapp", "messenger", "instagram", "telegram"])
        clinic["db"].session.commit()
    sent = []

    def fake_post(url, payload, headers=None, timeout=10):
        sent.append((url, payload))
        if "api.telegram.org" in url:
            return 200, json.dumps({"ok": True, "result": {"message_id": len(sent)}})
        return 200, json.dumps({"recipient_id": "x", "message_id": f"m_out{len(sent)}"})
    monkeypatch.setattr(social, "_post", fake_post)
    clinic["sent"] = sent
    return clinic


def _meta(client, payload, secret=SECRET, sign=True):
    raw = json.dumps(payload).encode()
    headers = {"Content-Type": "application/json"}
    if sign:
        headers["X-Hub-Signature-256"] = "sha256=" + hmac.new(
            secret.encode(), raw, hashlib.sha256).hexdigest()
    return client.post("/wa/webhook/social", data=raw, headers=headers)


def _msg(obj, sender, mid, text, own="PAGE1", **extra):
    message = {"mid": mid, "text": text, **extra}
    return {"object": obj, "entry": [{"id": own, "time": 1, "messaging": [{
        "sender": {"id": sender}, "recipient": {"id": own},
        "timestamp": int(time.time() * 1000), "message": message}]}]}


def _tg(client, update, secret=TG_SECRET):
    headers = {"Content-Type": "application/json"}
    if secret is not None:
        headers["X-Telegram-Bot-Api-Secret-Token"] = secret
    return client.post("/wa/webhook/telegram", data=json.dumps(update), headers=headers)


def test_nothing_is_filed_without_the_platforms_proof(hub):
    from app.models import MessageLog

    out = hub["app"].test_client()
    assert out.get("/wa/webhook/social?hub.mode=subscribe&hub.verify_token=verify-me"
                   "&hub.challenge=1158201444").get_data(as_text=True) == "1158201444"
    assert out.get("/wa/webhook/social?hub.mode=subscribe&hub.verify_token=nope"
                   "&hub.challenge=1").status_code == 403
    payload = _msg("page", "PSID1", "mid.1", "الدكتور موجود إمتى؟")
    assert _meta(out, payload, sign=False).status_code == 403
    assert _meta(out, payload, secret="wrong").status_code == 403
    assert _tg(out, {"update_id": 1}, secret=None).status_code == 403
    assert _tg(out, {"update_id": 1}, secret="wrong").status_code == 403
    with hub["app"].app_context():
        assert MessageLog.query.count() == 0
    assert _meta(out, payload).status_code == 200
    assert _meta(out, payload).status_code == 200, "Meta retries; the receiver dedupes"
    with hub["app"].app_context():
        assert MessageLog.query.count() == 1


def test_a_messenger_question_lands_in_the_inbox_and_is_answered_there(hub):
    from app.models import Contact, MessageLog

    out = hub["app"].test_client()
    _meta(out, _msg("page", "PSID7", "mid.7", "الكشف بكام؟"))
    with hub["app"].app_context():
        log = MessageLog.query.one()
        contact = Contact.query.one()
        assert (log.channel, log.contact_id, log.patient_id) == ("messenger", contact.id, None)
        assert contact.identity("messenger_psid").value == "PSID7"
        key = f"c{contact.id}"
    desk = hub["sign_in"]("desk")
    listing = desk.get("/messages/inbox?view=all").get_data(as_text=True)
    assert 'data-conv-channel="messenger"' in listing
    page = desk.get(f"/messages/inbox/{key}").get_data(as_text=True)
    assert 'data-thread-channel="messenger"' in page and 'data-social-state="RESPONSE"' in page
    desk.post(f"/messages/inbox/{key}/send", data={"body": "الكشف ٣٠٠ جنيه"})
    url, body = hub["sent"][-1]
    assert "/PAGE1/messages?" in url and "appsecret_proof=" in url and "appsecret_time=" in url
    assert body == {"recipient": {"id": "PSID7"}, "messaging_type": "RESPONSE",
                    "message": {"text": "الكشف ٣٠٠ جنيه"}}
    # Meta echoes what the Page sent; the echo of our own reply is not a
    # second copy.
    echo = _msg("page", "PAGE1", "m_out1", "الكشف ٣٠٠ جنيه", own="PAGE1", is_echo=True)
    echo["entry"][0]["messaging"][0]["recipient"] = {"id": "PSID7"}
    _meta(out, echo)
    with hub["app"].app_context():
        assert MessageLog.query.filter_by(direction="out").count() == 1


def test_after_24_hours_only_a_person_under_the_human_agent_tag(hub):
    from app.models import MessageLog, Setting

    out = hub["app"].test_client()
    _meta(out, _msg("instagram", "IGSID1", "ig.1", "عايزة أحجز", own="IGID"))
    with hub["app"].app_context():
        row = MessageLog.query.one()
        row.created_at = datetime.utcnow() - timedelta(hours=30)
        key = f"c{row.contact_id}"
        hub["db"].session.commit()
    desk = hub["sign_in"]("desk")
    assert 'data-social-state="window"' in desk.get(f"/messages/inbox/{key}").get_data(as_text=True)
    desk.post(f"/messages/inbox/{key}/send", data={"body": "أهلاً"})
    assert hub["sent"] == [], "refused before it is tried"
    with hub["app"].app_context():
        Setting.set("meta_human_agent", "1")
        hub["db"].session.commit()
    desk.post(f"/messages/inbox/{key}/send", data={"body": "أهلاً، أنا من الاستقبال"})
    assert hub["sent"][-1][1]["messaging_type"] == "MESSAGE_TAG"
    assert hub["sent"][-1][1]["tag"] == "HUMAN_AGENT"
    # Instagram text is at most 1000 bytes — said here, not by a failed send.
    before = len(hub["sent"])
    desk.post(f"/messages/inbox/{key}/send", data={"body": "ا" * 600})
    assert len(hub["sent"]) == before


def test_a_comment_is_a_lead_and_gets_one_private_reply(hub):
    from app.models import Lead, MessageLog

    out = hub["app"].test_client()
    feed = {"object": "page", "entry": [{"id": "PAGE1", "time": 1, "changes": [{
        "field": "feed", "value": {
            "from": {"id": "FBUSER9", "name": "منى أحمد"}, "item": "comment",
            "comment_id": "POST1_C9", "post_id": "PAGE1_POST1", "verb": "add",
            "created_time": int(time.time()), "message": "دكتور أحمد بيكشف السبت؟"}}]}]}
    _meta(out, feed)
    with hub["app"].app_context():
        log = MessageLog.query.one()
        assert (log.event, log.provider_msg_id) == ("comment", "POST1_C9")
        lead = Lead.query.one()
        assert (lead.channel, lead.source_kind) == ("messenger", "comment")
        assert lead.source_url == "https://www.facebook.com/PAGE1_POST1"
        key = f"c{log.contact_id}"
    desk = hub["sign_in"]("desk")
    assert 'data-social-state="comment"' in desk.get(f"/messages/inbox/{key}").get_data(as_text=True)
    desk.post(f"/messages/inbox/{key}/send", data={"body": "أيوه، تحب نحجزلك؟"})
    assert hub["sent"][-1][1] == {"recipient": {"comment_id": "POST1_C9"},
                                  "message": {"text": "أيوه، تحب نحجزلك؟"}}
    desk.post(f"/messages/inbox/{key}/send", data={"body": "تاني"})
    assert len(hub["sent"]) == 1, "one private reply per comment"
    with hub["app"].app_context():
        assert MessageLog.query.filter_by(event="private_reply").count() == 1


def test_an_ad_brings_a_lead_with_its_campaign(hub):
    from app.models import Lead

    out = hub["app"].test_client()
    payload = _msg("page", "PSID3", "mid.ad", "عايز أعرف أكتر", referral={
        "ref": "dr-ahmed", "ad_id": "AD9", "source": "ADS", "type": "OPEN_THREAD",
        "ads_context_data": {"ad_title": "Dr Ahmed October", "post_id": "P1"}})
    _meta(out, payload)
    with hub["app"].app_context():
        lead = Lead.query.one()
        assert (lead.source_kind, lead.campaign) == ("ad", "Dr-Ahmed-October")


def test_instagram_deletes_and_handles_find_the_same_person(hub):
    from app.models import Contact, MessageLog
    from app.utils import leads

    out = hub["app"].test_client()
    with hub["app"].app_context():
        typed = leads.contact_for("Mona", {"instagram": "@Mona.K"}).id
        hub["db"].session.commit()
    comment = {"object": "instagram", "entry": [{"id": "IGID", "time": 1, "changes": [{
        "field": "comments", "value": {
            "from": {"id": "IGSID5", "username": "mona.k"}, "id": "C5",
            "text": "السعر كام؟", "media": {"id": "M1", "media_product_type": "FEED"}}}]}]}
    _meta(out, comment)
    _meta(out, _msg("instagram", "IGSID5", "ig.5", "رقمي ٠١٠٠", own="IGID"))
    with hub["app"].app_context():
        assert Contact.query.count() == 1, "the typed handle and the platform's id are one person"
        assert MessageLog.query.filter_by(contact_id=typed).count() == 2
    gone = _msg("instagram", "IGSID5", "ig.5", "", own="IGID", is_deleted=True)
    _meta(out, gone)
    with hub["app"].app_context():
        assert MessageLog.query.filter_by(provider_msg_id="ig.5").count() == 0


def test_linking_a_contact_moves_the_thread_and_the_reply_keeps_its_channel(hub):
    from app.models import MessageLog

    out = hub["app"].test_client()
    _meta(out, _msg("instagram", "IGSID8", "ig.8", "ابني سخن", own="IGID"))
    with hub["app"].app_context():
        cid = MessageLog.query.one().contact_id
    desk = hub["sign_in"]("desk")
    desk.post(f"/messages/inbox/c{cid}/link", data={"patient_id": hub["ids"]["child"]})
    with hub["app"].app_context():
        assert MessageLog.query.one().patient_id == hub["ids"]["child"]
    _meta(out, _msg("instagram", "IGSID8", "ig.9", "لسه سخن", own="IGID"))
    with hub["app"].app_context():
        assert MessageLog.query.filter_by(provider_msg_id="ig.9").one().patient_id == hub["ids"]["child"]
    desk.post(f"/messages/inbox/p{hub['ids']['child']}/send", data={"body": "تعالى دلوقتي"})
    assert hub["sent"][-1][1]["recipient"] == {"id": "IGSID8"}


def test_telegram_through_its_secret_and_its_own_number(hub):
    from app.models import Contact, MessageLog

    out = hub["app"].test_client()
    update = {"update_id": 900, "message": {
        "message_id": 1, "date": int(time.time()),
        "chat": {"id": 5551, "type": "private", "first_name": "سارة"},
        "from": {"id": 5551, "is_bot": False, "first_name": "سارة", "username": "sara_m"},
        "contact": {"phone_number": "+201001112223", "first_name": "سارة", "user_id": 5551}}}
    assert _tg(out, update).status_code == 200
    assert _tg(out, update).status_code == 200
    group = {"update_id": 901, "message": {"message_id": 2, "date": 1,
             "chat": {"id": -100, "type": "group"}, "from": {"id": 7}, "text": "hi"}}
    _tg(out, group)
    with hub["app"].app_context():
        assert MessageLog.query.count() == 1, "duplicates and groups are not filed"
        contact = Contact.query.one()
        assert contact.phone == "201001112223" and contact.identity("telegram").value == "sara_m"
        key = f"c{contact.id}"
    desk = hub["sign_in"]("desk")
    desk.post(f"/messages/inbox/{key}/send", data={"body": "أهلاً سارة"})
    url, body = hub["sent"][-1]
    assert url.endswith("/bot123:ABC/sendMessage") and body == {"chat_id": "5551", "text": "أهلاً سارة"}


def test_a_channel_switched_off_is_accepted_and_dropped(hub):
    from app.models import MessageLog
    from app.utils import channels

    with hub["app"].app_context():
        channels.set_enabled(["whatsapp"])
        hub["db"].session.commit()
    out = hub["app"].test_client()
    assert _meta(out, _msg("page", "PSID1", "mid.off", "hi")).status_code == 200
    with hub["app"].app_context():
        assert MessageLog.query.count() == 0


def test_the_secret_proof_and_the_settings_screen(hub):
    from app.models import Setting
    from app.utils import social

    proof, stamp = social.appsecret_proof("TOKEN", "SECRET", now=1700000000)
    assert stamp == 1700000000 and proof == hmac.new(
        b"SECRET", b"TOKEN|1700000000", hashlib.sha256).hexdigest()
    boss = hub["sign_in"]()
    page = boss.get("/messages/channels").get_data(as_text=True)
    assert "data-connect" in page and "PAGE-TOKEN" not in page and SECRET not in page
    assert "/wa/webhook/social" in page and "/wa/webhook/telegram" in page
    boss.post("/messages/channels/connect", data={"meta_page_id": "PAGE2",
                                                  "meta_graph_version": "v25.0"})
    with hub["app"].app_context():
        assert Setting.get("meta_page_id") == "PAGE2"
        assert Setting.get("meta_page_token") == "PAGE-TOKEN", "a blank secret keeps its value"
    desk = hub["sign_in"]("desk")
    assert desk.post("/messages/channels/connect", data={}).status_code in (302, 403)
    with hub["app"].app_context():
        assert Setting.get("meta_page_id") == "PAGE2"


def test_out_of_hours_is_said_on_the_channel_they_wrote_from(hub, monkeypatch):
    from app.models import MessageLog, Setting
    from app.utils import service_desk

    monkeypatch.setattr(service_desk, "is_open", lambda *a, **k: False)
    with hub["app"].app_context():
        Setting.set("wa_away_enabled", "1")
        Setting.set("meta_human_agent", "1")
        hub["db"].session.commit()
    out = hub["app"].test_client()
    _meta(out, _msg("page", "PSID4", "mid.n1", "ابني سخن الساعة ٢ بالليل"))
    _meta(out, _msg("page", "PSID4", "mid.n2", "لو سمحتوا"))
    away = [b for _, b in hub["sent"]]
    assert len(away) == 1, "once, not on every message"
    assert away[0]["messaging_type"] == "RESPONSE" and "tag" not in away[0]
    feed = {"object": "page", "entry": [{"id": "PAGE1", "time": 1, "changes": [{
        "field": "feed", "value": {"from": {"id": "FB2", "name": "x"}, "item": "comment",
                                   "comment_id": "C2", "post_id": "P2", "verb": "add",
                                   "created_time": int(time.time()), "message": "?"}}]}]}
    _meta(out, feed)
    assert len(hub["sent"]) == 1, "a comment's one private reply is a person's, not the away note"
    with hub["app"].app_context():
        assert MessageLog.query.filter_by(template_type="away", channel="messenger").count() == 1


def test_a_photo_is_kept_after_the_answer_and_filed_on_a_linked_child(hub, monkeypatch):
    from app.models import Contact, MessageLog, PatientAttachment
    from app.utils import leads, social_media

    fetched = []

    def fake_get(url, headers=None):
        fetched.append(url)
        return b"\xff\xd8\xff fake jpeg", "image/jpeg"
    monkeypatch.setattr(social_media, "_get", fake_get)
    with hub["app"].app_context():
        contact = leads.contact_for("أم سلمى", {"instagram_igsid": "IGSID6"})
        from app.models import Patient
        leads.link_patient(contact, hub["db"].session.get(Patient, hub["ids"]["child"]), None)
        hub["db"].session.commit()
    out = hub["app"].test_client()
    payload = _msg("instagram", "IGSID6", "ig.ph", "", own="IGID",
                   attachments=[{"type": "image", "payload": {"url": "https://cdn.example/x.jpg"}}])
    payload["entry"][0]["messaging"][0]["message"].pop("text")
    resp = _meta(out, payload)
    resp.close()          # the platform has its answer; the queue is worked
    with hub["app"].app_context():
        row = MessageLog.query.filter_by(provider_msg_id="ig.ph").one()
        if row.error == social_media.PENDING:     # test client kept it open
            social_media.fetch_pending()
            row = MessageLog.query.filter_by(provider_msg_id="ig.ph").one()
        assert row.error is None and row.image_url.startswith("static/uploads/patient_docs/")
        att = PatientAttachment.query.one()
        assert (att.patient_id, att.source) == (hub["ids"]["child"], "instagram")
    assert fetched == ["https://cdn.example/x.jpg"]


def test_telegram_files_come_through_getfile(hub, monkeypatch):
    from app.models import MessageLog
    from app.utils import social, social_media

    def fake_post(url, payload, headers=None, timeout=10):
        if url.endswith("/getFile"):
            return 200, json.dumps({"ok": True, "result": {"file_path": "photos/f1.jpg"}})
        return 200, json.dumps({"ok": True, "result": {"message_id": 1}})
    monkeypatch.setattr(social, "_post", fake_post)
    monkeypatch.setattr(social_media, "_get", lambda url, headers=None: (
        b"bytes", "application/octet-stream"))
    out = hub["app"].test_client()
    _tg(out, {"update_id": 77, "message": {
        "message_id": 3, "date": int(time.time()),
        "chat": {"id": 42, "type": "private"}, "from": {"id": 42, "first_name": "س"},
        "photo": [{"file_id": "small"}, {"file_id": "BIG"}], "caption": "نتيجة التحليل"}}).close()
    with hub["app"].app_context():
        social_media.fetch_pending()
        row = MessageLog.query.one()
        assert row.error is None and row.image_url.endswith(".jpg")
