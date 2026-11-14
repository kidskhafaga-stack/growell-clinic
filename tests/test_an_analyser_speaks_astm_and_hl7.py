"""The analyser's own messages, read onto its tubes (LAB_GLAB360_PLAN.md م-٢ ب):
ASTM E1394 inside E1381 frames, and HL7 v2 ORU^R01 inside MLLP.

The same road as a result file: the tube's number finds one order, the code
is linked, the bench's own save checks it, nothing released; anything else
held with its reason. And the middleware's door: a key per device, a
heartbeat, and its protocol handling (frames, checksums, ACK/NAK, MLLP ACK).
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tests.test_a_result_line_by_line import _fresh_cache, _order, bench  # noqa: E402,F401
from tests.test_an_analyser_s_file_read_onto_its_tubes import (  # noqa: E402
    _device, _read, _states, _tube, _value)

ASTM = ("H|\\^&|||XN-350^00-25|||||||P|1\r"
        "P|1\r"
        "O|1|S1||^^^CBC|R\r"
        "R|1|^^^HGB^1|12.1|g/dL||N\r"
        "R|2|^^^PLT^1|250|10*3/uL||N\r"
        "O|2|S9||^^^CBC|R\r"
        "R|1|^^^HGB^1|10.0|g/dL||L\r"
        "L|1|N\r")

HL7 = ("MSH|^~\\&|XN|LAB|PEDIAPRO|CLINIC|20261114100000||ORU^R01|MSG0001|P|2.5\r"
       "PID|1||P1\r"
       "OBR|1|S2||CRP\r"
       "OBX|1|NM|CRP^C-reactive protein||3|mg/L|0-5|N|||F\r"
       "OBX|2|NM|HGB^Haemoglobin||12|g/dL||N|||F\r")


def _frames(text):
    """The E1381 frames an analyser would send, each with its checksum."""
    from app.utils.lab_messages import STX, ETX, checksum

    out = []
    for n, record in enumerate(text.split("\r")[:-1], start=1):
        body = f"{n % 8}{record}\r{ETX}"
        out.append(f"{STX}{body}{checksum(body)}\r\n")
    return "".join(out)


def _set(bench, did, protocol):
    from app.models import LabDevice

    with bench["app"].app_context():
        row = bench["db"].session.get(LabDevice, did)
        bench["sign_in"]("boss").post(f"/labs/devices/{did}", data={
            "name": row.name, "model": row.model or "", "protocol": protocol})


def test_astm_frames_are_read_onto_their_tubes(bench):
    cbc = _tube(bench, "cbc", "S1")
    did = _device(bench, HGB="hb")
    _set(bench, did, "astm")
    page = _read(bench, did, _frames(ASTM), name="xn.astm")
    assert "data-import-lines" in page
    assert _states(bench) == {("S1", "HGB"): "applied", ("S1", "PLT"): "no_code",
                              ("S9", "HGB"): "no_sample"}
    value, flag, released = _value(bench, cbc, "hb")
    assert value == 12.1 and released is None, "through the bench's save, not released"


def test_hl7_oru_is_read_onto_its_tubes(bench):
    crp = _tube(bench, "crp", "S2")
    did = _device(bench, CRP="crp_a", HGB="hb")
    _set(bench, did, "hl7")
    _read(bench, did, "\x0b" + HL7 + "\x1c\r", name="xn.hl7")
    assert _states(bench) == {("S2", "CRP"): "applied", ("S2", "HGB"): "not_on_test"}
    assert _value(bench, crp, "crp_a")[0] == 3


def test_a_broken_message_is_refused_not_half_read(bench):
    from app.models import LabImportLine

    did = _device(bench)
    _set(bench, did, "astm")
    page = _read(bench, did, "\x021H|\\^&|||XN", name="broken.astm")
    assert "data-import-lines" not in page
    with bench["app"].app_context():
        assert LabImportLine.query.count() == 0


def test_the_middleware_door_needs_the_device_s_key(bench):
    import re

    from app.models import LabDevice

    _tube(bench, "cbc", "S1")
    did = _device(bench, HGB="hb")
    _set(bench, did, "astm")
    api = bench["app"].test_client()
    assert api.post(f"/lab-intake/{did}/message", data=_frames(ASTM)).status_code == 401
    page = bench["sign_in"]("boss").post(f"/labs/devices/{did}/key").get_data(as_text=True)
    key = re.search(r"(pplab_[A-Za-z0-9_\-]+)", page).group(1)
    with bench["app"].app_context():
        assert key not in (bench["db"].session.get(LabDevice, did).key_hash or "")
    auth = {"Authorization": f"Bearer {key}"}
    assert api.post(f"/lab-intake/{did}/alive", json={"linked": True}, headers=auth).status_code == 200
    resp = api.post(f"/lab-intake/{did}/message", data=_frames(ASTM), headers=auth)
    assert resp.status_code == 200 and resp.get_json()["states"]["applied"] == 1
    page = bench["sign_in"]("boss").get(f"/labs/devices/{did}").get_data(as_text=True)
    assert 'data-device-link="ok"' in page and key not in page, "the key is shown once"


def test_the_middleware_answers_the_analyser_in_its_protocol():
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
    import lab_listener as mw

    session = mw.AstmSession()
    frames = _frames(ASTM).encode("latin-1")
    replies, messages = session.feed(mw.ENQ)
    assert replies == [mw.ACK] and messages == []
    bad = frames.replace(b"XN-350", b"XN-351", 1)        # checksum no longer matches
    replies, _ = session.feed(bad[:bad.index(b"\n") + 1])
    assert replies == [mw.NAK], "a damaged frame is asked again"
    replies, messages = session.feed(frames + mw.EOT)
    assert all(r == mw.ACK for r in replies) and len(messages) == 1
    from app.utils.lab_messages import parse_astm

    assert [r[2] for r in parse_astm(messages[0].decode("latin-1"))] == ["HGB", "PLT", "HGB"]

    wrapped = mw.VT + HL7.encode() + mw.FS + mw.CR
    found, rest = mw.mllp_messages(wrapped + mw.VT + b"MSH|partial")
    assert len(found) == 1 and rest.startswith(mw.VT)
    ack = mw.hl7_ack(found[0]).decode()
    assert "MSA|AA|MSG0001" in ack and ack.startswith("\x0b") and ack.endswith("\x1c\r")
    assert "MSA|AE|MSG0001" in mw.hl7_ack(found[0], ok=False).decode()
