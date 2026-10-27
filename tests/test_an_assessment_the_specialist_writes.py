"""Assessments for neurology and development — ASSESSMENTS_PLAN.md ت-١.

*«بتاعت الأعصاب شغالة على الحاجات دي وعايز أسهّل استخدامهم … يشيّك حاجة في
التقييم ويحط الدرجات، ويبقى في شكل افتراضي حسب الجايدلاين ويقدر يعدّل هو
عليه.»*

A form per kind (ADHD first) from the guideline; the specialist ticks and
writes scores, the program adds up and shows a tool's own criterion; a draft
goes to a doctor who approves it; it prints; the same tool's earlier values
sit beside it; and the clinic edits the form without touching what was
already written.
"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def neuro(clinic):
    """The specialties module on, and a psychologist holding «assessments»."""
    from app.models import Setting, User, UserCapability

    with clinic["app"].app_context():
        Setting.set("mod_enabled:panels", "1")
        psy = User(username="psy", full_name="أ. سارة", role="nursing", is_active=True)
        psy.set_password("secret")
        clinic["db"].session.add(psy)
        clinic["db"].session.flush()
        clinic["db"].session.add(UserCapability(user_id=psy.id, capability="assessments",
                                                granted_by=clinic["ids"]["admin"]))
        clinic["db"].session.commit()
        clinic["psy"] = psy.id
    return clinic


def _start(c, who="psy", kind="adhd"):
    reply = c["sign_in"](who).post(f"/assessments/patient/{c['ids']['child']}/new",
                                   data={"kind": kind})
    assert reply.status_code == 302, reply.status_code
    return int(reply.headers["Location"].rstrip("/").split("/")[-1])


def _row(c, aid):
    from app.models import Assessment

    with c["app"].app_context():
        row = c["db"].session.get(Assessment, aid)
        return {"status": row.status, "answers": row.answers, "form": row.form,
                "approved_by": row.approved_by}


FILLED = {
    "stage": "detailed", "sources": ["parent", "teacher"],
    "criteria": ["two_settings", "before_12"], "comorbid": ["anxiety"],
    "impression": "قلة انتباه واضحة في البيت والمدرسة", "recommendations": ["school_support"],
    "followup": "2027-01-26",
    "use_vanderbilt_parent": "1", "t_vanderbilt_parent_inattentive": "7",
    "t_vanderbilt_parent_hyperactive": "4", "t_vanderbilt_parent_odd": "٢",
    "use_vanderbilt_teacher": "0", "t_vanderbilt_teacher_inattentive": "9",
}


def test_a_new_adhd_assessment_opens_on_the_guidelines_form(neuro):
    aid = _start(neuro)
    page = neuro["sign_in"]("psy").get(f"/assessments/{aid}").get_data(as_text=True)
    for mark in ('data-section="sources"', 'data-section="criteria"', 'data-tool="vanderbilt_parent"',
                 'data-tool="vanderbilt_teacher"', "AAP", "data-send-review"):
        assert mark in page, mark
    # The commercial tools are one press away, not on the form.
    assert 'data-tool="conners3" hidden' in page


def test_the_specialist_fills_it_and_the_program_only_adds_up(neuro):
    aid = _start(neuro)
    c = neuro["sign_in"]("psy")
    c.post(f"/assessments/{aid}/save", data=dict(FILLED, then="save"))
    row = _row(neuro, aid)
    assert row["status"] == "draft"
    assert row["answers"]["sources"] == ["parent", "teacher"]
    assert row["answers"]["tools"] == {"vanderbilt_parent": {
        "inattentive": 7, "hyperactive": 4, "odd": 2, "conduct": None, "anxiety": None,
        "perf_4": None, "perf_5": None}}                  # the teacher's was not used
    page = c.get(f"/assessments/{aid}").get_data(as_text=True)
    # 7 of 9 meets the scale's 6; 4 does not.
    inatt = page[page.index('id="t_vanderbilt_parent_inattentive"'):]
    assert "data-meets-mark>" in inatt[:inatt.index("</div>")]
    hyper = page[page.index('id="t_vanderbilt_parent_hyperactive"'):]
    assert "data-meets-mark hidden" in hyper[:hyper.index("</div>")]


def test_a_count_beyond_its_scale_or_a_word_is_refused(neuro):
    aid = _start(neuro)
    c = neuro["sign_in"]("psy")
    for bad in ("12", "كتير"):
        c.post(f"/assessments/{aid}/save", data={"use_vanderbilt_parent": "1",
                                                 "t_vanderbilt_parent_inattentive": bad})
        assert _row(neuro, aid)["answers"] == {}


def test_a_doctor_approves_it_and_then_it_no_longer_changes(neuro):
    aid = _start(neuro)
    neuro["sign_in"]("psy").post(f"/assessments/{aid}/save", data=dict(FILLED, then="review"))
    assert _row(neuro, aid)["status"] == "review"
    # The specialist cannot approve; the doctor sees it waiting.
    neuro["sign_in"]("psy").post(f"/assessments/{aid}/approve")
    assert _row(neuro, aid)["status"] == "review"
    doc = neuro["sign_in"]("doc")
    assert f'data-review-row="{aid}"' in doc.get("/assessments/review").get_data(as_text=True)
    doc.post(f"/assessments/{aid}/approve", data={"doctor_note": "متفق — نبدأ بدعم المدرسة"})
    row = _row(neuro, aid)
    assert row["status"] == "approved" and row["approved_by"] == neuro["ids"]["doctor"]
    neuro["sign_in"]("psy").post(f"/assessments/{aid}/save", data={"impression": "تغيير"})
    assert _row(neuro, aid)["answers"]["impression"] == FILLED["impression"]
    page = doc.get(f"/assessments/{aid}").get_data(as_text=True)
    assert "data-approved-by" in page and "data-assessment-form" in page and "data-send-review" not in page


def test_the_report_prints_the_scores_the_criterion_and_the_approval(neuro):
    aid = _start(neuro)
    neuro["sign_in"]("psy").post(f"/assessments/{aid}/save", data=dict(FILLED, then="review"))
    doc = neuro["sign_in"]("doc")
    page = doc.get(f"/assessments/{aid}/report").get_data(as_text=True)
    assert "data-report-unapproved" in page and 'data-report-tool="vanderbilt_parent"' in page
    assert 'data-report-tool="vanderbilt_teacher"' not in page
    doc.post(f"/assessments/{aid}/approve")
    page = doc.get(f"/assessments/{aid}/report").get_data(as_text=True)
    assert "data-report-unapproved" not in page and "window.print()" in page


def test_the_same_tools_earlier_values_sit_beside_it(neuro):
    from app.models import Assessment

    first = _start(neuro)
    neuro["sign_in"]("psy").post(f"/assessments/{first}/save", data=dict(FILLED, then="review"))
    neuro["sign_in"]("doc").post(f"/assessments/{first}/approve")
    with neuro["app"].app_context():
        neuro["db"].session.get(Assessment, first).assessed_on = date(2026, 3, 1)
        neuro["db"].session.commit()
    second = _start(neuro)
    neuro["sign_in"]("psy").post(f"/assessments/{second}/save", data=dict(
        FILLED, t_vanderbilt_parent_inattentive="5"))
    page = neuro["sign_in"]("psy").get(f"/assessments/{second}").get_data(as_text=True)
    # The earlier value and today's on one line, with which way it went
    # (ت-٥: fewer symptoms on this scale is better).
    assert 'data-trend="vanderbilt_parent.inattentive"' in page
    assert "<title>2026-03-01: 7</title>" in page and 'data-trend-chip="better"' in page


def test_the_clinic_edits_the_form_and_an_old_assessment_keeps_its_own(neuro):
    old = _start(neuro)
    c = neuro["sign_in"]("psy")
    c.post("/assessments/form/adhd/option-add", data={"section": "comorbid", "label": "صرع"})
    c.post("/assessments/form/adhd/option-remove", data={"section": "sources", "option": "child"})
    c.post("/assessments/form/adhd/tool-place", data={"tool": "conners3", "where": "shown"})
    c.post("/assessments/form/adhd/field", data={"tool": "vanderbilt_parent", "field": "perf_4",
                                                 "label": "بنود الأداء بدرجة ٤", "meets": "2"})
    c.post("/assessments/form/adhd/tool-add", data={"name": "مقياس العيادة للانتباه",
                                                    "fields": "الانتباه\nالتركيز"})
    new = _start(neuro)
    form = _row(neuro, new)["form"]
    sections = {s["key"]: s for s in form["sections"]}
    assert "صرع" in [o["ar"] for o in sections["comorbid"]["options"]]
    assert "child" not in [o["key"] for o in sections["sources"]["options"]]
    assert "conners3" in sections["tools"]["shown"]
    own = [k for k in form["tool_defs"] if k.startswith("clinic_")]
    assert len(own) == 1 and [f["ar"] for f in form["tool_defs"][own[0]]["fields"]] == ["الانتباه", "التركيز"]
    perf = [f for f in form["tool_defs"]["vanderbilt_parent"]["fields"] if f["key"] == "perf_4"][0]
    assert perf["meets"] == 2
    # The one started before keeps the form it was started on.
    old_sections = {s["key"]: s for s in _row(neuro, old)["form"]["sections"]}
    assert "child" in [o["key"] for o in old_sections["sources"]["options"]]
    # An own tool switched off is not lost.
    c.post("/assessments/form/adhd/tool-place", data={"tool": own[0], "where": "off"})
    c.post("/assessments/form/adhd/tool-place", data={"tool": own[0], "where": "shown"})
    assert own[0] in _row(neuro, _start(neuro))["form"]["tool_defs"]
    # And back to the default.
    c.post("/assessments/form/adhd/reset")
    fresh = {s["key"]: s for s in _row(neuro, _start(neuro))["form"]["sections"]}
    assert "child" in [o["key"] for o in fresh["sources"]["options"]]
    page = c.get("/assessments/form/adhd").get_data(as_text=True)
    assert "data-form-default" in page


def test_who_may_open_write_and_approve(neuro):
    from app.models import Setting

    assert neuro["sign_in"]("desk").get(f"/assessments/patient/{neuro['ids']['child']}").status_code == 403
    assert neuro["sign_in"]("desk").post(f"/assessments/patient/{neuro['ids']['child']}/new",
                                         data={"kind": "adhd"}).status_code == 403
    assert neuro["sign_in"]("acct").get("/assessments/form/adhd").status_code == 403
    # The door on the child's file, and none without the module.
    profile = neuro["sign_in"]("doc").get(f"/patients/{neuro['ids']['child']}").get_data(as_text=True)
    assert "data-to-assessments" in profile
    with neuro["app"].app_context():
        Setting.set("mod_enabled:panels", "0")
        neuro["db"].session.commit()
    assert neuro["sign_in"]("doc").get(f"/assessments/patient/{neuro['ids']['child']}").status_code == 404
    profile = neuro["sign_in"]("doc").get(f"/patients/{neuro['ids']['child']}").get_data(as_text=True)
    assert "data-to-assessments" not in profile


def test_the_bell_tells_the_doctor(neuro):
    from app.models import User
    from app.utils.notifications import get_notifications

    aid = _start(neuro)
    neuro["sign_in"]("psy").post(f"/assessments/{aid}/save", data=dict(FILLED, then="review"))
    with neuro["app"].test_request_context():
        doc = neuro["db"].session.get(User, neuro["ids"]["doctor"])
        psy = neuro["db"].session.get(User, neuro["psy"])
        assert any(i["key"] == "assessments_review" for i in get_notifications(doc))
        assert not any(i["key"] == "assessments_review" for i in get_notifications(psy))
