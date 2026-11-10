"""One paper, every test it answers (asked: «التحاليل الى طلبها ممكن يرفعها
وتتملى بشكل تلقائي في التحاليل المنتظرة … والطبيب يقرا سواء كانت صور او PDF»).

A family brings one report with the CBC and the CRP on it. The assistant reads
it once against every test still waiting for the child, the answers come back
per test into one page beside the paper, and nothing is saved until the doctor
presses save — each test through its own save, the ticked ones only.
"""
import io
import os
import sys
import uuid

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tests.test_a_result_line_by_line import _fresh_cache, _order, _row, bench  # noqa: E402,F401
from tests.test_the_assistant_reads_a_report_too import _answer  # noqa: E402
from tests.test_the_assistant_reads_the_paper_a_person_saves import (  # noqa: E402,F401
    PNG, _WRITTEN, _ai, _no_files_left)


def _loose_paper(c, name="report.png"):
    from app.models import PatientAttachment
    from app.utils.uploads import docs_dir

    with c["app"].app_context():
        os.makedirs(docs_dir(), exist_ok=True)
        stored = f"test_loose_{uuid.uuid4().hex}_{name}"
        with open(os.path.join(docs_dir(), stored), "wb") as fh:
            fh.write(PNG)
        _WRITTEN.append(os.path.join(docs_dir(), stored))
        row = PatientAttachment(patient_id=c["ids"]["child"], visit_id=c["ids"]["visit"],
                                filename=stored, original_name=name, kind="result")
        c["db"].session.add(row)
        c["db"].session.commit()
        return row.id


def _second_visit(c):
    from app.models import Visit
    from app.utils.clock import local_today

    with c["app"].app_context():
        v = Visit(patient_id=c["ids"]["child"], doctor_id=c["ids"]["doctor"],
                  visit_date=local_today())
        c["db"].session.add(v)
        c["db"].session.commit()
        return v.id


def test_one_paper_fills_every_waiting_test_and_nothing_is_saved_until_the_doctor_does(bench, monkeypatch):
    _ai(bench)
    cbc = _order(bench, "cbc", collected_minutes_ago=60)
    crp = _order(bench, "crp", collected_minutes_ago=60)
    paper = _loose_paper(bench)
    visit = _second_visit(bench)
    doc = bench["sign_in"]("doc")
    assert "data-read-paper-all" in doc.get(f"/visits/{visit}/record").get_data(as_text=True)
    calls = _answer(monkeypatch, '{"t%d.%d": "12.4", "t%d.%d": "3", "t%d.%d": "8", "t999.1": "9"}' % (
        cbc, bench["hb"], crp, bench["crp_a"], cbc, 424242))
    page = doc.post(f"/visits/{visit}/read-paper-all",
                    data={"attachment_id": str(paper)}).get_data(as_text=True)
    assert calls and "Tests to look for" in calls[0]["messages"][0]["content"][1]["text"]
    assert page.count("data-found") == 2 and "data-ai-read" in page
    assert 'value="12.4"' in page and 'value="3"' in page
    with bench["app"].app_context():
        assert not _row(bench, cbc).analyte_values, "nothing saved by the reading"
    doc.post(f"/visits/{visit}/save-paper-all", data={
        "attachment_id": str(paper), "orders": [str(cbc), str(crp)],
        f"o{cbc}_use": "1", f"o{cbc}_a_{bench['hb']}": "12.4",
        f"o{crp}_a_{bench['crp_a']}": "3"})          # the CRP left unticked
    with bench["app"].app_context():
        hb = [v for v in _row(bench, cbc).analyte_values if v.analyte_id == bench["hb"]]
        assert hb and hb[0].value == 12.4 and hb[0].flag == "normal", "the bench's own save"
        assert not _row(bench, crp).analyte_values, "an unticked test is not saved"
        from app.models import PatientAttachment
        assert bench["db"].session.get(PatientAttachment, paper).investigation_id == cbc


def test_a_paper_uploaded_there_is_kept_on_the_child_and_read(bench, monkeypatch):
    from app.models import PatientAttachment
    from app.utils.uploads import docs_dir

    _ai(bench)
    cbc = _order(bench, "cbc", collected_minutes_ago=60)
    visit = _second_visit(bench)
    _answer(monkeypatch, '{"t%d.%d": "11"}' % (cbc, bench["hb"]))
    page = bench["sign_in"]("doc").post(
        f"/visits/{visit}/read-paper-all",
        data={"file": (io.BytesIO(PNG), "from_whatsapp.png")},
        content_type="multipart/form-data").get_data(as_text=True)
    assert "data-found" in page
    with bench["app"].app_context():
        row = PatientAttachment.query.filter_by(original_name="from_whatsapp.png").one()
        _WRITTEN.append(os.path.join(docs_dir(), row.filename))
        assert row.patient_id == bench["ids"]["child"]


def test_never_without_the_clinic_s_consent(bench, monkeypatch):
    _ai(bench, consent=False)
    _order(bench, "cbc", collected_minutes_ago=60)
    paper = _loose_paper(bench)
    visit = _second_visit(bench)
    calls = _answer(monkeypatch, "{}")
    bench["sign_in"]("doc").post(f"/visits/{visit}/read-paper-all", data={"attachment_id": str(paper)})
    assert not calls, "the paper never left the clinic"


def test_another_child_s_paper_is_refused(bench, monkeypatch):
    from app.models import Patient, PatientAttachment

    _ai(bench)
    _order(bench, "cbc", collected_minutes_ago=60)
    paper = _loose_paper(bench)
    with bench["app"].app_context():
        from datetime import date
        other = Patient(patient_number="X2", full_name="طفل تاني", gender="male",
                        date_of_birth=date(2022, 1, 1), is_active=True)
        bench["db"].session.add(other)
        bench["db"].session.flush()
        bench["db"].session.get(PatientAttachment, paper).patient_id = other.id
        bench["db"].session.commit()
    visit = _second_visit(bench)
    calls = _answer(monkeypatch, "{}")
    bench["sign_in"]("doc").post(f"/visits/{visit}/read-paper-all", data={"attachment_id": str(paper)})
    assert not calls
