"""فرز السقوط في العيادة — GAHAR `ICD.10` / `GSR.05` دليل ٤.

* **مقفول لحد ما المستشفى تشغّله** وتكتب معاييرها — وشاشة الزيارة زي ما هي؛
* **المعايير بتاعة المستشفى**، والبرنامج ما عندوش قايمة؛
* معيار بينطبق = إيجابي، ولازم الأهل يتبلّغوا (دليل ٥)، والإجراءات العامة
  بتتنسخ في السجل (دليل ٦)؛ ومن غير معيار = سلبي ومتسجل إنه اتبص عليه؛
* التقرير بالفترة: اتفرز كام، إيجابي كام، الأهل اتبلّغوا في كام.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

CRITERIA = "دوخة أو إغماء\nبعد تهدئة\nإعاقة حركية"


def _policy(c, on=True, criteria=CRITERIA, measures="سرير بحواجز، والأهل جنبه"):
    return c["sign_in"]().post("/settings/risks", data={
        "on_fall": "1", "on_pressure": "1", "on_vte": "1",
        "fall_outpatient": "1" if on else "", "fall_outpatient_criteria": criteria,
        "fall_outpatient_measures": measures})


def _record(c, who="doc"):
    return c["sign_in"](who).get(f"/visits/{c['ids']['visit']}/record").get_data(as_text=True)


def _screen(c, who="doc", **form):
    return c["sign_in"](who).post(f"/visits/{c['ids']['visit']}/fall-screen", data=form)


def test_off_the_visit_is_exactly_as_it_was(clinic):
    assert "data-fall-screen" not in _record(clinic)
    # Switched on with no criteria written: still nothing to ask.
    _policy(clinic, criteria="")
    assert "data-fall-screen" not in _record(clinic)
    _screen(clinic, criteria=["بعد تهدئة"], family_told="1")
    from app.models import RiskAssessment

    with clinic["app"].app_context():
        assert RiskAssessment.query.count() == 0


def test_the_criteria_are_the_hospital_s_own(clinic):
    _policy(clinic)
    page = _record(clinic)
    assert "data-fall-screen" in page
    for line in CRITERIA.splitlines():
        assert line in page
    settings = clinic["sign_in"]().get("/settings/risks").get_data(as_text=True)
    assert "data-fall-outpatient-policy" in settings and "بعد تهدئة" in settings


def test_a_positive_screening_needs_the_family_told(clinic):
    from app.models import RiskAssessment

    _policy(clinic)
    _screen(clinic, criteria=["بعد تهدئة", "مش من المعايير"])
    with clinic["app"].app_context():
        assert RiskAssessment.query.count() == 0
    _screen(clinic, criteria=["بعد تهدئة", "مش من المعايير"], family_told="1",
            note="نزل من السرير مرتين")
    with clinic["app"].app_context():
        row = RiskAssessment.query.one()
        assert row.kind == "fall" and row.admission_id is None
        assert row.visit_id == clinic["ids"]["visit"]
        assert row.at_risk is True and row.family_told is True
        assert row.criteria == "بعد تهدئة", "only the hospital's own criteria"
        assert row.general_measures == "سرير بحواجز، والأهل جنبه"
        assert row.plan == "نزل من السرير مرتين"
    page = _record(clinic)
    assert 'data-fall-result="positive"' in page


def test_nothing_ticked_is_a_negative_screening_on_record(clinic):
    from app.models import RiskAssessment

    _policy(clinic)
    _screen(clinic)
    with clinic["app"].app_context():
        row = RiskAssessment.query.one()
        assert row.at_risk is False and row.criteria is None
        assert row.general_measures is None and row.family_told is None
    assert 'data-fall-result="negative"' in _record(clinic)


def test_the_report_counts_screened_positive_and_told(clinic):
    from app.utils import fall_screen
    from app.utils.clock import local_today

    _policy(clinic)
    _screen(clinic)
    _screen(clinic, criteria=["دوخة أو إغماء", "إعاقة حركية"], family_told="1")
    with clinic["app"].app_context():
        data = fall_screen.report(local_today(), local_today())
        # The same visit screened twice is one visit, read by its last word.
        assert data["screened"] == 1 and data["positive"] == 1 and data["told"] == 1
        assert dict(data["criteria"]) == {"دوخة أو إغماء": 1, "إعاقة حركية": 1}
    page = clinic["sign_in"]().get("/visits/fall-screening").get_data(as_text=True)
    assert "data-fall-summary" in page and "data-n-told" in page
    assert "data-fall-off" not in page


def test_the_report_says_when_it_is_off(clinic):
    page = clinic["sign_in"]().get("/visits/fall-screening").get_data(as_text=True)
    assert "data-fall-off" in page
