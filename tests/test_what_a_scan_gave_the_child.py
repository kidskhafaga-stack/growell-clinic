"""What a scan gave the child, on radiology's own page — and the lab's own
part in a critical value.

Asked as *«الموضوع بتاع الصبغة ده مهم لان فى اشتراطات فى GAHAR … كل طفل
اتعرض لاشعة او للصبغة اد ايه ويقلل النسب»*, *«القيم الحرجة مش المفروض
المعمل يقدر يكتبها»*, *«وليه فى شورت كات للاشعات؟ فى المعمل مش مطلوبه»* and
*«الايكو ورسم المخ والترا ساوند دول بيتموا بطبيب»*.

**A gap found on the way.** A radiology report was written on the lab's
order page, behind the lab's module — a radiographer without the lab could
not report at all. Radiology has its own order page now. What is held here:

* the report, the dose and the contrast are written on radiology's page; the
  lab's page sends a scan there;
* the dose is kept in the measure the machine reports and never summed
  across measures; contrast keeps agent, route, amount and reaction;
* the next scan's screen shows what the child had before, and a previous
  contrast reaction in red; the child's file adds the doses up;
* a dose above the hospital's own reference level for the test is flagged
  and listed first on the review;
* the lab marks a result critical by hand, with its reason, and no later
  number takes the mark away; it records telling a doctor, with read-back;
* a device study names the doctor who did it.
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def xray(clinic):
    from app.models import Investigation, Setting

    with clinic["app"].app_context():
        db = clinic["db"]
        Setting.set("mod_enabled:labs", "1")
        Setting.set("mod_enabled:imaging", "1")
        ct = Investigation(name_ar="مقطعية مخ", kind="imaging", modality="ct",
                           dose_ref_kind="dlp", dose_ref_value=300, is_active=True)
        cbc = Investigation(name_ar="صورة دم", kind="lab", is_active=True)
        db.session.add_all([ct, cbc])
        db.session.commit()
        clinic["ids"].update(ct=ct.id, cbc=cbc.id)
    return clinic


def _order(c, key="ct", kind="imaging", days_ago=0):
    from app.models import VisitInvestigation

    with c["app"].app_context():
        row = VisitInvestigation(visit_id=c["ids"]["visit"], patient_id=c["ids"]["child"],
                                 investigation_id=c["ids"][key], kind=kind,
                                 name="مقطعية مخ" if kind == "imaging" else "صورة دم",
                                 status="requested",
                                 created_at=datetime.utcnow() - timedelta(days=days_ago))
        c["db"].session.add(row)
        c["db"].session.commit()
        return row.id


def _get(c, order_id):
    from app.models import VisitInvestigation

    with c["app"].app_context():
        return c["db"].session.get(VisitInvestigation, order_id)


def _expose(c, order_id, **form):
    return c["sign_in"]("boss").post(f"/imaging/order/{order_id}/exposure", data=form)


# ------------------------------------------------ radiology's own page --
def test_the_scan_is_reported_on_radiologys_page(xray):
    order = _order(xray)
    boss = xray["sign_in"]("boss")
    answer = boss.get(f"/labs/order/{order}")
    assert answer.status_code == 302 and f"/imaging/order/{order}" in answer.headers["Location"]
    page = boss.get(f"/imaging/order/{order}").get_data(as_text=True)
    assert "data-report" in page and "data-exposure" in page and "data-ionising" in page
    films = boss.get("/imaging/").get_data(as_text=True)
    assert f"/imaging/order/{order}" in films
    boss.post(f"/imaging/order/{order}/report",
              data={"result_text": "لا يوجد نزيف", "result_comment": "طبيعي"})
    row = _get(xray, order)
    assert row.status == "resulted" and row.result_comment == "طبيعي"


# --------------------------------------------------- dose and contrast --
def test_the_dose_and_the_contrast_are_kept_and_the_reference_flagged(xray):
    order = _order(xray)
    _expose(xray, order, dose_value="420", dose_measure="dlp:mgycm", contrast_agent="Omnipaque",
            contrast_route="iv", contrast_ml="12", contrast_reaction="mild",
            contrast_note="طفح بسيط")
    row = _get(xray, order)
    assert (row.dose_kind, row.dose_value, row.contrast_agent, row.contrast_ml,
            row.contrast_reaction) == ("dlp", 420.0, "Omnipaque", 12.0, "mild")
    from app.utils import radiation

    from app.models import VisitInvestigation

    with xray["app"].app_context():
        assert radiation.over_reference(
            xray["db"].session.get(VisitInvestigation, order)) is True
    page = xray["sign_in"]("boss").get(f"/imaging/order/{order}").get_data(as_text=True)
    assert "data-over-reference" in page


@pytest.mark.parametrize("form,why", [
    ({"dose_value": "100"}, "dose with no measure"),
    ({"contrast_ml": "10"}, "contrast amount with no agent"),
    ({"dose_value": "-3", "dose_measure": "dlp:mgycm"}, "a negative dose"),
])
def test_a_figure_that_cannot_be_kept_is_refused(xray, form, why):
    order = _order(xray)
    _expose(xray, order, **form)
    row = _get(xray, order)
    assert row.dose_value is None and row.contrast_ml is None, why


def test_the_next_scan_sees_what_came_before_and_the_reaction_in_red(xray):
    first = _order(xray, days_ago=40)
    _expose(xray, first, dose_value="200", dose_measure="dlp:mgycm", contrast_agent="Omnipaque",
            contrast_route="iv", contrast_reaction="moderate")
    second = _order(xray)
    _expose(xray, second, dose_value="1.5", dose_measure="msv:msv")
    third = _order(xray)
    page = xray["sign_in"]("boss").get(f"/imaging/order/{third}").get_data(as_text=True)
    assert "data-prior-reaction" in page
    from app.utils import radiation

    with xray["app"].app_context():
        found = radiation.summary(xray["ids"]["child"], exclude_id=third)
        # Two measures, never added together.
        assert found["totals"] == {"dlp": (200.0, "mgycm"), "msv": (1.5, "msv")}
        assert found["contrast"] == 1 and len(found["reactions"]) == 1
    profile = xray["sign_in"]("boss").get(f"/patients/{xray['ids']['child']}").get_data(as_text=True)
    assert "data-exposure-card" in profile and "data-file-reaction" in profile


def test_the_review_lists_the_ones_above_reference_first(xray):
    under = _order(xray)
    _expose(xray, under, dose_value="100", dose_measure="dlp:mgycm")
    over = _order(xray)
    _expose(xray, over, dose_value="500", dose_measure="dlp:mgycm")
    page = xray["sign_in"]("boss").get("/imaging/doses").get_data(as_text=True)
    assert page.index('data-dose-row="over"') < page.index('data-dose-row="ok"')
    assert "data-to-doses" in xray["sign_in"]("boss").get("/imaging/").get_data(as_text=True)


def test_the_test_list_sets_the_machine_and_the_reference(xray):
    from app.models import Investigation

    boss = xray["sign_in"]("boss")
    assert "data-modality-pick" in boss.get("/imaging/catalogue").get_data(as_text=True)
    boss.post(f"/imaging/catalogue/{xray['ids']['ct']}", data={
        "name_ar": "مقطعية مخ", "is_active": "1", "in_house": "1",
        "modality": "fluoro", "dose_ref_value": "250", "dose_ref_measure": "dap:gycm2"})
    with xray["app"].app_context():
        row = xray["db"].session.get(Investigation, xray["ids"]["ct"])
        assert (row.modality, row.dose_ref_value, row.dose_ref_kind, row.dose_ref_unit) == (
            "fluoro", 250.0, "dap", "gycm2")
    boss.post(f"/imaging/catalogue/{xray['ids']['ct']}", data={
        "name_ar": "مقطعية مخ", "is_active": "1", "in_house": "1", "modality": "fluoro"})
    with xray["app"].app_context():
        assert xray["db"].session.get(Investigation, xray["ids"]["ct"]).dose_ref_value is None


# ------------------------------------------------- the lab's critical --
def test_the_lab_marks_a_result_critical_by_hand_and_tells_a_doctor(xray):
    order = _order(xray, key="cbc", kind="lab")
    boss = xray["sign_in"]("boss")
    boss.post(f"/labs/order/{order}/result", data={"result_text": "مزرعة إيجابية"})
    page = boss.get(f"/labs/order/{order}").get_data(as_text=True)
    assert "data-critical-mark" in page
    boss.post(f"/labs/order/{order}/critical-mark", data={"reason": "مزرعة دم إيجابية"})
    row = _get(xray, order)
    assert row.critical_at is not None and row.critical_manual == "مزرعة دم إيجابية"
    critical = boss.get("/labs/critical").get_data(as_text=True)
    assert f'data-critical-row="{order}"' in critical and "data-not-called" in critical

    # A later save of the result does not take the hand's mark away.
    boss.post(f"/labs/order/{order}/result", data={"result_text": "مزرعة إيجابية — Staph"})
    assert _get(xray, order).critical_at is not None

    boss.post(f"/labs/order/{order}/critical-call",
              data={"called_to": "د. أحمد", "method": "phone", "read_back": "1"})
    row = _get(xray, order)
    assert (row.critical_called_to, row.critical_call_method, row.critical_read_back) == (
        "د. أحمد", "phone", True)
    assert row.critical_called_by == xray["ids"]["admin"]
    assert "data-called" in boss.get("/labs/critical").get_data(as_text=True)


def test_a_call_with_nobody_named_is_refused(xray):
    order = _order(xray, key="cbc", kind="lab")
    boss = xray["sign_in"]("boss")
    boss.post(f"/labs/order/{order}/result", data={"result_text": "إيجابي"})
    boss.post(f"/labs/order/{order}/critical-mark", data={"reason": "إيجابي"})
    boss.post(f"/labs/order/{order}/critical-call", data={"called_to": "", "method": "phone"})
    assert _get(xray, order).critical_called_at is None


# ----------------------------------------------- the device study's doctor --
def test_a_device_study_names_the_doctor_who_did_it(xray):
    from app.models import DeviceMeasurement, DeviceStudy, MedicalDevice

    with xray["app"].app_context():
        db = xray["db"]
        echo = MedicalDevice(name="إيكو", device_type="echo", is_active=True)
        db.session.add(echo)
        db.session.flush()
        db.session.add(DeviceMeasurement(device_id=echo.id, name="EF", sort_order=1))
        db.session.commit()
        echo_id = echo.id
    boss = xray["sign_in"]("boss")
    page = boss.get(f"/visits/studies/new/{xray['ids']['child']}?device_id={echo_id}").get_data(as_text=True)
    assert "data-study-doctor" in page
    boss.post(f"/visits/studies/new/{xray['ids']['child']}?device_id={echo_id}",
              data={"performed_by": str(xray["ids"]["doctor"]), "conclusion": "طبيعي",
                    "study_date": datetime.utcnow().strftime("%Y-%m-%d")})
    with xray["app"].app_context():
        assert DeviceStudy.query.one().performed_by == xray["ids"]["doctor"]


# ------------------------------------------------------ every machine's unit --
def test_a_dose_in_any_units_is_added_and_compared_by_the_units_own_factors(xray):
    """«مش هيتباع لجهة واحدة فقط فا كل مكان ليه طريقة واجهزة» — a DAP meter
    may print µGy·m² in one hospital and Gy·cm² in the next. Each figure is
    kept in its own unit, and added and compared in one."""
    from app.models import Investigation, Setting, VisitInvestigation
    from app.utils import radiation

    with xray["app"].app_context():
        db = xray["db"]
        ct = db.session.get(Investigation, xray["ids"]["ct"])
        # The reference level typed in mGy·cm²; the readings in other units.
        ct.dose_ref_kind, ct.dose_ref_value, ct.dose_ref_unit = "dap", 500, "mgycm2"
        db.session.commit()
    low = _order(xray)
    _expose(xray, low, dose_value="40", dose_measure="dap:ugym2")      # 400 mGy·cm²
    high = _order(xray)
    _expose(xray, high, dose_value="0.6", dose_measure="dap:gycm2")    # 600 mGy·cm²
    with xray["app"].app_context():
        db = xray["db"]
        assert db.session.get(VisitInvestigation, low).dose_unit == "ugym2"
        assert radiation.over_reference(db.session.get(VisitInvestigation, low)) is False
        assert radiation.over_reference(db.session.get(VisitInvestigation, high)) is True
        assert radiation.summary(xray["ids"]["child"])["totals"] == {"dap": (1000.0, "mgycm2")}
        # The hospital whose machines print Gy·cm² sees the total in it.
        Setting.set("dose_unit:dap", "gycm2")
        db.session.commit()
        assert radiation.summary(xray["ids"]["child"])["totals"] == {"dap": (1.0, "gycm2")}
        assert radiation.measures()[[k for k, _u in radiation.measures()].index("dap")] == ("dap", "gycm2")


def test_the_factors_are_the_units_own():
    from app.utils import radiation

    assert radiation.to_base(1, "dap", "ugym2") == 10.0
    assert radiation.to_base(1, "dap", "mgym2") == 10000.0
    assert radiation.to_base(2, "activity", "mci") == 74.0
    assert radiation.to_base(3, "fluoro_time", "min") == 180.0
    assert radiation.to_base(5, "dlp", None) == 5.0, "a row from before units read as base"


def test_the_hospital_names_its_machines_units(xray):
    from app.models import Setting

    boss = xray["sign_in"]("boss")
    assert "data-dose-units" in boss.get("/imaging/doses").get_data(as_text=True)
    boss.post("/imaging/dose-units", data={"unit_dap": "ugym2", "unit_dlp": "nonsense"})
    with xray["app"].app_context():
        assert Setting.get("dose_unit:dap") == "ugym2"
        assert not Setting.get("dose_unit:dlp")
