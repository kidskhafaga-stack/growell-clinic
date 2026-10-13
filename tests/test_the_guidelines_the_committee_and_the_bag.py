"""الأدلة الإكلينيكية، ولجنة مركزية المريض، وتفاعل نقل الدم.

* **ICD.16 / ICD.04**: الدليل بمصدره واعتماده وتدريبه ومراجعته كل سنتين
  (رقم المعيار)، والتلاتة في السنة (رقم المعيار)، والطوارئ اللي مالهاش دليل
  بتبان من غير ما تتحسب غلط. والمكتبة لأي حد، والتعديل للجودة بس.
* **PCC.01**: لجنة مركزية المريض بمحاضرها لوحدها، وكل ربع سنة.
* **PCC.03 / ICD.01**: نوع «حقوق المريض» في البلاغ.
* **ICD.21**: التفاعل بيفضل ظاهر لحد ما يتبلّغ لبنك الدم والجودة.
"""
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402,F401

from tests.test_the_chart_nobody_read import _admit, _child, ward  # noqa: E402,F401


def test_a_guideline_its_training_its_review_and_the_library(clinic):
    from app.models import ClinicalGuideline
    from app.utils import guidelines as cpg

    boss = clinic["sign_in"]("boss")
    boss.post("/quality/guidelines", data={"title": "الربو الحاد", "scope": "emergency",
                                           "adopted_on": "2026-01-10"})
    with clinic["app"].app_context():
        assert ClinicalGuideline.query.count() == 0, "who approved it"
    boss.post("/quality/guidelines", data={"title": "الربو الحاد عند الأطفال", "scope": "emergency",
                                           "topic": "asthma", "approved_by": "المدير الطبي",
                                           "adopted_on": "2024-01-10", "source": "GINA",
                                           "link": "javascript:alert(1)"})
    with clinic["app"].app_context():
        g = ClinicalGuideline.query.one()
        assert g.review_due == date(2026, 1, 10), "the standard's two years"
        state = cpg.board(date(2026, 3, 1))
        assert g.id in state["overdue"] and state["this_year"] == 0 and state["per_year"] == 3
        assert "asthma" not in state["uncovered"] and "shock" in state["uncovered"]
        gid = g.id
    page = boss.get("/quality/guidelines").get_data(as_text=True)
    assert 'href="javascript' not in page, "a link that is not http(s) is shown as text, never followed"
    boss.post(f"/quality/guideline/{gid}/event", data={"kind": "training", "held_on": "2026-02-01",
                                                      "note": "١٢ ممرضة وطبيبين"})
    boss.post(f"/quality/guideline/{gid}/event", data={"kind": "review", "held_on": "2026-02-15",
                                                      "note": "اتحدّث بنسخة ٢٠٢٥"})
    with clinic["app"].app_context():
        g = clinic["db"].session.get(ClinicalGuideline, gid)
        assert g.reviewed_on == date(2026, 2, 15) and g.review_due == date(2028, 2, 15)
        assert gid not in cpg.board(date(2026, 3, 1))["untrained"]
    doc = clinic["sign_in"]("doc")
    assert doc.get("/quality/guidelines").status_code == 403
    assert "الربو الحاد عند الأطفال" in doc.get("/quality/guidelines/library").get_data(as_text=True)


def test_the_patient_committee_keeps_its_own_minutes_every_quarter(clinic):
    from app.models.quality import QualityMeeting
    from app.utils import quality as q

    boss = clinic["sign_in"]("boss")
    page = boss.get("/quality/committee?c=patient").get_data(as_text=True)
    assert "data-quarter-late" in page and "data-q-evaluation" not in page
    boss.post("/quality/committee?c=patient", data={
        "committee": "patient", "held_on": date.today().isoformat(), "attendees": "أم مريض، تمريض، استقبال",
        "minutes": "رؤية المركزية", "decision": ["تدريب الاستقبال"], "owner": ["الجودة"], "due_on": [""]})
    with clinic["app"].app_context():
        assert QualityMeeting.query.one().committee == "patient"
        assert q.committee_board("quality")["meetings"] == []
        assert len(q.committee_board("patient")["open"]) == 1
        later = q.committee_board("patient", date.today() + timedelta(days=120))
        assert later["quarter_late"]
    assert "data-quarter-late" not in boss.get("/quality/committee?c=patient").get_data(as_text=True)
    assert "رؤية المركزية" not in boss.get("/quality/committee").get_data(as_text=True)


def test_rights_violations_are_an_incident_kind(clinic):
    from app.i18n import t
    from app.models.incident import CATEGORIES

    assert "patient_rights" in CATEGORIES
    with clinic["app"].test_request_context():
        assert t("incident.c_patient_rights") != "incident.c_patient_rights"


def test_a_transfusion_reaction_stays_loud_until_reported(ward):
    from app.models import Patient
    from app.models.admission import Admission
    from app.models.blood import Transfusion
    from app.utils import blood

    stay = _admit(ward, _child(ward, "مازن"))
    with ward["app"].app_context():
        row = ward["db"].session.get(Admission, stay)
        req = blood.request(ward["db"].session.get(Patient, row.patient_id), "prbc", "أنيميا Hb 5",
                            admission=row)
        ward["db"].session.flush()
        bag = blood.hang(req, unit_code="U1")
        blood.finish(bag, reaction=True, reaction_note="رعشة وحرارة، الكيس اتوقف")
        ward["db"].session.commit()
        bag_id = bag.id
    boss = ward["sign_in"]("boss")
    assert "data-bag-unreported" in boss.get(f"/beds/admission/{stay}").get_data(as_text=True)
    boss.post(f"/beds/transfusion/{bag_id}/reported", data={"reported_to": ""})
    with ward["app"].app_context():
        assert ward["db"].session.get(Transfusion, bag_id).reported_at is None
    boss.post(f"/beds/transfusion/{bag_id}/reported", data={"reported_to": "د. بنك الدم + الجودة"})
    page = boss.get(f"/beds/admission/{stay}").get_data(as_text=True)
    assert "data-bag-unreported" not in page and "data-bag-reported" in page
