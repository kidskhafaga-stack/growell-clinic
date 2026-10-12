"""برامج الرعاية الخاصة — GAHAR CSS.06 (غسيل)، CSS.07 (كيماوي)، CSS.10 (تأهيل).

* موديول اختياري: مقفول لحد ما المستشفى تشغّله؛
* الطفل بيتسجّل بخطته، والجلسة محتاجة التقييم قبلها واتسمح ولا لأ، والمضاعفات محتاجة اللي اتعمل؛
* الغسيل: الفيروسات مستحقة بفترة المستشفى بس، والتحوّل لإيجابي بيبان؛
* التأهيل ما يتقفلش من غير خطة خروج.
"""
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def unit(clinic):
    from app.models import Setting

    with clinic["app"].app_context():
        Setting.set("mod_enabled:programs", "1")
        clinic["db"].session.commit()
    return clinic


def test_off_until_switched_on(clinic):
    assert clinic["sign_in"]("boss").get("/programs/").status_code == 404


def test_dialysis_sessions_and_markers(unit):
    from app.models import ProgramEnrollment, ProgramSession

    boss = unit["sign_in"]("boss")
    kid = unit["ids"]["child"]
    boss.post("/programs/enroll", data={"program": "dialysis", "patient_id": kid, "plan": "غسيل دموي — قسطرة"})
    with unit["app"].app_context():
        eid = ProgramEnrollment.query.one().id
    url = f"/programs/{eid}"
    boss.post(url + "/session", data={"pre_check": "الوزن ٢٠ كجم، ضغط مستقر"})
    boss.post(url + "/session", data={"pre_check": "الوزن ٢٠ كجم", "cleared": "yes", "complications": "هبوط ضغط"})
    with unit["app"].app_context():
        assert ProgramSession.query.count() == 0
    boss.post(url + "/session", data={"pre_check": "الوزن ٢٠ كجم", "cleared": "yes", "complications": "هبوط ضغط",
                                      "action": "محلول ووقف السحب"})
    board = boss.get("/programs/?p=dialysis").get_data(as_text=True)
    assert "data-markers-due" not in board, "no hospital interval, nothing due"
    boss.post("/programs/marker-days", data={"days": "90"})
    assert "data-markers-due" in boss.get("/programs/?p=dialysis").get_data(as_text=True)
    boss.post(url + "/markers", data={"on": (date.today() - timedelta(days=10)).isoformat(), "hcv": "negative"})
    boss.post(url + "/markers", data={"hcv": "positive"})
    page = boss.get(url).get_data(as_text=True)
    assert "data-sero" in page and "data-markers-due" not in page
    with unit["app"].app_context():
        assert ProgramSession.query.count() == 1


def test_chemo_education_and_rehab_needs_a_discharge_plan(unit):
    from app.models import ProgramEnrollment

    boss = unit["sign_in"]("boss")
    kid = unit["ids"]["child"]
    boss.post("/programs/enroll", data={"program": "chemo", "patient_id": kid, "plan": "بروتوكول المستشفى", "cycles": "6"})
    boss.post("/programs/enroll", data={"program": "rehab", "patient_id": kid, "plan": "المشي بمساعدة"})
    with unit["app"].app_context():
        chemo = ProgramEnrollment.query.filter_by(program="chemo").one()
        rehab = ProgramEnrollment.query.filter_by(program="rehab").one()
        assert chemo.cycles == 6
        cid, rid = chemo.id, rehab.id
    boss.post(f"/programs/{cid}/educate", data={"educated_whom": "الأم"})
    boss.post(f"/programs/{rid}/end", data={})
    with unit["app"].app_context():
        assert unit["db"].session.get(ProgramEnrollment, rid).is_active
    boss.post(f"/programs/{rid}/end", data={"discharge_plan": "علاج طبيعي في البيت ومتابعة بعد شهر"})
    with unit["app"].app_context():
        assert not unit["db"].session.get(ProgramEnrollment, rid).is_active
        assert unit["db"].session.get(ProgramEnrollment, cid).educated_whom == "الأم"
