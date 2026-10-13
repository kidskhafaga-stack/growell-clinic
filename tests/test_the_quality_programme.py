"""برنامج الجودة — GAHAR QPI.01، QPI.05–09، QPI.11، QPI.12.

* المؤشر بكارت تعريفه والقيم بالبسط والمقام، والهدف بتاع المستشفى؛
* سجل المخاطر: العالي محتاج خطة تقليل؛ والتقييم الاستباقي السنوي باين لو ناقص؛
* المشاريع: ما تتقفلش من غير نتيجة، ومشروع ترشيد كل سنة؛
* اللجنة والتقييم الذاتي؛ ومواعيد الحدث الجسيم من البند نفسه؛
* للفريق بس (صلاحية الجودة)، والباب من لوحة البلاغات.
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402,F401


def test_a_measure_with_its_sheet_values_and_target(clinic):
    from app.models import MeasureValue, PerformanceMeasure

    boss = clinic["sign_in"]("boss")
    boss.post("/quality/measures", data={"name": "انتظار الطوارئ", "kind": "clinical", "area": "waiting"})
    with clinic["app"].app_context():
        assert PerformanceMeasure.query.count() == 0, "the sheet needs its elements"
    boss.post("/quality/measures", data={"name": "انتظار الطوارئ", "kind": "clinical", "area": "waiting",
                                         "definition": "نسبة اللي استنوا أكتر من الحد", "data_source": "سجل الطوارئ",
                                         "frequency": "شهري", "numerator": "اللي استنوا أكتر", "denominator": "كل الزيارات",
                                         "per": "100", "target": "10", "higher_better": "0"})
    with clinic["app"].app_context():
        mid = PerformanceMeasure.query.one().id
    boss.post(f"/quality/measure/{mid}", data={"period": "2026-08", "numerator": "5"})
    with clinic["app"].app_context():
        assert MeasureValue.query.count() == 0, "a measure with a denominator needs one"
    boss.post(f"/quality/measure/{mid}", data={"period": "2026-08", "numerator": "5", "denominator": "100"})
    boss.post(f"/quality/measure/{mid}", data={"period": "2026-09", "numerator": "15", "denominator": "100", "validated": "1"})
    page = boss.get(f"/quality/measure/{mid}").get_data(as_text=True)
    assert "data-chart" in page and "data-off-target" in page
    assert "data-to-quality" in boss.get("/incidents/").get_data(as_text=True)


def test_risks_projects_and_committee(clinic):
    from app.models import ImprovementProject, QualitySelfEvaluation, RiskItem

    boss = clinic["sign_in"]("boss")
    assert "data-no-proactive" in boss.get("/quality/risks").get_data(as_text=True)
    boss.post("/quality/risks", data={"what": "risk", "title": "انقطاع الأكسجين", "category": "clinical",
                                      "owner": "الصيانة", "high": "1"})
    with clinic["app"].app_context():
        assert RiskItem.query.count() == 0, "a high risk needs a mitigation"
    boss.post("/quality/risks", data={"what": "risk", "title": "انقطاع الأكسجين", "category": "clinical",
                                      "owner": "الصيانة", "high": "1", "mitigation": "خزان احتياطي"})
    boss.post("/quality/risks", data={"what": "proactive", "year": str(datetime.utcnow().year),
                                      "process": "صرف الأدوية عالية الخطورة", "tool": "FMEA", "findings": "خطوة التحقق ناقصة"})
    assert "data-no-proactive" not in boss.get("/quality/risks").get_data(as_text=True)
    boss.post("/quality/projects", data={"title": "تقليل التحاليل المكررة", "problem": "تكرار", "aim": "أقل ٢٠٪",
                                         "utilization": "1"})
    with clinic["app"].app_context():
        pid = ImprovementProject.query.one().id
    boss.post(f"/quality/project/{pid}", data={"close": "1"})
    with clinic["app"].app_context():
        assert clinic["db"].session.get(ImprovementProject, pid).closed_on is None, "not closed without a result"
    assert "data-no-utilization" not in boss.get("/quality/projects").get_data(as_text=True)
    boss.post("/quality/committee", data={"held_on": "2026-10-01", "attendees": "المدير، الجودة", "minutes": "مراجعة المؤشرات",
                                          "decision": ["متابعة الانتظار"], "owner": ["الطوارئ"], "due_on": [""]})
    boss.post("/quality/evaluation/2026", data={"text": "اللجنة اتقابلت ١٠ مرات"})
    with clinic["app"].app_context():
        assert QualitySelfEvaluation.query.filter_by(year=2026).one()
    assert clinic["sign_in"]("desk").get("/quality/measures").status_code == 403


def test_the_sentinel_clocks(clinic):
    from app.models.incident import SENTINEL, Incident
    from app.utils import incidents

    with clinic["app"].app_context():
        row = Incident(number="INC-T-1", occurred_at=datetime.utcnow() - timedelta(days=50),
                       reported_at=datetime.utcnow() - timedelta(days=50), category="clinical",
                       affected="patient", what_happened="x", classification=SENTINEL)
        clock = incidents.sentinel_clock(row)
        assert clock["gahar_late"] and clock["rca_late"]
        row.external_report = "اتبلّغت GAHAR برقم ٥"
        row.root_cause = "خطوة التحقق"
        row.action = "تعديل الإجراء"
        clock = incidents.sentinel_clock(row)
        assert not clock["gahar_late"] and not clock["rca_late"]
