"""الأشعة، وإعادة التحليل، وبنك الدم — GAHAR DAS.

* **الأشعة**: زمن التقرير قصاد زمن الأشعة نفسها والتأخير بيتبلّغ (DAS.07)،
  التقرير المطبوع بعناصره (DAS.08)، الفحص البديل واتبلّغ مين (DAS.04 هـ)،
  كفاءة الموظفين (DAS.02)، ورقابة الجودة والفاشل باللي اتعمل ومراجعة الشهر
  والتقييم السنوي (DAS.05، DAS.01).
* **إعادة التحليل** قبل أقل فترة بتتعلّم وسببها بيتكتب، وما بتترفضش.
* **بنك الدم** اللي الدم بتاعه من برّه: الاستلام بالملصق والفحص، والصرف
  بالتوافق والفحص بالعين، والتتبّع لحد الطفل (DAS.28–30).
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.utils.clock import local_today  # noqa: E402

import pytest  # noqa: E402,F401

from tests.test_what_a_scan_gave_the_child import _order, xray  # noqa: E402,F401


def _row(c, order_id):
    from app.models import VisitInvestigation

    return c["db"].session.get(VisitInvestigation, order_id)


def test_a_late_report_is_measured_told_and_printed(xray):
    from app.models import Investigation
    from app.utils import lab_tat

    order = _order(xray)
    with xray["app"].app_context():
        xray["db"].session.get(Investigation, xray["ids"]["ct"]).tat_max = 60
        row = _row(xray, order)
        row.status, row.performed_at = "performed", datetime.utcnow() - timedelta(hours=3)
        xray["db"].session.commit()
        assert lab_tat.waiting_late(row) is True
    boss = xray["sign_in"]("boss")
    page = boss.get(f"/imaging/order/{order}").get_data(as_text=True)
    assert "data-late-box" in page and "data-tell-delay" in page
    boss.post(f"/imaging/order/{order}/delay", data={"told_to": "د. أحمد", "reason": "الجهاز وقف"})
    with xray["app"].app_context():
        row = _row(xray, order)
        assert row.delay_told_to == "د. أحمد"
        row.status, row.resulted_at, row.result_text = "resulted", datetime.utcnow(), "نزيف بسيط"
        row.resulted_by = xray["ids"]["admin"]
        xray["db"].session.commit()
        per_test, late_rows = lab_tat.report(local_today() - timedelta(days=1), local_today(), kind="imaging")
        assert [r.id for r in late_rows] == [order]
    assert "data-to-img-turnaround" in boss.get("/imaging/").get_data(as_text=True)
    assert "مقطعية مخ" in boss.get("/imaging/turnaround").get_data(as_text=True)
    sheet = boss.get(f"/imaging/order/{order}/print").get_data(as_text=True)
    assert "data-imaging-report" in sheet and "P1" in sheet and "data-report-signer" in sheet


def test_a_substituted_study_says_who_was_told(xray):
    order = _order(xray)
    boss = xray["sign_in"]("boss")
    boss.post(f"/imaging/order/{order}/substitute", data={"substituted_with": "رنين بدل المقطعية"})
    with xray["app"].app_context():
        assert _row(xray, order).substituted_with is None
    boss.post(f"/imaging/order/{order}/substitute",
              data={"substituted_with": "رنين بدل المقطعية", "substitution_told": "الأم ود. أحمد"})
    with xray["app"].app_context():
        assert _row(xray, order).substitution_told == "الأم ود. أحمد"


def test_imaging_staff_competency_and_quality_control(xray):
    from app.models import ImagingQc, LabCompetency, ServiceReview

    boss = xray["sign_in"]("boss")
    doc = xray["ids"]["doctor"]
    assert boss.get("/imaging/staff").status_code == 200
    boss.post(f"/imaging/staff/{doc}/assess", data={"section": "radiology", "assessed_on": local_today().isoformat(),
                                                    "methods": ["observe_routine", "review_records"], "result": "competent"})
    with xray["app"].app_context():
        row = LabCompetency.query.one()
        assert row.section == "radiology"
    assert "data-staff-row" in boss.get("/imaging/staff").get_data(as_text=True)
    assert boss.get(f"/imaging/staff/{doc}").status_code == 200

    boss.post("/imaging/qc", data={"held_on": local_today().isoformat(), "device": "جهاز الأشعة ١",
                                   "test": "اختبار الفانتوم", "passed": "no"})
    with xray["app"].app_context():
        assert ImagingQc.query.count() == 0, "a fail needs what was done"
    boss.post("/imaging/qc", data={"held_on": local_today().isoformat(), "device": "جهاز الأشعة ١",
                                   "test": "اختبار الفانتوم", "passed": "no", "action": "معايرة الشركة"})
    month = local_today().strftime("%Y-%m")
    boss.post("/imaging/qc", data={"what": "review", "month": month, "note": "فشل واحد اتصلّح"})
    boss.post("/imaging/qc", data={"what": "service", "year": local_today().year, "text": "الخدمات مناسبة"})
    page = boss.get(f"/imaging/qc?month={month}").get_data(as_text=True)
    assert "data-qc-reviewed" in page and "data-review-missing" not in page
    boss.post("/labs/service-review", data={"year": local_today().year, "text": "نطاق المعمل اتراجع"})
    with xray["app"].app_context():
        assert {r.service for r in ServiceReview.query.all()} == {"imaging", "lab"}


def test_a_repeat_inside_the_interval_is_flagged_never_refused(xray):
    from app.models import Investigation

    with xray["app"].app_context():
        xray["db"].session.get(Investigation, xray["ids"]["cbc"]).retest_hours = 24
        xray["db"].session.commit()
    first = _order(xray, key="cbc", kind="lab", days_ago=0)
    second = _order(xray, key="cbc", kind="lab", days_ago=0)
    boss = xray["sign_in"]("boss")
    assert "data-repeat" not in boss.get(f"/labs/order/{first}").get_data(as_text=True)
    assert "data-repeat" in boss.get(f"/labs/order/{second}").get_data(as_text=True)
    boss.post(f"/labs/order/{second}/repeat-reason", data={"reason": "هبوط مفاجئ في الهيموجلوبين"})
    with xray["app"].app_context():
        assert _row(xray, second).repeat_reason == "هبوط مفاجئ في الهيموجلوبين"
    boss.post(f"/labs/order/{first}/repeat-reason", data={"reason": "مش إعادة"})
    with xray["app"].app_context():
        assert _row(xray, first).repeat_reason is None


def _unit_form(supplier, **over):
    form = {"unit_number": "U-100", "supplier_id": supplier, "product": "prbc", "volume_ml": "250", "abo": "O",
            "rh": "pos", "seronegative": "yes", "storage": "٢–٦ درجة", "collected_on": local_today().isoformat(),
            "expires_on": (local_today() + timedelta(days=20)).isoformat(), "transport_ok": "yes",
            "label_ok": "yes", "abo_confirmed": "yes"}
    form.update(over)
    return form


def test_a_unit_from_the_supplier_to_the_child(xray):
    from app.models import BloodSupplier, BloodUnit, Patient
    from app.models.blood import BloodRequest, Transfusion
    from app.utils import blood

    boss = xray["sign_in"]("boss")
    assert "data-to-blood-bank" in boss.get("/labs/").get_data(as_text=True)
    boss.post("/labs/blood-bank/suppliers", data={"name": "بنك الدم الإقليمي"})
    with xray["app"].app_context():
        assert BloodSupplier.query.count() == 0, "acceptance criteria"
    boss.post("/labs/blood-bank/suppliers", data={"name": "بنك الدم الإقليمي", "acceptance": "ملصق كامل وحرارة ٢–٦",
                                                 "agreement_until": "2027-12-31"})
    with xray["app"].app_context():
        sid = BloodSupplier.query.one().id
    boss.post("/labs/blood-bank", data=_unit_form(sid, transport_ok="no"))
    with xray["app"].app_context():
        assert BloodUnit.query.count() == 0, "a failed inspection needs the reason"
    boss.post("/labs/blood-bank", data=_unit_form(sid, unit_number="U-099", transport_ok="no",
                                                  reject_reason="الصندوق دافي"))
    boss.post("/labs/blood-bank", data=_unit_form(sid))
    with xray["app"].app_context():
        assert BloodUnit.query.filter_by(unit_number="U-099").one().status == "rejected"
        unit = BloodUnit.query.filter_by(unit_number="U-100").one()
        uid = unit.id
        req = blood.request(xray["db"].session.get(Patient, xray["ids"]["child"]), "prbc", "Hb 5")
        xray["db"].session.commit()
        rid = req.id
    boss.post(f"/labs/blood-bank/unit/{uid}/issue", data={"request_id": rid, "compatible": "no", "visual_ok": "yes"})
    with xray["app"].app_context():
        assert xray["db"].session.get(BloodUnit, uid).status == "stored", "incompatible is never issued"
    boss.post(f"/labs/blood-bank/unit/{uid}/issue", data={"request_id": rid, "compatible": "yes", "visual_ok": "yes",
                                                          "segment_number": "S1"})
    with xray["app"].app_context():
        unit = xray["db"].session.get(BloodUnit, uid)
        assert unit.status == "issued" and unit.request_id == rid
        blood.hang(xray["db"].session.get(BloodRequest, rid), unit_code="U-100")
        xray["db"].session.commit()
        assert xray["db"].session.get(BloodUnit, uid).status == "transfused"
        assert Transfusion.query.filter_by(unit_code="U-100").count() == 1
    page = boss.get(f"/labs/blood-bank/unit/{uid}").get_data(as_text=True)
    assert "data-bb-trace" in page and "data-bb-issued" in page
