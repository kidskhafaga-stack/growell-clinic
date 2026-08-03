"""Letting a clinic try the assistant before it buys anything.

The plan parked this as a product decision, and the three questions it raised
were the right ones: whose key, where the patient data goes, and how you count
three days on a clock anybody can change.

**Every one of them dissolves if the clinic brings its own free key.** There is
no shared account to meter, no per-clinic budget to police, no trial window to
enforce, and nobody else's patients on the same quota. What was left was not a
service to build but two things missing from a screen that already worked:

* nothing said **which providers cost nothing**, so a clinic setting this up
  alone had no reason to pick Gemini over the one with a credit card form;
* and there was **no way to find out whether it worked**. You saved, and found
  out when a doctor pressed "suggest a dose" mid-consultation and nothing
  happened — with no way to tell a wrong key from a wrong model from a
  firewall. That is the difference between software somebody else can install
  and software that needs you on the phone.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def boss(clinic):
    return clinic["sign_in"]("boss")


# =================================================== which ones cost nothing ==
def test_gemini_is_offered_as_the_free_one(clinic):
    from app.utils.ai import free_providers

    assert "gemini" in free_providers()


def test_the_local_ones_count_as_free_too(clinic):
    """They run on the clinic's own machine — no key, no bill, no data
    leaving the building."""
    from app.utils.ai import free_providers

    assert {"ollama", "lmstudio"} <= set(free_providers())


def test_a_paid_provider_is_not_marked_free(clinic):
    """A badge that is on everything says nothing."""
    from app.utils.ai import free_providers

    assert "openai" not in free_providers()
    assert "claude" not in free_providers()


def test_nothing_quotes_a_quota(clinic):
    """Free tiers move. A screen that promises "60 requests a minute" is a
    screen that is wrong later and blamed for it — so the claim is about the
    *key* being free, and stops there."""
    import json

    root = os.path.join(os.path.dirname(__file__), "..")
    for lang in ("ar", "en"):
        with open(os.path.join(root, "app", "i18n", "locales", f"{lang}.json"),
                  encoding="utf-8") as fh:
            section = json.load(fh)["settings"]
        blob = " ".join(str(section.get(k, "")) for k in section
                        if k.startswith("ai_free"))
        for forbidden in ("requests per", "/min", "في الدقيقة", "طلب في"):
            assert forbidden not in blob, forbidden


# ================================================= the one-button trial setup ==
def test_the_trial_setup_is_complete_except_the_key(clinic):
    """The clinic supplies the one thing only it can."""
    from app.utils.ai import trial_defaults

    setup = trial_defaults()
    assert setup["provider"] == "gemini"
    assert setup["model"] and setup["base_url"] and setup["keys_url"]


def test_the_screen_offers_it(boss, clinic):
    body = boss.get("/settings/").get_data(as_text=True)
    with clinic["app"].test_request_context("/"):
        from app.i18n import t
        assert t("settings.ai_free_use") in body
    assert "aistudio.google.com" in body


# ============================================================== does it work? ==
def test_the_test_button_is_on_the_screen(boss, clinic):
    body = boss.get("/settings/").get_data(as_text=True)
    assert "/settings/ai/test" in body


def test_testing_an_unconfigured_assistant_says_so_rather_than_crashing(clinic):
    from app.utils.ai import test_connection

    out = test_connection({"provider": "gemini", "provider_label": "G",
                           "base_url": "", "model": "", "api_key": "",
                           "local": False})
    assert out["ok"] is False and out["error"] == "not_configured"


def test_a_cloud_provider_with_no_key_is_named_as_the_problem(clinic):
    """"It does not work" is not an answer somebody can act on."""
    from app.utils.ai import test_connection

    out = test_connection({"provider": "gemini", "provider_label": "G",
                           "base_url": "https://x/", "model": "m",
                           "api_key": "", "local": False})
    assert out["ok"] is False and out["error"] == "no_key"


def test_a_local_provider_needs_no_key(clinic):
    """Ollama runs on the clinic machine. Demanding a key would refuse to test
    the one setup that cannot have one."""
    from app.utils.ai import test_connection

    out = test_connection({"provider": "ollama", "provider_label": "O",
                           "base_url": "http://127.0.0.1:1/v1/chat/completions",
                           "model": "llama3.1", "api_key": "", "local": True})
    # It will fail to connect — but on the network, not on a missing key.
    assert out["ok"] is False and out["error"] != "no_key"


def test_testing_works_before_the_assistant_is_switched_on(clinic):
    """Testing first and enabling second is the order people work in. A test
    that refused while disabled would be useless exactly when it is wanted."""
    from app.utils.ai import test_connection

    out = test_connection({"provider": "ollama", "provider_label": "O",
                           "base_url": "http://127.0.0.1:1/v1/chat/completions",
                           "model": "llama3.1", "api_key": "", "local": True,
                           "enabled": False, "system_prompt": ""})
    assert out["error"] != "disabled"


def test_the_route_reports_the_failure_to_the_user(boss, clinic):
    """The reason has to reach the screen; a silent redirect is what this
    replaces."""
    reply = boss.post("/settings/ai/test", data={
        "ai_provider": "ollama", "ai_model": "llama3.1",
        "ai_base_url": "http://127.0.0.1:1/v1/chat/completions"},
        follow_redirects=True)
    body = reply.get_data(as_text=True)
    with clinic["app"].test_request_context("/"):
        from app.i18n import t
        assert t("settings.ai_test_failed").split("{")[0].strip() in body


def test_only_an_admin_can_test(clinic):
    """It spends a request on the clinic's key and prints back what the
    provider said."""
    desk = clinic["sign_in"]("desk")
    assert desk.post("/settings/ai/test", data={}).status_code in (302, 403)


def test_an_empty_key_box_means_keep_the_saved_one(boss, clinic):
    """The field renders blank on a saved password. Reading that as "no key"
    would report a working setup as broken every time somebody tested it."""
    from app.models import Setting

    with clinic["app"].app_context():
        Setting.set("ai_provider", "gemini")
        Setting.set("ai_api_key", "saved-key-value")
        clinic["db"].session.commit()

    reply = boss.post("/settings/ai/test", data={
        "ai_provider": "gemini", "ai_model": "gemini-2.5-flash",
        "ai_api_key": ""}, follow_redirects=True)
    body = reply.get_data(as_text=True)
    with clinic["app"].test_request_context("/"):
        from app.i18n import t
        # Whatever the network did, it must not have stopped at "no key".
        assert t("settings.ai_test_failed").replace("{e}", "no_key") not in body


def test_both_languages_carry_the_words(clinic):
    import json

    root = os.path.join(os.path.dirname(__file__), "..")
    for lang in ("ar", "en"):
        with open(os.path.join(root, "app", "i18n", "locales", f"{lang}.json"),
                  encoding="utf-8") as fh:
            data = json.load(fh)
        for key in ("ai_free_title", "ai_free_hint", "ai_free_use",
                    "ai_free_key", "ai_free_badge", "ai_test",
                    "ai_test_hint", "ai_test_ok", "ai_test_failed"):
            assert data["settings"].get(key), f"{lang}.settings.{key}"


# ================================== and the list that ages, asked of the key ==
def test_the_models_come_from_the_key_not_from_this_program(clinic):
    """The bug this fixes was real and immediate: a clinic pressed "use the
    free setup", pasted a brand-new key, and got back *"this model is no
    longer available to new users"*. The id was right when it was written and
    wrong by the time somebody installed the program — and vendors retire
    models on their own schedule, so no shipped list survives contact."""
    import app.utils.ai as ai

    class _Reply:
        ok = True

        @staticmethod
        def json():
            return {"models": [{"name": "models/gemini-flash-latest",
                                "supportedGenerationMethods": ["generateContent"]}]}

    class _Requests:
        @staticmethod
        def get(*a, **k):
            return _Reply()

    out = ai._models_gemini(_Requests, {"base_url": "https://x/models",
                                        "api_key": "k"})
    assert out["ok"] and out["models"] == ["gemini-flash-latest"]
    # And the shipped suggestion is not what the screen ends up trusting.
    assert "gemini-flash-latest" not in ai.AI_PROVIDERS["gemini"]["models"]


def test_an_embedding_model_is_not_offered_as_an_assistant(clinic):
    """The same endpoint lists embedding models. Offering one as the clinic's
    assistant is a support call nobody can diagnose from the screen."""
    import app.utils.ai as ai

    class _Reply:
        ok = True

        @staticmethod
        def json():
            return {"models": [
                {"name": "models/chatty", "supportedGenerationMethods": ["generateContent"]},
                {"name": "models/embedder", "supportedGenerationMethods": ["embedContent"]},
            ]}

    class _Requests:
        @staticmethod
        def get(*a, **k):
            return _Reply()

    out = ai._models_gemini(_Requests, {"base_url": "https://x/models",
                                        "api_key": "k"})
    assert out["models"] == ["chatty"]


def test_the_listing_url_is_derived_from_the_chat_url(clinic):
    """One setting stays one setting: a self-hosted or custom endpoint must
    not need a second URL box to fill in wrongly."""
    from app.utils.ai import _sibling_url

    assert _sibling_url("https://h/v1/chat/completions", "models") == "https://h/v1/models"
    assert _sibling_url("https://api.anthropic.com/v1/messages", "models") \
        == "https://api.anthropic.com/v1/models"
    assert _sibling_url("http://localhost:11434/v1", "models") \
        == "http://localhost:11434/v1/models"


def test_listing_without_a_key_says_which_thing_is_missing(clinic):
    from app.utils.ai import list_models

    assert list_models({"provider": "gemini", "base_url": "", "api_key": "",
                        "local": False})["error"] == "not_configured"
    assert list_models({"provider": "gemini", "base_url": "https://x/",
                        "api_key": "", "local": False})["error"] == "no_key"


def test_the_route_answers_with_json(boss, clinic):
    reply = boss.post("/settings/ai/models", data={
        "ai_provider": "ollama", "ai_base_url": "http://127.0.0.1:1/v1/chat/completions"})
    assert reply.status_code == 200
    assert reply.get_json()["ok"] is False       # nothing listening — but JSON


def test_only_an_admin_can_list_models(clinic):
    desk = clinic["sign_in"]("desk")
    assert desk.post("/settings/ai/models", data={}).status_code in (302, 403)


def test_the_screen_offers_the_fetch_button(boss, clinic):
    body = boss.get("/settings/").get_data(as_text=True)
    assert "/settings/ai/models" in body
    with clinic["app"].test_request_context("/"):
        from app.i18n import t
        assert t("settings.ai_fetch_models") in body
