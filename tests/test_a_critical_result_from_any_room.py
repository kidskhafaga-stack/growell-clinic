"""A critical result, from any of the three rooms — GAHAR ICD.19 / GSR.03.

Step one of the safety goals plan:

* a film or a device study can be marked critical as a lab value can, with
  the reason, and told to a doctor with the read-back;
* each notification records (ج-٦) **the difficulties** met, beside who, how,
  when and by whom;
* the hospital's timeframe (ب) — none written, nothing is late; written, a
  call past it, or no call yet past it, says so;
* every critical result in a period with the figures the hospital monitors;
* the doctors' bell and the critical list reach a critical film even where
  the lab module is off.
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

from tests.test_what_a_scan_gave_the_child import _order, xray  # noqa: E402,F401


def _row(c, order_id):
    from app.models import VisitInvestigation

    return c["db"].session.get(VisitInvestigation, order_id)


def _reported(c, key="ct", kind="imaging"):
    order = _order(c, key=key, kind=kind)
    with c["app"].app_context():
        row = _row(c, order)
        row.result_text = "نزيف داخل الجمجمة"
        row.status = "resulted"
        row.resulted_at = datetime.utcnow()
        c["db"].session.commit()
    return order


def test_a_film_is_marked_critical_and_told_with_its_difficulty(xray):
    order = _reported(xray)
    boss = xray["sign_in"]("boss")
    page = boss.get(f"/imaging/order/{order}").get_data(as_text=True)
    assert "data-critical-mark" in page
    answer = boss.post(f"/labs/order/{order}/critical-mark",
                       data={"reason": "نزيف حاد", "back": "imaging"})
    assert f"/imaging/order/{order}" in answer.headers["Location"]
    boss.post(f"/labs/order/{order}/critical-call", data={
        "called_to": "د. أحمد", "method": "phone", "read_back": "1",
        "difficulty": "ما ردّش أول مرتين", "back": "imaging"})
    with xray["app"].app_context():
        row = _row(xray, order)
        assert row.critical_at is not None and row.critical_manual == "نزيف حاد"
        assert (row.critical_called_to, row.critical_read_back, row.critical_difficulty) == (
            "د. أحمد", True, "ما ردّش أول مرتين")
    page = boss.get(f"/imaging/order/{order}").get_data(as_text=True)
    assert "data-critical-difficulty" in page and "data-critical-called" in page


def test_nothing_is_late_until_the_hospital_writes_its_timeframe(xray):
    from app.utils import lab_critical

    order = _reported(xray)
    boss = xray["sign_in"]("boss")
    boss.post(f"/labs/order/{order}/critical-mark", data={"reason": "نزيف"})
    with xray["app"].app_context():
        row = _row(xray, order)
        row.critical_at = datetime.utcnow() - timedelta(minutes=50)
        xray["db"].session.commit()
        assert lab_critical.late_call(_row(xray, order)) is None
    boss.post("/labs/critical/timeframe", data={"minutes": "30"})
    with xray["app"].app_context():
        assert lab_critical.late_call(_row(xray, order)) is True, "not told and past it"
    assert "data-call-late" in boss.get("/labs/critical").get_data(as_text=True)
    boss.post(f"/labs/order/{order}/critical-call", data={"called_to": "د. أحمد", "method": "phone"})
    with xray["app"].app_context():
        row = _row(xray, order)
        assert lab_critical.minutes_to_call(row) >= 50 and lab_critical.late_call(row) is True
    # Only whoever builds the lists writes the timeframe.
    xray["sign_in"]("doc").post("/labs/critical/timeframe", data={"minutes": "500"})
    with xray["app"].app_context():
        assert lab_critical.timeframe() == 30


def test_the_report_counts_what_the_hospital_monitors(xray):
    first = _reported(xray)
    second = _reported(xray)
    boss = xray["sign_in"]("boss")
    for order in (first, second):
        boss.post(f"/labs/order/{order}/critical-mark", data={"reason": "نزيف"})
    boss.post(f"/labs/order/{first}/critical-call", data={
        "called_to": "د. أحمد", "method": "phone", "difficulty": "مشغول"})
    page = boss.get("/labs/critical/report").get_data(as_text=True)
    assert f'data-critical-report-row="{first}"' in page and f'data-critical-report-row="{second}"' in page
    from app.utils import lab_critical
    from app.utils.clock import local_today

    with xray["app"].app_context():
        _rows, sums = lab_critical.report(local_today() - timedelta(days=1), local_today())
        assert (sums["total"], sums["called"], sums["no_read_back"], sums["difficulty"],
                sums["by_kind"]["imaging"]) == (2, 1, 1, 1, 2)


def test_a_critical_film_reaches_the_doctor_with_the_lab_module_off(xray):
    from app.models import Setting
    from app.utils import lab_results

    order = _reported(xray)
    xray["sign_in"]("boss").post(f"/labs/order/{order}/critical-mark", data={"reason": "نزيف"})
    with xray["app"].app_context():
        Setting.set("mod_enabled:labs", "0")
        xray["db"].session.commit()
        lab_results.invalidate()
    doc = xray["sign_in"]("doc")
    page = doc.get("/labs/critical")
    assert page.status_code == 200 and f'data-critical-row="{order}"' in page.get_data(as_text=True)
    doc.post(f"/labs/order/{order}/critical-read", data={"back": "imaging"})
    with xray["app"].app_context():
        assert _row(xray, order).critical_seen_by == xray["ids"]["doctor"]


def test_a_lab_value_keeps_working_as_before(xray):
    order = _order(xray, key="cbc", kind="lab")
    with xray["app"].app_context():
        row = _row(xray, order)
        row.result_text = "مزرعة إيجابية"
        row.status = "resulted"
        xray["db"].session.commit()
    boss = xray["sign_in"]("boss")
    boss.post(f"/labs/order/{order}/critical-mark", data={"reason": "مزرعة دم إيجابية"})
    answer = boss.post(f"/labs/order/{order}/critical-call",
                       data={"called_to": "د. أحمد", "method": "phone", "read_back": "1"})
    assert f"/labs/order/{order}" in answer.headers["Location"]
    with xray["app"].app_context():
        row = _row(xray, order)
        assert row.critical_read_back is True and row.critical_difficulty is None


def test_a_device_study_carries_the_critical_box(xray):
    from app.models import DeviceStudy, MedicalDevice

    order = _reported(xray, key="cbc", kind="diagnostic")
    with xray["app"].app_context():
        db = xray["db"]
        device = MedicalDevice(name="جهاز إيكو")
        db.session.add(device)
        db.session.flush()
        study = DeviceStudy(patient_id=xray["ids"]["child"], device_id=device.id,
                            order_id=order)
        db.session.add(study)
        db.session.commit()
        study_id = study.id
    boss = xray["sign_in"]("boss")
    page = boss.get(f"/visits/studies/{study_id}").get_data(as_text=True)
    assert "data-critical-mark" in page
    answer = boss.post(f"/labs/order/{order}/critical-mark",
                       data={"reason": "اضطراب نظم خطير", "back": f"study:{study_id}"})
    assert f"/visits/studies/{study_id}" in answer.headers["Location"]
    assert "data-critical-box" in boss.get(f"/visits/studies/{study_id}").get_data(as_text=True)


def test_a_clinic_with_neither_lab_nor_radiology_sees_nothing_of_it(xray):
    from app.models import DeviceStudy, MedicalDevice, Setting

    order = _reported(xray, key="cbc", kind="diagnostic")
    with xray["app"].app_context():
        db = xray["db"]
        Setting.set("mod_enabled:labs", "0")
        Setting.set("mod_enabled:imaging", "0")
        device = MedicalDevice(name="جهاز رسم قلب")
        db.session.add(device)
        db.session.flush()
        study = DeviceStudy(patient_id=xray["ids"]["child"], device_id=device.id, order_id=order)
        db.session.add(study)
        db.session.commit()
        study_id = study.id
    doc = xray["sign_in"]("doc")
    assert "data-critical" not in doc.get(f"/visits/studies/{study_id}").get_data(as_text=True)
    assert doc.get("/labs/critical").status_code == 404
