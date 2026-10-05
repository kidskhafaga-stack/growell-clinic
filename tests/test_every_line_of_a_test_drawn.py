"""Every line of a test drawn, wherever it was written.

Asked as: *«لو شغال في عيادة … ولو في مستشفى وفيها معمل ترسم ده في ملف المريض
او الزيارة … لو البرنامج شغال في عيادة تبقى بيعمل نفس الحاجة ولو شغال في
مستشفى يبقى بيأدي بنفس الأداء»*.

* a test answered **line by line** draws a curve per line — haemoglobin one,
  platelets another — and a test of one line keeps the curve it always had;
* the doctor in a clinic types the family's paper **line by line**, by the
  same form and the same approved ranges as the bench, and it draws the same;
* the visit shows the curves that have a point from it;
* a specialty alert on a line of a bigger test reads it — ANC by its name,
  and «liver enzymes rising» on the line the clinic chose, never a guess.
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

from tests.test_a_result_line_by_line import (_fresh_cache, _order, _post,  # noqa: E402,F401
                                              _row, bench)


def _resulted(c, test="cbc", days_ago=0, **values):
    order = _order(c, test=test, collected_minutes_ago=30)
    _post(c, order, **values)
    with c["app"].app_context():
        row = _row(c, order)
        row.resulted_at = datetime.utcnow() - timedelta(days=days_ago)
        c["db"].session.commit()
    return order


def _curves(c):
    from app.utils import lab_series

    with c["app"].app_context():
        return {g["key"]: g for g in lab_series.series_for(c["ids"]["child"])}


def test_each_line_of_a_cbc_is_its_own_curve(bench):
    _resulted(bench, days_ago=10, hb="11.2", plt="300")
    _resulted(bench, days_ago=1, hb="9.8", plt="280")
    curves = _curves(bench)
    hb = curves[f"an:{bench['hb']}"]
    assert [p["value"] for p in hb["points"]] == [11.2, 9.8]
    assert hb["name"] == "Hemoglobin" and hb["unit"] == "g/dL"
    assert hb["points"][0]["low"] == 10.5, "the approved range it was read against"
    plt = curves[f"an:{bench['plt']}"]
    assert plt["points"][0]["low"] is None, "a draft range draws no band"


def test_a_test_of_one_line_keeps_the_curve_it_had(bench):
    _resulted(bench, test="crp", days_ago=5, crp_a="3")
    _resulted(bench, test="crp", days_ago=1, crp_a="12")
    curves = _curves(bench)
    assert f"id:{bench['crp']}" in curves
    assert f"an:{bench['crp_a']}" not in curves, "one reading, one line"


def test_the_clinic_types_the_paper_line_by_line_and_it_draws_the_same(bench):
    from app.models import Setting

    with bench["app"].app_context():
        Setting.set("mod_enabled:labs", "0")
        bench["db"].session.commit()
    doc = bench["sign_in"]("doc")
    page = doc.get(f"/visits/{bench['ids']['visit']}/record")
    for days in (8, 2):
        order = _order(bench)
        page = doc.get(f"/visits/{bench['ids']['visit']}/record").get_data(as_text=True)
        assert f'data-analyte-entry="{order}"' in page
        doc.post(f"/visits/investigations/{order}/result",
                 data={f"a_{bench['hb']}": "12.0" if days == 8 else "6.5",
                       f"a_{bench['plt']}": "250", "result_comment": "من ورقة الأهل"},
                 headers={"Referer": f"/visits/{bench['ids']['visit']}/record"})
        with bench["app"].app_context():
            row = _row(bench, order)
            assert row.status == "resulted" and row.result_comment == "من ورقة الأهل"
            row.resulted_at = datetime.utcnow() - timedelta(days=days)
            bench["db"].session.commit()
    with bench["app"].app_context():
        flags = [v.flag for v in _row(bench, order).analyte_values]
        assert "critical_low" in flags, "the same approved range and critical check"
    hb = _curves(bench)[f"an:{bench['hb']}"]
    assert [p["value"] for p in hb["points"]] == [12.0, 6.5]
    page = doc.get(f"/visits/{bench['ids']['visit']}/record").get_data(as_text=True)
    assert "data-visit-curves" in page


def test_a_test_of_one_number_keeps_its_one_box(bench):
    order = _order(bench, test="plain")
    page = bench["sign_in"]("doc").get(
        f"/visits/{bench['ids']['visit']}/record").get_data(as_text=True)
    assert f'data-analyte-entry="{order}"' not in page
    assert 'name="result_value"' in page


def test_anc_is_read_off_the_cbc_by_its_name(bench):
    from app.models import LabAnalyte, LabTestAnalyte
    from app.utils import panel_alerts

    with bench["app"].app_context():
        db = bench["db"]
        anc = LabAnalyte(name="ANC", aliases="Absolute Neutrophil Count",
                         unit="x10^9/L")
        db.session.add(anc)
        db.session.flush()
        db.session.add(LabTestAnalyte(investigation_id=bench["cbc"],
                                      analyte_id=anc.id, sort_order=2))
        db.session.commit()
        bench["anc"] = anc.id
    _resulted(bench, hb="11", plt="300", anc="0.4")
    with bench["app"].app_context():
        value, _when = panel_alerts.measure(
            bench["ids"]["child"], {"source": "lab", "of": "anc", "when": "below"})
        assert value == 0.4


def test_liver_enzymes_watch_the_line_the_clinic_chose(bench):
    from app.models import (Investigation, LabAnalyte, LabTestAnalyte,
                            PanelAlertRule)
    from app.utils import panel_alerts

    with bench["app"].app_context():
        db = bench["db"]
        lft = Investigation(name_ar="وظائف كبد", name_en="Liver Function Tests",
                            code="lft", kind="lab")
        alt = LabAnalyte(name="ALT", unit="U/L")
        ast = LabAnalyte(name="AST", unit="U/L")
        db.session.add_all([lft, alt, ast])
        db.session.flush()
        db.session.add_all([
            LabTestAnalyte(investigation_id=lft.id, analyte_id=alt.id, sort_order=0),
            LabTestAnalyte(investigation_id=lft.id, analyte_id=ast.id, sort_order=1)])
        db.session.commit()
        bench.update(lft=lft.id, alt=alt.id, ast=ast.id)
    _resulted(bench, test="lft", days_ago=20, alt="30", ast="35")
    _resulted(bench, test="lft", days_ago=1, alt="90", ast="40")
    watches = {"source": "lab", "of": "lft", "when": "rise"}
    alert = {"code": "x", "watches": watches}
    with bench["app"].app_context():
        assert panel_alerts.measure(bench["ids"]["child"], watches) == (None, None), \
            "no line chosen: nothing guessed"
        assert [a.id for a in panel_alerts.lines_to_choose(alert)] == [bench["alt"], bench["ast"]]
        rule = PanelAlertRule(panel_key="k", alert_code="x", analyte_id=bench["alt"])
        chosen = panel_alerts._with_line(alert, "k", {("k", "x"): rule})
        value, _ = panel_alerts.measure(bench["ids"]["child"], chosen["watches"])
        assert value == 90
        pair = panel_alerts._last_two(bench["ids"]["child"], "lab", "lft", bench["alt"])
        assert [v for v, _w in pair] == [90, 30]
