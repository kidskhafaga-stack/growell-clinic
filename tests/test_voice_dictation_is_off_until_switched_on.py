"""الإملاء بالصوت (DOCTOR_EASE_PLAN.md ب-٥).

* مقفول افتراضياً: المتصفح بيبعت الصوت لخدمة جوجل، فده قرار العيادة؛
* لما يتفتح: الشكوى والفحص وقصة الحالة عليهم ميكروفون؛ والمقفول مفيهوش أي حاجة؛
* المفتاح في الإعدادات ومعاه جملة بتقول الصوت رايح فين.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def _visit_page(clinic):
    return clinic["sign_in"]("doc").get(f"/visits/{clinic['ids']['visit']}/record").get_data(as_text=True)


def test_off_by_default_nothing_on_the_page(clinic):
    page = _visit_page(clinic)
    assert "data-dictate" not in page and "SpeechRecognition" not in page


def test_on_puts_a_microphone_on_the_three_boxes(clinic):
    from app.models import Setting

    with clinic["app"].app_context():
        Setting.set("voice_dictation", "1")
        clinic["db"].session.commit()
    page = _visit_page(clinic)
    assert 'name="chief_complaint" rows="2" x-model="cc" data-dictate' in page
    assert 'name="clinical_exam" rows="3" x-model="exam" data-dictate' in page
    assert "SpeechRecognition" in page


def test_the_switch_says_where_the_voice_goes(clinic):
    page = clinic["sign_in"]("boss").get("/settings/").get_data(as_text=True)
    assert "data-voice-setting" in page and 'name="voice_dictation"' in page
    assert "جوجل" in page or "Google" in page
