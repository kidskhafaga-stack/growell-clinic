"""لوح التخصص: الإجابة بضغطة واحدة (DOCTOR_EASE_PLAN.md أ-١، أ-٥).

* الاختيار اللي إجاباته ٦ أو أقل بقى أزرار بنفس الاسم ونفس القيم، والقايمة
  فضلت للي إجاباته كتير؛
* السيرفر بيقرا نفس اللي كان بيقراه: الإجابة المختارة بتتحفظ، ومفيش اختيار =
  مفيش قراءة، زي «—» بالظبط؛
* خانات الأرقام بتفتح كيبورد أرقام على التابلت.
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tests.test_a_clinic_that_does_not_work_specialties import (  # noqa: E402,F401
    _module, _page, _readings, _save, desk)


def _dentistry():
    path = os.path.join(os.path.dirname(__file__), "..", "app", "data", "specialty_panels.json")
    return {f["code"]: f for f in json.load(open(path, encoding="utf-8"))["panels"]["dentistry"]["fields"]}


def test_a_short_choice_is_one_tap_and_a_long_one_stays_a_menu(desk):
    _module(desk, True)
    page = _page(desk)
    fields = _dentistry()
    short = [c for c, f in fields.items() if f["type"] == "choice" and len(f["options"]) <= 6]
    long_ = [c for c, f in fields.items() if f["type"] == "choice" and len(f["options"]) > 6]
    assert short and long_
    for code in short:
        assert f'data-pchips="{code}"' in page, code
        assert f'<select class="select" name="m_{code}">' not in page, code
        for opt in fields[code]["options"]:
            assert f'name="m_{code}" value="{opt}"' in page
    for code in long_:
        assert f'<select class="select" name="m_{code}">' in page, code
    numbers = re.findall(r'<input class="input" type="number"[^>]*name="m_[a-z0-9_]+"', page)
    assert numbers and all('inputmode="decimal"' in n for n in numbers)


def test_the_tapped_answer_is_saved_shown_and_cleared_as_before(desk):
    _module(desk, True)
    _save(desk, specialty_panel="dentistry", m_oral_hygiene="جيدة", m_gingiva="سليمة")
    rows = _readings(desk)
    assert rows["oral_hygiene"].value_text == "جيدة" and rows["gingiva"].value_text == "سليمة"
    page = _page(desk)
    assert re.search(r'class="md-chip pchip is-selected">\s*<input type="radio" name="m_oral_hygiene" value="جيدة"\s*checked', page)
    # Nothing ticked is nothing recorded — what «—» meant.
    _save(desk, specialty_panel="dentistry", m_gingiva="سليمة")
    rows = _readings(desk)
    assert "oral_hygiene" not in rows and rows["gingiva"].value_text == "سليمة"
