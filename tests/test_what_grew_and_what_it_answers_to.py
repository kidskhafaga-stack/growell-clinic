"""الميكروبيولوجي — اللي نما، وحساسيته للمضادات.

* القوايم **بتاعة المعمل**: الكائنات والمضادات، بتتلزق مرة؛ ومفيش حاجة جاهزة؛
* التحليل اللي المعمل علّمه «مزرعة» بتتكتب نتيجته بالكائن وقراءات S/I/R
  اللي المعمل قراها — والملخص بيتكتب في تقرير الطلب فبيظهر في كل مكان؛
* المبدئي بيقول إنه مبدئي، والكائن المعلّم «تنبيه» بيتقال؛
* الأنتيبيوجرام بيعدّ **أول عزلة لكل كائن لكل طفل** (CLSI M39)، والقليل بيبان باهت.
"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def bench(clinic):
    from app.models import Investigation, Setting

    with clinic["app"].app_context():
        Setting.set("mod_enabled:labs", "1")
        urine = Investigation(name_ar="مزرعة بول", name_en="Urine culture", kind="lab",
                              is_culture=True)
        clinic["db"].session.add(urine)
        clinic["db"].session.commit()
        clinic["urine"] = urine.id
    boss = clinic["sign_in"]("boss")
    boss.post("/labs/micro/organisms", data={"names": "Escherichia coli\nStaphylococcus aureus (MRSA)\nescherichia COLI"})
    boss.post("/labs/micro/antibiotics", data={"names": "Ampicillin\nCeftriaxone\nNitrofurantoin"})
    from app.models import MicroAntibiotic, MicroOrganism
    with clinic["app"].app_context():
        clinic["org"] = {o.name: o.id for o in MicroOrganism.query}
        clinic["abx"] = {a.name: a.id for a in MicroAntibiotic.query}
    return clinic


def _order(c, patient=None):
    from app.models import VisitInvestigation

    with c["app"].app_context():
        row = VisitInvestigation(visit_id=c["ids"]["visit"], patient_id=patient or c["ids"]["child"],
                                 investigation_id=c["urine"], kind="lab", name="مزرعة بول",
                                 status="collected")
        c["db"].session.add(row)
        c["db"].session.commit()
        return row.id


def _isolate(c, order, organism, readings, count=">10^5 CFU/mL"):
    from app.models import CultureIsolate

    boss = c["sign_in"]("boss")
    boss.post(f"/labs/order/{order}/culture/isolate",
              data={"organism_id": c["org"][organism], "count": count})
    with c["app"].app_context():
        iso = CultureIsolate.query.order_by(CultureIsolate.id.desc()).first().id
    data = {"count": count, **{f"r_{c['abx'][k]}": v for k, v in readings.items()}}
    boss.post(f"/labs/order/{order}/culture/isolate/{iso}", data=data)
    return iso


def _order_row(c, order_id):
    from app.models import VisitInvestigation

    with c["app"].app_context():
        return c["db"].session.get(VisitInvestigation, order_id)


def test_the_lists_are_the_lab_s_and_pasted_once(bench):
    assert len(bench["org"]) == 2, "a name already there, in any case, is skipped"
    assert set(bench["abx"]) == {"Ampicillin", "Ceftriaxone", "Nitrofurantoin"}
    assert bench["sign_in"]("doc").get("/labs/micro").status_code in (302, 403)


def test_a_culture_is_answered_with_what_grew_and_its_readings(bench):
    order = _order(bench)
    page = bench["sign_in"]("boss").get(f"/labs/order/{order}").get_data(as_text=True)
    assert "data-culture" in page and 'name="result_value"' not in page
    _isolate(bench, order, "Escherichia coli", {"Ampicillin": "R", "Ceftriaxone": "S"})
    row = _order_row(bench, order)
    assert row.status == "resulted"
    assert "PRELIMINARY" in row.result_text and "Escherichia coli (>10^5 CFU/mL)" in row.result_text
    assert "Resistant: Ampicillin" in row.result_text and "Sensitive: Ceftriaxone" in row.result_text
    bench["sign_in"]("boss").post(f"/labs/order/{order}/culture",
                                  data={"outcome": "growth", "final": "1"})
    assert "PRELIMINARY" not in _order_row(bench, order).result_text


def test_no_growth_and_an_alert_organism(bench):
    from app.models import MicroOrganism

    order = _order(bench)
    bench["sign_in"]("boss").post(f"/labs/order/{order}/culture", data={"outcome": "no_growth"})
    assert _order_row(bench, order).result_text.endswith("No growth")
    mrsa = bench["org"]["Staphylococcus aureus (MRSA)"]
    bench["sign_in"]("boss").post(f"/labs/micro/organisms/{mrsa}", data={"action": "alert"})
    with bench["app"].app_context():
        assert bench["db"].session.get(MicroOrganism, mrsa).alert
    other = _order(bench)
    _isolate(bench, other, "Staphylococcus aureus (MRSA)", {"Ceftriaxone": "R"})
    assert "ALERT ORGANISM" in _order_row(bench, other).result_text
    page = bench["sign_in"]("boss").get(f"/labs/order/{other}").get_data(as_text=True)
    assert "data-alert-organism" in page


def test_a_test_that_is_not_a_culture_has_no_culture_door(bench):
    from app.models import Investigation, VisitInvestigation

    with bench["app"].app_context():
        cbc = Investigation(name_ar="صورة دم", kind="lab")
        bench["db"].session.add(cbc)
        bench["db"].session.flush()
        row = VisitInvestigation(visit_id=bench["ids"]["visit"], patient_id=bench["ids"]["child"],
                                 investigation_id=cbc.id, kind="lab", name="CBC", status="collected")
        bench["db"].session.add(row)
        bench["db"].session.commit()
        oid = row.id
    assert bench["sign_in"]("boss").post(f"/labs/order/{oid}/culture",
                                         data={"outcome": "no_growth"}).status_code == 404


def test_the_antibiogram_counts_the_first_isolate_per_child(bench):
    from app.utils import micro

    first = _order(bench)
    _isolate(bench, first, "Escherichia coli", {"Ampicillin": "R", "Ceftriaxone": "S"})
    again = _order(bench)                                   # same child, same organism
    _isolate(bench, again, "Escherichia coli", {"Ampicillin": "S", "Ceftriaxone": "S"})
    with bench["app"].app_context():
        table = micro.antibiogram(date(2000, 1, 1), date(2100, 1, 1))
        row = table["rows"][0]
        assert row["n"] == 1 and row["cells"][bench["abx"]["Ampicillin"]] == (0, 1)
    page = bench["sign_in"]("boss").get("/labs/antibiogram?start=2000-01-01&end=2100-01-01").get_data(as_text=True)
    assert "data-antibiogram" in page and f'data-org="{bench["org"]["Escherichia coli"]}"' in page


def test_an_isolate_taken_off_leaves_the_summary_without_it(bench):
    from app.models import CultureIsolate

    order = _order(bench)
    keep = _isolate(bench, order, "Escherichia coli", {"Ampicillin": "R"})
    gone = _isolate(bench, order, "Staphylococcus aureus (MRSA)", {"Ceftriaxone": "S"})
    page = bench["sign_in"]("boss").post(f"/labs/order/{order}/culture/isolate/{gone}",
                                         data={"remove": "1"})
    assert page.status_code == 302
    with bench["app"].app_context():
        assert bench["db"].session.get(CultureIsolate, gone) is None
        assert bench["db"].session.get(CultureIsolate, keep) is not None
    text = _order_row(bench, order).result_text
    assert "Escherichia coli" in text and "Staphylococcus" not in text
