"""التحاليل المحسوبة — رقم بيطلع من أرقام تانية بدل ما يتكتب على الآلة الحاسبة.

* المعمل **بيختار** المعادلة (المنشورة بثوابتها) ومن أنهي مكوّنات — البرنامج
  مش بيشغّل حاجة لوحده؛
* الوحدة لازم تبقى وحدة المعادلة — مفيش تحويل من ورا حد؛
* الرقم بيتحسب لما المكوّنات تتكتب، ومش بيتكتب بالإيد، وبيتقرا على حدوده؛
* لو ناقص حاجة بيقول ليه بدل ما يطلع رقم: مكوّن ناقص، الدهون أعلى من حد
  Friedewald، مفيش طول في الزيارة لمعادلة Schwartz.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def calc(clinic):
    from app.models import Investigation, LabAnalyte, LabTestAnalyte, Setting

    with clinic["app"].app_context():
        db = clinic["db"]
        Setting.set("mod_enabled:labs", "1")
        lipid = Investigation(name_ar="دهون", name_en="Lipid profile", kind="lab")
        kft = Investigation(name_ar="وظائف كلى", name_en="KFT", kind="lab")
        tc, hdl, tg = (LabAnalyte(name=n, unit="mg/dL") for n in ("Cholesterol", "HDL", "TG"))
        ldl = LabAnalyte(name="LDL (calc)", unit="mg/dL")
        cr = LabAnalyte(name="Creatinine", unit="mg/dL")
        gfr = LabAnalyte(name="eGFR")
        db.session.add_all([lipid, kft, tc, hdl, tg, ldl, cr, gfr])
        db.session.flush()
        for i, a in enumerate((tc, hdl, tg, ldl)):
            db.session.add(LabTestAnalyte(investigation_id=lipid.id, analyte_id=a.id, sort_order=i))
        for i, a in enumerate((cr, gfr)):
            db.session.add(LabTestAnalyte(investigation_id=kft.id, analyte_id=a.id, sort_order=i))
        db.session.commit()
        clinic.update(lipid=lipid.id, kft=kft.id, tc=tc.id, hdl=hdl.id, tg=tg.id,
                      ldl=ldl.id, cr=cr.id, gfr=gfr.id)
    return clinic


def _order(c, test):
    from app.models import VisitInvestigation

    with c["app"].app_context():
        row = VisitInvestigation(visit_id=c["ids"]["visit"], patient_id=c["ids"]["child"],
                                 investigation_id=c[test], kind="lab", name=test,
                                 status="collected")
        c["db"].session.add(row)
        c["db"].session.commit()
        return row.id


def _values(c, order_id):
    from app.models import LabResultValue

    with c["app"].app_context():
        return {v.analyte_id: v for v in LabResultValue.query.filter_by(order_id=order_id)}


def _formula(c, test, analyte, formula, **inputs):
    data = {"formula": formula, **{f"in_{formula}_{k}": c[v] for k, v in inputs.items()}}
    return c["sign_in"]("boss").post(f"/labs/tests/{c[test]}/analytes/{c[analyte]}/formula",
                                     data=data)


def test_nothing_is_worked_out_until_the_lab_chooses_the_formula(calc):
    order = _order(calc, "lipid")
    calc["sign_in"]("boss").post(f"/labs/order/{order}/result",
                                 data={f"a_{calc['tc']}": "180", f"a_{calc['hdl']}": "50",
                                       f"a_{calc['tg']}": "100"})
    assert calc["ldl"] not in _values(calc, order)


def test_ldl_is_worked_out_from_the_three_and_cannot_be_typed(calc):
    _formula(calc, "lipid", "ldl", "ldl_mgdl", tc="tc", hdl="hdl", tg="tg")
    order = _order(calc, "lipid")
    boss = calc["sign_in"]("boss")
    boss.post(f"/labs/order/{order}/result",
              data={f"a_{calc['tc']}": "180", f"a_{calc['hdl']}": "50",
                    f"a_{calc['tg']}": "100", f"a_{calc['ldl']}": "999"})
    ldl = _values(calc, order)[calc["ldl"]]
    assert ldl.value == 110.0 and ldl.calculated          # 180 − 50 − 100/5
    page = boss.get(f"/labs/order/{order}").get_data(as_text=True)
    assert f'data-calculated="{calc["ldl"]}"' in page
    # Friedewald's own limit: triglycerides over 400 mg/dL — no number.
    boss.post(f"/labs/order/{order}/result",
              data={f"a_{calc['tc']}": "180", f"a_{calc['hdl']}": "50", f"a_{calc['tg']}": "450"})
    assert calc["ldl"] not in _values(calc, order)
    assert 'data-calc-why="over_limit"' in boss.get(f"/labs/order/{order}").get_data(as_text=True)


def test_an_input_in_another_unit_is_refused(calc):
    from app.models import LabAnalyte

    with calc["app"].app_context():
        calc["db"].session.get(LabAnalyte, calc["tg"]).unit = "mmol/L"
        calc["db"].session.commit()
    _formula(calc, "lipid", "ldl", "ldl_mgdl", tc="tc", hdl="hdl", tg="tg")
    with calc["app"].app_context():
        assert calc["db"].session.get(LabAnalyte, calc["ldl"]).formula is None


def test_schwartz_takes_the_height_from_the_same_visit(calc):
    from app.models import VitalSigns

    _formula(calc, "kft", "gfr", "schwartz_mgdl", cr="cr")
    order = _order(calc, "kft")
    boss = calc["sign_in"]("boss")
    boss.post(f"/labs/order/{order}/result", data={f"a_{calc['cr']}": "0.4"})
    assert calc["gfr"] not in _values(calc, order)
    assert 'data-calc-why="no_height"' in boss.get(f"/labs/order/{order}").get_data(as_text=True)
    with calc["app"].app_context():
        calc["db"].session.add(VitalSigns(visit_id=calc["ids"]["visit"], height_cm=100.0))
        calc["db"].session.commit()
    boss.post(f"/labs/order/{order}/result", data={f"a_{calc['cr']}": "0.4"})
    gfr = _values(calc, order)[calc["gfr"]]
    assert gfr.value == pytest.approx(103.25) and gfr.unit == "mL/min/1.73m²"   # 0.413×100/0.4
