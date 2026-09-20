"""تنبيه بيصرخ على كل طفل مش تنبيه — والسن مش حدث.

تلات تنبيهات لافتتهم بتقول «لم يُفحص» وكانوا متوصّلين بـ`age_months` لوحده.
و`age_months` بيعرف يقول إن الطفل عدّى السن اللي العيادة كتبته — **وما
بيعرفش يقول إن الفحص ما اتعملش**. فعيادة كتبت «٣٦ شهر» كانت بتشوف التنبيه
على كل طفل عدّى تلات سنين، بما فيهم طفل اتفحص الصبح.

وتنبيه على الكل أسوأ من مفيش تنبيه: اللي يهمّ بيوصل في نفس الصف الرمادي مع
التسعين اللي ما يهمّوش، والنتيجة إن الاتنين بيتجاهلوا.

**والسبب التاني كان أعمق.** كل أسئلة «اتعمل ولا لأ» في اللوحات دي **اختيارات**
وكل واحد فيهم أول اختيار فيه «لم يُعمل» — يعني إجابتهم بتروح `value_text`،
والقارئ كان بيفلتر على `value_num` بس. طفل اتفحص الصبح كان بيرجع `None`،
واللي معناها للتنبيه «عمره ما اتفحص».

فالسؤال مالوش جوابين، له **تلاتة**، وده اللي بيتختبر هنا:

1. **محدّش كتب حاجة** — التنبيه بيشتغل.
2. **مكتوب «لم يُعمل»** — التنبيه بيفضل شغّال، لأن ورقة مكتوب فيها إن الفحص
   ما اتعملش مش فحص.
3. **اتعمل فعلاً** — التنبيه بيسكت.
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def specialty(clinic):
    """عيادة اللوحات شغّالة فيها، وطفل عنده ست سنين."""
    from app.models import Patient, Setting
    from app.utils.clock import local_today
    from app.utils.investigations import seed_investigations

    with clinic["app"].app_context():
        Setting.set("mod_enabled:panels", "1")
        child = clinic["db"].session.get(Patient, clinic["ids"]["child"])
        child.date_of_birth = local_today() - timedelta(days=365 * 6)
        other = Patient(patient_number="AL-2", full_name="طفل تاني",
                        gender="female", is_active=True,
                        date_of_birth=local_today() - timedelta(days=365 * 6))
        clinic["db"].session.add(other)
        clinic["db"].session.commit()
        clinic["ids"]["other_child"] = other.id
        seed_investigations()
    return clinic


def _number(specialty, panel, code, value):
    return specialty["sign_in"]("boss").post("/panels/alerts/set", data={
        "panel_key": panel, "alert_code": code, "threshold": str(value),
        "is_active": "1"}, follow_redirects=True)


def _reading(specialty, code, text=None, num=None, patient_id=None,
             days_ago=0):
    from app.models import Measurement

    with specialty["app"].app_context():
        specialty["db"].session.add(Measurement(
            patient_id=patient_id or specialty["ids"]["child"], code=code,
            value_text=text, value_num=num,
            recorded_at=datetime.utcnow() - timedelta(days=days_ago)))
        specialty["db"].session.commit()


def _fired(specialty, keys, patient_id=None):
    from app.utils import panel_alerts

    with specialty["app"].app_context():
        return {a["code"] for a in panel_alerts.evaluate(
            patient_id or specialty["ids"]["child"], keys)}


# ------------------------------------------------- الحالات التلاتة ----
def test_nothing_on_record_is_what_the_alert_is_for(specialty):
    _number(specialty, "ophthalmology", "never_examined", 48)

    assert "never_examined" in _fired(specialty, ["ophthalmology"])


def test_written_down_as_not_done_is_still_not_done(specialty):
    """«لم يُفحص» مكتوبة إجابة صادقة — وهي مش فحص.

    ودي الحالة اللي بتفرّق بين «فيه صف» و«اتعمل»: لو الشرط كان مجرد وجود
    قراية، طبيب كتب «لم يُفحص» كان هيقفل التنبيه على الطفل اللي هو محتاجه.
    """
    _number(specialty, "ophthalmology", "never_examined", 48)
    _reading(specialty, "fundus", text="لم يُفحص")

    assert "never_examined" in _fired(specialty, ["ophthalmology"])


def test_an_examination_on_record_shuts_it_up(specialty):
    _number(specialty, "ophthalmology", "never_examined", 48)
    _reading(specialty, "fundus", text="طبيعي")

    assert "never_examined" not in _fired(specialty, ["ophthalmology"])


def test_an_abnormal_result_also_counts_as_examined(specialty):
    """التنبيه ده عن **الفحص**، مش عن نتيجته. نتيجة وحشة شغل الطبيب."""
    _number(specialty, "ophthalmology", "never_examined", 48)
    _reading(specialty, "fundus", text="غير طبيعي")

    assert "never_examined" not in _fired(specialty, ["ophthalmology"])


def test_any_one_of_the_listed_readings_is_enough(specialty):
    """«اتفحص نظره» مش خانة واحدة — حدّة إبصار أو قاع عين أو ضغط عين."""
    _number(specialty, "ophthalmology", "never_examined", 48)
    _reading(specialty, "iop", num=14)

    assert "never_examined" not in _fired(specialty, ["ophthalmology"])


def test_some_other_reading_entirely_does_not_count_as_an_eye_exam(specialty):
    """طفرة عاشت: قارئ من غير فلتر كود.

    من غيره أي قراية على الطفل — عدد أيام السخونة، ساعات النضّارة، أي حاجة —
    كانت بتقفل التنبيه، لأن السؤال بقى «فيه أي قراية؟» بدل «الفحص ده اتعمل؟».
    والفرق بينهم إن الأولانية بتبقى صح على كل طفل دخل العيادة مرة.
    """
    _number(specialty, "ophthalmology", "never_examined", 48)
    _reading(specialty, "fever_days", num=9)
    _reading(specialty, "glasses_hours", num=4)

    assert "never_examined" in _fired(specialty, ["ophthalmology"])


def test_another_childs_examination_does_not_shut_this_ones_up(specialty):
    _number(specialty, "ophthalmology", "never_examined", 48)
    _reading(specialty, "fundus", text="طبيعي",
             patient_id=specialty["ids"]["other_child"])

    assert "never_examined" in _fired(specialty, ["ophthalmology"])


def test_under_the_age_it_says_nothing_however_empty_the_record(specialty):
    """الشرط الأصلي لسه قايم: السن لسه ما عدّاش، فمفيش كلام."""
    _number(specialty, "ophthalmology", "never_examined", 240)

    assert "never_examined" not in _fired(specialty, ["ophthalmology"])


# ------------------------------- القارئ اللي مكانش بيشوف الاختيارات ----
def test_the_reader_can_see_a_choice_not_only_a_number(specialty):
    """السبب الجذري: كل أسئلة «اتعمل ولا لأ» اختيارات، والقارئ كان رقمي بس."""
    from app.utils import panel_alerts

    _reading(specialty, "rop_screen", text="طبيعي")

    with specialty["app"].app_context():
        value, when = panel_alerts._latest_panel_reading(
            specialty["ids"]["child"], "rop_screen")

    assert value == "طبيعي" and when is not None


def test_the_numeric_reader_stays_numeric(specialty):
    """و`_latest_panel` فضل رقمي عن قصد: بيغذّي `above`/`below`، ومقارنة
    رقم بكلمة «طبيعي» مش مقارنة — دي بتقع، مش بتدّي جواب غلط."""
    from app.utils import panel_alerts

    _reading(specialty, "iop", text="مرتفع")

    with specialty["app"].app_context():
        assert panel_alerts._latest_panel(
            specialty["ids"]["child"], "iop") == (None, None)


# --------------------------------------- الخمسة اللي اتوصّلوا لأول مرة ----
@pytest.mark.parametrize("panel,code,field", [
    ("neonatology", "rop_due", "rop_screen"),
    ("neonatology", "no_hearing", "hearing_screen"),
    ("ophthalmology", "preterm_rop_due", "rop_screen"),
    ("orthopaedics", "hip_not_screened", "hip_exam"),
])
def test_a_screening_alert_fires_then_clears(specialty, panel, code, field):
    _number(specialty, panel, code, 3)

    assert code in _fired(specialty, [panel])

    _reading(specialty, field, text="طبيعي")

    assert code not in _fired(specialty, [panel])


def test_the_eye_review_counts_the_months_since_the_last_one(specialty):
    """الروماتيزم بيسأل «فحص العين فات ميعاده» — ودي `since` على قراية
    اختيار، اللي القارئ الرقمي مكانش بيشوفها أصلاً."""
    _number(specialty, "rheumatology", "uveitis_overdue", 6)
    _reading(specialty, "uveitis_screen", text="سليم", days_ago=400)

    assert "uveitis_overdue" in _fired(specialty, ["rheumatology"])


def test_a_recent_eye_review_is_not_overdue(specialty):
    _number(specialty, "rheumatology", "uveitis_overdue", 6)
    _reading(specialty, "uveitis_screen", text="سليم", days_ago=10)

    assert "uveitis_overdue" not in _fired(specialty, ["rheumatology"])


# ------------------------------------------------- قواعد الكتالوج ----
def test_every_unless_names_a_source_the_reader_knows(specialty):
    from app.utils import panel_alerts, panels

    for key in panels.all_panels():
        for alert in panel_alerts.declared(key):
            unless = alert.get("unless")
            if not unless:
                continue
            assert unless["source"] in {"panel", "lab"}, alert["code"]
            assert unless.get("of"), alert["code"]


def test_every_unless_reading_is_a_field_some_panel_actually_takes(specialty):
    """نفس قاعدة `watches`، بفرق واحد مقصود: **`unless` مسموح له يعدّي
    اللوحة**.

    فحص الشبكية بيتسجّل في لوحة حديثي الولادة، واللي بيسأل عنه كمان هو طبيب
    العيون. القراية واحدة في `Measurement` بكودها، والتنبيه في لوحة تانية
    بيقراها — وده صح، بس لازم يكون مكتوب مش مستنتج من إن محدّش فحص.
    """
    from app.utils import panel_alerts, panels

    every = {f["code"] for key in panels.all_panels()
             for f in (panels.panel(key).get("fields") or [])}
    for key in panels.all_panels():
        for alert in panel_alerts.declared(key):
            unless = alert.get("unless")
            if not unless or unless["source"] != "panel":
                continue
            for code in unless["of"].split(","):
                assert code.strip() in every, f"{key}.{alert['code']}:{code}"


def test_every_means_no_is_a_real_option_of_that_field(specialty):
    """**أخطر غلطة ممكنة هنا حرف.**

    لو `means_no` مكتوبة غلط، «لم يُعمل» مش هتتعرّف — فالتنبيه هيسكت على
    الطفل اللي اتكتب عنه صراحةً إن الفحص ما اتعملش. يعني غلطة إملائية
    بتقلب التنبيه لعكسه، من غير ما أي حاجة تقع.
    """
    from app.utils import panel_alerts, panels

    options = {}
    for key in panels.all_panels():
        for f in (panels.panel(key).get("fields") or []):
            if f.get("options"):
                options.setdefault(f["code"], set()).update(f["options"])
    checked = 0
    for key in panels.all_panels():
        for alert in panel_alerts.declared(key):
            unless = alert.get("unless") or {}
            if unless.get("source") != "panel":
                continue
            words = list(unless.get("means_no") or ())
            codes = [c.strip() for c in unless["of"].split(",") if c.strip()]
            with_options = [c for c in codes if c in options]

            # نصّ القاعدة الأولى: كل كلمة لازم تكون اختيار حقيقي في واحدة من
            # الخانات المذكورة. اتحاد مش تقاطع، لأن ده بالظبط اللي الكود
            # بيعمله — بيقارن القيمة بالقايمة كلها من غير ما يسأل جت منين —
            # وكمان لأن الخانات بتقول نفس المعنى بألفاظ مختلفة: «لم تُقَس»
            # لحدّة الإبصار و«لم يُفحص» لقاع العين.
            for word in words:
                assert any(word in options[c] for c in with_options), \
                    f"{alert['code']}: «{word}» مش اختيار في ولا خانة"
                checked += 1

            # والقاعدة التانية هي اللي بتمسك النسيان: خانة ليها اختيار معناه
            # «ما اتعملش» ومحدّش غطّاه هي خانة هتقفل التنبيه على طفل مكتوب
            # عنه صراحةً إنه ما اتفحصش.
            for code in with_options:
                assert any(word in options[code] for word in words), \
                    f"{alert['code']}: خانة {code} مالهاش «ما اتعملش» مغطّاة"
    assert checked, "مفيش ولا `means_no` اتفحصت — الاختبار ده بيعدّي فاضي"


def test_the_catalogue_still_holds_no_clinical_number(specialty):
    """القاعدة اللي البرنامج كله قايم عليها: الكتالوج بيقول **يبصّ على إيه**،
    والعيادة بتقول **إمتى تقلق**."""
    import json

    with open("app/data/specialty_panels.json", encoding="utf-8") as fh:
        raw = json.load(fh)
    for panel in raw["panels"].values():
        for alert in panel.get("alerts", []):
            for block in (alert.get("watches"), alert.get("unless")):
                if not block:
                    continue
                for value in block.values():
                    assert not isinstance(value, (int, float)), alert["code"]
