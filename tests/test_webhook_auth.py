"""Proving a webhook came from the provider — for both of them.

These two endpoints are the only doors into the clinic open to the whole
internet, and what comes through them is written onto patients' records: a
message in the inbox, a rating against a doctor's name, a file filed on a
child and tied to the X-ray somebody ordered.

Meta signs its requests; WaPilot v2 publishes no signing secret and is proved
by a long token in the path instead. Both have to fail closed — an endpoint
that accepts anything until it happens to be configured is not a webhook, it
is an open write port onto medical records.
"""
import hashlib
import hmac
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

APP_SECRET = "meta-app-secret-value"
PATH_SECRET = "a-long-enough-webhook-secret-value"

# A real-shaped Meta delivery: one text message from one number.
PAYLOAD = {"entry": [{"changes": [{"value": {"messages": [
    {"from": "201000000001", "type": "text", "text": {"body": "السلام عليكم"}}
]}}]}]}


def _sign(body, secret=APP_SECRET):
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


@pytest.fixture()
def wired():
    """A clinic with inbound switched on and both providers configured."""
    from app import create_app
    from app.extensions import db

    app = create_app("testing")
    with app.app_context():
        db.create_all()
        from app.models import Setting

        Setting.set("wa_inbound_enabled", "1")
        Setting.set("wa_meta_app_secret", APP_SECRET)
        Setting.set("wa_meta_verify_token", "verify-me")
        Setting.set("wa_webhook_secret", PATH_SECRET)
        db.session.commit()
    return {"app": app, "db": db, "client": app.test_client()}


def _messages(wired):
    from app.models import MessageLog

    with wired["app"].app_context():
        return MessageLog.query.filter_by(direction="in").count()


def _post_meta(wired, payload=None, sign_with=APP_SECRET, header=True):
    body = json.dumps(payload if payload is not None else PAYLOAD).encode()
    headers = {"Content-Type": "application/json"}
    if header:
        headers["X-Hub-Signature-256"] = _sign(body, sign_with)
    return wired["client"].post("/wa/webhook/meta", data=body, headers=headers)


# ------------------------------------------------------------------ Meta --
def test_a_properly_signed_message_is_accepted(wired):
    assert _post_meta(wired).status_code == 200
    assert _messages(wired) == 1


def test_an_unsigned_message_is_refused(wired):
    """The whole vulnerability in one test: without this, anyone who knows the
    URL can write into the inbox and onto patients' records."""
    assert _post_meta(wired, header=False).status_code == 403
    assert _messages(wired) == 0


def test_a_message_signed_with_the_wrong_secret_is_refused(wired):
    assert _post_meta(wired, sign_with="not-the-secret").status_code == 403
    assert _messages(wired) == 0


def test_a_signature_from_a_different_body_is_refused(wired):
    """A replayed signature from an earlier delivery must not carry new
    content: the signature covers the bytes, not the sender."""
    other = json.dumps({"entry": []}).encode()
    body = json.dumps(PAYLOAD).encode()
    resp = wired["client"].post(
        "/wa/webhook/meta", data=body,
        headers={"Content-Type": "application/json",
                 "X-Hub-Signature-256": _sign(other)})
    assert resp.status_code == 403
    assert _messages(wired) == 0


def test_one_flipped_character_is_refused(wired):
    body = json.dumps(PAYLOAD).encode()
    good = _sign(body)
    bad = good[:-1] + ("0" if good[-1] != "0" else "1")
    resp = wired["client"].post(
        "/wa/webhook/meta", data=body,
        headers={"Content-Type": "application/json",
                 "X-Hub-Signature-256": bad})
    assert resp.status_code == 403


def test_with_no_app_secret_configured_everything_is_refused(wired):
    """Fail closed. A clinic that hasn't pasted the secret yet accepts
    nothing — rather than accepting everyone."""
    from app.models import Setting

    with wired["app"].app_context():
        Setting.set("wa_meta_app_secret", "")
        wired["db"].session.commit()

    assert _post_meta(wired).status_code == 403
    assert _post_meta(wired, header=False).status_code == 403
    assert _messages(wired) == 0


def test_the_signature_is_checked_before_inbound_is_even_consulted(wired):
    """An unsigned request gets 403 whether inbound is switched on or off:
    a forger learns nothing about how the clinic is configured."""
    from app.models import Setting

    with wired["app"].app_context():
        Setting.set("wa_inbound_enabled", "0")
        wired["db"].session.commit()

    assert _post_meta(wired, header=False).status_code == 403
    assert _post_meta(wired).status_code == 200      # signed, but ignored
    assert _messages(wired) == 0


# ------------------------------------------------------ Meta's handshake --
def test_the_verify_handshake_answers_the_right_token(wired):
    resp = wired["client"].get("/wa/webhook/meta?hub.mode=subscribe"
                               "&hub.verify_token=verify-me&hub.challenge=1234")
    assert resp.status_code == 200
    assert resp.get_data(as_text=True) == "1234"


def test_the_verify_handshake_refuses_the_wrong_token(wired):
    resp = wired["client"].get("/wa/webhook/meta?hub.mode=subscribe"
                               "&hub.verify_token=wrong&hub.challenge=1234")
    assert resp.status_code == 403


def test_the_verify_handshake_never_leaks_the_challenge_unconfigured(wired):
    from app.models import Setting

    with wired["app"].app_context():
        Setting.set("wa_meta_verify_token", "")
        wired["db"].session.commit()
    resp = wired["client"].get("/wa/webhook/meta?hub.mode=subscribe"
                               "&hub.challenge=1234")
    assert resp.status_code == 403


# --------------------------------------------------------------- WaPilot --
def test_the_right_path_token_is_accepted(wired):
    resp = wired["client"].post(f"/wa/webhook/wapilot/{PATH_SECRET}",
                                json={"message": {"from": "201000000001",
                                                  "text": "أهلاً"}})
    assert resp.status_code == 200
    assert _messages(wired) == 1


def test_a_wrong_path_token_is_refused(wired):
    resp = wired["client"].post("/wa/webhook/wapilot/not-the-secret",
                                json={"message": {"from": "201000000001",
                                                  "text": "أهلاً"}})
    assert resp.status_code == 403
    assert _messages(wired) == 0


def test_an_almost_right_path_token_is_refused(wired):
    resp = wired["client"].post(f"/wa/webhook/wapilot/{PATH_SECRET[:-1]}x",
                                json={"message": {"from": "2010", "text": "x"}})
    assert resp.status_code == 403


def test_with_no_path_token_configured_everything_is_refused(wired):
    from app.models import Setting

    with wired["app"].app_context():
        Setting.set("wa_webhook_secret", "")
        wired["db"].session.commit()
    assert wired["client"].post("/wa/webhook/wapilot/anything",
                                json={}).status_code == 403


def test_a_token_too_short_to_be_a_secret_is_refused(wired):
    """Somebody typed "clinic123" into the box. Matching it exactly still
    isn't proof of anything — it is guessable in an afternoon."""
    from app.models import Setting

    with wired["app"].app_context():
        Setting.set("wa_webhook_secret", "clinic123")
        wired["db"].session.commit()
    assert wired["client"].post("/wa/webhook/wapilot/clinic123",
                                json={}).status_code == 403


# ------------------------------------------------------- the pure checks --
def test_the_comparisons_refuse_empty_everything():
    """Every "not configured" path says no, on both providers."""
    from app.utils.webhook_auth import (meta_signature_ok, path_secret_ok,
                                        verify_token_ok)

    assert meta_signature_ok(b"{}", None, APP_SECRET) is False
    assert meta_signature_ok(b"{}", _sign(b"{}"), "") is False
    assert meta_signature_ok(None, _sign(b"{}"), APP_SECRET) is False
    assert path_secret_ok("", PATH_SECRET) is False
    assert path_secret_ok(PATH_SECRET, "") is False
    assert verify_token_ok("", "x") is False
    assert verify_token_ok("x", "") is False


def test_a_signature_with_surrounding_whitespace_still_matches():
    """Proxies trim and pad header values; that is not an attack."""
    from app.utils.webhook_auth import meta_signature_ok

    assert meta_signature_ok(b"{}", "  " + _sign(b"{}") + " ", APP_SECRET) is True
