"""لوح التخصص: «زي آخر مرة» والخانة اللي بتظهر لما تلزم
(DOCTOR_EASE_PLAN.md أ-٢، أ-٤).

* إجابة الزيارة اللي فاتت بتظهر جنب كل خانة بتاريخها؛ زرار النقل للاختيارات بس
  — مش للأرقام، ومش للخانة اللي التخصص قال إنها بتتقرر كل جلسة؛
* «سبب التخدير الكلي» بيتحفظ بس لما طريقة التعامل «تخدير كلي» — السيرفر بيطبّق
  الشرط مش الشاشة بس؛
* كل شرط بيشاور على خانة موجودة في نفس اللوح وعلى إجابات من اختياراتها.
"""
import json
import os
import sys
from datetime import timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tests.test_a_clinic_that_does_not_work_specialties import (  # noqa: E402,F401
    _module, _page, _readings, _save, desk)


def _catalogue():
    path = os.path.join(os.path.dirname(__file__), "..", "app", "data", "specialty_panels.json")
    return json.load(open(path, encoding="utf-8"))["panels"]


def test_every_condition_points_inside_its_own_panel():
    for key, panel in _catalogue().items():
        fields = {f["code"]: f for f in panel["fields"]}
        for f in panel["fields"]:
            assert f.get("carry", True) in (True, False), (key, f["code"])
            cond = f.get("show_if")
            if not cond:
                continue
            target = fields.get(cond["code"])
            assert target is not None and target["type"] == "choice", (key, f["code"])
            assert cond["in"] and set(cond["in"]) <= set(target["options"]), (key, f["code"])


def test_last_time_is_shown_and_only_a_choice_offers_the_copy(desk):
    from app.models import Measurement, Visit

    _module(desk, True)
    db = desk["db"]
    with desk["app"].app_context():
        now = db.session.get(Visit, desk["ids"]["visit"])
        before = Visit(patient_id=now.patient_id, doctor_id=now.doctor_id,
                       visit_date=now.visit_date - timedelta(days=30))
        db.session.add(before)
        db.session.flush()
        for code, text, num in (("oral_hygiene", "متوسطة", None), ("ortho_decision", "متابعة", None),
                                ("overjet_mm", None, 4.5)):
            db.session.add(Measurement(patient_id=now.patient_id, visit_id=before.id, code=code,
                                       panel="dentistry", value_text=text, value_num=num))
        db.session.commit()
    page = _page(desk)
    assert 'data-last-of="oral_hygiene"' in page and 'data-carry="oral_hygiene"' in page
    assert 'data-last-of="overjet_mm"' in page and 'data-carry="overjet_mm"' not in page, "a number is shown, never copied"
    assert 'data-last-of="ortho_decision"' in page and 'data-carry="ortho_decision"' not in page, \
        "a per-session decision offers no copy"
    assert 'data-carry-all="dentistry"' in page
    assert 'data-field="oral_hygiene"' in page and 'data-last="متوسطة"' in page


def test_a_conditional_field_is_saved_only_when_it_applies(desk):
    _module(desk, True)
    page = _page(desk)
    assert 'data-field="ga_reason"' in page and 'data-show-if="behaviour_route"' in page
    _save(desk, specialty_panel="dentistry", m_behaviour_route="إقناع وتطمين",
          m_ga_reason="صغر السن", m_occlusion="طبيعي", m_crossbite_site="أمامي")
    rows = _readings(desk)
    assert "ga_reason" not in rows and "crossbite_site" not in rows
    assert rows["behaviour_route"].value_text == "إقناع وتطمين"
    _save(desk, specialty_panel="dentistry", m_behaviour_route="تخدير كلي",
          m_ga_reason="صغر السن", m_occlusion="إطباق عكسي", m_crossbite_site="أمامي")
    rows = _readings(desk)
    assert rows["ga_reason"].value_text == "صغر السن" and rows["crossbite_site"].value_text == "أمامي"
    # The answer that called for it changes: the dependent reading goes too.
    _save(desk, specialty_panel="dentistry", m_behaviour_route="إقناع وتطمين",
          m_ga_reason="صغر السن", m_occlusion="طبيعي")
    assert "ga_reason" not in _readings(desk)
