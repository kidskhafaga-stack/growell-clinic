"""«اتبعت» مش معناها «وصلت» — reading the receipts the program threw away.

**The gap, measured before building.** ``normalize_meta`` read
``value["messages"]`` and nothing else; ``value["statuses"]`` — the delivery
receipts Meta sends for every message the clinic sends — was never touched, and
``MessageLog`` had no column to match one against. ``_send_cloud`` even threw
the provider's message id away on the line that received it
(``status, _ = _post_json(...)``).

So ``status="sent"`` meant one thing only: *the provider accepted it*. A number
disconnected a year ago, a family that blocked the clinic, and a mother who
read the message all looked identical on every screen. A clinic reading its own
delivery board would see every vaccine reminder "sent" while one a week
silently went nowhere.

**The two rules worth testing hardest** are not the happy path. Receipts arrive
out of order, so a status may only ever move *up*; and ``failed`` is not a rung
on that ladder but the one status somebody has to act on, so it always wins.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

WAMID = "wamid.HBgLMjAxMDAwMDAwMDkVAgARGBI5QUY4"


def _receipt(msg_id, status, errors=None):
    """A Meta webhook payload carrying one delivery receipt."""
    st = {"id": msg_id, "status": status, "timestamp": "1786300000",
          "recipient_id": "201000000009"}
    if errors:
        st["errors"] = errors
    return {"entry": [{"changes": [{"value": {"statuses": [st]}}]}]}


@pytest.fixture()
def logged(clinic):
    """One message already sent, carrying the provider's id."""
    with clinic["app"].app_context():
        from app.models import MessageLog
        row = MessageLog(to_phone="201000000009", body="تذكير",
                         provider="cloud_api", direction="out",
                         status="sent", provider_msg_id=WAMID,
                         template_type="appointment_reminder")
        clinic["db"].session.add(row)
        clinic["db"].session.commit()
    return clinic


def _status_of(clinic, msg_id=WAMID):
    from app.models import MessageLog
    return MessageLog.query.filter_by(provider_msg_id=msg_id).first().status


# --- the id, which everything else depends on ------------------------------

def test_the_provider_id_is_kept_instead_of_dropped(clinic, monkeypatch):
    """It was discarded on the line that received it.

    Without the id there is nothing to match a receipt against, so no amount
    of webhook reading would have helped — this is the first half of the fix
    and it is one assignment.
    """
    with clinic["app"].app_context():
        from app.models import MessageLog, Patient, Setting
        from app.utils import whatsapp as wa

        Setting.set("crm_mode", "automatic")
        Setting.set("wa_provider", "cloud_api")
        Setting.set("wa_cloud_token", "tok")
        Setting.set("wa_cloud_phone_id", "1")
        child = clinic["db"].session.get(Patient, clinic["ids"]["child"])
        child.own_phone = "01000000009"
        clinic["db"].session.commit()

        monkeypatch.setattr(wa, "_post_json", lambda *a, **k: (
            200, '{"messages":[{"id":"' + WAMID + '"}]}'))
        wa.send("تذكير", "201000000009", patient_id=child.id)
        clinic["db"].session.commit()

        row = MessageLog.query.order_by(MessageLog.id.desc()).first()
        assert row.provider_msg_id == WAMID


def test_a_reply_meta_cannot_parse_never_costs_the_send(clinic, monkeypatch):
    """The id is a nice-to-have; the message going out is not.

    A body that does not parse must cost a receipt, never a delivery — so the
    extraction swallows everything and returns None.
    """
    from app.utils.whatsapp import _cloud_msg_id

    assert _cloud_msg_id("not json at all") is None
    assert _cloud_msg_id("") is None
    assert _cloud_msg_id('{"messages":[]}') is None
    assert _cloud_msg_id('{"messages":[{"id":"' + WAMID + '"}]}') == WAMID


# --- reading the receipts --------------------------------------------------

def test_the_statuses_meta_sends_are_no_longer_dropped(logged):
    """The webhook read only half of what arrives in it."""
    from app.utils.inbound import normalize_meta_statuses

    items = normalize_meta_statuses(_receipt(WAMID, "delivered"))
    assert items == [{"msg_id": WAMID, "status": "delivered", "error": None}]


def test_delivered_reaches_the_row_through_the_public_webhook(logged):
    """End to end, through the endpoint Meta actually calls.

    Testing the normaliser alone would have passed with the webhook route
    still ignoring statuses — which was the entire bug.
    """
    import hashlib
    import hmac
    import json

    with logged["app"].app_context():
        from app.models import Setting
        Setting.set("wa_inbound_enabled", "1")
        Setting.set("wa_meta_app_secret", "shh")
        logged["db"].session.commit()

    payload = json.dumps(_receipt(WAMID, "delivered")).encode()
    signature = "sha256=" + hmac.new(b"shh", payload, hashlib.sha256).hexdigest()
    client = logged["app"].test_client()
    response = client.post("/wa/webhook/meta", data=payload,
                           content_type="application/json",
                           headers={"X-Hub-Signature-256": signature})
    assert response.status_code == 200

    with logged["app"].app_context():
        assert _status_of(logged) == "delivered"


@pytest.mark.parametrize("first,second,expected", [
    ("delivered", "read", "read"),        # the ordinary way round
    ("read", "delivered", "read"),        # …and the way they actually arrive
    ("delivered", "sent", "delivered"),   # a late "sent" must not undo it
    ("read", "sent", "read"),
])
def test_a_status_only_ever_moves_up(logged, first, second, expected):
    """Receipts arrive out of order, and a plain assignment loses the better one.

    Meta will hand you ``delivered`` after ``read`` often enough that this is
    not a theoretical case: the clinic would read fewer opens than really
    happened, and would never know why.
    """
    from app.utils.inbound import apply_status

    with logged["app"].app_context():
        for status in (first, second):
            apply_status({"msg_id": WAMID, "status": status, "error": None})
        logged["db"].session.commit()
        assert _status_of(logged) == expected


def test_failed_always_wins_because_it_is_the_one_to_act_on(logged):
    """It is not a rung on the ladder — it is the message not arriving.

    A ``failed`` receipt after a ``delivered`` is rare, but the reverse rule
    (highest rank wins) would silently hide the only status a human needs to
    do something about.
    """
    from app.utils.inbound import apply_status

    with logged["app"].app_context():
        apply_status({"msg_id": WAMID, "status": "read", "error": None})
        apply_status({"msg_id": WAMID, "status": "failed",
                      "error": "Receiver is not a WhatsApp user"})
        logged["db"].session.commit()

        from app.models import MessageLog
        row = MessageLog.query.filter_by(provider_msg_id=WAMID).first()
        assert row.status == "failed"
        assert "WhatsApp user" in row.error


def test_the_reason_is_shown_in_the_providers_own_words(logged):
    """"This number is not on WhatsApp" is something reception can fix.

    A numeric code is something they will ask somebody else about, so the
    title is preferred and the code is only a fallback.
    """
    from app.utils.inbound import normalize_meta_statuses

    payload = _receipt(WAMID, "failed", errors=[
        {"code": 131026, "title": "Message undeliverable",
         "message": "Receiver is not a WhatsApp user"}])
    assert normalize_meta_statuses(payload)[0]["error"] == "Message undeliverable"

    coded = _receipt(WAMID, "failed", errors=[{"code": 131026}])
    assert normalize_meta_statuses(coded)[0]["error"] == "131026"


def test_a_receipt_for_a_message_we_never_sent_is_not_an_error(logged):
    """Every clinic will receive some.

    Messages sent before this column existed carry no id, and a shared number
    can see receipts that are not ours. Raising on those would take the
    webhook down for the messages that *are*.
    """
    from app.utils.inbound import apply_status

    with logged["app"].app_context():
        assert apply_status({"msg_id": "wamid.someone-else",
                             "status": "read", "error": None}) is None
        assert _status_of(logged) == "sent", "an unrelated receipt moved our row"


def test_a_status_meta_invents_tomorrow_is_ignored_not_stored(logged):
    """The vocabulary is Meta's, and it is theirs to extend.

    An unknown word must leave the row alone rather than be written into it —
    a status column holding something no screen knows how to render is worse
    than one that did not move.
    """
    from app.utils.inbound import apply_status

    with logged["app"].app_context():
        apply_status({"msg_id": WAMID, "status": "teleported", "error": None})
        logged["db"].session.commit()
        assert _status_of(logged) == "sent"


# --- and the number a clinic should actually look at -----------------------

def test_the_board_counts_arrived_apart_from_accepted(logged):
    """The measurement the whole change exists to make possible.

    Adding "sent" and "delivered" together would tell a clinic every reminder
    landed while a dead number quietly swallows one a week. ``unconfirmed`` is
    the messages the provider took and never came back about — the ones nobody
    can say arrived.
    """
    from app.utils.inbound import apply_status

    with logged["app"].app_context():
        from app.models import MessageLog
        db = logged["db"]
        # A second message of the same type that never got a receipt.
        db.session.add(MessageLog(
            to_phone="201000000008", body="تذكير", provider="cloud_api",
            direction="out", status="sent", provider_msg_id="wamid.other",
            template_type="appointment_reminder"))
        db.session.commit()

        apply_status({"msg_id": WAMID, "status": "read", "error": None})
        db.session.commit()

        from app.blueprints.messages.routes import _delivery_by_type
        row = [r for r in _delivery_by_type()
               if r["type"] == "appointment_reminder"][0]
        assert row["total"] == 2
        assert row["arrived"] == 1, "a read message is not counted as arrived"
        assert row["unconfirmed"] == 1, (
            "a message the provider never confirmed is being counted as landed")


def test_the_column_reaches_clinics_that_already_have_the_program():
    """A new column on an existing table only exists if the migration knows.

    ``provider_msg_id`` on a fresh install comes from ``db.create_all``; on the
    clinic that has been running since June it comes from this list and
    nowhere else, and without it every receipt would silently match nothing.
    """
    from app.utils.schema import ADDITIONS

    assert ("message_logs", "provider_msg_id", "VARCHAR(120)") in ADDITIONS
