"""برنامج سلامة الإشعاع — GAHAR `DAS.09` / `GSR.12`.

* **الموظفين المتابَعين**، وآخر قراءة TLD وآخر صورة دم والجاية بعد ٦ شهور؛
* القراءة بتتسجّل زي ما اتقرت — و«فوق الحد» بس قصاد حد برنامج المستشفى،
  ووقتها لازم إجراء؛
* صورة الدم الحدّية أو غير الطبيعية لازم الفحص اللي اتطلب؛
* قراءة مكان فوق حدّه، ومريلة فيها عيب: لازم إجراء؛
* **الرنين**: أسئلة المستشفى بس — من غيرها ما فيش حاجة بتتسأل — وأي «أيوه»
  لازم قرار؛ وده تسجيل مش قفل.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

from app.utils.clock import local_today  # noqa: E402


@pytest.fixture()
def rad(clinic):
    from app.models import Investigation, Setting, User, VisitInvestigation

    with clinic["app"].app_context():
        db = clinic["db"]
        Setting.set("mod_enabled:imaging", "1")
        tech = User(username="tech", full_name="الفني", role="doctor", is_active=True)
        tech.set_password("secret")
        mri = Investigation(name_ar="رنين مخ", name_en="MRI brain", kind="imaging",
                            modality="mri", is_active=True)
        ct = Investigation(name_ar="مقطعية", kind="imaging", modality="ct", is_active=True)
        db.session.add_all([tech, mri, ct])
        db.session.flush()
        orders = {}
        for key, inv in (("mri", mri), ("ct", ct)):
            row = VisitInvestigation(visit_id=clinic["ids"]["visit"],
                                     patient_id=clinic["ids"]["child"],
                                     investigation_id=inv.id, kind="imaging",
                                     name=inv.name_ar, status="requested")
            db.session.add(row)
            db.session.flush()
            orders[key] = row.id
        db.session.commit()
        clinic["ids"].update(tech=tech.id, mri_order=orders["mri"], ct_order=orders["ct"])
    return clinic


def _post(c, path, **form):
    return c["sign_in"]().post(f"/imaging/safety/{path}", data=form)


def test_the_monitored_staff_and_when_the_blood_count_is_due(rad):
    from app.utils import radiation_safety as rs

    today = local_today()
    _post(rad, "worker", user_id=str(rad["ids"]["tech"]), area="الأشعة", badge_number="T-7")
    page = rad["sign_in"]().get("/imaging/safety").get_data(as_text=True)
    assert f'data-rad-worker="{rad["ids"]["tech"]}"' in page and 'data-cbc-state="never"' in page
    _post(rad, "cbc", user_id=str(rad["ids"]["tech"]), done_on=today.isoformat(),
          result="borderline")                                   # no follow-up
    _post(rad, "cbc", user_id=str(rad["ids"]["tech"]), done_on=today.isoformat(),
          result="borderline", action="إعادة بعد شهر وتحويل لأمراض الدم")
    with rad["app"].app_context():
        row = rs.board(today)[0]
        assert row["cbc_state"] == "ok" and row["cbc"].result == "borderline"
        assert (row["cbc_due"].year * 12 + row["cbc_due"].month) - (today.year * 12 + today.month) == 6
    # Somebody not on the list has no readings written for them.
    assert _post(rad, "cbc", user_id=str(rad["ids"]["admin"]), done_on=today.isoformat(),
                 result="normal").status_code == 302
    with rad["app"].app_context():
        from app.models import StaffBloodCount

        assert StaffBloodCount.query.count() == 1


def test_a_badge_is_over_only_against_the_hospital_s_level(rad):
    from app.models import DoseBadgeReading

    today = local_today().isoformat()
    _post(rad, "worker", user_id=str(rad["ids"]["tech"]))
    form = {"user_id": str(rad["ids"]["tech"]), "period_from": today, "period_to": today,
            "dose_msv": "2.5"}
    _post(rad, "badge", **form)
    page = rad["sign_in"]().get("/imaging/safety").get_data(as_text=True)
    assert "data-badge-over" not in page, "no level written, nothing over"
    _post(rad, "settings", badge_level="1.5")
    _post(rad, "badge", **form)                                   # over, no action
    with rad["app"].app_context():
        assert DoseBadgeReading.query.count() == 1
    _post(rad, "badge", **form, action="اتراجعت ساعات العمل")
    page = rad["sign_in"]().get("/imaging/safety").get_data(as_text=True)
    assert "data-badge-over" in page


def test_an_area_over_its_limit_and_a_defective_apron_need_the_action(rad):
    from app.models import ApronCheck, AreaMeasurement

    today = local_today().isoformat()
    _post(rad, "area", area="غرفة التحكم", measured_on=today, value="3", limit="2")
    _post(rad, "apron", apron="مريلة ٣", checked_on=today, result="fail")
    with rad["app"].app_context():
        assert AreaMeasurement.query.count() == 0 and ApronCheck.query.count() == 0
    _post(rad, "area", area="غرفة التحكم", measured_on=today, value="3", limit="2",
          action="اتقفل الباب الرصاص واتعادت القراءة")
    _post(rad, "apron", apron="مريلة ٣", checked_on=today, result="fail",
          method="فحص بالأشعة", action="اتشالت من الخدمة")
    with rad["app"].app_context():
        assert AreaMeasurement.query.one().over and ApronCheck.query.one().result == "fail"


def test_the_mri_screening_is_the_hospital_s_questions_and_a_yes_needs_a_decision(rad):
    from app.models import MriScreening

    boss = rad["sign_in"]()
    page = boss.get(f"/imaging/order/{rad['ids']['mri_order']}").get_data(as_text=True)
    assert "data-mri-screening" not in page, "no questions written, nothing asked"
    _post(rad, "settings", mri_questions="منظم ضربات قلب؟\nشظايا معدنية في العين؟")
    page = boss.get(f"/imaging/order/{rad['ids']['mri_order']}").get_data(as_text=True)
    assert "data-mri-screening" in page and "منظم ضربات قلب؟" in page
    assert "data-mri-screening" not in boss.get(
        f"/imaging/order/{rad['ids']['ct_order']}").get_data(as_text=True), "a CT is not an MRI"
    url = f"/imaging/order/{rad['ids']['mri_order']}/mri-screening"
    boss.post(url, data={"q0": "no", "outcome": "cleared"})                     # one unanswered
    boss.post(url, data={"q0": "yes", "q1": "no", "outcome": "cleared"})        # yes, no decision
    with rad["app"].app_context():
        assert MriScreening.query.count() == 0
    boss.post(url, data={"q0": "yes", "q1": "no", "outcome": "not_cleared",
                         "decision": "د. الأشعة: يتعمل مقطعية بدل الرنين"})
    page = boss.get(f"/imaging/order/{rad['ids']['mri_order']}").get_data(as_text=True)
    assert "data-mri-done" in page and "يتعمل مقطعية بدل الرنين" in page
    # Recorded, never a lock: the scan can still be marked done.
    boss.post(f"/imaging/order/{rad['ids']['mri_order']}/performed")
    with rad["app"].app_context():
        assert MriScreening.query.one().outcome == "not_cleared"


def test_radiology_links_to_the_program(rad):
    page = rad["sign_in"]().get("/imaging/").get_data(as_text=True)
    assert "data-to-safety" in page
