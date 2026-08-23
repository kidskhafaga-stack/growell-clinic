"""Groq and GitHub Models, and the word "Copilot" not being used for either.

Asked for after Google answered with *"Your prepayment credits are depleted"*
— which the assistant screen now renders as a sentence rather than as raw
JSON, but a sentence about being out of credit is still a clinic with no
assistant. Two more places to get a key, both free to create, neither
requiring a card.

**Neither needed any code.** Both speak the OpenAI request shape, so each is a
dict entry in `AI_PROVIDERS` and nothing else — the settings screen builds its
menu, its model suggestions and its "free key" badges from that table. That is
the design working, and it is also the thing to be careful about: a provider
this cheap to add is a provider nobody looks at twice. So the entries are
tested rather than trusted.

**On "Copilot", which is what was actually asked for.** The Copilot in an
editor and the Copilot at copilot.microsoft.com have no API a program like
this may call. What Microsoft publishes for programs is GitHub Models: the
same model families, an OpenAI-shaped endpoint, a GitHub personal access token
for a key. So that is what the entry is, and the label says so. Offering
"Copilot" in a settings menu and quietly meaning something else is a small lie
that costs somebody an afternoon when their token does not work.

**What these tests do not check** is that the endpoints answer. They cannot:
there is no key here, and firing requests at somebody else's API from a test
suite is not a test, it is traffic. A URL that has moved is caught by the
"test connection" button on the settings screen, which exists precisely
because a saved setting that has never been tried is a guess.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

NEW = ("groq", "github")


@pytest.mark.parametrize("pid", NEW)
def test_the_provider_is_offered_at_all(pid):
    from app.utils.ai import AI_PROVIDERS

    assert pid in AI_PROVIDERS, f"{pid} is not in the provider table"


@pytest.mark.parametrize("pid", NEW)
def test_it_needs_no_code_of_its_own(pid):
    """Both speak the OpenAI shape. An entry claiming a dialect the sender
    does not implement would fail at the first message rather than here."""
    from app.utils.ai import AI_PROVIDERS

    dialects = {meta["api"] for meta in AI_PROVIDERS.values()}
    meta = AI_PROVIDERS[pid]

    assert meta["api"] == "openai", \
        f"{pid} claims the {meta['api']!r} dialect — is there code for it?"
    assert meta["api"] in dialects, "a dialect nothing else in the table speaks"


@pytest.mark.parametrize("pid", NEW)
def test_it_is_reachable_over_https_and_names_a_real_host(pid):
    """Not a connection test — a shape test.

    A base URL that is blank, or http, or missing its path is a setting that
    fails on a clinic machine long after anybody remembers adding it. WHO's
    own sample code turns TLS verification off; nothing here follows it.
    """
    from urllib.parse import urlparse

    from app.utils.ai import AI_PROVIDERS

    url = urlparse(AI_PROVIDERS[pid]["base_url"])
    assert url.scheme == "https", \
        f"{pid} would send the clinic's prompts in clear text: {url.geturl()}"
    assert url.netloc, f"{pid} has no host"
    assert url.path not in ("", "/"), \
        f"{pid} has a host and no endpoint path: {url.geturl()}"


@pytest.mark.parametrize("pid", NEW)
def test_a_clinic_is_told_where_to_get_the_key(pid):
    """The badge that says "free" is only useful next to a link that says
    where. Both of these are free to create and neither is discoverable by
    guessing."""
    from urllib.parse import urlparse

    from app.utils.ai import AI_PROVIDERS

    meta = AI_PROVIDERS[pid]
    assert meta["keys_url"], f"{pid} says nothing about where a key comes from"
    assert urlparse(meta["keys_url"]).scheme == "https"


@pytest.mark.parametrize("pid", NEW)
def test_the_default_model_is_one_of_the_suggestions(pid):
    """Otherwise the screen opens on a model that is not in its own menu, and
    the first thing a clinic does is change a setting it did not choose."""
    from app.utils.ai import AI_PROVIDERS

    meta = AI_PROVIDERS[pid]
    assert meta["default_model"], f"{pid} opens with no model at all"
    assert meta["default_model"] in meta["models"], \
        (f"{pid} defaults to {meta['default_model']!r}, which is not among "
         f"{meta['models']}")


@pytest.mark.parametrize("pid", NEW)
def test_both_keys_cost_nothing_and_say_so(pid):
    """The flag is a fact about the *key* — free to create, no card — and not
    a promise about a quota. Quotas move; this does not claim one."""
    from app.utils.ai import free_providers

    assert pid in free_providers()


def test_github_models_ids_carry_their_publisher():
    """`openai/gpt-4o-mini`, not `gpt-4o-mini`. That prefix is this endpoint's
    own convention, and a suggestion list that dropped it would hand every
    clinic a model id the endpoint rejects."""
    from app.utils.ai import AI_PROVIDERS

    meta = AI_PROVIDERS["github"]
    unprefixed = [m for m in meta["models"] if "/" not in m]
    assert not unprefixed, \
        f"GitHub Models ids need a publisher prefix; these have none: {unprefixed}"


def test_the_menu_does_not_call_it_copilot():
    """The label a doctor reads has to match the page they will land on.

    Neither Copilot has a callable API. Naming this entry after the product
    somebody asked for, when it is a different product with a different key
    from a different settings page, is the kind of small lie that is only
    discovered by the person whose token does not work.
    """
    from app.utils.ai import AI_PROVIDERS

    for pid, meta in AI_PROVIDERS.items():
        label = meta["label"]
        if "copilot" in label.lower():
            assert pid == "github" and "GitHub Models" in label, \
                (f"{pid} is labelled {label!r} — if it says Copilot it has to "
                 f"say what it actually is first")


def test_the_screen_offers_them_without_being_told_to(clinic):
    """The provider table drives the settings menu, so a new entry needs no
    template change — which is exactly why it is worth checking that it
    really does reach the page."""
    from markupsafe import escape

    from app.utils.ai import AI_PROVIDERS

    page = clinic["sign_in"]("boss").get("/settings/").get_data(as_text=True)

    for pid in NEW:
        assert f'value="{pid}"' in page, \
            f"{pid} is in the table and not on the settings screen"
        # Compared escaped, because that is what the template does to a label.
        # The first draft compared the raw string and failed on an apostrophe
        # — a real failure about nothing a doctor would ever notice.
        assert str(escape(AI_PROVIDERS[pid]["label"])) in page, \
            f"{pid} is on the screen with no label a doctor can read"
