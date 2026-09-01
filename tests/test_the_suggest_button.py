"""The button on the visit screen, and the three ways it must stay shut.

The suggestion appears inside the consultation, at the moment the diagnosis is
being chosen. That is both the most useful place for it and the place where a
machine's opinion has the most power to become the answer — so what this file
is mostly about is the guards, not the feature.
"""
import json

import pytest

REPLY = ('{"suggestions":[{"ar":"التهاب لوزتين حاد","en":"Acute tonsillitis",'
         '"why":"لوزتين محتقنتين","danger":false},'
         '{"ar":"التهاب سحائي","en":"Meningitis","why":"سخونية وصداع",'
         '"danger":true}]}')


@pytest.fixture
def wired(clinic, monkeypatch):
    """AI configured, the switch on, and the model answering a fixed reply."""
    from app.models import Setting, Visit
    from app.utils import ai as ai_utils

    with clinic["app"].app_context():
        Setting.set("ai_enabled", "1")
        Setting.set("ai_provider", "claude")
        Setting.set("ai_api_key", "k")
        Setting.set("ai_model", "m")
        Setting.set("ai_dx_suggest", "1")
        visit = Visit.query.get(clinic["ids"]["visit"])
        visit.chief_complaint = "سخونية ٣ أيام وصداع"
        visit.clinical_exam = "لوزتين محتقنتين"
        clinic["db"].session.commit()

    monkeypatch.setattr(ai_utils, "chat",
                        lambda *a, **k: {"ok": True, "text": REPLY})
    return clinic


def _ask(app_client, visit_id, **payload):
    return app_client.post(f"/ai/visit/{visit_id}/suggest-dx",
                           data=json.dumps(payload),
                           content_type="application/json")


# ------------------------------------------------------------ it answers ----
def test_it_returns_suggestions_with_the_program_s_own_codes(wired):
    res = _ask(wired["sign_in"]("doc"), wired["ids"]["visit"])
    assert res.status_code == 200
    body = res.get_json()
    assert body["ok"]
    names = [item["ar"] for item in body["suggestions"]]
    assert "التهاب لوزتين حاد" in names
    coded = [item for item in body["suggestions"] if item["code"]]
    assert coded, "nothing resolved to a code the program holds"


def test_the_dangerous_one_is_marked(wired):
    body = _ask(wired["sign_in"]("doc"), wired["ids"]["visit"]).get_json()
    flagged = [item["ar"] for item in body["suggestions"] if item["danger"]]
    assert "التهاب سحائي" in flagged


def test_what_the_doctor_is_typing_reaches_the_model(wired, monkeypatch):
    """The button is pressed mid-sentence. A brief built from the saved row
    would answer about the screen as it was two minutes ago."""
    from app.utils import ai as ai_utils

    seen = {}

    def spy(messages, system=None, feature=None):
        seen["brief"] = messages[0]["content"]
        return {"ok": True, "text": REPLY}

    monkeypatch.setattr(ai_utils, "chat", spy)
    _ask(wired["sign_in"]("doc"), wired["ids"]["visit"],
         cc="كحة وزلة نفس من ساعتين")
    assert "كحة وزلة نفس" in seen["brief"]


def test_it_is_written_down(wired):
    """"Was the assistant asked about this consultation" must have an answer
    from the clinic's own record, not from whoever was in the room."""
    from app.models import ActivityLog

    _ask(wired["sign_in"]("doc"), wired["ids"]["visit"])
    with wired["app"].app_context():
        assert ActivityLog.query.filter_by(action="ai.suggest_dx",
                                           entity="visit").count() == 1


# -------------------------------------------------------------- it refuses --
def test_it_is_off_until_the_clinic_turns_it_on(clinic, monkeypatch):
    """Default off, like the discussion mode. A suggestion about what a child
    might have is not a feature that arrives switched on."""
    from app.models import Setting
    from app.utils import ai as ai_utils

    with clinic["app"].app_context():
        Setting.set("ai_enabled", "1")
        Setting.set("ai_provider", "claude")
        Setting.set("ai_api_key", "k")
        Setting.set("ai_model", "m")
        clinic["db"].session.commit()
        assert Setting.get("ai_dx_suggest") is None

    called = []
    monkeypatch.setattr(ai_utils, "chat",
                        lambda *a, **k: called.append(1) or {"ok": True})
    res = _ask(clinic["sign_in"]("doc"), clinic["ids"]["visit"])
    assert res.status_code == 403
    assert res.get_json()["error"] == "dx_suggest_disabled"
    assert called == []


def test_turning_on_the_discussion_does_not_turn_this_on(clinic, monkeypatch):
    """Three switches, three decisions. A clinic that wanted a colleague to
    discuss a case on the patient's screen has not thereby asked for a machine
    opinion inside every consultation."""
    from app.models import Setting
    from app.utils import ai as ai_utils

    with clinic["app"].app_context():
        for key in ("ai_enabled", "ai_patient_context", "ai_discussion"):
            Setting.set(key, "1")
        Setting.set("ai_provider", "claude")
        Setting.set("ai_api_key", "k")
        Setting.set("ai_model", "m")
        clinic["db"].session.commit()

    monkeypatch.setattr(ai_utils, "chat", lambda *a, **k: {"ok": True})
    res = _ask(clinic["sign_in"]("doc"), clinic["ids"]["visit"])
    assert res.status_code == 403


def test_it_needs_a_login(clinic):
    res = _ask(clinic["app"].test_client(), clinic["ids"]["visit"])
    assert res.status_code in (302, 401, 403)


# --------------------------------------------------------------- the screen -
def _screen(clinic):
    return clinic["sign_in"]("doc").get(
        f"/visits/{clinic['ids']['visit']}/record").get_data(as_text=True)


def test_the_button_is_on_the_visit_screen_when_it_is_on(wired):
    page = _screen(wired)
    assert "suggestDx()" in page
    assert f"/ai/visit/{wired['ids']['visit']}/suggest-dx" in page


def test_the_search_box_is_still_there(wired):
    """*"من غير ما نلغي البحث عن التشخيص"* — the whole point. This is beside
    the search, never instead of it."""
    page = _screen(wired)
    assert "askIcd()" in page
    assert 'name="title"' in page


def test_nothing_of_it_shows_when_the_switch_is_off(clinic):
    """The panel is gone and the address is not on the page.

    Not asserted on the Alpine method's name: that is defined unconditionally
    inside the component and returns immediately on an empty URL, which is a
    second lock rather than a leak. What must be absent is the markup a doctor
    can press and the endpoint it would call."""
    page = _screen(clinic)
    assert "suggest-dx" not in page
    assert 'class="dx-ai"' not in page
    assert "dxSuggestUrl" not in page or '"dxSuggestUrl": ""' in page


def test_the_button_cannot_fire_without_an_address(wired):
    """The guard inside the method, checked as text because there is no JS
    engine here. It is what makes the always-defined method harmless."""
    page = _screen(wired)
    body = page[page.index("async suggestDx()"):]
    assert "if (!this.dxs.url" in body[:200]


def test_the_screen_shows_no_raw_translation_keys(wired):
    page = _screen(wired)
    for key in ("ai.dx_suggest", "ai.dx_danger", "ai.dx_no_code",
                "ai.dx_too_thin", "ai.dx_from_ai"):
        assert key not in page, f"untranslated key on the screen: {key}"
