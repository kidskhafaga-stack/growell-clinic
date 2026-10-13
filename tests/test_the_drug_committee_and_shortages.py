"""لجنة الدواء ونقص الأدوية — GAHAR MMS.01 دليل ٣ و٥، MMS.03 دليل ٥ و٦.

* الاجتماع بالحضور والمحضر، والقرار محتاج مسؤول، والإضافة/الحذف من الدليل محتاجة المادة؛
* المراجعة السنوية بالعناصر (أ–ز)؛
* النقص بيتعلن للأطباء في الجرس ويقروه، ولما يرجع بيختفي.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402,F401

from tests.test_the_chart_nobody_read import ward  # noqa: E402,F401


def test_meeting_decisions_and_the_annual_review(ward):
    from app.models import DtcAnnualReview, DtcDecision, DtcMeeting, GenericDrug

    with ward["app"].app_context():
        g = GenericDrug(name_en="cefepime", name_ar="سيفيبيم")
        ward["db"].session.add(g)
        ward["db"].session.commit()
        gid = g.id
    chem = ward["sign_in"]("chem")
    chem.post("/pharmacy/dtc/meeting", data={"held_on": "2026-10-01", "attendees": "د. هاني، الصيدلي",
                                             "minutes": "مراجعة الدليل", "kind": ["formulary_add"],
                                             "decision": ["إضافة سيفيبيم"], "owner": ["الصيدلية"],
                                             "generic_id": [""], "due_on": [""]})
    with ward["app"].app_context():
        assert DtcMeeting.query.count() == 0, "a formulary decision names its ingredient"
    chem.post("/pharmacy/dtc/meeting", data={"held_on": "2026-10-01", "attendees": "د. هاني، الصيدلي",
                                             "minutes": "مراجعة الدليل", "kind": ["formulary_add"],
                                             "decision": ["إضافة سيفيبيم"], "owner": ["الصيدلية"],
                                             "generic_id": [str(gid)], "due_on": ["2026-10-20"]})
    with ward["app"].app_context():
        d = DtcDecision.query.one()
        assert d.kind == "formulary_add" and d.generic_id == gid
        did = d.id
    chem.post(f"/pharmacy/dtc/decision/{did}/done", data={"note": "اتضاف"})
    chem.post("/pharmacy/dtc/review/2026", data={"storage": "التفتيش الشهري منتظم", "monitoring": "معدّل الأخطاء"})
    with ward["app"].app_context():
        assert DtcDecision.query.one().done_at is not None
        assert DtcAnnualReview.query.filter_by(year=2026).one().storage == "التفتيش الشهري منتظم"
    page = chem.get("/pharmacy/dtc?year=2026").get_data(as_text=True)
    assert "التفتيش الشهري منتظم" in page and "data-review-missing" not in page
    assert "data-to-dtc" in chem.get("/pharmacy/").get_data(as_text=True)


def test_a_shortage_reaches_the_prescriber_until_it_ends(ward):
    from app.models import DrugShortage, User
    from app.utils import notifications

    chem = ward["sign_in"]("chem")
    chem.post("/pharmacy/shortages/announce", data={"name": "Ceftriaxone 1 g", "alternative": "Cefotaxime"})
    with ward["app"].app_context():
        notifications.invalidate()
        doc = User.query.filter_by(username="doc").first()
        assert any(i["key"] == "drug_shortages" for i in notifications.get_notifications(doc))
        rid = DrugShortage.query.one().id
    page = ward["sign_in"]("doc").get("/prescriptions/shortages").get_data(as_text=True)
    assert "Cefotaxime" in page and "data-shortage" in page
    chem.post(f"/pharmacy/shortages/{rid}/end")
    with ward["app"].app_context():
        notifications.invalidate()
        doc = User.query.filter_by(username="doc").first()
        assert not any(i["key"] == "drug_shortages" for i in notifications.get_notifications(doc))
