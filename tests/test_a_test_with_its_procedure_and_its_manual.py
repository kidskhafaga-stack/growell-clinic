"""The laboratory's documents about its own tests — GAHAR DAS.17, DAS.16,
DAS.14 evidence 2 and DAS.10 evidence 3–4.

* **the procedure** — the version in force, where it is, who approved it,
  when it is due its review; an overdue review shows; old versions stay;
* **the verification** — the laboratory's verdict against its own
  criteria, never the program's; a failed or overdue one shows;
* **read at the bench, written by the head of the laboratory**;
* **the service manual** — printed from the catalogue, for whoever orders,
  with who last reviewed the scope of service.
"""
import os
import sys
from datetime import timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

from tests.test_the_sample_nobody_drew import _order, lab  # noqa: E402,F401


def _proc(c, who="boss", **extra):
    from app.utils.clock import local_today

    data = {"version": "2", "location": "https://drive.example/cbc.pdf",
            "effective_on": local_today().isoformat(), "approved_by": "د. المعمل",
            **extra}
    return c["sign_in"](who).post(f"/labs/tests/{c['urine']}/procedure", data=data)


def test_the_procedure_in_force_and_its_review(lab):
    from app.models import LabProcedure
    from app.utils import lab_documents
    from app.utils.clock import local_today

    today = local_today()
    _proc(lab, version="1", effective_on=(today - timedelta(days=400)).isoformat(),
          review_due=(today - timedelta(days=35)).isoformat())
    with lab["app"].app_context():
        assert lab_documents.procedure_state(
            lab_documents.current_procedure(lab["urine"]), today) == "overdue"
    page = lab["sign_in"]("boss").get("/labs/documents").get_data(as_text=True)
    assert f'data-doc-row="{lab["urine"]}" data-p-state="overdue"' in page

    _proc(lab, review_due=(today + timedelta(days=365)).isoformat())
    with lab["app"].app_context():
        assert LabProcedure.query.count() == 2, "old versions stay"
        current = lab_documents.current_procedure(lab["urine"])
        assert current.version == "2"
        assert lab_documents.procedure_state(current, today) == "ok"
    page = lab["sign_in"]("doc").get(f"/labs/tests/{lab['urine']}/documents").get_data(as_text=True)
    assert "data-procedure-link" in page and "https://drive.example/cbc.pdf" in page

    # A review before the procedure is even in force is refused.
    _proc(lab, version="3", review_due=(today - timedelta(days=1)).isoformat())
    with lab["app"].app_context():
        assert LabProcedure.query.count() == 2


def test_a_place_is_shown_as_words_and_never_as_a_link(lab):
    _proc(lab, location="javascript:alert(1)")
    page = lab["sign_in"]("boss").get(f"/labs/tests/{lab['urine']}/documents").get_data(as_text=True)
    assert "data-procedure-link" not in page and 'href="javascript' not in page


def test_the_verification_is_the_lab_s_verdict(lab):
    from app.models import MethodCheck
    from app.utils import lab_documents
    from app.utils.clock import local_today

    today = local_today()
    boss = lab["sign_in"]("boss")
    url = f"/labs/tests/{lab['urine']}/method-check"
    base = {"kind": "verification", "done_on": today.isoformat(),
            "summary": "الدقة قصاد معايير المعمل", "signed_by": "د. المعمل"}
    boss.post(url, data=base)
    with lab["app"].app_context():
        assert MethodCheck.query.count() == 0, "no verdict, no record"
    boss.post(url, data={**base, "accepted": "0"})
    with lab["app"].app_context():
        assert lab_documents.check_state(
            lab_documents.latest_check(lab["urine"]), today) == "failed"
    boss.post(url, data={**base, "accepted": "1",
                         "due_again": (today + timedelta(days=365)).isoformat()})
    with lab["app"].app_context():
        assert lab_documents.check_state(
            lab_documents.latest_check(lab["urine"]), today) == "ok"
        later = today + timedelta(days=400)
        assert lab_documents.check_state(
            lab_documents.latest_check(lab["urine"]), later) == "overdue"


def test_read_at_the_bench_and_written_by_the_head_of_the_lab(lab):
    from app.models import LabProcedure, UserCapability

    _proc(lab, who="doc")
    with lab["app"].app_context():
        assert LabProcedure.query.count() == 0
    page = lab["sign_in"]("doc").get(f"/labs/tests/{lab['urine']}/documents").get_data(as_text=True)
    assert "data-procedure-form" not in page
    with lab["app"].app_context():
        lab["db"].session.add(UserCapability(user_id=lab["ids"]["doctor"],
                                             capability="lab_release"))
        lab["db"].session.commit()
    _proc(lab, who="doc")
    with lab["app"].app_context():
        assert LabProcedure.query.count() == 1
    # And the bench reaches it from the order it is working on.
    order = _order(lab, name="تحليل بول", test="urine")
    page = lab["sign_in"]("boss").get(f"/labs/order/{order}").get_data(as_text=True)
    assert "data-to-procedure" in page


def test_the_manual_is_the_catalogue_for_whoever_orders(lab):
    from app.models import Investigation

    with lab["app"].app_context():
        row = lab["db"].session.get(Investigation, lab["urine"])
        row.preparation = "عينة الصبح الأولى"
        row.tube = "كوباية معقّمة"
        lab["db"].session.commit()
    page = lab["sign_in"]("doc").get("/labs/manual").get_data(as_text=True)
    assert f'data-manual-row="{lab["urine"]}"' in page
    assert "عينة الصبح الأولى" in page and "كوباية معقّمة" in page
    assert "data-scope-form" not in page
    visit = lab["sign_in"]("doc").get(f"/visits/{lab['ids']['visit']}/record").get_data(as_text=True)
    assert "data-to-lab-manual" in visit


def test_the_scope_of_service_says_who_reviewed_it(lab):
    from app.utils import lab_documents

    boss = lab["sign_in"]("boss")
    page = boss.get("/labs/manual").get_data(as_text=True)
    assert "data-scope-form" in page
    lab["sign_in"]("doc").post("/labs/manual/reviewed")
    with lab["app"].app_context():
        assert lab_documents.scope_reviewed() == (None, None)
    boss.post("/labs/manual/reviewed")
    with lab["app"].app_context():
        day, who = lab_documents.scope_reviewed()
        assert day is not None and who == "المدير"


def test_the_doors_lead_to_it(lab):
    boss = lab["sign_in"]("boss")
    rack = boss.get("/labs/").get_data(as_text=True)
    assert "data-to-documents" in rack
    assert "data-to-manual" in boss.get("/labs/documents").get_data(as_text=True)
    assert "data-to-test-documents" in boss.get(
        f"/labs/tests/{lab['urine']}/ranges").get_data(as_text=True)
