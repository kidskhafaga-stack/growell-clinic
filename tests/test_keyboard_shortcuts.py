"""اختصارات لوحة المفاتيح (DOCTOR_EASE_PLAN.md ب-٧).

* زرار بيقول حرفه بنفسه (`data-key="KeyR"` — الزرار الفعلي، علشان يشتغل
  والكيبورد عربي)، و`data-key-save` لـ Ctrl+S؛
* في الكشف: حفظ (Ctrl+S)، روشتة (R)، شهادة (C)، حجز متابعة (B)؛ وفي الروشتة:
  حفظ وطباعة (Ctrl+S)، وطباعة (P)؛
* «?» بتفتح شاشة «اختصارات» صغيرة فيها اللي في الصفحة؛
* إنهاء الزيارة مالوش اختصار: ضغطة غلط ما تقفلش زيارة.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def test_the_visit_names_its_keys(clinic):
    page = clinic["sign_in"]("doc").get(f"/visits/{clinic['ids']['visit']}/record").get_data(as_text=True)
    assert 'form="visitForm" data-key-save' in page
    for key in ("KeyR", "KeyC", "KeyB"):
        assert f'data-key="{key}"' in page, key
    assert 'id="keysBox"' in page and "data-keys-open" in page
    start = page.index('action="/visits/%d/complete"' % clinic["ids"]["visit"])
    assert "data-key" not in page[start:start + 400], "finishing a visit has no key"


def test_every_page_has_the_shortcuts_box_and_one_key_each(clinic):
    import re

    page = clinic["sign_in"]("doc").get(f"/visits/{clinic['ids']['visit']}/record").get_data(as_text=True)
    keys = re.findall(r'<[a-z]+ [^>\n]*data-key="(\w+)"', page)
    assert len(keys) == len(set(keys)), "two buttons on one key"
    home = clinic["sign_in"]("doc").get("/dashboard").get_data(as_text=True)
    assert 'id="keysBox"' in home
