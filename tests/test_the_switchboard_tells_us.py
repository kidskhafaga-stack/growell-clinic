"""The telephone, through whatever switchboard the clinic has.

``CONNECTHUB_PLAN.md`` stage 6 — «التليفون (VoIP/CTI): حسب السنترال اللي عند
كل عميل». The program speaks no switchboard's language; it opens its own
door, and these hold it:

* the door is shut until the telephone is turned on, and needs the clinic's
  key — kept only as its hash;
* the ring, the answer and the hang-up of one call land on one row, and the
  same event twice changes nothing; JSON or form fields alike;
* a ring that is never answered is a **missed** call, listed until somebody
  marks it returned or the same number later gets through;
* the person whose extension rings sees who is calling — the children on
  the number, and the chat's own panel **by their own permissions**;
* the handset lookup says names and file numbers, nothing medical or owed;
* the screens have their doors, and nothing is recorded.
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

NUMBER = "01000000001"       # the child's own phone, set below


@pytest.fixture()
def phone(clinic):
    """The telephone on, with a key, and the guardian's number on file."""
    from app.extensions import db
    from app.models import Patient, User
    from app.utils import telephony

    with clinic["app"].app_context():
        telephony.set_enabled(True)
        clinic["key"] = telephony.new_key()
        db.session.get(Patient, clinic["ids"]["child"]).own_phone = NUMBER
        db.session.get(User, clinic["ids"]["desk"]).phone_extension = "201"
        db.session.commit()
    return clinic


def _event(c, key=None, as_form=False, **body):
    client = c["app"].test_client()
    headers = {"Authorization": f"Bearer {key or c['key']}"}
    if as_form:
        return client.post("/telephony/event", data=body, headers=headers)
    return client.post("/telephony/event", json=body, headers=headers)


def _calls(c):
    from app.models import PhoneCall

    with c["app"].app_context():
        return [(r.call_ref, r.status, r.extension, r.number)
                for r in PhoneCall.query.order_by(PhoneCall.id)]


# ------------------------------------------------------------- the door ---
def test_the_door_is_shut_until_turned_on_and_needs_the_key(clinic):
    from app.models import Setting
    from app.utils import telephony

    client = clinic["app"].test_client()
    body = {"event": "ring", "call_id": "x1", "from": NUMBER}
    assert client.post("/telephony/event", json=body).status_code == 404
    with clinic["app"].app_context():
        telephony.set_enabled(True)
        key = telephony.new_key()
        clinic["db"].session.commit()
        # Only the fingerprint is kept.
        assert key not in (Setting.get(telephony.KEY_HASH) or "")
    assert client.post("/telephony/event", json=body).status_code == 401
    assert client.post("/telephony/event", json=body, headers={
        "Authorization": "Bearer pptel_wrong"}).status_code == 401
    assert client.post("/telephony/event", json=body, headers={
        "Authorization": f"Bearer {key}"}).status_code == 200


def test_one_call_is_one_row_whatever_is_sent_twice(phone):
    _event(phone, event="ring", call_id="c1", **{"from": NUMBER},
           to="201", direction="in")
    _event(phone, event="ring", call_id="c1", **{"from": NUMBER}, to="201")
    _event(phone, event="answer", call_id="c1", extension="202")
    _event(phone, event="hangup", call_id="c1")
    _event(phone, event="hangup", call_id="c1")
    [(ref, status, ext, number)] = _calls(phone)
    # Answered at 202 — on a ring group, not the extension it rang at.
    assert (ref, status, ext, number) == ("c1", "ended", "202", "201000000001")
    # Asterisk's CURL() posts form fields: those work too.
    resp = _event(phone, as_form=True, event="ring", call_id="c2",
                  **{"from": NUMBER})
    assert resp.status_code == 200
    assert _event(phone, event="sing", call_id="c3").status_code == 400


def test_a_missed_call_waits_until_returned_or_reached(phone):
    from app.extensions import db
    from app.models import PhoneCall
    from app.utils import telephony

    _event(phone, event="ring", call_id="m1", **{"from": NUMBER})
    _event(phone, event="hangup", call_id="m1")
    _event(phone, event="ring", call_id="m2", **{"from": "01099999999"})
    _event(phone, event="hangup", call_id="m2")
    with phone["app"].app_context():
        assert {c.call_ref for c in telephony.missed()} == {"m1", "m2"}
    page = phone["sign_in"]("desk").get("/messages/calls") \
        .get_data(as_text=True)
    assert 'data-missed="2"' in page and 'href="tel:+201000000001"' in page
    # The family got through later — m1 is answered by that.
    _event(phone, event="ring", call_id="m3", **{"from": NUMBER})
    _event(phone, event="answer", call_id="m3")
    # Somebody returned m2 by hand.
    with phone["app"].app_context():
        m2 = PhoneCall.query.filter_by(call_ref="m2").one().id
    phone["sign_in"]("desk").post(f"/messages/calls/{m2}/returned",
                                  data={"note": "اتكلمنا وحجزنا"})
    with phone["app"].app_context():
        assert telephony.missed() == []
        row = db.session.get(PhoneCall, m2)
        assert (row.returned_by, row.returned_note) == \
            (phone["ids"]["desk"], "اتكلمنا وحجزنا")


def test_whoever_rings_sees_who_is_calling_by_their_own_rights(phone):
    _event(phone, event="ring", call_id="r1", **{"from": NUMBER},
           to="201", direction="in")
    got = phone["sign_in"]("desk").get("/messages/calls/ringing").get_json()
    assert got["ids"] and 'data-ringing="' in got["html"]
    with phone["app"].app_context():
        from app.models import Patient
        kid = phone["db"].session.get(Patient, phone["ids"]["child"])
        assert f"({kid.patient_number})" in got["html"]
    # Reception reaches neither the laboratory nor the medical file.
    assert "data-ringing-tests" not in got["html"]
    # Not this person's extension: nothing pops up for them.
    with phone["app"].app_context():
        from app.models import User
        phone["db"].session.get(User, phone["ids"]["admin"]) \
            .phone_extension = "305"
        phone["db"].session.commit()
    assert phone["sign_in"]("boss").get("/messages/calls/ringing") \
        .get_json()["ids"] == []
    # Answered: it stops ringing for everyone.
    _event(phone, event="answer", call_id="r1", extension="201")
    assert phone["sign_in"]("desk").get("/messages/calls/ringing") \
        .get_json()["ids"] == []


def test_an_old_ring_with_no_hangup_is_not_ringing_now(phone):
    from app.models import PhoneCall
    from app.utils import telephony

    _event(phone, event="ring", call_id="old", **{"from": NUMBER}, to="201")
    with phone["app"].app_context():
        row = PhoneCall.query.filter_by(call_ref="old").one()
        row.started_at = datetime.utcnow() - timedelta(minutes=5)
        phone["db"].session.commit()
        from app.models import User
        desk = phone["db"].session.get(User, phone["ids"]["desk"])
        assert telephony.ringing_for(desk) == []


def test_the_handset_lookup_says_names_only(phone):
    from app.extensions import db
    from app.models import Patient

    client = phone["app"].test_client()
    headers = {"Authorization": f"Bearer {phone['key']}"}
    got = client.get(f"/telephony/lookup?number={NUMBER}",
                     headers=headers).get_json()
    with phone["app"].app_context():
        kid = db.session.get(Patient, phone["ids"]["child"])
        assert got["found"] is True
        assert {"file": kid.patient_number, "name": kid.full_name} in \
            got["patients"]
    assert set(got) == {"number", "found", "name", "patients"}
    assert client.get(f"/telephony/lookup?number={NUMBER}").status_code == 401


def test_setup_is_for_whoever_sets_up_channels(phone):
    from app.models import User

    assert phone["sign_in"]("desk").get("/messages/calls/setup") \
        .status_code in (302, 403)
    boss = phone["sign_in"]("boss")
    page = boss.get("/messages/calls/setup").get_data(as_text=True)
    assert 'data-calls-toggle="on"' in page and "/telephony/event" in page
    page = boss.post("/messages/calls/setup", data={"action": "key"}) \
        .get_data(as_text=True)
    assert "data-new-key" in page and "pptel_" in page
    boss.post("/messages/calls/setup", data={
        "action": "extensions", f"ext_{phone['ids']['doctor']}": "310"})
    with phone["app"].app_context():
        assert phone["db"].session.get(
            User, phone["ids"]["doctor"]).phone_extension == "310"
    # The old key no longer opens the door.
    assert _event(phone, event="ring", call_id="k1",
                  **{"from": NUMBER}).status_code == 401


def test_the_screens_have_their_doors(phone):
    client = phone["sign_in"]("boss")
    inbox = client.get("/messages/inbox").get_data(as_text=True)
    assert "data-to-calls" in inbox
    channels = client.get("/messages/channels").get_data(as_text=True)
    assert 'data-channel-settings="phone"' in channels
    assert 'data-channel-row="phone:connected"' in channels
    calls = client.get("/messages/calls").get_data(as_text=True)
    assert "data-to-calls-setup" in calls
    # And the pop-up is on every page once the telephone is on.
    assert 'id="gc-ringing"' in calls
