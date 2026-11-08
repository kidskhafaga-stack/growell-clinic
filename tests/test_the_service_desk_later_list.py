"""The service desk's «بعد كده» list, asked for by the owner.

* **A Facebook comment and the same person's Messenger thread are one
  person.** A commenter is filed under the id the comment carries, their
  Messenger thread under another. Meta's answer to the private reply names
  the Messenger id (``recipient_id``) — the program now keeps it, and when
  that person already wrote on Messenger the two contacts become one.
* **Search reads every message**, not the last one of each conversation.
* **Hours per day**: Friday is not Wednesday.
* **A reply with a picture or a PDF** from the inbox, on WhatsApp.
"""
import io
import json
import os
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

from tests.test_every_channel_into_the_inbox import _meta, _msg, hub  # noqa: E402,F401

PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06"
       b"\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\x0f\x00\x00\x01\x01"
       b"\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82")


def _comment(client, user="FBUSER9", cid="POST1_C9", text="دكتور أحمد بيكشف السبت؟"):
    _meta(client, {"object": "page", "entry": [{"id": "PAGE1", "time": 1, "changes": [{
        "field": "feed", "value": {
            "from": {"id": user, "name": "منى أحمد"}, "item": "comment",
            "comment_id": cid, "post_id": "PAGE1_POST1", "verb": "add",
            "created_time": int(time.time()), "message": text}}]}]})


@pytest.fixture()
def psid(hub, monkeypatch):
    """Meta answers the private reply with the commenter's Messenger id."""
    from app.utils import social

    def fake_post(url, payload, headers=None, timeout=10):
        hub["sent"].append((url, payload))
        return 200, json.dumps({"recipient_id": "PSID77", "message_id": f"m_out{len(hub['sent'])}"})
    monkeypatch.setattr(social, "_post", fake_post)
    return hub


def _contact_key(app, **filt):
    from app.models import MessageLog

    with app.app_context():
        return f"c{MessageLog.query.filter_by(**filt).first().contact_id}"


def test_the_commenter_s_messenger_reply_lands_in_the_same_thread(psid):
    from app.models import Contact, MessageLog

    web = psid["app"].test_client()
    _comment(web)
    key = _contact_key(psid["app"], event="comment")
    psid["sign_in"]("desk").post(f"/messages/inbox/{key}/send", data={"body": "تحب نحجزلك؟"})
    _meta(web, _msg("page", "PSID77", "mid.1", "أيوه السبت الساعة كام؟"))
    with psid["app"].app_context():
        rows = MessageLog.query.order_by(MessageLog.id).all()
        assert len({r.contact_id for r in rows}) == 1, "one person, one thread"
        assert Contact.query.count() == 1


def test_one_who_wrote_on_messenger_first_becomes_one_person(psid):
    from app.models import Contact, Lead, MessageLog

    web = psid["app"].test_client()
    _meta(web, _msg("page", "PSID77", "mid.0", "مساء الخير"))
    first = _contact_key(psid["app"], provider_msg_id="mid.0")
    _comment(web)
    key = _contact_key(psid["app"], event="comment")
    assert key != first, "two contacts until Meta says otherwise"
    psid["sign_in"]("desk").post(f"/messages/inbox/{key}/send", data={"body": "تحب نحجزلك؟"})
    with psid["app"].app_context():
        ids = {r.contact_id for r in MessageLog.query.all()}
        assert ids == {int(first[1:])}, "every message is now on the Messenger contact"
        assert Lead.query.filter(Lead.closed_at.is_(None)).count() <= 1
        gone = psid["db"].session.get(Contact, int(key[1:]))
        assert not gone.identities and "merged" in (gone.note or "")
    page = psid["sign_in"]("desk").get(f"/messages/inbox/{first}").get_data(as_text=True)
    assert "دكتور أحمد بيكشف السبت؟" in page and "مساء الخير" in page


def test_search_reads_every_message_not_the_last(hub):
    from app.models import MessageLog

    with hub["app"].app_context():
        db = hub["db"]
        for i, body in enumerate(("نتيجة صورة الدم جاهزة يا فندم", "تمام شكراً", "مع السلامة")):
            db.session.add(MessageLog(direction="in" if i else "out", to_phone="201001112223",
                                      patient_id=hub["ids"]["child"], body=body, status="sent",
                                      created_at=datetime(2026, 3, 1, 10, i)))
        db.session.commit()
    page = hub["sign_in"]("desk").get("/messages/inbox?q=صورة الدم").get_data(as_text=True)
    assert "data-search-hit" in page and "نتيجة صورة الدم" in page
    none = hub["sign_in"]("desk").get("/messages/inbox?q=كلمة مش موجودة").get_data(as_text=True)
    assert "data-search-hit" not in none


def test_hours_of_their_own_on_friday(clinic):
    from app.models import Setting
    from app.utils import service_desk as sd

    with clinic["app"].app_context():
        Setting.set("wa_open_days", "5,6,0,1,2,3,4")
        Setting.set("wa_open_from", "16:00")
        Setting.set("wa_open_to", "22:00")
        Setting.set(sd.PER_DAY_KEY, json.dumps({"4": ["18:00", "21:00"]}))
        cfg = sd.hours_config()
        friday_17 = datetime(2026, 11, 6, 17, 0)        # a Friday
        wednesday_17 = datetime(2026, 11, 4, 17, 0)
        assert not sd.is_open(friday_17, cfg) and sd.is_open(wednesday_17, cfg)
        assert sd.is_open(datetime(2026, 11, 6, 20, 0), cfg)
        label = sd.hours_label(cfg)
        assert "16:00 – 22:00" in label and "18:00 – 21:00" in label


def test_an_overnight_day_of_its_own_runs_past_midnight(clinic):
    from app.models import Setting
    from app.utils import service_desk as sd

    with clinic["app"].app_context():
        Setting.set("wa_open_days", "3")                 # Thursday only
        Setting.set(sd.PER_DAY_KEY, json.dumps({"3": ["20:00", "02:00"]}))
        cfg = sd.hours_config()
        assert sd.is_open(datetime(2026, 11, 6, 1, 0), cfg), "Friday 1 a.m. is Thursday's shift"
        assert not sd.is_open(datetime(2026, 11, 6, 3, 0), cfg)


def test_the_settings_screen_saves_a_day_s_hours(clinic):
    from app.models import Setting
    from app.utils import service_desk as sd

    boss = clinic["sign_in"]("boss")
    page = boss.get("/messages/quick-replies").get_data(as_text=True)
    assert "data-per-day-hours" in page
    boss.post("/messages/away-hours", data={
        "open_days": ["5", "6", "0", "4"], "open_from": "16:00", "open_to": "22:00",
        "day_from_4": "18:00", "day_to_4": "21:00",
        "day_from_0": "09:00", "day_to_0": "",            # half filled: ignored
        "day_from_2": "10:00", "day_to_2": "12:00"})       # not a working day: ignored
    with clinic["app"].app_context():
        assert sd.parse_per_day(Setting.get(sd.PER_DAY_KEY)) == {4: ("18:00", "21:00")}


def test_a_picture_from_the_inbox_on_whatsapp(clinic):
    from app.models import MessageLog, PatientAttachment

    with clinic["app"].app_context():
        clinic["db"].session.add(MessageLog(direction="in", to_phone="201001112223",
                                            patient_id=clinic["ids"]["child"],
                                            body="ابعتلي الروشتة", status="received"))
        clinic["db"].session.commit()
    key = f"p{clinic['ids']['child']}"
    desk = clinic["sign_in"]("desk")
    assert "data-send-file" in desk.get(f"/messages/inbox/{key}").get_data(as_text=True)
    r = desk.post(f"/messages/inbox/{key}/send-file",
                  data={"file": (io.BytesIO(PNG), "rx.png"), "caption": "الروشتة"},
                  content_type="multipart/form-data")
    assert r.status_code == 302 and "wa.me" in r.headers["Location"], \
        "click-to-send opens the chat; the person attaches the file"
    with clinic["app"].app_context():
        log = MessageLog.query.filter_by(direction="out").one()
        assert log.body == "الروشتة" and log.patient_id == clinic["ids"]["child"]
        assert PatientAttachment.query.filter_by(patient_id=clinic["ids"]["child"]).count() == 1


def test_a_file_that_is_not_a_picture_or_pdf_is_refused(clinic):
    from app.models import MessageLog

    with clinic["app"].app_context():
        clinic["db"].session.add(MessageLog(direction="in", to_phone="201001112223",
                                            patient_id=clinic["ids"]["child"],
                                            body="?", status="received"))
        clinic["db"].session.commit()
    key = f"p{clinic['ids']['child']}"
    clinic["sign_in"]("desk").post(f"/messages/inbox/{key}/send-file",
                                   data={"file": (io.BytesIO(b"MZ\x90\x00x"), "x.exe")},
                                   content_type="multipart/form-data")
    with clinic["app"].app_context():
        assert MessageLog.query.filter_by(direction="out").count() == 0


def test_files_on_another_channel_are_said_not_sent(hub):
    from app.models import MessageLog

    web = hub["app"].test_client()
    _meta(web, _msg("page", "PSID5", "mid.5", "سلام"))
    key = _contact_key(hub["app"], provider_msg_id="mid.5")
    r = hub["sign_in"]("desk").post(f"/messages/inbox/{key}/send-file",
                                    data={"file": (io.BytesIO(PNG), "a.png")},
                                    content_type="multipart/form-data", follow_redirects=True)
    assert "واتساب بس" in r.get_data(as_text=True)
    with hub["app"].app_context():
        assert MessageLog.query.filter_by(direction="out").count() == 0
