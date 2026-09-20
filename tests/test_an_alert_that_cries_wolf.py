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


# ------------------------------- تاريخ متكتوب: القيمة مش ساعة الكتابة ----
def _date_reading(specialty, code, when, patient_id=None):
    """خانة تاريخ، زي ما `<input type="date">` بيبعتها: نص ISO."""
    _reading(specialty, code, text=when.isoformat(), patient_id=patient_id)


def test_a_date_that_has_gone_by_needs_no_number_from_anybody(specialty):
    """**الشكل الوحيد اللي بيشتغل يوم التركيب.**

    مفيش حاجة تتخترع: التاريخ متكتوب، وعدّى. ودي بالحرف اللي الكتالوج
    بيسمّيها `overdue` — *"a date the program already holds"*.
    """
    from app.utils.clock import local_today

    _date_reading(specialty, "planned_surgery", local_today() - timedelta(days=9))

    assert "surgery_overdue" in _fired(specialty, ["surgery"])


def test_a_date_still_ahead_says_nothing(specialty):
    from app.utils.clock import local_today

    _date_reading(specialty, "planned_surgery", local_today() + timedelta(days=9))

    assert "surgery_overdue" not in _fired(specialty, ["surgery"])


def test_today_itself_is_not_late(specialty):
    """الميعاد النهارده هو ميعاد النهارده. ودي المقارنة اللي حطّت تلات
    ساعات من ورديّة كل ليلة على اليوم الغلط لما اتعملت بإهمال — فبتتقاس
    بساعة العيادة، مش ساعة السيرفر."""
    from app.utils.clock import local_today

    _date_reading(specialty, "ga_planned_date", local_today())

    assert "ga_overdue" not in _fired(specialty, ["dentistry"])


def test_it_is_the_clinics_today_that_decides_not_the_servers(specialty):
    """طفرة عاشت: `date.today()` مكان `local_today()`.

    والاختبار اللي فوق مكانش يقدر يمسكها، لأنه بيحسب الميعاد بنفس الساعة
    اللي الكود بيقراها — فالغلط بينزاح على الاتنين مع بعض ويفضل أخضر.

    فالساعتين بيتبعدوا عن بعض هنا بالقوة: عيادة يومها قدّام السيرفر بخمس
    تيام، وميعاد بعد بكرة **بتوقيت السيرفر**. بتوقيت العيادة ده ميعاد
    عدّى. ودي مش حالة نظرية: نفس المقارنة اتعملت بإهمال قبل كده وحطّت
    تلات ساعات من ورديّة كل ليلة على اليوم الغلط.
    """
    from datetime import date

    import app.utils.clock as clock

    ahead = date.today() + timedelta(days=5)
    was = clock.local_today
    clock.local_today = lambda: ahead
    try:
        _date_reading(specialty, "planned_surgery",
                      date.today() + timedelta(days=2))
        assert "surgery_overdue" in _fired(specialty, ["surgery"])
    finally:
        clock.local_today = was


def test_and_a_clinic_behind_the_server_is_not_late_yet(specialty):
    """الاتجاه التاني، علشان الحارس ما يبقاش نص قاعدة: عيادة يومها ورا
    السيرفر بخمس تيام، وميعاد إمبارح بتوقيت السيرفر لسه ما جاش عندها."""
    from datetime import date

    import app.utils.clock as clock

    behind = date.today() - timedelta(days=5)
    was = clock.local_today
    clock.local_today = lambda: behind
    try:
        _date_reading(specialty, "planned_surgery",
                      date.today() - timedelta(days=1))
        assert "surgery_overdue" not in _fired(specialty, ["surgery"])
    finally:
        clock.local_today = was


def test_no_date_written_is_not_overdue(specialty):
    assert "surgery_overdue" not in _fired(specialty, ["surgery"])


def test_a_date_shaped_alert_is_offered_no_number_box(specialty):
    """خانة رقم لتنبيه بيتجاهل الرقم هي نفس الوعد المكسور من الناحية
    التانية: بتتملّى وما بتغيّرش حاجة."""
    from app.utils import panel_alerts

    offered = {a["code"] for a in panel_alerts.watchable("surgery")}

    assert "surgery_overdue" not in offered
    assert "testis_age" in offered          # ده فعلاً محتاج رقم


def test_a_date_shaped_alert_is_not_counted_as_waiting(specialty):
    """«مستني إيه» هو عدد الحاجات اللي حد لسه يقدر يعملها.

    وتنبيه بيجاوب نفسه مش واحد منهم — عدّه كان هيخلّي الرقم ده رقم
    ما بينزلش مهما الواحد شتغل، وهي نفس شكوى «باب مالوش نهاية».
    """
    from app.utils import panel_alerts

    with specialty["app"].app_context():
        counted = sum(panel_alerts.waiting(["surgery"]).values())
        answers_itself = [a for a in panel_alerts.declared("surgery")
                          if a.get("watches")
                          and not panel_alerts.needs_a_number(a)]
        still_open = [a for a in panel_alerts.declared("surgery")
                      if not a.get("live") and panel_alerts.needs_a_number(a)
                      or not a.get("live") and not a.get("watches")]

    assert answers_itself, "مفيش تنبيه بيجاوب نفسه في الجراحة — الاختبار فاضي"
    assert counted == len(still_open)


def test_something_that_is_not_a_date_is_not_read_as_one(specialty):
    """متصفّح من غير منتقي تواريخ، أو صف قديم، أو غلطة كتابة. قارئ بيخمّن
    كان هيحطّ تنبيهات عيادة على يوم متأليف."""
    from app.utils import panel_alerts

    _reading(specialty, "planned_surgery", text="الأسبوع الجاي")

    with specialty["app"].app_context():
        assert panel_alerts._panel_date(
            specialty["ids"]["child"], "planned_surgery") is None
    assert "surgery_overdue" not in _fired(specialty, ["surgery"])


# ------------------------------------ والفرق بين التاريخين هو كل الحكاية ----
def test_the_date_written_in_the_box_wins_over_when_it_was_typed(specialty):
    """ممرضة بتدخّل تاريخ الشهر اللي فات النهارده.

    `since` كانت هتقيس من ساعة الكتابة — يعني «حقنة الصبح». والخانة اسمها
    «تاريخ آخر حقنة»، وجوابها هو التاريخ اللي فيها.
    """
    from app.utils.clock import local_today

    _number(specialty, "cardiology", "penicillin_late", 1)
    # القراية اتكتبت دلوقتي، والتاريخ اللي فيها من تلات شهور
    _date_reading(specialty, "last_penicillin",
                  local_today() - timedelta(days=95))

    assert "penicillin_late" in _fired(specialty, ["cardiology"])


def test_a_recent_dose_is_not_late(specialty):
    from app.utils.clock import local_today

    _number(specialty, "cardiology", "penicillin_late", 1)
    _date_reading(specialty, "last_penicillin",
                  local_today() - timedelta(days=10))

    assert "penicillin_late" not in _fired(specialty, ["cardiology"])


def test_no_dose_ever_recorded_is_not_called_late(specialty):
    """**الفرق عن `since`، وهو مقصود.**

    `since` بتعتبر «عمره ما اتعمل» أقوى حالة من المتأخر — وده صح لتحليل
    متابعة. وخانة «تاريخ آخر جرعة» فاضية حاجة تانية: طفل عمره ما خد
    الجرعة **مش متأخر عن الجرعة الجاية**. دي فجوة تسجيل، و«متأخر» عليها
    بتبعت حد يدّي جرعة.
    """
    _number(specialty, "oncology", "chemo_late", 1)

    assert "chemo_late" not in _fired(specialty, ["oncology"])


def test_the_interval_is_the_clinics_and_nothing_fires_without_it(specialty):
    from app.utils.clock import local_today

    _date_reading(specialty, "ivig_last", local_today() - timedelta(days=200))

    assert "ivig_overdue" not in _fired(specialty, ["immunology"])

    _number(specialty, "immunology", "ivig_overdue", 2)

    assert "ivig_overdue" in _fired(specialty, ["immunology"])


def test_another_childs_date_is_not_this_childs(specialty):
    from app.utils.clock import local_today

    _date_reading(specialty, "planned_surgery",
                  local_today() - timedelta(days=9),
                  patient_id=specialty["ids"]["other_child"])

    assert "surgery_overdue" not in _fired(specialty, ["surgery"])
    assert "surgery_overdue" in _fired(
        specialty, ["surgery"], patient_id=specialty["ids"]["other_child"])


# ---------------------- تاريخ عدّى مش حدث — نفس الغلطة من ناحية تانية ----
def test_a_session_that_happened_is_not_overdue(specialty):
    """**الباج ده كان في شغل الشغلانة دي نفسها.**

    وصّلت «ميعاد الجلسة» بـ`past` من غير ما أسأل: طيب والجلسة حصلت؟
    فجلسة اتعملت من شهر ومتابعتها خلصت فضلت بتقول «فات ميعادها» — نفس
    الغلطة اللي الملف ده اتكتب علشانها، من ناحية تانية.
    """
    from app.utils.clock import local_today

    _date_reading(specialty, "ga_planned_date",
                  local_today() - timedelta(days=30))
    _reading(specialty, "surgical_procedure", text="خلع")
    _reading(specialty, "post_op_check", text="تمام")

    assert "ga_overdue" not in _fired(specialty, ["dentistry"])


def test_an_operation_that_happened_is_not_overdue(specialty):
    from app.utils.clock import local_today

    _date_reading(specialty, "planned_surgery",
                  local_today() - timedelta(days=30))
    _reading(specialty, "wound_status", text="ملتئم")

    assert "surgery_overdue" not in _fired(specialty, ["surgery"])


def test_the_three_states_of_a_session_do_not_overlap(specialty):
    """«ما حصلتش» و«حصلت ومفيش متابعة» و«تمام» تلات إجابات مختلفة، وتنبيه
    واحد لكل واحدة — واتنين بيشتغلوا مع بعض معناه إن الشاشة مش عارفة
    الفرق."""
    from app.utils.clock import local_today

    _date_reading(specialty, "ga_planned_date",
                  local_today() - timedelta(days=30))

    assert _fired(specialty, ["dentistry"]) & {
        "ga_overdue", "post_op_missing"} == {"ga_overdue"}

    _reading(specialty, "surgical_procedure", text="خلع")

    assert _fired(specialty, ["dentistry"]) & {
        "ga_overdue", "post_op_missing"} == {"post_op_missing"}

    _reading(specialty, "post_op_check", text="تمام")

    assert _fired(specialty, ["dentistry"]) & {
        "ga_overdue", "post_op_missing"} == set()


def test_given_is_what_stops_the_follow_up_alert_firing_on_nothing(specialty):
    """`given` هو النص التاني: «ما تشتغلش غير لو ده حصل».

    من غيره «مفيش متابعة بعد الجلسة» كان هيشتغل على طفل الجلسة بتاعته
    ما اتعملتش أصلاً — ويبعت حد يدوّر على متابعة لحاجة محصلتش.
    """
    from app.utils.clock import local_today

    _date_reading(specialty, "ga_planned_date",
                  local_today() - timedelta(days=30))

    assert "post_op_missing" not in _fired(specialty, ["dentistry"])


def test_a_recorded_none_is_not_a_procedure(specialty):
    """«لا يوجد» إجابة صادقة معناها مفيش إجراء — مش إجراء اسمه «لا يوجد»."""
    from app.utils.clock import local_today

    _date_reading(specialty, "ga_planned_date",
                  local_today() - timedelta(days=30))
    _reading(specialty, "surgical_procedure", text="لا يوجد")

    fired = _fired(specialty, ["dentistry"])

    assert "post_op_missing" not in fired
    assert "ga_overdue" in fired


# ------------------------------------------ وشبّاك قدّام، عكس اللي عدّى ----
def test_a_session_coming_up_with_fasting_unconfirmed_says_so(specialty):
    from app.utils.clock import local_today

    _number(specialty, "dentistry", "ga_fasting_unconfirmed", 7)
    _date_reading(specialty, "ga_planned_date", local_today() + timedelta(days=3))

    assert "ga_fasting_unconfirmed" in _fired(specialty, ["dentistry"])


def test_confirming_the_fasting_clears_it(specialty):
    from app.utils.clock import local_today

    _number(specialty, "dentistry", "ga_fasting_unconfirmed", 7)
    _date_reading(specialty, "ga_planned_date", local_today() + timedelta(days=3))
    _reading(specialty, "fasting_confirmed", text="نعم")

    assert "ga_fasting_unconfirmed" not in _fired(specialty, ["dentistry"])


def test_saying_no_to_the_fasting_is_not_confirming_it(specialty):
    """«لأ» و«لا ينطبق» مش «نعم». واحدة بس بتقفل التنبيه ده."""
    from app.utils.clock import local_today

    _number(specialty, "dentistry", "ga_fasting_unconfirmed", 7)
    _date_reading(specialty, "ga_planned_date", local_today() + timedelta(days=3))
    _reading(specialty, "fasting_confirmed", text="لأ")

    assert "ga_fasting_unconfirmed" in _fired(specialty, ["dentistry"])


def test_a_session_already_gone_by_is_not_coming_up(specialty):
    """طفرة عاشت: شبّاك من غير حدّ سُفلي.

    «الصيام مااتأكدش» سؤال عن جلسة **جاية** — بتتعمل حاجة قبلها. جلسة
    عدّت خلاص ليها تنبيهاتها هي (فات ميعادها · مفيش متابعة)، وسؤال
    الصيام عليها بيبعت حد يحضّر لحاجة راحت.
    """
    from app.utils.clock import local_today

    _number(specialty, "dentistry", "ga_fasting_unconfirmed", 7)
    _date_reading(specialty, "ga_planned_date", local_today() - timedelta(days=3))

    assert "ga_fasting_unconfirmed" not in _fired(specialty, ["dentistry"])


def test_a_session_beyond_the_window_is_not_near(specialty):
    from app.utils.clock import local_today

    _number(specialty, "dentistry", "ga_fasting_unconfirmed", 7)
    _date_reading(specialty, "ga_planned_date", local_today() + timedelta(days=30))

    assert "ga_fasting_unconfirmed" not in _fired(specialty, ["dentistry"])


def test_a_window_alert_does_need_a_number(specialty):
    """عكس `past`: «قربت» شبّاك، وكام يوم يعتبر قريب جواب العيادة مش جوابنا."""
    from app.utils import panel_alerts
    from app.utils.clock import local_today

    _date_reading(specialty, "ga_planned_date", local_today() + timedelta(days=3))

    assert "ga_fasting_unconfirmed" not in _fired(specialty, ["dentistry"])
    assert "ga_fasting_unconfirmed" in {
        a["code"] for a in panel_alerts.watchable("dentistry")}


def test_every_date_shape_actually_reads_the_date(specialty):
    """غلطة اتمسكت بالتشغيل وأنا بكتب: `within` اتضاف لقايمة المقارنات
    ومااتضافش لقايمة الأشكال اللي بتقرا **قيمة** التاريخ، فكان بيقرا
    العمود الرقمي ويرجع فاضي دايماً."""
    from app.utils import panel_alerts, panels

    for key in panels.all_panels():
        for alert in panel_alerts.declared(key):
            watches = alert.get("watches") or {}
            if watches.get("source") != "panel":
                continue
            field = next((f for f in panels.panel(key).get("fields") or []
                          if f["code"] == watches.get("of")), None)
            if field is None or field.get("type") != "date":
                continue
            assert watches["when"] in panel_alerts.DATE_SHAPES, \
                f"{key}.{alert['code']} بيقرا خانة تاريخ بشكل مش بيقرا التاريخ"


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


def test_every_overdue_alert_is_answered_or_says_why_not(specialty):
    """**تنبيه محدّش قرّر فيه حاجة.**

    `overdue` هو الصنف اللي الكتالوج بيقول عنه إنه *"a date the program
    already holds; nothing has to be invented"* — فواحد منهم مش مجاوب هو
    إمّا شغل لسه ما اتعملش أو حاجة مستحيلة، **والفرق بينهم لازم يكون
    مكتوب**. من غير السطر ده الاتنين بيبانوا نفس الشكل: فاضي.

    ودي القاعدة اللي منعت الشغلانة دي تقول «مش قابل للإجابة» على تلات
    تنبيهات طلعت مجاوبة — البنسلين والكيماوي والغلوبولين — لأن اللوحات
    فيها خانات تاريخ محدّش كان بصّ عليها.
    """
    from app.utils import panel_alerts, panels

    undecided = []
    for key in panels.all_panels():
        for alert in panel_alerts.declared(key):
            if alert.get("needs") != "overdue":
                continue
            if alert.get("watches") or alert.get("live"):
                continue
            if not (alert.get("blocked_by_ar") or "").strip():
                undecided.append(f"{key}.{alert['code']}")
    assert not undecided, (
        "تنبيهات «متأخر» مش مجاوبة ومحدّش كاتب ليه: " + ", ".join(undecided))


def test_a_blocked_alert_is_never_also_a_wired_one(specialty):
    """السطر بيقول «ما نقدرش»، والتوصيلة بتقول «نقدر». وجودهم مع بعض معناه
    إن واحد فيهم اتنسي وهو بيتحدّث — وده بيخلّي الشاشة تكدب في اتجاه."""
    from app.utils import panel_alerts, panels

    for key in panels.all_panels():
        for alert in panel_alerts.declared(key):
            if alert.get("blocked_by_ar"):
                assert not alert.get("watches"), f"{key}.{alert['code']}"
                assert not alert.get("live"), f"{key}.{alert['code']}"


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
