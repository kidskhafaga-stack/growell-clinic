"""المقارنة بآخر نتيجة (Delta check).

هيموجلوبين ٧ واطي؛ وهيموجلوبين ٧ لطفل كان ١٢ يوم التلات يا إما نزيف يا إما
أنبوبة طفل تاني — والحدود الطبيعية بتمسك الأولى ومش بتمسك التانية. المتمسوك:

* المقارنة **بأرقام المعمل** — من غيرها مفيش مقارنة خالص؛
* فرق بالوحدة أو بالنسبة، وآخر نتيجة لازم تكون من خلال الأيام اللي المعمل كتبها؛
* اللي اتقارن بيه بيتحفظ على النتيجة، وبيبان جنبها للفني والطبيب؛
* وحدة مختلفة مش بتتقارن؛ ومفيش حاجة بتتمنع.
"""
import os
import sys
from datetime import timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tests.test_a_result_line_by_line import _fresh_cache, _order, _post, bench  # noqa: E402,F401


def _arm(c, **limits):
    from app.models import LabAnalyte

    with c["app"].app_context():
        a = c["db"].session.get(LabAnalyte, c["hb"])
        for k, v in limits.items():
            setattr(a, k, v)
        c["db"].session.commit()


def _value(c, order_id):
    from app.models import LabResultValue

    with c["app"].app_context():
        return LabResultValue.query.filter_by(order_id=order_id, analyte_id=c["hb"]).one()


def test_nothing_is_compared_until_the_lab_writes_its_figures(bench):
    first = _order(bench, collected_minutes_ago=60 * 24 * 3)
    _post(bench, first, hb="12")
    second = _order(bench, collected_minutes_ago=5)
    _post(bench, second, hb="7")
    v = _value(bench, second)
    assert v.delta_hit is None and v.delta_prev is None


def test_a_jump_past_the_lab_s_figure_is_said_beside_the_value(bench):
    _arm(bench, delta_abs=2.0)
    first = _order(bench, collected_minutes_ago=60 * 24 * 3)
    _post(bench, first, hb="12")
    second = _order(bench, collected_minutes_ago=5)
    resp = _post(bench, second, hb="7")
    assert resp.status_code in (200, 302), "nothing is blocked"
    v = _value(bench, second)
    assert v.delta_hit is True and v.delta_prev == 12.0 and v.value == 7.0
    page = bench["sign_in"]("boss").get(f"/labs/order/{second}").get_data(as_text=True)
    assert f'data-delta-hit="{v.id}"' in page
    third = _order(bench, collected_minutes_ago=1)
    _post(bench, third, hb="7.5")
    small = _value(bench, third)
    assert not small.delta_hit and small.delta_prev == 7.0


def test_a_percentage_and_an_old_previous(bench):
    _arm(bench, delta_pct=30.0, delta_days=7)
    first = _order(bench, collected_minutes_ago=60 * 24 * 30)
    _post(bench, first, hb="12")
    with bench["app"].app_context():
        from app.models import VisitInvestigation
        row = bench["db"].session.get(VisitInvestigation, first)
        row.created_at = row.created_at - timedelta(days=30)
        bench["db"].session.commit()
    second = _order(bench, collected_minutes_ago=5)
    _post(bench, second, hb="7")
    assert not _value(bench, second).delta_hit, "the last one is older than the lab's window"
    third = _order(bench, collected_minutes_ago=1)
    _post(bench, third, hb="10")
    v = _value(bench, third)
    assert v.delta_hit is True and v.delta_prev == 7.0          # 3/7 = 43% > 30%


def test_a_different_unit_is_not_compared(bench):
    from app.models import LabResultValue

    _arm(bench, delta_abs=2.0)
    first = _order(bench, collected_minutes_ago=60)
    _post(bench, first, hb="12")
    with bench["app"].app_context():
        row = LabResultValue.query.filter_by(order_id=first).one()
        row.unit = "g/L"
        bench["db"].session.commit()
    second = _order(bench, collected_minutes_ago=5)
    _post(bench, second, hb="7")
    assert _value(bench, second).delta_prev is None


def test_the_lab_writes_its_figures_on_the_test_s_page(bench):
    from app.models import LabAnalyte

    boss = bench["sign_in"]("boss")
    page = boss.get(f"/labs/tests/{bench['cbc']}/ranges").get_data(as_text=True)
    assert f'data-delta-box="{bench["hb"]}"' in page
    url = f"/labs/tests/{bench['cbc']}/analytes/{bench['hb']}/delta"
    boss.post(url, data={"delta_abs": "-1"})
    with bench["app"].app_context():
        assert bench["db"].session.get(LabAnalyte, bench["hb"]).delta_abs is None
    boss.post(url, data={"delta_abs": "2,5", "delta_days": "14"})
    with bench["app"].app_context():
        a = bench["db"].session.get(LabAnalyte, bench["hb"])
        assert (a.delta_abs, a.delta_pct, a.delta_days) == (2.5, None, 14)
    assert bench["sign_in"]("doc").post(url, data={"delta_abs": "9"}).status_code in (302, 403)
