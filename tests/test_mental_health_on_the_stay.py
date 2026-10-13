"""الصحة النفسية على الإقامة — GAHAR CSS.11 (ب)(ح).

* فحص خطر إيذاء النفس أو الغير بأداة المستشفى، و«في خطر» محتاج خطة؛
* التهدئة السريعة بتتسجّل بالمتابعة بعدها؛
* ومش بتبقى «ناقص» على لوحات المخاطر التلاتة لأي طفل.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402,F401

from tests.test_the_chart_nobody_read import _admit, _child, ward  # noqa: E402,F401


def test_screened_with_a_plan_and_tranquilization_recorded(ward):
    from app.models import RapidTranquilization, RiskAssessment
    from app.models.admission import Admission
    from app.utils import risks

    stay = _admit(ward, _child(ward, "عمر", days=4500))
    boss = ward["sign_in"]("boss")
    boss.post("/beds/harm-screen/tool", data={"tool": "ASQ"})
    boss.post(f"/beds/admission/{stay}/harm-screen", data={"at_risk": "yes"})
    with ward["app"].app_context():
        assert RiskAssessment.query.filter_by(kind="self_harm").count() == 0, "at risk needs a plan"
    boss.post(f"/beds/admission/{stay}/harm-screen", data={"at_risk": "yes", "level": "إيجابي",
                                                         "plan": "مراقبة مستمرة وإبعاد الأدوات", "family_told": "1"})
    boss.post(f"/beds/admission/{stay}/tranquilization", data={"reason": "هياج شديد", "given": "Midazolam IM"})
    boss.post(f"/beds/admission/{stay}/tranquilization", data={"reason": "هياج شديد", "given": "Midazolam IM",
                                                              "monitoring": "نبض وتشبع كل ١٥ دقيقة لمدة ساعة"})
    with ward["app"].app_context():
        row = RiskAssessment.query.filter_by(kind="self_harm").one()
        assert row.tool == "ASQ" and row.at_risk is True
        assert RapidTranquilization.query.count() == 1
        kinds = [p["kind"] for p in risks.panel(ward["db"].session.get(Admission, stay))]
        assert "self_harm" not in kinds, "not a gap on every child's risk panel"
    page = boss.get(f"/beds/admission/{stay}").get_data(as_text=True)
    assert "data-harm-risk" in page and "mental: 'treatment'" in page
    # Inside a tab, not floating between two of them — it showed on every tab.
    panel = page[page.index('data-stay-panel="treatment"'):page.index('data-stay-panel="safety"')]
    assert 'id="mental"' in panel
