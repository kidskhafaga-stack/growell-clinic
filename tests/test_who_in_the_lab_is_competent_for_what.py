"""كفاءة العاملين في المعمل — GAHAR `DAS.11`.

* **(أ)–(هـ)** — كل تقييم بيقول استعمل أنهي طريقة من الخمسة؛
* **دليل ٢** — سنوي ومتسجّل في ملف الشخص، والقديم بيفضل؛ واللي ما اتقيّمش
  أو عدّى ميعاده باين؛
* **دليل ٣** — الشغل حسب الكفاءة: تقرير بالنتايج اللي اتكتبت أو اتعتمدت من
  حد مالوش تقييم ساري للقسم، وتنبيه لو المعمل شغّله — **كلمة مش منع**.
"""
import os
import sys
from datetime import timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

from tests.test_the_sample_nobody_drew import _order, lab  # noqa: E402,F401


@pytest.fixture()
def bench(lab):
    """The blood count in the haematology section."""
    from app.models import Investigation

    with lab["app"].app_context():
        lab["db"].session.get(Investigation, lab["cbc"]).category = "Hematology"
        lab["db"].session.commit()
    return lab


def _assess(c, user="doctor", who="boss", **extra):
    from app.utils.clock import local_today

    data = {"section": "Hematology", "assessed_on": local_today().isoformat(),
            "methods": ["observe_routine", "blind_samples"],
            "result": "competent", **extra}
    return c["sign_in"](who).post(f"/labs/staff/{c['ids'][user]}/assess",
                                  data=data)


def test_an_assessment_names_its_methods_and_the_assessor_decides(bench):
    from app.models import LabCompetency

    _assess(bench, methods=[])                       # no method
    _assess(bench, result="")                        # no verdict
    _assess(bench, methods=["made_up"])              # not one of the five
    with bench["app"].app_context():
        assert LabCompetency.query.count() == 0
    _assess(bench, note="ممتاز في العينات العمياء")
    with bench["app"].app_context():
        (row,) = LabCompetency.query.all()
        assert row.method_list == ["observe_routine", "blind_samples"]
        assert row.result == "competent" and row.section == "Hematology"
        assert row.assessor_id == bench["ids"]["admin"]
    page = bench["sign_in"]("boss").get(
        f"/labs/staff/{bench['ids']['doctor']}").get_data(as_text=True)
    assert "data-file-row" in page and "ممتاز في العينات العمياء" in page


def test_dates_are_checked(bench):
    from app.models import LabCompetency
    from app.utils.clock import local_today

    today = local_today()
    _assess(bench, assessed_on=(today + timedelta(days=1)).isoformat())
    _assess(bench, due_on=today.isoformat())         # due on the same day
    _assess(bench, assessed_on="غلط")
    with bench["app"].app_context():
        assert LabCompetency.query.count() == 0


def test_the_file_keeps_every_year_and_the_newest_decides(bench):
    from app.models import LabCompetency
    from app.utils import lab_competency as comp
    from app.utils.clock import local_today

    today = local_today()
    _assess(bench, assessed_on=(today - timedelta(days=400)).isoformat(),
            due_on=(today - timedelta(days=35)).isoformat())
    with bench["app"].app_context():
        doc = bench["ids"]["doctor"]
        assert not comp.stands(doc, "Hematology")            # past due
        assert comp.stands(doc, "Hematology", today - timedelta(days=100))
        line = next(l for l in comp.overview() if l["user"].id == doc)
        assert line["states"]["Hematology"] == "overdue" and line["attention"]

    _assess(bench, result="needs_training")
    with bench["app"].app_context():
        assert LabCompetency.query.count() == 2, "last year's stays"
        assert not comp.stands(bench["ids"]["doctor"], "Hematology")

    # A competent assessment for the whole laboratory covers every section.
    _assess(bench, section="")
    with bench["app"].app_context():
        assert comp.stands(bench["ids"]["doctor"], "Chemistry")
        assert comp.stands(bench["ids"]["doctor"], None)


def test_only_the_head_of_the_lab_writes(bench):
    from app.models import LabCompetency

    assert _assess(bench, who="doc").status_code == 403
    assert bench["sign_in"]("doc").post("/labs/staff/check",
                                        data={"on": "1"}).status_code == 403
    with bench["app"].app_context():
        assert LabCompetency.query.count() == 0
    page = bench["sign_in"]("doc").get("/labs/staff").get_data(as_text=True)
    assert "data-staff-overview" in page and "data-competency-check" not in page
    # Reception does not reach the laboratory at all.
    assert bench["sign_in"]("desk").get("/labs/staff").status_code in (302, 403)


def test_the_list_says_who_was_never_assessed(bench):
    page = bench["sign_in"]("boss").get("/labs/staff").get_data(as_text=True)
    assert f'data-staff-row="{bench["ids"]["doctor"]}"' in page
    assert "data-never" in page
    # The rack says nothing until the lab keeps these files at all.
    rack = bench["sign_in"]("boss").get("/labs/").get_data(as_text=True)
    assert "data-to-staff" in rack and "data-staff-attention" not in rack
    _assess(bench, result="not_competent")
    rack = bench["sign_in"]("boss").get("/labs/").get_data(as_text=True)
    assert "data-staff-attention" in rack


def test_a_word_on_the_order_never_a_wall(bench):
    order = _order(bench)
    doc = bench["sign_in"]("doc")
    page = doc.get(f"/labs/order/{order}").get_data(as_text=True)
    assert "data-competency-warning" not in page, "off until switched on"

    bench["sign_in"]("boss").post("/labs/staff/check", data={"on": "1"})
    page = doc.get(f"/labs/order/{order}").get_data(as_text=True)
    assert "data-competency-warning" in page and "Hematology" in page
    # And the result is saved all the same.
    doc.post(f"/labs/order/{order}/result", data={"result_value": "11.2"})
    from tests.test_the_sample_nobody_drew import _state

    assert _state(bench, order)["status"] == "resulted"

    _assess(bench)
    page = doc.get(f"/labs/order/{order}").get_data(as_text=True)
    assert "data-competency-warning" not in page


def test_the_report_counts_work_outside_competency(bench):
    from app.utils import lab_competency as comp
    from app.utils.clock import local_today

    first = _order(bench)
    bench["sign_in"]("doc").post(f"/labs/order/{first}/result",
                                 data={"result_value": "11.2"})
    _assess(bench)
    second = _order(bench)
    bench["sign_in"]("doc").post(f"/labs/order/{second}/result",
                                 data={"result_value": "12.0"})
    today = local_today()
    with bench["app"].app_context():
        rows = comp.outside(today, today)
        # Assessed the same day: the assessment stands for the whole day,
        # so neither result counts.
        assert rows == []
        from app.models import LabCompetency

        LabCompetency.query.delete()
        bench["db"].session.commit()
        rows = comp.outside(today, today)
        assert {r["order"].id for r in rows} == {first, second}
        assert all(r["role"] == "resulted" and r["section"] == "Hematology"
                   for r in rows)
    page = bench["sign_in"]("boss").get("/labs/staff/outside").get_data(as_text=True)
    assert f'data-outside-row="{first}-resulted"' in page
