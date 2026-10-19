"""لوح التخصص: الرقم واتجاهه (DOCTOR_EASE_PLAN.md أ-٧).

* جنب خانة الرقم: آخر قراءة بتاريخها (أ-٢)، والقراءات اللي قبلها خط صغير —
  من قرايتين وطالع؛ قراية واحدة مش اتجاه؛
* ورقم النهارده قصاد آخر مرة وهو بيتكتب: الفرق بوحدة القراية بس، من غير
  لون يقول كويس ولا وحش — ده قرار الطبيب؛
* الاختيار ما لوش خط.
"""
import os
import sys
from datetime import timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tests.test_a_clinic_that_does_not_work_specialties import (  # noqa: E402,F401
    _module, _page, desk)


def _earlier(desk, days, readings):
    from app.models import Measurement, Visit

    db = desk["db"]
    with desk["app"].app_context():
        now = db.session.get(Visit, desk["ids"]["visit"])
        v = Visit(patient_id=now.patient_id, doctor_id=now.doctor_id,
                  visit_date=now.visit_date - timedelta(days=days))
        db.session.add(v)
        db.session.flush()
        for code, text, num in readings:
            db.session.add(Measurement(patient_id=now.patient_id, visit_id=v.id, code=code,
                                       panel="dentistry", value_text=text, value_num=num))
        db.session.commit()


def test_one_reading_is_not_a_trend(desk):
    _module(desk, True)
    _earlier(desk, 30, [("overjet_mm", None, 4.5)])
    page = _page(desk)
    assert 'data-last-of="overjet_mm"' in page
    assert 'data-trend-of="overjet_mm"' not in page
    # The live difference is still offered, against the one reading there is.
    assert 'data-delta-of="overjet_mm" data-prev="4.5"' in page


def test_earlier_readings_draw_a_line_oldest_first(desk):
    from app.utils import panels

    _module(desk, True)
    _earlier(desk, 90, [("overjet_mm", None, 6.0), ("oral_hygiene", "سيئة", None)])
    _earlier(desk, 60, [("overjet_mm", None, 5.0)])
    _earlier(desk, 30, [("overjet_mm", None, 4.5), ("oral_hygiene", "متوسطة", None)])
    page = _page(desk)
    assert 'data-trend-of="overjet_mm"' in page
    assert 'data-delta-of="overjet_mm" data-prev="4.5"' in page
    # A choice has no line and no difference.
    assert 'data-trend-of="oral_hygiene"' not in page and 'data-delta-of="oral_hygiene"' not in page
    from app.models import Visit

    with desk["app"].app_context():
        last = panels.last_values(desk["db"].session.get(Visit, desk["ids"]["visit"]))
        assert [p["v"] for p in last["overjet_mm"]["trend"]] == [6.0, 5.0, 4.5]
        assert last["overjet_mm"]["value"] == "4.5"
        assert last["oral_hygiene"]["value"] == "متوسطة"
