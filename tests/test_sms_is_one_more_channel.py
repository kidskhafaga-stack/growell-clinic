"""SMS كقناة إضافية جنب واتساب.

* مقفولة لحد ما العيادة تشغّلها، ومفيش شركة مفترضة: العنوان وشكل الطلب من
  شرح شركتها، والبرنامج بيملا {to} {text} {sender} {key}؛
* الأنواع المعلّمة بتروح SMS بدل واتساب (في الإرسال التلقائي بس)؛
* رسالة واتساب فشلت بتتبعت SMS لو العيادة طالبة كده — صف جديد، والفشل فاضل؛
* تقرير الوصول بأسماء الخانات والكلمات اللي العيادة كتبتها، بسر في العنوان؛
* العربي ٧٠ حرف والجزء ٦٧.
"""
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def _setup(clinic, **extra):
    from app.models import Setting

    values = {"sms_enabled": "1", "sms_endpoint": "https://sms.example.test/send",
              "sms_method": "json", "sms_auth_header": "Authorization",
              "sms_auth_value": "Bearer K", "sms_sender": "GrowWell",
              "sms_payload": '{"to": "{to}", "msg": "{text}", "from": "{sender}"}',
              "sms_phone_format": "intl", "sms_id_field": "data.id"}
    values.update(extra)
    for k, v in values.items():
        Setting.set(k, v)
    clinic["db"].session.commit()


class _Resp:
    def __init__(self, body, status=200):
        self.status, self._body = status, body.encode()

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _capture(monkeypatch, reply='{"data": {"id": "m-77"}}'):
    import urllib.request

    seen = []

    def fake(req, timeout=None):
        seen.append(req)
        return _Resp(reply)
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    return seen


def test_the_request_is_the_company_s_own_shape(clinic, monkeypatch):
    from app.utils import sms

    with clinic["app"].app_context():
        _setup(clinic)
        seen = _capture(monkeypatch)
        log = sms.send('موعدك بكرة "الساعة ٥"', "01001234567", ignore_window=True)
        assert log.status == "sent" and log.channel == "sms" and log.provider_msg_id == "m-77"
        req = seen[0]
        assert req.full_url == "https://sms.example.test/send"
        assert req.headers.get("Authorization") == "Bearer K"
        body = json.loads(req.data.decode())
        assert body == {"to": "201001234567", "msg": 'موعدك بكرة "الساعة ٥"', "from": "GrowWell"}


def test_off_or_empty_sends_nothing(clinic, monkeypatch):
    from app.utils import sms

    with clinic["app"].app_context():
        _setup(clinic, sms_enabled="0")
        seen = _capture(monkeypatch)
        log = sms.send("x", "01001234567", ignore_window=True)
        assert log.status == "failed" and log.error == "sms_not_configured" and not seen


def test_a_ticked_type_goes_by_sms_in_automatic_mode(clinic, monkeypatch):
    from app.models import Setting
    from app.utils import whatsapp as wa

    with clinic["app"].app_context():
        _setup(clinic, sms_types="appointment_reminder")
        wa.seed_system_templates()
        Setting.set("crm_mode", "automatic")
        Setting.set("wa_provider", "cloud_api")
        from app.models import MessageTemplate
        tpl = MessageTemplate.query.filter_by(occasion="appointment_reminder", is_system=True).first()
        tpl.send_mode, tpl.is_active = "auto", True
        clinic["db"].session.commit()
        _capture(monkeypatch)
        log = wa.send("تذكير", "01001234567", template_type="appointment_reminder", ignore_window=True)
        assert log.channel == "sms" and log.status == "sent"
        # Manual mode stays a WhatsApp link.
        Setting.set("crm_mode", "manual")
        log = wa.send("تذكير", "01001234567", template_type="appointment_reminder")
        assert log.channel_key == "whatsapp" and log.status == "link"


def test_a_failed_whatsapp_message_is_sent_again_by_sms(clinic, monkeypatch):
    from app.models import MessageLog, Setting
    from app.utils import whatsapp as wa

    with clinic["app"].app_context():
        _setup(clinic, sms_fallback="1")
        Setting.set("crm_mode", "automatic")
        Setting.set("wa_provider", "cloud_api")     # no token: WhatsApp fails
        clinic["db"].session.commit()
        _capture(monkeypatch)
        first = wa.send("رسالة", "01001234567", ignore_window=True)
        assert first.status == "failed"
        again = MessageLog.query.filter_by(retry_of=first.id).one()
        assert again.channel == "sms" and again.status == "sent" and again.body == "رسالة"
        # A test send is never repeated by SMS.
        wa.send("رسالة", "01001234567", template_type="test", ignore_window=True)
        assert MessageLog.query.filter_by(channel="sms").count() == 1


def test_delivery_reports_by_the_clinic_s_own_words(clinic, monkeypatch):
    from app.models import MessageLog, Setting
    from app.utils import sms

    with clinic["app"].app_context():
        _setup(clinic, sms_dlr_id_field="msgid", sms_dlr_status_field="stat",
               sms_dlr_delivered="DELIVRD", sms_dlr_failed="UNDELIV,REJECTD")
        Setting.set("sms_webhook_secret", "s" * 32)
        clinic["db"].session.commit()
        _capture(monkeypatch)
        log = sms.send("x", "01001234567", ignore_window=True)
        clinic["db"].session.commit()
        rid = log.id
    client = clinic["app"].test_client()
    assert client.get("/wa/webhook/sms/wrong?msgid=m-77&stat=DELIVRD").status_code == 403
    assert client.get("/wa/webhook/sms/" + "s" * 32 + "?msgid=m-77&stat=DELIVRD").status_code == 200
    with clinic["app"].app_context():
        assert clinic["db"].session.get(MessageLog, rid).status == "delivered"
    client.post("/wa/webhook/sms/" + "s" * 32, json={"msgid": "m-77", "stat": "UNDELIV"})
    with clinic["app"].app_context():
        row = clinic["db"].session.get(MessageLog, rid)
        assert row.status == "failed" and "UNDELIV" in row.error


def test_arabic_is_counted_in_seventies():
    from app.utils import sms

    assert sms.segments("أ" * 70) == (1, 70, True)
    assert sms.segments("أ" * 71) == (2, 67, True)
    assert sms.segments("a" * 160) == (1, 160, False)
    assert sms.format_phone("201001234567", "local") == "01001234567"
    assert sms.format_phone("201001234567", "plus") == "+201001234567"


def test_the_settings_screen_saves_and_keeps_the_key(clinic):
    from app.models import Setting

    boss = clinic["sign_in"]("boss")
    page = boss.get("/messages/occasions").get_data(as_text=True)
    assert "data-sms-settings" in page and 'data-sms-preset="opensms"' in page
    boss.post("/messages/sms", data={"sms_enabled": "1", "sms_endpoint": "https://x.test",
                                     "sms_method": "json", "sms_auth_value": "Bearer SECRET",
                                     "sms_payload": '{"n": "{to}", "t": "{text}"}',
                                     "sms_types": ["appointment_reminder", "bogus"]})
    boss.post("/messages/sms", data={"sms_enabled": "1", "sms_endpoint": "https://x.test",
                                     "sms_method": "json", "sms_payload": '{"n": "{to}", "t": "{text}"}'})
    with clinic["app"].app_context():
        assert Setting.get("sms_auth_value") == "Bearer SECRET", "a blank box keeps the key"
        assert len(Setting.get("sms_webhook_secret") or "") >= 24
    page = boss.get("/messages/occasions").get_data(as_text=True)
    assert "Bearer SECRET" not in page
    # Reception may not change it.
    assert clinic["sign_in"]("desk").post("/messages/sms", data={"sms_enabled": "0"}).status_code in (302, 403)
    with clinic["app"].app_context():
        assert Setting.get("sms_enabled") == "1"
