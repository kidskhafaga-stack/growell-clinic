"""التحليل اللي بعده بقاعدة المعمل (Reflex).

* القاعدة **بتاعة المعمل**: أنهي مكوّن، أعلى أو أقل من أنهي رقم، وإيه بعده؛
* «اقتراح للطبيب»: بيظهر في الزيارة، والطبيب بيطلبه بضغطة أو بيقول لأ؛
* «يتطلب لوحده»: بيتكتب على نفس الزيارة ومعلّم إنه من القاعدة — ومرة واحدة؛
* نتيجة اتصلّحت والقاعدة ما بقتش تنطبق بتسحب الاقتراح اللي محدش ردّ عليه.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def thyroid(clinic):
    from app.models import Investigation, LabAnalyte, LabTestAnalyte, Setting

    with clinic["app"].app_context():
        db = clinic["db"]
        Setting.set("mod_enabled:labs", "1")
        tsh_test = Investigation(name_ar="هرمون الغدة", name_en="TSH", kind="lab")
        ft4 = Investigation(name_ar="الثيروكسين الحر", name_en="FT4", kind="lab")
        tsh = LabAnalyte(name="TSH", unit="mIU/L")
        db.session.add_all([tsh_test, ft4, tsh])
        db.session.flush()
        db.session.add(LabTestAnalyte(investigation_id=tsh_test.id, analyte_id=tsh.id))
        db.session.commit()
        clinic.update(tsh_test=tsh_test.id, ft4=ft4.id, tsh=tsh.id)
    return clinic


def _order(c):
    from app.models import VisitInvestigation

    with c["app"].app_context():
        row = VisitInvestigation(visit_id=c["ids"]["visit"], patient_id=c["ids"]["child"],
                                 investigation_id=c["tsh_test"], kind="lab", name="TSH",
                                 status="collected")
        c["db"].session.add(row)
        c["db"].session.commit()
        return row.id


def _rule(c, mode="suggest"):
    return c["sign_in"]("boss").post(f"/labs/tests/{c['tsh_test']}/reflex", data={
        "analyte_id": c["tsh"], "op": "above", "value": "4.5", "then_id": c["ft4"], "mode": mode})


def _result(c, order, value):
    c["sign_in"]("boss").post(f"/labs/order/{order}/result", data={f"a_{c['tsh']}": value})


def _ft4_orders(c):
    from app.models import VisitInvestigation

    with c["app"].app_context():
        return VisitInvestigation.query.filter_by(investigation_id=c["ft4"]).all()


def test_no_rule_no_suggestion(thyroid):
    from app.models import LabReflexHit

    _result(thyroid, _order(thyroid), "9")
    with thyroid["app"].app_context():
        assert LabReflexHit.query.count() == 0


def test_a_suggestion_the_doctor_orders_with_one_press(thyroid):
    from app.models import LabReflexHit

    _rule(thyroid)
    order = _order(thyroid)
    _result(thyroid, order, "3.0")
    with thyroid["app"].app_context():
        assert LabReflexHit.query.count() == 0
    _result(thyroid, order, "7.2")
    assert _ft4_orders(thyroid) == [], "suggested, not ordered"
    doc = thyroid["sign_in"]("doc")
    page = doc.get(f"/visits/{thyroid['ids']['visit']}/record").get_data(as_text=True)
    with thyroid["app"].app_context():
        hit = LabReflexHit.query.one()
        hit_id = hit.id
    assert f'data-reflex="{hit_id}"' in page
    doc.post(f"/visits/reflex/{hit_id}", data={"answer": "order"})
    rows = _ft4_orders(thyroid)
    assert len(rows) == 1 and rows[0].ordered_by == thyroid["ids"]["doctor"]
    page = doc.get(f"/visits/{thyroid['ids']['visit']}/record").get_data(as_text=True)
    assert f'data-reflex="{hit_id}"' not in page


def test_a_rule_that_orders_on_its_own_does_so_once_and_says_why(thyroid):
    _rule(thyroid, mode="order")
    order = _order(thyroid)
    _result(thyroid, order, "7.2")
    _result(thyroid, order, "8.0")              # corrected again — still once
    rows = _ft4_orders(thyroid)
    assert len(rows) == 1 and rows[0].reflex_of == order and rows[0].ordered_by is None


def test_a_corrected_value_withdraws_an_unanswered_suggestion(thyroid):
    from app.models import LabReflexHit

    _rule(thyroid)
    order = _order(thyroid)
    _result(thyroid, order, "7.2")
    _result(thyroid, order, "2.0")
    with thyroid["app"].app_context():
        assert LabReflexHit.query.one().status == "withdrawn"


def test_only_the_lab_s_administrator_writes_rules(thyroid):
    from app.models import LabReflexRule

    assert thyroid["sign_in"]("doc").post(f"/labs/tests/{thyroid['tsh_test']}/reflex", data={
        "analyte_id": thyroid["tsh"], "op": "above", "value": "4.5",
        "then_id": thyroid["ft4"]}).status_code in (302, 403)
    with thyroid["app"].app_context():
        assert LabReflexRule.query.count() == 0
    page = thyroid["sign_in"]("boss").get(f"/labs/tests/{thyroid['tsh_test']}/ranges").get_data(as_text=True)
    assert "data-reflex-rules" in page
