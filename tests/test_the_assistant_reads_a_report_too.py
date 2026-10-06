"""The assistant reads a scan's report, a test of one value, and the outside
laboratory's paper on the bench — and a person saves it.

«الطبيب لما يرفع الPDF والAI يقراء التحليل لو متفعل ويحط النتائج لواحدة او
تقرير اشعة».

* a test with no lines and a scan fill the **report** — the text as printed,
  and for a test of one value its number, unit and printed range;
* a number box takes a plain number or nothing: «<1» is not 1;
* a scan is text only, whatever comes back;
* the lab bench keeps the outside laboratory's paper on the order and reads
  it the same way;
* nothing is written until a person presses save, and never without the
  clinic's consent.
"""
import io
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

from tests.test_a_result_line_by_line import _fresh_cache, _order, _row, bench  # noqa: E402,F401
from tests.test_the_assistant_reads_the_paper_a_person_saves import (  # noqa: E402,F401
    PNG, _WRITTEN, _ai, _no_files_left, _paper)


def _answer(monkeypatch, text):
    from app.utils import ai

    calls = []

    def fake_chat(messages, system=None, config=None, feature=None):
        calls.append({"messages": messages, "system": system, "feature": feature})
        return {"ok": True, "text": text}

    monkeypatch.setattr(ai, "chat", fake_chat)
    return calls


def test_the_reply_is_read_narrowly():
    from app.utils.lab_read import parse_report

    got = parse_report('{"value": "7,2", "unit": "mg/dL", "low": "<1", "high": "5",'
                       ' "text": "  Mildly raised  ", "opinion": "sick"}')
    assert got == {"value": "7.2", "unit": "mg/dL", "high": "5", "text": "Mildly raised"}
    assert parse_report('{"value": "3", "text": "No consolidation."}', imaging=True) == {
        "text": "No consolidation."}
    assert parse_report("not json") == {}


def test_a_test_of_one_value_fills_the_report_and_nothing_is_saved(bench, monkeypatch):
    _ai(bench)
    order = _order(bench, test="plain")
    paper = _paper(bench, order, name="urine.png")
    calls = _answer(monkeypatch, '{"value": "6.5", "unit": "pH", "text": "Clear, no cells."}')
    doc = bench["sign_in"]("doc")
    record = f"/visits/{bench['ids']['visit']}/record"
    assert f'data-read-paper="{order}"' in doc.get(record).get_data(as_text=True)
    page = doc.post(f"/visits/investigations/{order}/read-paper",
                    data={"attachment_id": str(paper)}).get_data(as_text=True)
    assert calls and calls[0]["feature"] == "lab_read"
    assert 'name="result_value"' in page and 'value="6.5"' in page
    assert "Clear, no cells." in page and "data-ai-read" in page
    with bench["app"].app_context():
        assert _row(bench, order).result_value is None, "nothing saved yet"
    got = doc.post(f"/visits/investigations/{order}/result",
                   data={"result_value": "6.5", "result_unit": "pH",
                         "result_text": "Clear, no cells.", "next": record + "#inv"})
    assert got.headers["Location"].endswith(record + "#inv")
    with bench["app"].app_context():
        assert _row(bench, order).result_value == 6.5


def test_a_scan_is_read_as_its_report_only(bench, monkeypatch):
    from app.models import VisitInvestigation

    _ai(bench)
    with bench["app"].app_context():
        row = VisitInvestigation(visit_id=bench["ids"]["visit"], patient_id=bench["ids"]["child"],
                                 kind="imaging", name="أشعة صدر", name_en="Chest X-ray",
                                 status="requested")
        bench["db"].session.add(row)
        bench["db"].session.commit()
        order = row.id
    paper = _paper(bench, order, name="cxr.png")
    calls = _answer(monkeypatch, '{"value": "9", "text": "Lungs clear. Normal heart size."}')
    page = bench["sign_in"]("doc").post(f"/visits/investigations/{order}/read-paper",
                                        data={"attachment_id": str(paper)}).get_data(as_text=True)
    assert "radiology report" in calls[0]["messages"][0]["content"][1]["text"]
    assert "Lungs clear. Normal heart size." in page and 'name="result_value"' not in page


def test_the_bench_keeps_and_reads_the_outside_laboratory_s_paper(bench, monkeypatch):
    _ai(bench)
    order = _order(bench, test="plain", collected_minutes_ago=30)
    boss = bench["sign_in"]("boss")
    page = boss.get(f"/labs/order/{order}").get_data(as_text=True)
    assert "data-lab-paper" in page and "data-lab-read-paper" not in page
    boss.post(f"/labs/order/{order}/paper", content_type="multipart/form-data",
              data={"file": (io.BytesIO(PNG), "outside.png")})
    from app.models import PatientAttachment
    from app.utils.uploads import docs_dir

    with bench["app"].app_context():
        att = PatientAttachment.query.filter_by(investigation_id=order).one()
        _WRITTEN.append(os.path.join(docs_dir(), att.filename))
        paper = att.id
    page = boss.get(f"/labs/order/{order}").get_data(as_text=True)
    assert "data-lab-read-paper" in page and "outside.png" in page
    _answer(monkeypatch, '{"value": "1.020", "text": "Specific gravity 1.020"}')
    page = boss.post(f"/labs/order/{order}/read-paper",
                     data={"attachment_id": str(paper)}).get_data(as_text=True)
    assert f'action="/labs/order/{order}/result"' in page and 'value="1.020"' in page
    with bench["app"].app_context():
        assert _row(bench, order).result_value is None


def test_never_sent_without_the_clinic_s_consent(bench, monkeypatch):
    from app.utils import ai

    _ai(bench, consent=False)
    order = _order(bench, test="plain")
    paper = _paper(bench, order)
    monkeypatch.setattr(ai, "chat", lambda *a, **k: pytest.fail("sent anyway"))
    got = bench["sign_in"]("boss").post(f"/labs/order/{order}/read-paper",
                                        data={"attachment_id": str(paper)})
    assert got.status_code == 302
