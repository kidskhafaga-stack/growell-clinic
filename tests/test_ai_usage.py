"""What the assistant costs, and the number this deliberately does not show.

The clinic asked for "the remaining tokens and the usage". Half of that is
possible and half of it is not, and the honest half is the one that got built.

**Remaining is not knowable.** No provider — Anthropic, OpenAI, Google — tells
a chat request how much quota is left on the key. That figure lives in the
vendor's billing console, moves on their schedule, and depends on a plan the
program has never been told about. A screen that guessed would be wrong in the
direction that hurts: a clinic that reads "plenty left" and stops in the middle
of a consultation. So the screen says what was spent, and links to the vendor
for what it cannot know. There is a test below whose entire job is to keep it
that way.

**Usage is knowable exactly, and was being discarded.** All three request
shapes already report their token counts in the reply the program parses
anyway — ``usage`` for OpenAI and Anthropic, ``usageMetadata`` for Gemini.
Nothing extra is sent to anybody to collect it.

It is recorded per *feature* because that is the only shape anybody can act on.
"The month cost 400,000 tokens" tells a clinic nothing. "Visit summaries are
three quarters of it" tells them what to switch off.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


class _Reply:
    """Stands in for a provider, answering in that provider's own shape."""

    ok = True

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class _Requests:
    """A ``requests`` stand-in carrying the real exception classes.

    ``chat`` catches ``requests.exceptions.RequestException``, so a bare mock
    without them would turn a genuine bug into a passing test.
    """

    def __init__(self, payload):
        import requests as real

        self.exceptions = real.exceptions
        self._payload = payload

    def post(self, *args, **kwargs):
        return _Reply(self._payload)


@pytest.fixture()
def ai_app(clinic):
    """The fixture clinic with a provider configured but never called."""
    with clinic["app"].app_context():
        from app.models import Setting
        for key, value in (("ai_enabled", "1"), ("ai_provider", "openai"),
                           ("ai_api_key", "sk-test"), ("ai_model", "gpt-4o-mini")):
            Setting.set(key, value)
        clinic["db"].session.commit()
    return clinic


OPENAI = {"choices": [{"message": {"content": "ok"}}],
          "usage": {"prompt_tokens": 1200, "completion_tokens": 340}}
ANTHROPIC = {"content": [{"type": "text", "text": "ok"}],
             "usage": {"input_tokens": 900, "output_tokens": 110}}
GEMINI = {"candidates": [{"content": {"parts": [{"text": "ok"}]}}],
          "usageMetadata": {"promptTokenCount": 500, "candidatesTokenCount": 60}}


@pytest.mark.parametrize("shape,payload,prompt,completion", [
    ("_chat_openai", OPENAI, 1200, 340),
    ("_chat_anthropic", ANTHROPIC, 900, 110),
    ("_chat_gemini", GEMINI, 500, 60),
])
def test_every_provider_reports_its_own_tokens(ai_app, shape, payload,
                                               prompt, completion):
    """Three vendors, three different field names, one shared answer.

    Parametrised rather than written once against OpenAI because the three
    shapes spell it differently — ``prompt_tokens``, ``input_tokens``,
    ``promptTokenCount`` — and a single test would leave two of them free to
    silently return nothing.
    """
    with ai_app["app"].app_context():
        from app.utils import ai
        cfg = ai.get_config()
        result = getattr(ai, shape)(_Requests(payload), cfg,
                                    [{"role": "user", "content": "hi"}], None)
        assert result["ok"]
        assert result["usage"] == {"prompt": prompt, "completion": completion}


def _spend(ai_app, feature, times=1, payload=None):
    """Run ``chat`` against a stubbed provider and let the metering happen."""
    with ai_app["app"].app_context():
        from app.utils import ai
        original = ai._chat_openai

        def patched(requests, cfg, messages, system_prompt):
            return original(_Requests(payload or OPENAI), cfg, messages,
                            system_prompt)

        ai._chat_openai = patched
        try:
            for _ in range(times):
                result = ai.chat([{"role": "user", "content": "hi"}],
                                 feature=feature)
        finally:
            ai._chat_openai = original
        return result


def test_the_bill_is_broken_down_by_what_spent_it(ai_app):
    """The whole reason the table exists.

    A clinic can act on "visit summaries are most of it". It can do nothing
    with a single monthly total, which is all the vendor's own console shows.
    """
    _spend(ai_app, "visit_summary", times=6)
    _spend(ai_app, "chat", times=2)

    with ai_app["app"].app_context():
        from app.utils import ai
        summary = ai.usage_summary()
        assert summary["calls"] == 8
        assert summary["total"] == 8 * (1200 + 340)
        # Biggest spender first: a table sorted by anything else buries the
        # row somebody opened the screen to find.
        assert [row["feature"] for row in summary["features"]] == [
            "visit_summary", "chat"]
        assert summary["features"][0]["calls"] == 6


def test_a_feature_nobody_labelled_is_still_counted(ai_app):
    """Metering must not depend on remembering to meter.

    It is done inside ``chat``, which every AI call already passes through, so
    a feature added next year appears in the total whether or not its author
    thought about billing. Unlabelled it lands under "chat" rather than
    vanishing.
    """
    _spend(ai_app, None)
    with ai_app["app"].app_context():
        from app.utils import ai
        assert ai.usage_summary()["features"][0]["feature"] == "chat"


def test_a_failed_call_is_not_billed(ai_app):
    """A provider that refused us charged us nothing, and the table says so."""
    with ai_app["app"].app_context():
        from app.utils import ai
        original = ai._chat_openai

        class _Refused:
            ok = False
            status_code = 401
            text = "bad key"

            def json(self):
                return {}

        class _Bad(_Requests):
            def post(self, *args, **kwargs):
                return _Refused()

        def patched(requests, cfg, messages, system_prompt):
            return original(_Bad(OPENAI), cfg, messages, system_prompt)

        ai._chat_openai = patched
        try:
            result = ai.chat([{"role": "user", "content": "hi"}],
                             feature="chat")
        finally:
            ai._chat_openai = original
        assert not result["ok"]
        assert ai.usage_summary()["calls"] == 0


def test_a_reply_that_failed_but_carried_a_count_is_still_not_billed(ai_app):
    """The guard the route above cannot reach, tested where it lives.

    Today an unsuccessful ``chat`` returns no ``usage`` at all, so the failure
    test above passes with or without the ``ok`` check — measured, by deleting
    the check and watching it stay green. That makes the check defensive code
    for a provider shape that does not exist yet: one that reports a token
    count alongside a refusal (a content filter that charges for the prompt it
    read is the obvious candidate).

    Defensive code with no test is how a guard gets deleted in a tidy-up. This
    calls the recorder directly with exactly that shape, so the check is a
    live rule rather than a line nobody dares touch.
    """
    with ai_app["app"].app_context():
        from app.utils import ai
        ai._record_usage(ai.get_config(),
                         {"ok": False, "error": "content_filter",
                          "usage": {"prompt": 900, "completion": 0}},
                         "chat")
        assert ai.usage_summary()["calls"] == 0


def test_metering_never_costs_the_doctor_their_answer(ai_app):
    """A reporting table is not a reason to lose a clinical reply.

    If the write fails — a locked database, a migration half-applied — the
    answer the provider already gave still reaches the doctor. The clinic is
    then short one row in a report, which is the right way round.
    """
    with ai_app["app"].app_context():
        from app.utils import ai
        original = ai._chat_openai

        def patched(requests, cfg, messages, system_prompt):
            return original(_Requests(OPENAI), cfg, messages, system_prompt)

        def explode(*args, **kwargs):
            raise RuntimeError("database is locked")

        # Break the write itself rather than the metering function, so the
        # guard inside it is the thing under test.
        from app.extensions import db
        ai._chat_openai = patched
        real_add = db.session.add
        db.session.add = explode
        try:
            result = ai.chat([{"role": "user", "content": "hi"}],
                             feature="chat")
        finally:
            db.session.add = real_add
            ai._chat_openai = original

        assert result["ok"] is True
        assert result["text"] == "ok"
        assert ai.usage_summary()["calls"] == 0


def test_the_screen_never_claims_to_know_the_remaining_balance(ai_app):
    """The guard on the one thing that would be a lie.

    Every provider's chat response is silent about quota. If a "remaining"
    figure ever appears on this screen it will have been inferred, and a clinic
    that trusts it will find out it was wrong at the worst moment. The screen
    instead states that it cannot know, and links to the place that does.
    """
    _spend(ai_app, "chat")
    page = ai_app["sign_in"]("boss").get("/ai/")
    body = page.get_data(as_text=True)
    assert page.status_code == 200
    assert "الاستخدام" in body
    # It says, in words, that the balance is not something it can see.
    assert "المزوّد مش بيقول كام باقي في الرصيد" in body
    assert "platform.openai.com/api-keys" in body


def test_the_usage_panel_stays_away_until_there_is_something_to_show(ai_app):
    """An empty table teaches people to ignore the screen it is on."""
    body = ai_app["sign_in"]("boss").get("/ai/").get_data(as_text=True)
    assert "الاستخدام" not in body


def test_no_prompt_or_reply_is_kept(ai_app):
    """Metering stores counts, never content.

    What a doctor asked belongs in the visit record. A second copy of clinical
    text in a billing table is a second place to leak it from, and it would be
    the copy nobody remembers is there.
    """
    _spend(ai_app, "patient_chat")
    with ai_app["app"].app_context():
        from app.models import AiUsage
        columns = {column.name for column in AiUsage.__table__.columns}
        assert not columns & {"prompt", "reply", "text", "content", "messages",
                              "patient_id"}
