"""How long the laboratory took — GAHAR DAS.21 and DAS.22.

Step four of the laboratory plan:

* measured from the sample's collection to its result, and judged only
  against the time the laboratory wrote on the test — STAT for an urgent
  order, routine otherwise; a test with no time is measured, never late;
* per test and period: count, median, slowest tenth, on time and late;
* every late result is listed with the reason the laboratory wrote, and the
  reason can be written from the list;
* a sample waiting past its time: whoever asked is told, and that is kept;
* the STAT list is the tests the laboratory gave a STAT time.
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

from tests.test_the_sample_nobody_drew import _order, lab  # noqa: E402,F401


def _row(c, order_id):
    from app.models import VisitInvestigation

    return c["db"].session.get(VisitInvestigation, order_id)


def _times(c, inv_key, routine=None, stat=None):
    from app.models import Investigation

    with c["app"].app_context():
        inv = c["db"].session.get(Investigation, c[inv_key])
        inv.tat_max, inv.tat_stat_max = routine, stat
        c["db"].session.commit()


def _done(c, took, urgent=None, test="cbc", name="صورة دم"):
    order = _order(c, test=test, name=name)
    now = datetime.utcnow()
    with c["app"].app_context():
        row = _row(c, order)
        row.urgent = urgent
        row.collected_at = now - timedelta(minutes=took)
        row.resulted_at = now
        row.status = "resulted"
        row.result_text = "تم"
        c["db"].session.commit()
    return order


def test_judged_only_against_the_lab_s_own_time(lab):
    from app.utils import lab_tat

    _times(lab, "cbc", routine=60, stat=20)
    routine_ok = _done(lab, 50)
    stat_late = _done(lab, 30, urgent=True)
    no_time = _done(lab, 500, test="urine", name="تحليل بول")
    with lab["app"].app_context():
        assert lab_tat.was_late(_row(lab, routine_ok)) is False
        assert lab_tat.was_late(_row(lab, stat_late)) is True
        assert lab_tat.was_late(_row(lab, no_time)) is None, "no time written, never late"


def test_the_report_per_test_and_the_late_ones_with_their_reason(lab):
    from app.utils import lab_tat
    from app.utils.clock import local_today

    _times(lab, "cbc", routine=60)
    for took in (20, 30, 40, 90):
        _done(lab, took)
    with lab["app"].app_context():
        per_test, late_rows = lab_tat.report(local_today() - timedelta(days=1), local_today())
        (entry,) = [e for e in per_test if e["name"] == "صورة دم"]
        assert (entry["count"], entry["within"], entry["late"], entry["limit"]) == (4, 3, 1, 60)
        assert entry["median"] in (30, 40) and entry["p90"] == 90
        late_id = late_rows[0].id
    boss = lab["sign_in"]("boss")
    page = boss.get("/labs/turnaround").get_data(as_text=True)
    assert f'data-late-row="{late_id}"' in page and "data-per-test" in page
    boss.post(f"/labs/order/{late_id}/late-reason", data={"reason": "الجهاز وقف ساعة", "back": "report"})
    with lab["app"].app_context():
        assert _row(lab, late_id).delay_reason == "الجهاز وقف ساعة"
    assert "data-to-turnaround" in boss.get("/labs/").get_data(as_text=True)


def test_a_sample_waiting_past_its_time_and_whoever_asked_is_told(lab):
    from app.utils import labs

    _times(lab, "cbc", routine=30)
    order = _order(lab)
    with lab["app"].app_context():
        labs.collect(_row(lab, order), at=datetime.utcnow() - timedelta(minutes=45))
        lab["db"].session.commit()
    boss = lab["sign_in"]("boss")
    page = boss.get(f"/labs/order/{order}").get_data(as_text=True)
    assert "data-late-box" in page and "data-tell-delay" in page
    boss.post(f"/labs/order/{order}/delay", data={"reason": "إعادة التحليل"})
    with lab["app"].app_context():
        assert _row(lab, order).delay_told_at is None, "nobody named, nothing recorded"
    boss.post(f"/labs/order/{order}/delay", data={"told_to": "د. أحمد", "reason": "إعادة التحليل"})
    with lab["app"].app_context():
        row = _row(lab, order)
        assert (row.delay_told_to, row.delay_reason, row.delay_told_by) == (
            "د. أحمد", "إعادة التحليل", lab["ids"]["admin"])
    assert "data-delay-told" in boss.get(f"/labs/order/{order}").get_data(as_text=True)


def test_the_stat_list_is_the_tests_given_a_stat_time(lab):
    from app.utils import lab_tat

    _times(lab, "cbc", routine=60, stat=20)
    with lab["app"].app_context():
        assert [i.id for i in lab_tat.stat_list()] == [lab["cbc"]]
    page = lab["sign_in"]("boss").get("/labs/turnaround").get_data(as_text=True)
    assert f'data-stat-row="{lab["cbc"]}"' in page
