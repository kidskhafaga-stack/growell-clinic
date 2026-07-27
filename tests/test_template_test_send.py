"""One number, before fifty.

The automatic replies go out unread. A template with a mistake in it reaches
every family the trigger fires for before anyone notices, and not one of those
messages can be taken back — so there is a way to send it to a single phone
first, filled with sample values, exactly as the provider will deliver it.
"""
import os
import sys


sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def desk(clinic):
    """A clinic with a birthday template in it, and the manager signed in."""
    from app.models import MessageTemplate
    from app.utils import whatsapp as wa

    with clinic["app"].app_context():
        wa.seed_system_templates()
        tpl = MessageTemplate.query.filter_by(occasion="birthday",
                                              is_system=True).first()
        tpl.body = "كل سنة وأنت طيب يا {patient} ❤️ من {clinic}"
        clinic["db"].session.commit()
        clinic["tpl"] = tpl.id
    clinic["boss"] = clinic["sign_in"]("boss")
    return clinic


def _settings(desk, **pairs):
    from app.models import Setting

    with desk["app"].app_context():
        for key, value in pairs.items():
            Setting.set(key, value)
        desk["db"].session.commit()


def _tests_sent(desk):
    from app.models import MessageLog

    with desk["app"].app_context():
        return MessageLog.query.filter_by(template_type="test").order_by(
            MessageLog.id).all()


def _post(desk, **data):
    return desk["boss"].post(f"/messages/type/{desk['tpl']}/test-send",
                             data=data)


# ------------------------------------------------------------- the samples --
def test_the_preview_fills_the_tokens():
    from app.utils.wa_preview import fill

    assert fill("يا {patient} من {clinic}") == "يا محمد أحمد من العيادة"


def test_a_token_nobody_recognises_stays_visible():
    """Blanking {patinet} would hide the typo. Leaving it in the preview is
    how the typo gets noticed."""
    from app.utils.wa_preview import fill

    assert fill("يا {patinet}") == "يا {patinet}"


def test_the_clinics_own_name_is_used_when_we_know_it():
    from app.utils.wa_preview import fill, samples

    assert fill("{clinic}", samples("عيادة جروويل")) == "عيادة جروويل"


# ----------------------------------------------------------- the test send --
def test_it_sends_the_filled_body_to_the_number_given(desk, monkeypatch):
    from app.utils import whatsapp as wa

    sent = {}

    def fake_cloud(cfg, phone, body, image_url=None):
        sent["phone"], sent["body"] = phone, body
        return True, None

    monkeypatch.setattr(wa, "_send_cloud", fake_cloud)
    _settings(desk, crm_mode="automatic", wa_provider="cloud_api",
              wa_cloud_token="tok", wa_cloud_phone_id="1")

    _post(desk, phone="01000000009")

    assert sent["phone"] == "201000000009"
    assert "محمد أحمد" in sent["body"] and "{patient}" not in sent["body"]
    assert _tests_sent(desk)[0].status == "sent"


def test_it_tests_what_is_on_the_screen_not_what_was_saved(desk, monkeypatch):
    """Testing the version you already replaced is the exact mistake this is
    meant to prevent."""
    from app.utils import whatsapp as wa

    sent = {}
    monkeypatch.setattr(wa, "_send_cloud",
                        lambda cfg, phone, body, image_url=None: (
                            sent.update(body=body), (True, None))[1])
    _settings(desk, crm_mode="automatic", wa_provider="cloud_api",
              wa_cloud_token="tok", wa_cloud_phone_id="1")

    _post(desk, phone="01000000009", body="نص جديد لسه ما اتحفظش يا {patient}")

    assert "نص جديد" in sent["body"]
    assert "كل سنة" not in sent["body"]


def test_an_empty_editor_falls_back_to_the_saved_body(desk, monkeypatch):
    from app.utils import whatsapp as wa

    sent = {}
    monkeypatch.setattr(wa, "_send_cloud",
                        lambda cfg, phone, body, image_url=None: (
                            sent.update(body=body), (True, None))[1])
    _settings(desk, crm_mode="automatic", wa_provider="cloud_api",
              wa_cloud_token="tok", wa_cloud_phone_id="1")

    _post(desk, phone="01000000009", body="   ")

    assert "كل سنة" in sent["body"]


def test_no_number_sends_nothing(desk, monkeypatch):
    from app.utils import whatsapp as wa

    monkeypatch.setattr(wa, "_send_cloud",
                        lambda *a, **k: pytest.fail("should not have sent"))
    _settings(desk, crm_mode="automatic", wa_provider="cloud_api")

    _post(desk, phone="  ")

    assert _tests_sent(desk) == []


def test_it_goes_out_now_even_outside_the_sending_window(desk, monkeypatch):
    """The window and the cap exist to stop the clinic messaging families at
    2 a.m. in bulk. Holding back a test somebody is standing there waiting for
    would only look broken."""
    from app.utils import whatsapp as wa

    monkeypatch.setattr(wa, "_send_cloud",
                        lambda *a, **k: (True, None))
    _settings(desk, crm_mode="automatic", wa_provider="cloud_api",
              wa_cloud_token="tok", wa_cloud_phone_id="1",
              # A one-minute window that has certainly passed or not arrived.
              wa_send_from="3", wa_send_to="4", wa_daily_cap="1")

    _post(desk, phone="01000000009")
    _post(desk, phone="01000000009")

    assert [log.status for log in _tests_sent(desk)] == ["sent", "sent"]


def test_a_manual_type_still_tests_through_the_real_provider(desk, monkeypatch):
    """A test that quietly becomes a click-to-send link because the type is set
    to manual has tested nothing."""
    from app.models import MessageTemplate
    from app.utils import whatsapp as wa

    monkeypatch.setattr(wa, "_send_cloud", lambda *a, **k: (True, None))
    _settings(desk, crm_mode="automatic", wa_provider="cloud_api",
              wa_cloud_token="tok", wa_cloud_phone_id="1")
    with desk["app"].app_context():
        desk["db"].session.get(MessageTemplate, desk["tpl"]).send_mode = "manual"
        desk["db"].session.commit()

    _post(desk, phone="01000000009")

    assert _tests_sent(desk)[0].provider == "cloud_api"


def test_a_click_to_send_clinic_gets_the_ready_message_to_click(desk):
    """No API, no test send — but the wa.me link with the filled text is the
    same check by hand."""
    _settings(desk, crm_mode="manual")

    resp = _post(desk, phone="01000000009")

    assert resp.status_code in (301, 302)
    assert "wa.me/201000000009" in resp.headers["Location"]


def test_a_failure_says_so(desk, monkeypatch):
    from app.utils import whatsapp as wa

    monkeypatch.setattr(wa, "_send_cloud", lambda *a, **k: (False, "http_401"))
    _settings(desk, crm_mode="automatic", wa_provider="cloud_api",
              wa_cloud_token="tok", wa_cloud_phone_id="1")

    resp = _post(desk, phone="01000000009")

    assert resp.status_code in (301, 302)
    assert _tests_sent(desk)[0].status == "failed"


def test_the_test_button_is_on_the_screen(desk):
    body = desk["boss"].get("/messages/occasions").get_data(as_text=True)
    assert "/test-send" in body


def test_a_test_send_is_not_counted_as_a_notification_to_anyone(desk,
                                                                monkeypatch):
    """It went to the receptionist's own phone. Counting it as a birthday
    greeting would make the delivery report lie."""
    from app.models import MessageLog
    from app.utils import whatsapp as wa

    monkeypatch.setattr(wa, "_send_cloud", lambda *a, **k: (True, None))
    _settings(desk, crm_mode="automatic", wa_provider="cloud_api",
              wa_cloud_token="tok", wa_cloud_phone_id="1")

    _post(desk, phone="01000000009")

    with desk["app"].app_context():
        assert MessageLog.query.filter_by(template_type="birthday").count() == 0
        assert MessageLog.query.filter_by(patient_id=desk["ids"]["child"]
                                          ).count() == 0
