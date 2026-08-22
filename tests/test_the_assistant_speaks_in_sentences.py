"""What the assistant says when it cannot answer.

A clinic whose account had run out of credit was shown this, in the middle of
a right-to-left Arabic screen:

    HTTP 429: {"error": {"message": "You exceeded your current quota, please
    check your plan and billing details", "type": "insufficient_quota",
    "param": null, "code": "insufficient_quota"}}

Every part of that is wrong for the person reading it. It is a JSON object. It
is in English. It quotes a vendor's internal field names. And the one fact
inside it that the clinic could have acted on — *the key is fine, the account
needs topping up* — is buried in a sentence nobody was going to read.

Worse, it is indistinguishable on screen from the other thing HTTP 429 means:
too many requests in the last minute, which fixes itself while you wait. One
of those is "try again in a moment" and the other is "somebody has to open the
provider's billing page", and a clinic told the wrong one loses a week.

So the provider's words go to the program log, where somebody debugging wants
them, and what reaches a screen is a sentence naming what to do. The tests
here hold three things: that the status becomes the right sentence, that no
failure this module can produce is missing one, and that no screen goes back
to printing the raw string.
"""
import ast
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
AI_SOURCE = os.path.join(HERE, "..", "app", "utils", "ai.py")


class _Response:
    def __init__(self, status_code, text=""):
        self.status_code = status_code
        self.text = text


# ------------------------------------------------------- what a status means

@pytest.mark.parametrize("status,body,expected", [
    (401, "", "err_key"),
    (403, "", "err_key"),
    (404, "no such model", "err_model"),
    (400, "", "err_request"),
    (413, "", "err_too_long"),
    (500, "", "err_provider"),
    (503, "", "err_provider"),
    (418, "", "err_http"),
])
def test_each_refusal_becomes_the_key_for_its_own_sentence(
        clinic, status, body, expected):
    from app.utils.ai import _http_error

    with clinic["app"].app_context():
        assert _http_error(_Response(status, body)) == expected


def test_too_many_requests_and_out_of_credit_are_told_apart(clinic):
    """The distinction the whole thing exists for. Both are HTTP 429."""
    from app.utils.ai import _http_error

    ran_out = json.dumps({"error": {
        "message": "You exceeded your current quota, please check your plan "
                   "and billing details",
        "type": "insufficient_quota"}})
    too_fast = json.dumps({"error": {
        "message": "Rate limit reached for requests", "type": "rate_limit"}})

    with clinic["app"].app_context():
        assert _http_error(_Response(429, ran_out)) == "err_quota"
        assert _http_error(_Response(429, too_fast)) == "err_rate"


def test_the_provider_s_own_words_never_reach_the_answer(clinic):
    from app.utils.ai import _http_error, error_sentence

    body = json.dumps({"error": {
        "message": "You exceeded your current quota", "param": None,
        "code": "insufficient_quota"}})
    with clinic["app"].app_context():
        key = _http_error(_Response(429, body))
        sentence = error_sentence(key)

    for leak in ("insufficient_quota", "HTTP 429", '"error"', "param"):
        assert leak not in sentence, \
            f"the vendor's own text is still on the screen: {sentence!r}"
    assert sentence != key, "the key was shown instead of a sentence"


# ---------------------------------------------- and none of them is missing

def _errors_this_module_can_return():
    """Every literal handed back as ``{"ok": False, "error": ...}`` in ai.py.

    Read with `ast` rather than by searching the text, because the text
    includes this module's own documentation of the strings — and a test that
    matches its own explanation of a bug is a test that passes after the bug
    comes back.
    """
    with open(AI_SOURCE, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    found = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        keys = [k.value for k in node.keys
                if isinstance(k, ast.Constant) and isinstance(k.value, str)]
        if "ok" not in keys or "error" not in keys:
            continue
        value = node.values[keys.index("error")]
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            found.add(value.value)
    return found


def test_every_failure_it_can_report_has_a_sentence(clinic):
    from app.utils.ai import ERROR_KEYS

    produced = _errors_this_module_can_return()
    assert produced, "the reader found no failures at all — it has drifted"

    missing = sorted(produced - set(ERROR_KEYS))
    assert not missing, \
        f"these failures would reach a clinic as bare identifiers: {missing}"


def test_every_sentence_exists_in_both_languages(clinic):
    from app.utils.ai import ERROR_KEYS

    for lang in ("ar", "en"):
        with open(os.path.join(HERE, "..", "app/i18n/locales", f"{lang}.json"),
                  encoding="utf-8") as fh:
            block = json.load(fh)
        for key in set(ERROR_KEYS.values()):
            section, leaf = key.split(".", 1)
            assert leaf in block[section], f"{lang} is missing {key}"


def test_anything_unrecognised_is_still_a_sentence(clinic):
    """A string that reaches here unlisted is a bug in the module, and the
    person in front of the screen is not the one who can fix it."""
    from app.utils.ai import error_sentence

    with clinic["app"].app_context():
        said = error_sentence("something nobody wrote a wording for")

    assert said and "something nobody wrote" not in said


# ---------------------------------------------------- and no screen prints it

SCREENS = [
    "app/templates/ai/index.html",
    "app/templates/patients/profile.html",
    "app/templates/prescriptions/new.html",
    "app/templates/settings/index.html",
    "app/templates/visits/record.html",
]


@pytest.mark.parametrize("path", SCREENS)
def test_no_screen_builds_its_own_sentence_out_of_the_raw_error(clinic, path):
    """`data.error` is the machine-readable key and belongs in a branch, not
    in a string a person reads. Every one of these screens used to concatenate
    it into the message, and every one of them printed the provider's JSON."""
    with open(os.path.join(HERE, "..", path), encoding="utf-8") as fh:
        source = fh.read()

    # Concatenating the error into a message — the exact shape that leaked.
    for bad in ("+ (data.error", "+(data.error", "+ (d.error", "+(d.error",
                "' + (data.error", "+ ' ' + (data.error"):
        assert bad not in source, \
            f"{path} is putting the raw error into a sentence again ({bad})"
