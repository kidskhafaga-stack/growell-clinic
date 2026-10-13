"""رعاية نهاية الحياة — GAHAR CSS.04.

* الخطة بأهداف الرعاية واتقرّرت مع مين (القرار المشترك)؛
* مراجعة الأعراض: الموجود منها محتاج اللي اتعمل، ومفيش مقياس من عندنا.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402,F401

from tests.test_the_chart_nobody_read import _admit, _child, ward  # noqa: E402,F401


def test_goals_decided_with_the_family_and_symptoms_reviewed(ward):
    from app.models import PalliativePlan, PalliativeReview

    stay = _admit(ward, _child(ward, "مريم"))
    boss = ward["sign_in"]("boss")
    boss.post(f"/beds/admission/{stay}/palliative/plan", data={"goals": "راحة الطفل"})
    with ward["app"].app_context():
        assert PalliativePlan.query.count() == 0, "decided with whom"
    boss.post(f"/beds/admission/{stay}/palliative/plan",
              data={"goals": "راحة الطفل ووقف التدخلات اللي ما بتفيدش", "decided_with": "الأب والأم",
                    "support": "طلبوا شيخ"})
    boss.post(f"/beds/admission/{stay}/palliative/review", data={"present": ["pain", "dyspnea"]})
    with ward["app"].app_context():
        assert PalliativeReview.query.count() == 0, "a present symptom needs what was done"
    boss.post(f"/beds/admission/{stay}/palliative/review",
              data={"present": ["pain", "dyspnea"], "action": "مورفين بأمر الطبيب وأكسجين"})
    with ward["app"].app_context():
        assert PalliativeReview.query.one().present_list == ["pain", "dyspnea"]
    page = boss.get(f"/beds/admission/{stay}").get_data(as_text=True)
    assert "data-pall-plan" in page and "palliative: 'care'" in page and "الأب والأم" in page
