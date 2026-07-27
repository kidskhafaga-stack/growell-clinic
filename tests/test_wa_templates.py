"""The two ways a template goes wrong: untested, and unusable.

**Untested** — the automatic replies go out unread. A template with a mistake
in it reaches fifty families before anyone notices, and not one of those
messages can be taken back. One send to the receptionist's own phone catches
it while it still costs nothing.

**Unusable** — 24 hours after the family's last message WhatsApp refuses free
text and delivers only a template Meta approved in advance. The program knew
that rule and warned about it, which left the receptionist reading "the window
is closed" with nothing to do. An old conversation was a dead end.
"""
import os
import sys
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

REGISTRY = ("result_ready | ar | نتيجة {{1}} جاهزة يا {{2}}\n"
            "clinic_closed | ar | العيادة مقفولة النهارده")


@pytest.fixture()
def desk(clinic):
    """A family with a phone number, and the manager signed in."""
    from app.models import Family, Parent, Patient

    with clinic["app"].app_context():
        family = Family(family_name="عائلة")
        clinic["db"].session.add(family)
        clinic["db"].session.flush()
        clinic["db"].session.add(Parent(family_id=family.id, full_name="الأم",
                                        relation="mother", phone="01000000001"))
        child = Patient(patient_number="T-1", full_name="طفل", gender="male",
                        date_of_birth=date(2024, 1, 1), family_id=family.id,
                        is_active=True)
        clinic["db"].session.add(child)
        clinic["db"].session.flush()
        clinic["kid"] = child.id
        clinic["db"].session.commit()
    clinic["boss"] = clinic["sign_in"]("boss")
    return clinic


def _settings(desk, **pairs):
    from app.models import Setting

    with desk["app"].app_context():
        for key, value in pairs.items():
            Setting.set(key, value)
        desk["db"].session.commit()


def _on_the_api(desk, **extra):
    """Put the clinic on the Cloud API — approved templates are its concept."""
    _settings(desk, crm_mode="automatic", wa_provider="cloud_api",
              wa_cloud_token="tok", wa_cloud_phone_id="123", **extra)


def _wrote(desk, hours_ago):
    from app.models import MessageLog

    with desk["app"].app_context():
        log = MessageLog(direction="in", provider="meta",
                         to_phone="201000000001", body="السلام عليكم",
                         status="received", patient_id=desk["kid"])
        desk["db"].session.add(log)
        desk["db"].session.flush()
        log.created_at = datetime.utcnow() - timedelta(hours=hours_ago)
        desk["db"].session.commit()


def _thread(desk):
    return desk["boss"].get(f"/messages/inbox/p{desk['kid']}").get_data(as_text=True)


def _logs(desk, **filters):
    from app.models import MessageLog

    with desk["app"].app_context():
        return MessageLog.query.filter_by(**filters).order_by(
            MessageLog.id).all()


# ------------------------------------------------------------- the registry --
def test_a_line_becomes_a_template():
    from app.utils.wa_templates import parse

    rows = parse(REGISTRY)
    assert [r["name"] for r in rows] == ["result_ready", "clinic_closed"]
    assert rows[0]["lang"] == "ar" and rows[0]["params"] == 2
    assert rows[1]["params"] == 0


def test_a_name_meta_would_reject_is_dropped_here():
    """A name with a space fails at send time with an error nobody can act on.
    Rejecting it in the settings screen puts it next to the line that caused
    it."""
    from app.utils.wa_templates import parse

    assert parse("Result Ready | ar | x") == []
    assert parse("result-ready | ar | x") == []
    assert [r["name"] for r in parse("RESULT_READY | ar | x")] == ["result_ready"]


def test_blank_lines_and_notes_are_not_templates():
    from app.utils.wa_templates import parse

    raw = "# القوالب المعتمدة\n\nresult_ready | ar | x\n\n"
    assert [r["name"] for r in parse(raw)] == ["result_ready"]


def test_the_same_name_twice_is_one_template():
    from app.utils.wa_templates import parse

    assert len(parse("a_b | ar | one\na_b | en | two")) == 1


def test_a_language_left_out_defaults_rather_than_failing():
    from app.utils.wa_templates import parse

    assert parse("result_ready")[0]["lang"] == "ar"
    assert parse("result_ready")[0]["params"] == 0


def test_the_parameter_count_is_the_highest_marker_not_the_tally():
    """A body using {{1}} twice and {{3}} once still needs three parameters.
    Asking for two produces a send Meta refuses."""
    from app.utils.wa_templates import param_count

    assert param_count("{{1}} و {{1}} و {{3}}") == 3
    assert param_count("{{ 2 }}") == 2
    assert param_count("مافيش متغيّرات") == 0


def test_filling_shows_the_sentence_the_family_reads():
    from app.utils.wa_templates import fill

    assert fill("نتيجة {{1}} جاهزة يا {{2}}", ["الصورة", "أم محمد"]) == (
        "نتيجة الصورة جاهزة يا أم محمد")


def test_a_parameter_nobody_supplied_stays_visible():
    """Blanking it would hide the mistake; leaving the marker is how it gets
    noticed before it goes out."""
    from app.utils.wa_templates import fill

    assert fill("{{1}} و {{2}}", ["واحد"]) == "واحد و {{2}}"


# ------------------------------------------------- when the path is offered --
def test_a_closed_window_offers_the_templates(desk):
    _on_the_api(desk)
    _settings(desk, wa_approved_templates=REGISTRY)
    _wrote(desk, hours_ago=30)

    body = _thread(desk)
    assert "result_ready" in body
    assert "/template-send" in body


def test_an_open_window_does_not(desk):
    """Free text is what the family should get while it is free. Offering both
    invites sending the stiffer, paid one by mistake."""
    _on_the_api(desk)
    _settings(desk, wa_approved_templates=REGISTRY)
    _wrote(desk, hours_ago=2)

    assert "/template-send" not in _thread(desk)


def test_click_to_send_is_never_offered_templates(desk):
    """A staff member's own WhatsApp has no window and no template API. The
    button would be a button that cannot work."""
    _settings(desk, crm_mode="manual", wa_approved_templates=REGISTRY)
    _wrote(desk, hours_ago=30)

    assert "/template-send" not in _thread(desk)


def test_wapilot_is_not_offered_templates(desk):
    """WaPilot drives an ordinary WhatsApp session; there is no template
    endpoint to send to."""
    _settings(desk, crm_mode="automatic", wa_provider="wapilot",
              wa_approved_templates=REGISTRY)
    _wrote(desk, hours_ago=30)

    assert "/template-send" not in _thread(desk)


def test_a_clinic_on_the_api_with_none_registered_is_told_where_to_add_them(desk):
    """"Nothing to offer" and "nothing registered" are different situations,
    and the second one is a settings link, not a shrug."""
    _on_the_api(desk)
    _wrote(desk, hours_ago=30)

    body = _thread(desk)
    assert "/template-send" not in body
    assert "#connection" in body


def test_a_family_who_never_wrote_is_the_same_dead_end(desk):
    """Reaching out first has no window open either — it is the case the
    templates exist for."""
    _on_the_api(desk)
    _settings(desk, wa_approved_templates=REGISTRY)

    body = desk["boss"].get(f"/messages/inbox/start/{desk['kid']}",
                            follow_redirects=True).get_data(as_text=True)
    assert "result_ready" in body


# ------------------------------------------------------------ sending one ----
def test_sending_one_records_what_the_family_reads(desk, monkeypatch):
    """The wire carries a name and a list of parameters. The conversation has
    to show the sentence, or the thread stops being a record of what was
    said."""
    from app.utils import whatsapp as wa

    sent = {}

    def fake_post(url, payload, headers, timeout=12):
        sent["url"], sent["payload"] = url, payload
        return 200, "{}"

    monkeypatch.setattr(wa, "_post_json", fake_post)
    _on_the_api(desk)
    _settings(desk, wa_approved_templates=REGISTRY)
    _wrote(desk, hours_ago=30)

    desk["boss"].post(f"/messages/inbox/p{desk['kid']}/template-send",
                      data={"name": "result_ready", "p1": "الأشعة",
                            "p2": "أم محمد"})

    out = _logs(desk, template_type="approved")
    assert len(out) == 1
    assert out[0].body == "نتيجة الأشعة جاهزة يا أم محمد"
    assert out[0].status == "sent"
    # …and the wire format is Meta's, not our text.
    assert sent["payload"]["type"] == "template"
    assert sent["payload"]["template"]["name"] == "result_ready"
    assert [p["text"] for p in
            sent["payload"]["template"]["components"][0]["parameters"]] == [
        "الأشعة", "أم محمد"]


def test_a_template_with_no_parameters_sends_without_a_components_block(desk,
                                                                       monkeypatch):
    """An empty parameters list is not the same as no parameters, and Meta
    treats the difference as an error."""
    from app.utils import whatsapp as wa

    sent = {}
    monkeypatch.setattr(wa, "_post_json",
                        lambda u, p, h, timeout=12: (sent.update(payload=p),
                                                     (200, "{}"))[1])
    _on_the_api(desk)
    _settings(desk, wa_approved_templates=REGISTRY)
    _wrote(desk, hours_ago=30)

    desk["boss"].post(f"/messages/inbox/p{desk['kid']}/template-send",
                      data={"name": "clinic_closed"})

    assert "components" not in sent["payload"]["template"]


def test_a_blank_parameter_is_refused_before_it_reaches_meta(desk, monkeypatch):
    """Meta rejects it anyway, and "نتيجة  جاهزة" reaching a mother would be
    worse than the rejection. Catch it while there is still a form to fix."""
    from app.utils import whatsapp as wa

    monkeypatch.setattr(wa, "_post_json",
                        lambda *a, **k: pytest.fail("should not have sent"))
    _on_the_api(desk)
    _settings(desk, wa_approved_templates=REGISTRY)
    _wrote(desk, hours_ago=30)

    desk["boss"].post(f"/messages/inbox/p{desk['kid']}/template-send",
                      data={"name": "result_ready", "p1": "الأشعة", "p2": " "})

    assert _logs(desk, template_type="approved") == []


def test_a_name_that_is_not_registered_sends_nothing(desk, monkeypatch):
    from app.utils import whatsapp as wa

    monkeypatch.setattr(wa, "_post_json",
                        lambda *a, **k: pytest.fail("should not have sent"))
    _on_the_api(desk)
    _settings(desk, wa_approved_templates=REGISTRY)
    _wrote(desk, hours_ago=30)

    desk["boss"].post(f"/messages/inbox/p{desk['kid']}/template-send",
                      data={"name": "whatever"})

    assert _logs(desk, template_type="approved") == []


def test_a_provider_without_templates_fails_loudly_rather_than_silently(desk):
    """A log that says "sent" for a message no provider could carry is the
    worst outcome here."""
    from app.utils import whatsapp as wa

    _settings(desk, crm_mode="automatic", wa_provider="wapilot")
    with desk["app"].app_context():
        log = wa.send_approved({"name": "x", "lang": "ar", "body": "hi",
                                "params": 0}, [], "01000000001")
        desk["db"].session.commit()
        assert log.status == "failed"
        assert log.error == "templates_need_cloud_api"


def test_a_provider_error_is_recorded_not_swallowed(desk, monkeypatch):
    from app.utils import whatsapp as wa

    monkeypatch.setattr(wa, "_post_json",
                        lambda *a, **k: (400, "bad template"))
    _on_the_api(desk)
    _settings(desk, wa_approved_templates=REGISTRY)
    _wrote(desk, hours_ago=30)

    desk["boss"].post(f"/messages/inbox/p{desk['kid']}/template-send",
                      data={"name": "clinic_closed"})

    out = _logs(desk, template_type="approved")
    assert out[0].status == "failed" and out[0].error == "http_400"


def test_an_opted_out_family_is_not_reached_by_a_template_either(desk,
                                                                monkeypatch):
    """The opt-out is the family's answer to being messaged at all — a
    different send path is not a way around it."""
    from app.models import Patient
    from app.utils import whatsapp as wa

    monkeypatch.setattr(wa, "_post_json",
                        lambda *a, **k: pytest.fail("should not have sent"))
    _on_the_api(desk)
    _settings(desk, wa_approved_templates=REGISTRY)
    _wrote(desk, hours_ago=30)
    with desk["app"].app_context():
        desk["db"].session.get(Patient, desk["kid"]).wa_opt_out = True
        desk["db"].session.commit()

    desk["boss"].post(f"/messages/inbox/p{desk['kid']}/template-send",
                      data={"name": "clinic_closed"})

    out = _logs(desk, template_type="approved")
    assert out[0].status == "skipped"


# ------------------------------------------------- the registry on a screen --
def test_the_settings_screen_reads_back_what_parsed(desk):
    """A mistyped line has to visibly disappear here, rather than on the night
    somebody needs it."""
    _on_the_api(desk)
    _settings(desk, wa_approved_templates=REGISTRY + "\nBad Name | ar | x")

    body = desk["boss"].get("/messages/occasions").get_data(as_text=True)
    # The badge list is the read-back; the textarea still shows every line the
    # clinic typed, including the bad one, because that is what needs fixing.
    assert "result_ready · ar" in body
    assert "Bad Name · " not in body


def test_saving_the_connection_keeps_the_registry(desk):
    from app.models import Setting

    _on_the_api(desk)
    desk["boss"].post("/messages/connection",
                      data={"crm_mode": "automatic", "wa_provider": "cloud_api",
                            "wa_approved_templates": REGISTRY})
    with desk["app"].app_context():
        assert "result_ready" in Setting.get("wa_approved_templates", "")
