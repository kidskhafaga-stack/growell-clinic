"""The WaPilot payloads and uploads, checked against WaPilot's own contract.

Everything here was written from a guess. The inbound normalizer, the upload
field, the tests themselves — all of it was built before anybody had seen a
real WaPilot request, and the one test that sent a body sent *our* invented
shape, so it proved the code understood itself rather than the provider. Then
the API v2 documentation arrived and settled three things:

* the ``message`` envelope is shaped as this program assumed — that guess held;
* there is a **second** public event, ``message.any``, which wraps the message
  under ``payload`` instead, and reading only the first meant answering 200 to
  a parent and filing nothing;
* the image upload field is ``media``. It was ``image``, which is the one name
  the endpoint rejects — *"The media field is required."* — so every picture
  ever sent through WaPilot came back 422.

These tests are pinned to that contract, and to the behaviour around it: what
the program does with an envelope it cannot read, and with the same message
delivered twice.
"""
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

PATH_SECRET = "a-long-enough-webhook-secret-value"

# WaPilot API v2 → Webhooks → "message event", copied from the documented
# payload example rather than composed here.
MESSAGE_EVENT = {
    "event": "message",
    "instance_id": "INSTANCE_ID",
    "message": {"id": "MESSAGE_ID", "chat_id": "201001234567",
                "text": "Hello"},
}

# The same page, "message.any event". The message rides under `payload`.
ANY_EVENT = {
    "event": "message.any",
    "instance_id": "INSTANCE_ID",
    "payload": {"id": "MESSAGE_ID_2", "chat_id": "201001234567",
                "text": "تمام يا دكتور"},
}


@pytest.fixture()
def wired():
    """A clinic with inbound switched on and the path secret set."""
    from app import create_app
    from app.extensions import db

    app = create_app("testing")
    with app.app_context():
        db.create_all()
        from app.models import Setting

        Setting.set("wa_inbound_enabled", "1")
        Setting.set("wa_webhook_secret", PATH_SECRET)
        db.session.commit()
    return {"app": app, "db": db, "client": app.test_client()}


def _post(wired, payload):
    return wired["client"].post(f"/wa/webhook/wapilot/{PATH_SECRET}",
                                json=payload)


def _inbound(wired):
    from app.models import MessageLog

    with wired["app"].app_context():
        return MessageLog.query.filter_by(direction="in").all()


# ------------------------------------------------------- the two envelopes --
def test_the_documented_message_event_is_read():
    from app.utils.inbound import normalize_wapilot

    items = normalize_wapilot(MESSAGE_EVENT)
    assert len(items) == 1
    assert items[0]["from_phone"] == "201001234567"
    assert items[0]["text"] == "Hello"
    assert items[0]["msg_id"] == "MESSAGE_ID"


def test_the_broader_stream_is_read_too():
    """``message.any`` wraps it under a different key, and used to vanish."""
    from app.utils.inbound import normalize_wapilot

    items = normalize_wapilot(ANY_EVENT)
    assert len(items) == 1
    assert items[0]["from_phone"] == "201001234567"
    assert items[0]["text"] == "تمام يا دكتور"


@pytest.mark.parametrize("payload", [MESSAGE_EVENT, ANY_EVENT])
def test_either_event_reaches_the_inbox(wired, payload):
    assert _post(wired, payload).status_code == 200
    assert len(_inbound(wired)) == 1


def test_an_envelope_with_no_event_still_works(wired):
    """What the older tests sent. A clinic mid-upgrade must not go quiet."""
    assert _post(wired, {"message": {"from": "201000000001",
                                     "text": "أهلاً"}}).status_code == 200
    assert len(_inbound(wired)) == 1


# ------------------------------------------------- what cannot be read yet --
def test_an_unreadable_message_event_is_kept_not_dropped(wired):
    """The failure this whole file exists to prevent.

    An event that says it carries a message and yields none used to return
    200 with nothing written: the provider considered it delivered, never
    retried, and the parent's message existed nowhere.
    """
    assert _post(wired, {"event": "message",
                         "instance_id": "X",
                         "unexpected": {"body": "hi"}}).status_code == 200
    rows = _inbound(wired)
    assert len(rows) == 1
    assert rows[0].error == "unreadable_payload"


def test_what_was_kept_is_the_envelope_itself(wired):
    """Whoever is called about it has to see the shape, not a summary."""
    _post(wired, {"event": "message.any", "instance_id": "X",
                  "surprise": {"chat_id": "201000000001"}})
    body = _inbound(wired)[0].body
    assert json.loads(body) == {"event": "message.any", "instance_id": "X",
                                "surprise": {"chat_id": "201000000001"}}


def test_a_message_object_with_nobody_on_it_is_kept_too(wired):
    """The near miss: the envelope parses, the message inside does not.

    A ``message`` key that is present but carries no sender used to file a
    row with an empty body and no number — which is the same disappearance
    wearing a receipt. It belongs on the unreadable pile with the rest.
    """
    assert _post(wired, {"event": "message",
                         "message": {"id": "X", "text": "hi"}}).status_code == 200
    rows = _inbound(wired)
    assert len(rows) == 1
    assert rows[0].error == "unreadable_payload"
    assert json.loads(rows[0].body)["message"]["text"] == "hi"


def test_an_event_about_something_else_is_left_alone(wired):
    """Not every callback is a message; only a lost message is a problem."""
    assert _post(wired, {"event": "instance.status",
                         "instance_id": "X"}).status_code == 200
    assert _inbound(wired) == []


def test_an_empty_body_writes_nothing(wired):
    assert _post(wired, {}).status_code == 200
    assert _inbound(wired) == []


# ------------------------------------------------------- the same message --
def test_the_same_message_on_both_events_is_filed_once(wired):
    """A clinic may subscribe to both, and then every reply arrives twice."""
    both = dict(ANY_EVENT, payload=dict(MESSAGE_EVENT["message"]))
    _post(wired, MESSAGE_EVENT)
    _post(wired, both)
    rows = _inbound(wired)
    assert len(rows) == 1
    assert rows[0].provider_msg_id == "MESSAGE_ID"


def test_two_different_messages_are_still_two(wired):
    _post(wired, MESSAGE_EVENT)
    _post(wired, ANY_EVENT)
    assert len(_inbound(wired)) == 2


def test_messages_without_an_id_are_never_merged(wired):
    """Meta sends no id through this path, and two families can write the
    same words. With nothing to compare, nothing is treated as a repeat."""
    for _ in range(2):
        _post(wired, {"message": {"chat_id": "201000000001", "text": "تمام"}})
    assert len(_inbound(wired)) == 2


# ------------------------------------------------------------ the upload --
def test_the_image_upload_uses_the_field_wapilot_requires(tmp_path):
    """``media``. It was ``image``, and WaPilot answers that with a 422."""
    from app.utils import whatsapp

    picture = tmp_path / "one.png"
    picture.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)
    seen = {}

    def fake_multipart(url, fields, file_field, file_path, headers,
                       timeout=20):
        seen.update(url=url, fields=fields, file_field=file_field,
                    headers=headers)
        return 200, "{}"

    original_post = whatsapp._post_multipart
    original_local = whatsapp._local_image_path
    whatsapp._post_multipart = fake_multipart
    whatsapp._local_image_path = lambda url: str(picture)
    try:
        ok, err = whatsapp._send_wapilot(
            {"wapilot_key": "t", "wapilot_instance": "instance_123"},
            "201000000001", "صورة", image_url="/static/one.png")
    finally:
        whatsapp._post_multipart = original_post
        whatsapp._local_image_path = original_local

    assert (ok, err) == (True, None)
    assert seen["file_field"] == "media"
    assert seen["url"].endswith("/instance_123/send-image")
    assert seen["headers"]["token"] == "t"
    assert seen["fields"]["chat_id"] == "201000000001"


def test_a_text_message_still_goes_where_it_did(tmp_path):
    """The send path that was never broken must not move."""
    from app.utils import whatsapp

    seen = {}

    def fake_json(url, payload, headers, timeout=20):
        seen.update(url=url, payload=payload, headers=headers)
        return 200, "{}"

    original = whatsapp._post_json
    whatsapp._post_json = fake_json
    try:
        ok, _ = whatsapp._send_wapilot(
            {"wapilot_key": "t", "wapilot_instance": "instance_123"},
            "201000000001", "أهلاً")
    finally:
        whatsapp._post_json = original

    assert ok
    assert seen["url"].endswith("/instance_123/send-message")
    assert seen["payload"] == {"chat_id": "201000000001", "text": "أهلاً"}
