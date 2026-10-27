"""تقرير التقييم للأهل (ASSESSMENTS_PLAN.md ت-٣).

The same road as the lab result (م-٤):

* only after the doctor approved it — a draft never leaves;
* a link that asks the child's date of birth when the clinic is online, and
  the report itself as a file when it is not;
* Arabic and English in one page, printable, and self-contained;
* the link ends, five wrong answers lock it, and a second working link for
  the same assessment is not sent.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

from tests.test_an_assessment_the_specialist_writes import _start, neuro  # noqa: E402,F401

BORN = "2025-01-01"          # the test child's date of birth (conftest)


@pytest.fixture()
def family(neuro):
    from app.models import Patient, Setting

    with neuro["app"].app_context():
        Setting.set("wa_public_base_url", "https://clinic.example.com")
        child = neuro["db"].session.get(Patient, neuro["ids"]["child"])
        child.own_phone, child.full_name = "01001234567", "سليم وجدي"
        neuro["db"].session.commit()
    return neuro


def _approved(c):
    aid = _start(c, kind="autism")
    psy = c["sign_in"]("psy")
    psy.post(f"/assessments/{aid}/save", data={
        "stage": "initial", "domains": ["social"], "use_mchat_rf": "1", "t_mchat_rf_total": "4",
        "impression": "تأخر في التواصل الاجتماعي", "then": "review"})
    c["sign_in"]("doc").post(f"/assessments/{aid}/approve", data={"doctor_note": "نكمّل بتقييم تفصيلي"})
    return aid


def _shares(c):
    from app.models import AssessmentShare

    with c["app"].app_context():
        return [(s.mode, s.token, s.assessment_id) for s in AssessmentShare.query.all()]


def test_a_draft_never_leaves(family):
    aid = _start(family, kind="autism")
    page = family["sign_in"]("doc").get(f"/assessments/{aid}").get_data(as_text=True)
    assert "data-send-family" not in page
    family["sign_in"]("doc").post(f"/assessments/{aid}/send")
    assert _shares(family) == []
    assert family["sign_in"]("doc").get(f"/assessments/{aid}/sheet").status_code == 404


def test_online_a_link_that_asks_the_date_of_birth(family):
    from app.models import MessageLog

    aid = _approved(family)
    doc = family["sign_in"]("doc")
    assert "data-send-family" in doc.get(f"/assessments/{aid}").get_data(as_text=True)
    doc.post(f"/assessments/{aid}/send")
    [(mode, token, said)] = _shares(family)
    assert mode == "link" and said == aid
    with family["app"].app_context():
        log = MessageLog.query.one()
        assert log.template_type == "assessment_report"
        assert f"/assessments/r/{token}" in log.body and "4" not in log.body.split("/assessments/r/")[0], \
            "no score in the message, only the link"

    doc.post(f"/assessments/{aid}/send")
    assert len(_shares(family)) == 1, "a second working link is not sent"

    anon = family["app"].test_client()
    page = anon.get(f"/assessments/r/{token}").get_data(as_text=True)
    assert "data-public-ask" in page and "mchat" not in page
    page = anon.post(f"/assessments/r/{token}", data={"born": "2020-01-01"}).get_data(as_text=True)
    assert "data-public-wrong" in page
    page = anon.post(f"/assessments/r/{token}", data={"born": BORN}).get_data(as_text=True)
    assert page.startswith("<!doctype html>") and "data-assessment-sheet" in page
    assert 'data-sheet-tool="mchat_rf"' in page and "نكمّل بتقييم تفصيلي" in page
    assert 'data-lang="ar"' in page and 'data-lang="en"' in page and "data-print" in page
    assert "<link " not in page and 'src="http' not in page, "self-contained"
    assert anon.get("/assessments/r/nothing-here").status_code == 404


def test_five_wrong_answers_lock_the_link(family):
    aid = _approved(family)
    family["sign_in"]("doc").post(f"/assessments/{aid}/send")
    [(_m, token, _a)] = _shares(family)
    anon = family["app"].test_client()
    for _ in range(5):
        anon.post(f"/assessments/r/{token}", data={"born": "2019-02-02"})
    assert anon.get(f"/assessments/r/{token}").status_code == 410
    assert anon.post(f"/assessments/r/{token}", data={"born": BORN}).status_code == 410


def test_offline_the_report_goes_as_a_file(family):
    from app.models import MessageLog, Setting

    with family["app"].app_context():
        Setting.set("wa_public_base_url", "")
        family["db"].session.commit()
    aid = _approved(family)
    doc = family["sign_in"]("doc")
    doc.post(f"/assessments/{aid}/send")
    [(mode, _t, _a)] = _shares(family)
    assert mode == "file"
    with family["app"].app_context():
        assert MessageLog.query.one().template_type == "assessment_report_file"
    got = doc.get(f"/assessments/{aid}/sheet")
    assert got.status_code == 200 and "attachment" in got.headers["Content-Disposition"]
    assert 'data-sheet-tool="mchat_rf"' in got.get_data(as_text=True)


def test_no_phone_nothing_goes(family):
    from app.models import Patient

    with family["app"].app_context():
        child = family["db"].session.get(Patient, family["ids"]["child"])
        child.own_phone = None
        child.phone = None if hasattr(child, "phone") else None
        family["db"].session.commit()
        has_phone = bool(child.contact_phone)
    if has_phone:
        return
    aid = _approved(family)
    page = family["sign_in"]("doc").post(f"/assessments/{aid}/send", follow_redirects=True).get_data(as_text=True)
    assert "مفيش رقم تليفون" in page and _shares(family) == []
