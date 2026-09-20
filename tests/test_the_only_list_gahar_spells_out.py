"""قايمة `ICD.03(e)` التمانية — وليه الحضور نفسه كان مش متسجّل.

ده المكان الوحيد في الكتاب كله اللي بيعدّد محتويات ملف بالنص (سطر ٤٦٧٧)،
والمراجِع بيفتح الملف والقايمة في إيده يدوس عليها بند بند.

**وأربعة من التمانية كانوا ❌، والسبب مكانش عمود ناقص هنا وعمود هناك.**
`beds.admit` بيرفض من غير سرير بالنص، فالطفل اللي بيدخل الطوارئ ويتفرز
ويتعالج ويمشي من غير سرير مكانش ليه سجل خالص — لا وصول ولا مغادرة ولا مآل.
ودي أغلب حالات الطوارئ. فالحضور بقى حاجة قايمة بذاتها.

واللي بيتختبر هنا بالترتيب اللي بيهمّ:

1. **حضور من غير سرير** — السطر اللي الشغلانة دي كلها عليه.
2. **الستّة اللي بيتقروا من اللي موجود** وما بيتنسخوش.
3. **الفرز بيتخزّن بلحظته** — لأن المراجِع بيسأل «كان مستواه إيه ساعتها»،
   والحساب الحيّ بيرد بنطاقات النهارده على أرقام إمبارح.
4. **مفتوح مش ناقص** — الطفل لسه جوّه، والبنود دي بتتكتب وهو ماشي.
"""
import os
import sys
from datetime import timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def er(clinic):
    """عيادة الطوارئ شغّالة فيها، وطفل تاني علشان فلتر ناقص ما يعديش."""
    from app.models import Patient, Setting
    from app.utils.clock import local_today

    with clinic["app"].app_context():
        Setting.set("mod_enabled:emergency", "1")
        other = Patient(patient_number="ER-2", full_name="طفل تاني",
                        gender="female", is_active=True,
                        date_of_birth=local_today() - timedelta(days=500))
        clinic["db"].session.add(other)
        clinic["db"].session.commit()
        clinic["ids"]["other_child"] = other.id
    return clinic


def _arrive(er, patient_id=None, arrival="walk_in"):
    from app.models import Patient
    from app.utils import emergency as util

    with er["app"].app_context():
        patient = er["db"].session.get(
            Patient, patient_id or er["ids"]["child"])
        row = util.arrive(patient, arrival=arrival)
        er["db"].session.commit()
        return row.id


def _row(er, visit_id):
    from app.models import EmergencyVisit

    return er["db"].session.get(EmergencyVisit, visit_id)


def _missing(er, visit_id):
    from app.utils import emergency as util

    with er["app"].app_context():
        return util.missing(_row(er, visit_id))


# ------------------------------------------ حضور من غير سرير ----
def test_a_child_can_be_in_the_emergency_without_a_bed(er):
    """**السطر اللي الشغلانة دي كلها عليه.**

    `beds.admit` بيرفض من غير سرير، فالطفل اللي بيتعالج ويمشي كان بيختفي
    من السجل خالص — لا وقت وصول، ولا مغادرة، ولا مآل.
    """
    from app.models import Admission, EmergencyVisit

    visit_id = _arrive(er)

    with er["app"].app_context():
        row = er["db"].session.get(EmergencyVisit, visit_id)
        assert row.arrived_at is not None
        assert row.admission_id is None
        assert Admission.query.count() == 0


def test_the_arrival_time_is_recorded_without_anybody_typing_it(er):
    visit_id = _arrive(er)

    with er["app"].app_context():
        assert _row(er, visit_id).arrived_at is not None


def test_how_the_child_came_is_part_of_the_record(er):
    visit_id = _arrive(er, arrival="ambulance")

    with er["app"].app_context():
        assert _row(er, visit_id).arrival == "ambulance"


def test_an_arrival_the_screen_cannot_draw_is_refused(er):
    from app.models import Patient
    from app.utils import emergency as util

    with er["app"].app_context():
        patient = er["db"].session.get(Patient, er["ids"]["child"])
        with pytest.raises(ValueError):
            util.arrive(patient, arrival="teleported")


# ------------------------------------------------- الفرز ----
def test_triage_without_a_level_is_not_triage(er):
    """صف بيقول «اتفرز» ومفيهوش «طلع إيه» بيخلّي الملف يدّعي إن البند
    اتعمل وهو ما اتعملش."""
    from app.utils import emergency as util

    visit_id = _arrive(er)

    with er["app"].app_context():
        with pytest.raises(ValueError):
            util.triage(_row(er, visit_id), level="   ")


def test_the_level_is_kept_in_the_hospitals_own_words(er):
    """البرنامج ما بيخترعش مقياس فرز: «متوسط» فوق الخط في مقياس وتحته في
    مقياس تاني."""
    from app.utils import emergency as util

    visit_id = _arrive(er)
    with er["app"].app_context():
        util.triage(_row(er, visit_id), level="أصفر", scale="CTAS")
        er["db"].session.commit()
        row = _row(er, visit_id)

    assert (row.level, row.scale) == ("أصفر", "CTAS")


def test_urgent_has_three_answers_not_two(er):
    """«محدّش قال» مش «مش عاجل»."""
    from app.utils import emergency as util

    visit_id = _arrive(er)
    with er["app"].app_context():
        row = _row(er, visit_id)
        util.triage(row, level="أخضر")
        er["db"].session.commit()
        assert _row(er, visit_id).urgent is None
        util.triage(_row(er, visit_id), level="أخضر", urgent=False)
        er["db"].session.commit()
        assert _row(er, visit_id).urgent is False


def test_the_level_stays_what_it_was_when_it_was_decided(er):
    """**ليه بيتخزّن والمشروع كله «مشتق أحسن من مخزّن».**

    `red_flags` بيحسب «عاجل» حيّ من العلامات، وده صح لشاشة بتقول «شوف
    مين دلوقتي». والمراجِع بيسأل «كان مستواه إيه **ساعتها**» — ولو العيادة
    عدّلت نطاقاتها، الحساب الحيّ كان هيغيّر كل ملفات الماضي بأثر رجعي.
    """
    from app.models import Setting
    from app.utils import emergency as util

    visit_id = _arrive(er)
    with er["app"].app_context():
        util.triage(_row(er, visit_id), level="أحمر", urgent=True)
        er["db"].session.commit()
        # العيادة بتغيّر نطاقاتها بعدين
        Setting.set("red_flag_bands", "[]")
        er["db"].session.commit()
        row = _row(er, visit_id)

    assert (row.level, row.urgent) == ("أحمر", True)


def test_the_wait_to_triage_is_read_not_typed(er):
    from app.utils import emergency as util

    visit_id = _arrive(er)
    with er["app"].app_context():
        assert _row(er, visit_id).wait_to_triage is None
        util.triage(_row(er, visit_id), level="أخضر")
        er["db"].session.commit()
        assert _row(er, visit_id).wait_to_triage is not None


def test_who_has_not_been_triaged_is_its_own_question(er):
    """الشاشة الحيّة بتقرا الأسرّة، والطفل ده لسه ماخدش واحد."""
    from app.utils import emergency as util

    visit_id = _arrive(er)
    _arrive(er, patient_id=er["ids"]["other_child"])

    with er["app"].app_context():
        util.triage(_row(er, visit_id), level="أخضر")
        er["db"].session.commit()
        waiting = [v.patient_id for v in util.untriaged()]

    assert waiting == [er["ids"]["other_child"]]


# ------------------------------------------ الخروج والقايمة ----
def test_the_eight_items_are_named_when_they_are_missing(er):
    """«الملف ناقص» من غير «ناقص إيه» بتخلّي اللي بيقرا يعيد قراية كل
    حاجة علشان يلاقيه."""
    visit_id = _arrive(er)

    gaps = _missing(er, visit_id)

    assert "triage" in gaps
    assert set(gaps) <= {"triage", "assessment", "care", "diagnosis",
                         "times", "disposition", "condition", "followup"}


def test_a_child_still_here_is_not_an_incomplete_record(er):
    """**مفتوح مش شغل.** المآل وحالة المغادرة بيتكتبوا وهو ماشي — عدّهم
    ناقصين وهو جوّه بيخلّي كل ملف مفتوح أحمر، وبيعلّم اللي بيقرا يتجاهل
    اللون."""
    visit_id = _arrive(er)

    gaps = _missing(er, visit_id)

    assert "disposition" not in gaps
    assert "condition" not in gaps
    assert "followup" not in gaps


def test_leaving_is_what_makes_those_three_count(er):
    from app.utils import emergency as util

    visit_id = _arrive(er)
    with er["app"].app_context():
        util.depart(_row(er, visit_id), "home")
        er["db"].session.commit()

    gaps = _missing(er, visit_id)

    assert "condition" in gaps
    assert "followup" in gaps


def test_a_departure_records_all_four_of_its_items_at_once(er):
    from app.utils import emergency as util

    visit_id = _arrive(er)
    with er["app"].app_context():
        util.depart(_row(er, visit_id), "home", condition="مستقر",
                    followup="يرجع لو السخونة فضلت")
        er["db"].session.commit()
        row = _row(er, visit_id)

    assert row.departed_at is not None
    assert row.disposition == "home"
    assert row.condition == "مستقر"
    assert row.followup_instructions

    gaps = _missing(er, visit_id)
    assert not {"times", "disposition", "condition", "followup"} & set(gaps)


def test_a_disposition_the_record_does_not_know_is_refused(er):
    from app.utils import emergency as util

    visit_id = _arrive(er)
    with er["app"].app_context():
        with pytest.raises(ValueError):
            util.depart(_row(er, visit_id), "wandered_off")


def test_left_without_being_seen_is_a_real_outcome(er):
    """مشي من غير ما حد يشوفه حاجة بتحصل وبتتقاس — وحذفها من القايمة
    بيخلّي الملف يسكت عن أهم حاجة فيه."""
    from app.utils import emergency as util

    visit_id = _arrive(er)
    with er["app"].app_context():
        util.depart(_row(er, visit_id), "left_unseen")
        er["db"].session.commit()
        assert _row(er, visit_id).disposition == "left_unseen"


def test_the_stay_is_read_from_the_two_times(er):
    """قعد قد إيه مشتقّة مش مخزّنة — عمود تالت كان هيقدر يخالف الاتنين."""
    from app.utils import emergency as util

    visit_id = _arrive(er)
    with er["app"].app_context():
        util.depart(_row(er, visit_id), "home")
        er["db"].session.commit()
        row = _row(er, visit_id)

    assert row.minutes >= 0
    assert row.is_open is False


def test_a_triage_time_with_no_level_is_still_a_gap(er):
    """حارس على مستويين، والاتنين بيتختبروا.

    `triage()` بترفض من غير مستوى، و`missing()` بتشوف المستوى مش الوقت.
    طفرة شالت التاني عاشت لأن الأول بيمنع الحالة — **وده مش سبب نشيل
    واحد فيهم**: صف بيوصل للجدول من أي طريق تاني (استيراد، تصليح بإيد،
    كود جديد) بيبقى مكتوب فيه إن الفرز اتعمل وهو ما اتعملش.
    """
    from datetime import datetime

    from app.utils import emergency as util

    visit_id = _arrive(er)
    with er["app"].app_context():
        row = _row(er, visit_id)
        row.triaged_at = datetime.utcnow()
        er["db"].session.commit()

        assert "triage" in util.missing(_row(er, visit_id))


def test_the_one_waiting_longest_is_at_the_top(er):
    """اللي قاعد من ساعتين هو اللي محدّش بصّله — وده السؤال اللي الشاشة
    موجودة علشانه. الأحدث الأول كان بيحطّه في الآخر."""
    from datetime import datetime

    from app.utils import emergency as util

    first = _arrive(er)
    second = _arrive(er, patient_id=er["ids"]["other_child"])
    with er["app"].app_context():
        older = _row(er, first)
        older.arrived_at = datetime.utcnow() - timedelta(hours=3)
        er["db"].session.commit()
        order = [v.id for v in util.open_visits()]

    assert order == [first, second]


def test_a_complete_record_is_not_on_the_short_list(er):
    """القايمة دي شغل حد لازم يرجعله. حضور كامل فيها بيخلّي الرقم رقم
    ما بينزلش مهما الواحد شتغل."""
    from app.models import Diagnosis, Visit
    from app.utils import emergency as util

    visit_id = _arrive(er)
    with er["app"].app_context():
        row = _row(er, visit_id)
        row.visit_id = er["ids"]["visit"]
        visit = er["db"].session.get(Visit, er["ids"]["visit"])
        visit.clinical_exam = "صدر سليم"
        visit.plan = "محلول وريدي"
        er["db"].session.add(Diagnosis(visit_id=visit.id, title="جفاف"))
        util.triage(row, level="أصفر")
        util.depart(row, "home", condition="مستقر", followup="يرجع بكرة")
        er["db"].session.commit()

        assert util.missing(_row(er, visit_id)) == []
        assert util.complete(_row(er, visit_id))
        assert util.incomplete_departed() == []


# ---------------------------- الستّة اللي بيتقروا من اللي موجود ----
def test_the_assessment_is_read_from_the_visit_not_copied(er):
    """نسخة تانية من تقييم هي نسختين بيفرقوا."""
    from app.models import Visit
    from app.utils import emergency as util

    visit_id = _arrive(er)
    with er["app"].app_context():
        row = _row(er, visit_id)
        assert "assessment" in util.missing(row)
        row.visit_id = er["ids"]["visit"]
        visit = er["db"].session.get(Visit, er["ids"]["visit"])
        visit.clinical_exam = "صدر سليم"
        er["db"].session.commit()
        assert "assessment" not in util.missing(_row(er, visit_id))


def test_the_care_is_read_from_the_plan_or_what_was_given(er):
    from app.models import Visit
    from app.utils import emergency as util

    visit_id = _arrive(er)
    with er["app"].app_context():
        row = _row(er, visit_id)
        row.visit_id = er["ids"]["visit"]
        er["db"].session.commit()
        assert "care" in util.missing(_row(er, visit_id))
        visit = er["db"].session.get(Visit, er["ids"]["visit"])
        visit.plan = "محلول وريدي ومراقبة ساعتين"
        er["db"].session.commit()
        assert "care" not in util.missing(_row(er, visit_id))


def test_a_diagnosis_from_another_visit_is_not_this_ones_conclusion(er):
    """التشخيص بتاع لقاء معيّن. تشخيص من زيارة الشهر اللي فات مش خلاصة
    حضور النهارده."""
    from app.models import Diagnosis, Visit
    from app.utils import emergency as util
    from app.utils.clock import local_today

    visit_id = _arrive(er)
    with er["app"].app_context():
        older = Visit(patient_id=er["ids"]["child"],
                      doctor_id=er["ids"]["doctor"],
                      visit_date=local_today() - timedelta(days=30))
        er["db"].session.add(older)
        er["db"].session.flush()
        er["db"].session.add(Diagnosis(visit_id=older.id, title="نزلة برد"))
        row = _row(er, visit_id)
        row.visit_id = er["ids"]["visit"]
        er["db"].session.commit()

        assert "diagnosis" in util.missing(_row(er, visit_id))

        er["db"].session.add(Diagnosis(visit_id=er["ids"]["visit"],
                                       title="التهاب رئوي"))
        er["db"].session.commit()
        assert "diagnosis" not in util.missing(_row(er, visit_id))


def test_another_childs_attendance_is_not_this_ones(er):
    from app.utils import emergency as util

    _arrive(er, patient_id=er["ids"]["other_child"])

    with er["app"].app_context():
        assert util.for_patient(er["ids"]["child"]) == []
        assert len(util.for_patient(er["ids"]["other_child"])) == 1


# ------------------------------------------------------- الشاشة ----
def test_the_register_shows_who_is_in_the_department(er):
    _arrive(er)

    page = er["sign_in"]("doc").get("/emergency/register")

    assert page.status_code == 200
    assert b"data-open-row" in page.data


def test_the_register_lists_the_finished_records_that_are_short(er):
    from app.utils import emergency as util

    visit_id = _arrive(er)
    with er["app"].app_context():
        util.depart(_row(er, visit_id), "home")
        er["db"].session.commit()

    page = er["sign_in"]("doc").get("/emergency/register").get_data(
        as_text=True)

    assert "data-incomplete-row" in page
    assert 'data-missing="condition"' in page


def test_a_child_still_here_is_not_on_the_incomplete_list(er):
    _arrive(er)

    page = er["sign_in"]("doc").get("/emergency/register").get_data(
        as_text=True)

    assert "data-incomplete-row" not in page


def test_the_file_carries_the_tab_only_where_there_was_an_attendance(er):
    doc = er["sign_in"]("doc")
    before = doc.get(f"/patients/{er['ids']['child']}").get_data(as_text=True)

    assert 'data-tab="emergency"' not in before

    _arrive(er)
    after = doc.get(f"/patients/{er['ids']['child']}").get_data(as_text=True)

    assert 'data-tab="emergency"' in after


def test_the_module_off_means_no_register(er):
    from app.models import Setting

    with er["app"].app_context():
        Setting.set("mod_enabled:emergency", "0")
        er["db"].session.commit()

    assert er["sign_in"]("doc").get(
        "/emergency/register").status_code in (302, 403, 404)


def test_every_emergency_word_is_written_in_both_languages(er):
    from app.i18n import _load_translations, _lookup
    from app.models.emergency_visit import ARRIVALS, DISPOSITIONS
    from app.utils.emergency import ITEMS

    tables = _load_translations()
    keys = [f"item_{i}" for i in ITEMS]
    keys += [f"disp_{d}" for d in DISPOSITIONS]
    keys += [f"arr_{a}" for a in ARRIVALS]
    keys += ["register_title", "register_sub", "untriaged", "in_department",
             "incomplete", "needs_a_level", "not_saved", "still_here"]
    for key in keys:
        for lang in ("ar", "en"):
            assert _lookup(tables, lang, f"emergency.{key}"), f"{lang}:{key}"
    for lang in ("ar", "en"):
        assert _lookup(tables, lang, "patients.tab_emergency")
