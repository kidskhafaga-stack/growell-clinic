"""«١٢ كجم» ما بتقولش حاجة عن طفل.

على طفل سنتين دي طبيعية، وعلى طفل ست سنين دي مشكلة. الرقم الخام لوحده مش
قراية إكلينيكية — **المئوي** هو القراية، والفرق بينهم هو محرّك LMS اللي
موجود في البرنامج من زمان.

والمحرّك كان شغّال فعلاً: WHO صفر لخمس سنين وCDC لعشرين، أربع مؤشرات منهم
محيط الرأس، وتصحيح خداج. وكان بيوصل لشاشة المنحنى وللروشتة المطبوعة —
**والملف مكانش واحد منهم**. تبويب النمو كان بيقرا الجدول الخام ويطبع
كيلوجرامات، والخاصية اللي بتحسب المئوي (`growth_picture`) قاعدة جنبه
بيستعملها غيره.

ودي بالظبط فجوة النوع الأول في جدول الملف الطبي: شغل اتعمل واتدفع تمنه
وما بيوصلش من الملف — `IMT.08` دليل ٥.

**والنص التاني من الملف ده عن التنبيهات.** «عبر منحنى النمو لأسفل» مش
«الكيلو نزل»: طفل ممكن يزيد ٢٠٠ جرام وينزل من المئوي ٩٧ للمئوي ٨٥، وطفل
وزنه ثابت ممكن يكون ماشي صح. اللي بيتحرّك هو الـZ.
"""
import os
import sys
from datetime import timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def grown(clinic):
    """طفل سنتين، وطفل تاني علشان فلتر ناقص ما يعديش."""
    from app.models import Patient
    from app.utils.clock import local_today

    with clinic["app"].app_context():
        child = clinic["db"].session.get(Patient, clinic["ids"]["child"])
        child.date_of_birth = local_today() - timedelta(days=365 * 2)
        other = Patient(patient_number="GR-2", full_name="طفل تاني",
                        gender="male", is_active=True,
                        date_of_birth=local_today() - timedelta(days=365 * 2))
        clinic["db"].session.add(other)
        clinic["db"].session.commit()
        clinic["ids"]["other_child"] = other.id
    return clinic


def _measure(grown, weight=None, height=None, head=None, days_ago=0,
             patient_id=None):
    from app.models import GrowthRecord
    from app.utils.clock import local_today

    with grown["app"].app_context():
        grown["db"].session.add(GrowthRecord(
            patient_id=patient_id or grown["ids"]["child"],
            record_date=local_today() - timedelta(days=days_ago),
            weight_kg=weight, height_cm=height, head_circ_cm=head))
        grown["db"].session.commit()


def _file(grown):
    return grown["sign_in"]("doc").get(
        f"/patients/{grown['ids']['child']}").get_data(as_text=True)


# ------------------------------------------- الملف بيوري المئوي ----
def test_the_file_shows_the_centile_next_to_the_measurement(grown):
    """مش الكيلو لوحده. ده اللي الملف كان بيعمله."""
    _measure(grown, weight=12.0, height=80.0)

    page = _file(grown)

    assert 'data-growth-centile="wfa"' in page
    assert 'data-growth-centile="hfa"' in page


def test_the_file_still_shows_a_measurement_the_standard_cannot_score(grown):
    """قياس بره مدى المرجع بيتكتب برقمه من غير مئوي — شيل الصف كان هيخفي
    قياس حقيقي علشان المعيار مالوش كلام عليه."""
    from app.models import Patient
    from app.utils.clock import local_today

    with grown["app"].app_context():
        child = grown["db"].session.get(Patient, grown["ids"]["child"])
        child.date_of_birth = local_today() - timedelta(days=365 * 30)
        grown["db"].session.commit()
    _measure(grown, weight=70.0)

    page = _file(grown)

    assert 'data-growth-row="wfa"' in page
    assert "70.0" in page


def test_a_file_with_no_measurements_says_so(grown):
    assert 'data-growth-picture' not in _file(grown)


def test_the_banner_and_the_tab_cannot_disagree(grown):
    """كانوا استعلامين وحسابين لنفس الصف على نفس الشاشة.

    دلوقتي الشريط مشتقّ من نفس الصفوف اللي التبويب بيرسمها، فاتفاقهم
    بالبناء مش بالصدفة — وده اللي docstring بتاع `reference_for` بيحذّر
    منه بالحرف بين الروشتة والملف.
    """
    from app.models import Patient
    from app.utils.growth import concern

    _measure(grown, weight=6.0, height=70.0)

    with grown["app"].app_context():
        child = grown["db"].session.get(Patient, grown["ids"]["child"])
        picture = child.growth_picture
        flagged = concern(picture["rows"], picture["record"])

    assert flagged is not None
    row = next(r for r in picture["rows"]
               if r["indicator"] == flagged["indicator"])
    assert (row["z"], row["percentile"]) == (flagged["z"],
                                             flagged["percentile"])


def test_the_worst_reading_is_the_one_flagged(grown):
    from app.models import Patient
    from app.utils.growth import concern

    _measure(grown, weight=6.0, height=95.0)

    with grown["app"].app_context():
        child = grown["db"].session.get(Patient, grown["ids"]["child"])
        picture = child.growth_picture
        flagged = concern(picture["rows"], picture["record"])
        worst = max((r for r in picture["rows"] if r["z"] is not None),
                    key=lambda r: abs(r["z"]))

    assert flagged["indicator"] == worst["indicator"]


def test_a_reading_inside_the_normal_band_is_not_flagged(grown):
    """الشريط للي بره ±٢. طفل في المنتصف مالوش شريط — وشريط دايماً موجود
    بيبطّل يعني حاجة."""
    from app.models import Patient
    from app.utils.growth import concern

    _measure(grown, weight=12.5, height=87.0)

    with grown["app"].app_context():
        child = grown["db"].session.get(Patient, grown["ids"]["child"])
        picture = child.growth_picture
        assert concern(picture["rows"], picture["record"]) is None


# ------------------------------- الكيلو بيزيد والطفل بينزل ----
def _number(grown, panel, code, value):
    return grown["sign_in"]("boss").post("/panels/alerts/set", data={
        "panel_key": panel, "alert_code": code, "threshold": str(value),
        "is_active": "1"}, follow_redirects=True)


def _fired(grown, keys, patient_id=None):
    from app.utils import panel_alerts

    with grown["app"].app_context():
        return {a["code"] for a in panel_alerts.evaluate(
            patient_id or grown["ids"]["child"], keys)}


def _panels_on(grown):
    from app.models import Setting

    with grown["app"].app_context():
        Setting.set("mod_enabled:panels", "1")
        grown["db"].session.commit()


def test_a_weight_that_rose_can_still_be_a_child_falling(grown):
    """**السطر اللي الملف ده موجود علشانه.**

    وزن زاد ٢٠٠ جرام، والطفل نزل من المئوي ٩٧ للمئوي ٨٥. قراية خام
    كانت هتشوف «زيادة»، والـZ بيشوف «عبر خط».
    """
    _panels_on(grown)
    _number(grown, "gastroenterology", "wt_drop", 0.67)
    _measure(grown, weight=13.5, days_ago=180)
    _measure(grown, weight=13.7, days_ago=0)

    assert "wt_drop" in _fired(grown, ["gastroenterology"])


def test_a_child_tracking_their_own_line_is_left_alone(grown):
    """وزن بيزيد والطفل ماشي على خطه — ده اللي المفروض يحصل، ومفيش كلام."""
    _panels_on(grown)
    _number(grown, "gastroenterology", "wt_drop", 0.67)
    _measure(grown, weight=11.5, days_ago=180)
    _measure(grown, weight=12.8, days_ago=0)

    assert "wt_drop" not in _fired(grown, ["gastroenterology"])


def test_one_measurement_is_not_a_curve(grown):
    _panels_on(grown)
    _number(grown, "gastroenterology", "wt_drop", 0.67)
    _measure(grown, weight=13.5)

    assert "wt_drop" not in _fired(grown, ["gastroenterology"])


def test_the_head_alert_reads_the_head_not_the_weight(grown):
    """محيط الرأس بيزيد بسرعة غير طبيعية — مؤشر تاني خالص، وتنبيه بيقرا
    الوزن بدله كان هيسكت على الحاجة اللي اسمه عليها."""
    _panels_on(grown)
    _number(grown, "neonatology", "hc_fast", 0.67)
    _measure(grown, weight=12.0, head=46.0, days_ago=180)
    _measure(grown, weight=12.1, head=51.0, days_ago=0)

    assert "hc_fast" in _fired(grown, ["neonatology"])


def test_another_childs_curve_is_not_this_ones(grown):
    _panels_on(grown)
    _number(grown, "gastroenterology", "wt_drop", 0.67)
    _measure(grown, weight=13.5, days_ago=180,
             patient_id=grown["ids"]["other_child"])
    _measure(grown, weight=13.7, days_ago=0,
             patient_id=grown["ids"]["other_child"])

    assert "wt_drop" not in _fired(grown, ["gastroenterology"])
    assert "wt_drop" in _fired(grown, ["gastroenterology"],
                               patient_id=grown["ids"]["other_child"])


def test_a_growth_alert_needs_the_clinics_number_like_the_rest(grown):
    _panels_on(grown)
    _measure(grown, weight=13.5, days_ago=180)
    _measure(grown, weight=13.7, days_ago=0)

    assert "wt_drop" not in _fired(grown, ["gastroenterology"])


def test_a_record_with_no_reading_for_that_indicator_is_skipped(grown):
    """زيارة اتوزن فيها بس، وزيارة اتقاس فيها الرأس كمان. مقارنة الرأس
    بتاخد آخر مرتين **الرأس اتقاس فيهم**، مش آخر زيارتين."""
    _panels_on(grown)
    _number(grown, "neonatology", "hc_fast", 0.67)
    _measure(grown, head=46.0, days_ago=180)
    _measure(grown, weight=12.0, days_ago=90)          # مفيهاش رأس
    _measure(grown, head=51.0, days_ago=0)

    assert "hc_fast" in _fired(grown, ["neonatology"])


def test_a_third_measurement_does_not_break_the_comparison(grown):
    """طفرة عاشت وطلّعت باج حقيقي.

    القارئ كان بيوقف عند اتنين، والمقارنة كانت **بتفكّ** الاتنين
    (`(a, b) = pair`) بدل ما تاخدهم بالترتيب. فطفل عنده تلات قياسات —
    وده الحالة العادية مش الشاذة — كان هيقع بـ`ValueError` **على ملفه
    هو**. مفيش اختبار كان عنده قراية تالتة، فمحدّش كان يقدر يشوفها.
    """
    _panels_on(grown)
    _number(grown, "gastroenterology", "wt_drop", 0.67)
    _measure(grown, weight=10.0, days_ago=540)
    _measure(grown, weight=12.0, days_ago=360)
    _measure(grown, weight=13.5, days_ago=180)
    _measure(grown, weight=13.7, days_ago=0)

    assert "wt_drop" in _fired(grown, ["gastroenterology"])


def test_the_worst_wins_when_two_readings_are_both_outside(grown):
    """قراءتين الاتنين بره النطاق، والشريط بياخد الأبعد — مش الأولانية.

    الترتيب هنا مقصود: الوزن بيتحسب قبل الطول في `INDICATORS`، فلو
    الشريط بياخد أول واحدة كان هياخد الأقل سوءاً ويسيب الأخطر.
    """
    from app.models import Patient
    from app.utils.growth import concern

    _measure(grown, weight=8.5, height=70.0)

    with grown["app"].app_context():
        child = grown["db"].session.get(Patient, grown["ids"]["child"])
        picture = child.growth_picture
        outside = [r for r in picture["rows"]
                   if r["status"] in ("caution", "alert")]
        flagged = concern(picture["rows"], picture["record"])

    assert len(outside) >= 2, f"الاختبار محتاج قراءتين بره النطاق: {outside}"
    assert abs(flagged["z"]) == max(abs(r["z"]) for r in outside)
    assert flagged["indicator"] != outside[0]["indicator"]


def test_the_file_itself_carries_the_banner(grown):
    """الشريط اللي فوق الملف، مش الدالة لوحدها.

    الاختبارات كانت بتنادي `growth.concern` على طول، فالسلك اللي بين
    الصفحة وبينها مكانش متغطّي: تفريغه كان بيخلّي كل حاجة خضرا وشريط
    الملف يختفي.
    """
    _measure(grown, weight=6.0, height=70.0)

    page = _file(grown)

    assert "ab-growth" in page


def test_a_child_in_the_middle_gets_no_banner_on_the_file(grown):
    _measure(grown, weight=12.5, height=87.0)

    assert "ab-growth" not in _file(grown)


def test_every_growth_alert_names_an_indicator_the_engine_knows(grown):
    """كود مؤشر غلط بيدّي تنبيه ساكت للأبد — نفس الفخ بتاع كود التحليل."""
    from app.utils import panel_alerts, panels
    from app.utils.growth import INDICATORS

    checked = 0
    for key in panels.all_panels():
        for alert in panel_alerts.declared(key):
            watches = alert.get("watches") or {}
            if watches.get("source") != "growth":
                continue
            assert watches["of"] in INDICATORS, f"{key}.{alert['code']}"
            assert watches["when"] in panel_alerts.TREND_SHAPES, \
                f"{key}.{alert['code']}"
            checked += 1
    assert checked, "مفيش ولا تنبيه نمو اتفحص — الاختبار ده بيعدّي فاضي"
