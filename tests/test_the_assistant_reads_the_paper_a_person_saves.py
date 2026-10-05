"""The assistant reads the paper a family brought — and a person saves it.

* each provider is sent the picture **in its own documented shape** — Claude
  image/document blocks, an OpenAI data-URL image part, a Gemini inline_data
  part — and a PDF goes to Claude only, refused by name elsewhere;
* only where the clinic switched the assistant on **and** agreed to send it
  patients' papers;
* the reading fills the line-by-line form, marked, beside the paper — and
  **nothing is written** until a person presses save, through the ordinary
  save with the bench's ranges;
* what comes back is read narrowly: only this test's lines, only short
  strings.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

from tests.test_a_result_line_by_line import _fresh_cache, _order, _row, bench  # noqa: E402,F401

PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
       b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\x0f"
       b"\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82")


def _ai(c, provider="claude", consent=True):
    from app.models import Setting

    with c["app"].app_context():
        Setting.set("ai_enabled", "1")
        Setting.set("ai_provider", provider)
        Setting.set("ai_api_key", "test-key")
        Setting.set("ai_model", "test-model")
        Setting.set("ai_patient_context", "1" if consent else "0")
        c["db"].session.commit()


_WRITTEN = []


@pytest.fixture(autouse=True)
def _no_files_left():
    yield
    while _WRITTEN:
        try:
            os.remove(_WRITTEN.pop())
        except OSError:
            pass


def _paper(c, order_id, name="cbc.png", data=PNG):
    from app.models import PatientAttachment
    from app.utils.uploads import docs_dir

    with c["app"].app_context():
        os.makedirs(docs_dir(), exist_ok=True)
        stored = f"test_{order_id}_{name}"
        with open(os.path.join(docs_dir(), stored), "wb") as fh:
            fh.write(data)
        _WRITTEN.append(os.path.join(docs_dir(), stored))
        row = PatientAttachment(patient_id=c["ids"]["child"],
                                visit_id=c["ids"]["visit"],
                                investigation_id=order_id, filename=stored,
                                original_name=name, kind="result")
        c["db"].session.add(row)
        c["db"].session.commit()
        return row.id


@pytest.fixture()
def posted(monkeypatch):
    """Every request the AI helper would have sent, and a canned answer."""
    sent = []

    class _Resp:
        ok = True
        status_code = 200
        text = ""

        def __init__(self, body):
            self._body = body

        def json(self):
            return self._body

    def fake_post(url, headers=None, json=None, params=None, timeout=None):
        sent.append({"url": url, "json": json})
        if "generateContent" in url:
            return _Resp({"candidates": [{"content": {"parts": [{"text": "{}"}]}}]})
        if "anthropic" in url:
            return _Resp({"content": [{"type": "text", "text": "{}"}]})
        return _Resp({"choices": [{"message": {"content": "{}"}}]})

    import requests

    monkeypatch.setattr(requests, "post", fake_post)
    return sent


IMG = {"type": "image", "media_type": "image/png", "data": "QUJD"}
PDF = {"type": "pdf", "data": "QUJD"}


def test_each_provider_gets_the_picture_in_its_documented_shape(bench, posted):
    from app.utils import ai

    with bench["app"].app_context():
        for provider in ("claude", "openai", "gemini"):
            _ai(bench, provider)
            assert ai.chat([{"role": "user", "content": [
                IMG, {"type": "text", "text": "read"}]}])["ok"]
    claude, openai, gemini = (p["json"] for p in posted)
    assert claude["messages"][0]["content"][0] == {
        "type": "image", "source": {"type": "base64", "media_type": "image/png",
                                    "data": "QUJD"}}
    assert openai["messages"][0]["content"][0] == {
        "type": "image_url", "image_url": {"url": "data:image/png;base64,QUJD"}}
    assert gemini["contents"][0]["parts"][0] == {
        "inline_data": {"mime_type": "image/png", "data": "QUJD"}}


def test_a_pdf_goes_to_claude_only(bench, posted):
    from app.utils import ai

    with bench["app"].app_context():
        _ai(bench, "claude")
        assert ai.chat([{"role": "user", "content": [PDF]}])["ok"]
        assert posted[-1]["json"]["messages"][0]["content"][0]["type"] == "document"
        for provider in ("openai", "gemini"):
            _ai(bench, provider)
            before = len(posted)
            result = ai.chat([{"role": "user", "content": [PDF]}])
            assert result == {"ok": False, "error": "unsupported_part"}
            assert len(posted) == before, "refused before anything was sent"


def test_plain_text_chat_is_unchanged(bench, posted):
    from app.utils import ai

    with bench["app"].app_context():
        _ai(bench, "openai")
        ai.chat([{"role": "user", "content": "hello"}])
    assert posted[-1]["json"]["messages"][-1] == {"role": "user", "content": "hello"}


def test_the_reading_fills_the_form_and_nothing_is_saved_until_a_person_saves(
        bench, monkeypatch):
    from app.utils import ai

    _ai(bench)
    order = _order(bench)
    paper = _paper(bench, order)
    calls = []

    def fake_chat(messages, system=None, config=None, feature=None):
        calls.append({"messages": messages, "feature": feature})
        return {"ok": True, "text": 'Here: {"%d": "11.4", "999": "7", "%d": {"x": 1}}'
                % (bench["hb"], bench["plt"])}

    monkeypatch.setattr(ai, "chat", fake_chat)
    doc = bench["sign_in"]("doc")
    record = f"/visits/{bench['ids']['visit']}/record"
    assert f'data-read-paper="{order}"' in doc.get(record).get_data(as_text=True)

    page = doc.post(f"/visits/investigations/{order}/read-paper",
                    data={"attachment_id": str(paper)}).get_data(as_text=True)
    assert calls and calls[0]["feature"] == "lab_read"
    sent = calls[0]["messages"][0]["content"]
    assert sent[0]["type"] == "image" and sent[0]["media_type"] == "image/png"
    assert "data-ai-read" in page and 'value="11.4"' in page and "data-paper" in page
    with bench["app"].app_context():
        assert not _row(bench, order).analyte_values, "a reading is not a save"

    answer = doc.post(f"/visits/investigations/{order}/result",
                      data={f"a_{bench['hb']}": "11.4", "next": record})
    assert answer.headers["Location"].endswith(record)
    with bench["app"].app_context():
        row = _row(bench, order)
        assert row.status == "resulted"
        assert [(v.analyte_id, v.value) for v in row.analyte_values] == [(bench["hb"], 11.4)]


def test_without_the_clinic_s_consent_the_paper_is_not_sent(bench, monkeypatch):
    from app.utils import ai

    _ai(bench, consent=False)
    order = _order(bench)
    paper = _paper(bench, order)
    monkeypatch.setattr(ai, "chat", lambda *a, **k: pytest.fail("sent anyway"))
    doc = bench["sign_in"]("doc")
    record = f"/visits/{bench['ids']['visit']}/record"
    assert f'data-read-paper="{order}"' not in doc.get(record).get_data(as_text=True)
    answer = doc.post(f"/visits/investigations/{order}/read-paper",
                      data={"attachment_id": str(paper)})
    assert answer.status_code == 302


def test_a_paper_on_another_order_is_not_read(bench, monkeypatch):
    from app.utils import ai

    _ai(bench)
    mine, other = _order(bench), _order(bench)
    paper = _paper(bench, other)
    monkeypatch.setattr(ai, "chat", lambda *a, **k: pytest.fail("sent anyway"))
    answer = bench["sign_in"]("doc").post(
        f"/visits/investigations/{mine}/read-paper", data={"attachment_id": str(paper)})
    assert answer.status_code == 302


def test_what_comes_back_is_read_narrowly(bench):
    from app.utils import lab_read, lab_results

    order = _order(bench)
    with bench["app"].app_context():
        lines = lab_results.sheet(_row(bench, order))
        hb, plt = bench["hb"], bench["plt"]
        assert lab_read.parse_reply("no json here", lines) == {}
        assert lab_read.parse_reply('{"%d": "  9.8 ", "%d": null, "x": "1"}' % (hb, plt),
                                    lines) == {hb: "9.8"}
        assert lab_read.parse_reply('["%d"]' % hb, lines) == {}
