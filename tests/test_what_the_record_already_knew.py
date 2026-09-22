"""تقييم التمريض — GAHAR `ICD.07`.

المعيار بيسمّي محتوى السجل الأدنى في ستة بنود — **وتلاتة منهم البرنامج
بيعرفهم قبل ما التقييم ده يتعمل**: العلامات والقياسات (أ)، وتقييم السقوط
(ب)، والفرز المطلوب — ألم وفراش وتغذية (ج).

فالسجل ده **قارئ أكتر منه كاتب**، ونفس قسمة `CarePlan` بالحرف: البرنامج
بيجمّع اللي الملف شايله، والممرضة بتكتب اللي مفيش حاجة تانية بتعرفه —
(د) الفحص، و(هـ) المخرجات، و(و) الجهاز اللي عليه الشكوى.

**ونسخهم كان هيخلّي نسختين من كل قراءة، والنسخة اللي على الورقة هي اللي
هتقدم** — لأن الممرضة بتحدّث العلامات مش الورقة.
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

MODULE = "beds"
SIX = ("airway", "breathing", "circulation", "disability", "skin", "hydration")
FULL = dict(airway="سالك", breathing="طبيعي", circulation="دافي",
            disability="واعي", skin="سليم", hydration="كويس",
            focus="الصدر: صفير في القاعدتين")


@pytest.fixture()
def stay(clinic):
    from app.models import Admission, Setting

    with clinic["app"].app_context():
        Setting.set(f"mod_enabled:{MODULE}", "1")
        row = Admission(patient_id=clinic["ids"]["child"],
                        admitted_at=datetime.utcnow() - timedelta(hours=2))
        clinic["db"].session.add(row)
        clinic["db"].session.commit()
        clinic["stay"] = row.id
    return clinic


def _stay(clinic):
    from app.models import Admission

    return Admission.query.get(clinic["stay"])


def _user(clinic):
    from app.models import User

    return User.query.get(clinic["ids"]["doctor"])


# ============ البرنامج بيجمّع اللي يعرفه ============
def test_the_three_it_already_knows_are_read_not_copied(stay):
    """(أ) و(ب) و(ج) — مفيش أعمدة ليهم في الجدول ده خالص."""
    from app.models.nursing import NursingAssessment

    columns = set(NursingAssessment.__table__.columns.keys())
    for absent in ("temperature_c", "pulse_bpm", "height", "weight",
                   "fall_score", "pain_score", "diet_key"):
        assert absent not in columns


def test_an_empty_file_says_so_element_by_element(stay):
    """**ورقة ساكتة عن تقييم السقوط بتتقرا «مفيش خطر»** — ودي مش نفس
    «محدّش قاس»."""
    from app.utils import nursing

    with stay["app"].app_context():
        known = nursing.assembled(_stay(stay))
        assert set(known) == {"vitals", "growth", "fall", "pressure", "pain",
                              "nutrition"}
        assert all(row is None for row in known.values())
        assert set(nursing.assembled_gaps(_stay(stay))) == set(known)


def test_a_reading_taken_during_the_stay_is_picked_up(stay):
    from app.models import Observation
    from app.utils import nursing

    with stay["app"].app_context():
        obs = Observation(patient_id=stay["ids"]["child"],
                          temperature_c=37.2, taken_at=datetime.utcnow())
        stay["db"].session.add(obs)
        stay["db"].session.commit()

        assert nursing.assembled(_stay(stay))["vitals"].id == obs.id
        assert "vitals" not in nursing.assembled_gaps(_stay(stay))


def test_a_reading_from_before_the_stay_is_not_this_assessment(stay):
    """قراءة من زيارة الشهر اللي فات مش تقييم الدخول ده."""
    from app.models import Observation
    from app.utils import nursing

    with stay["app"].app_context():
        stay["db"].session.add(Observation(
            patient_id=stay["ids"]["child"], temperature_c=37.0,
            taken_at=datetime.utcnow() - timedelta(days=30)))
        stay["db"].session.commit()

        assert nursing.assembled(_stay(stay))["vitals"] is None


def test_the_fall_and_pressure_rows_come_from_the_risk_table(stay):
    """(ب) و(ج) — `RiskAssessment` موجودة من `ICD.10` و`ICD.11`."""
    from app.models import RiskAssessment
    from app.utils import nursing

    with stay["app"].app_context():
        stay["db"].session.add(RiskAssessment(
            patient_id=stay["ids"]["child"], admission_id=stay["stay"],
            kind="fall"))
        stay["db"].session.commit()

        known = nursing.assembled(_stay(stay))
        assert known["fall"] is not None
        assert known["pressure"] is None


def test_the_pain_screening_counts_as_the_pain_screening(stay):
    """(ج) — و`PainScreen` هي اللي `ICD.09` عملها، مش عمود تاني هنا."""
    from app.utils import nursing
    from app.utils import pain

    with stay["app"].app_context():
        pain.screen(_stay(stay).patient, False, user=_user(stay),
                    admission=_stay(stay))
        stay["db"].session.commit()

        assert nursing.assembled(_stay(stay))["pain"] is not None


# ============ اللي الممرضة بتكتبه ============
def test_the_six_are_six_not_one(stay):
    """«الجلد سليم» مش بيقول حاجة عن الترطيب، وخانة واحدة للستة بتخلّي
    أول إجابة تنوب عن الباقي."""
    from app.utils import nursing

    with stay["app"].app_context():
        row = nursing.record(_stay(stay), user=_user(stay), skin="سليم")
        stay["db"].session.commit()

        gaps = nursing.missing(row)
        assert "skin" not in gaps
        assert set(gaps) == {"airway", "breathing", "circulation",
                             "disability", "hydration", "focus"}


def test_outputs_are_never_counted_missing(stay):
    """نصّها *(as relevant)* — وطفل مالوش مخرجات تتقاس ورقته كاملة."""
    from app.utils import nursing

    with stay["app"].app_context():
        row = nursing.record(_stay(stay), user=_user(stay), **FULL)
        stay["db"].session.commit()

        assert row.outputs is None
        assert nursing.missing(row) == []


def test_the_focus_is_what_nothing_else_knows(stay):
    from app.utils import nursing

    with stay["app"].app_context():
        row = nursing.record(_stay(stay), user=_user(stay),
                             **{k: v for k, v in FULL.items() if k != "focus"})
        stay["db"].session.commit()

        assert nursing.missing(row) == ["focus"]


def test_the_rest_is_written_from_the_same_row(stay):
    from app.utils import nursing

    with stay["app"].app_context():
        row = nursing.record(_stay(stay), user=_user(stay), airway="سالك")
        stay["db"].session.commit()
        nursing.describe(row, **{k: v for k, v in FULL.items()
                                 if k != "airway"})
        stay["db"].session.commit()

        assert nursing.missing(row) == []
        assert row.airway == "سالك"


def test_a_field_not_sent_is_not_wiped(stay):
    from app.utils import nursing

    with stay["app"].app_context():
        row = nursing.record(_stay(stay), user=_user(stay), airway="سالك",
                             skin="سليم")
        stay["db"].session.commit()
        nursing.describe(row, breathing="طبيعي")
        stay["db"].session.commit()

        assert row.airway == "سالك"
        assert row.skin == "سليم"


def test_a_box_with_only_spaces_is_still_empty(stay):
    from app.utils import nursing

    with stay["app"].app_context():
        row = nursing.record(_stay(stay), user=_user(stay), **FULL)
        stay["db"].session.commit()
        row.skin = "   "
        stay["db"].session.commit()

        assert nursing.missing(row) == ["skin"]


# ============ الأول واحد، والباقي إعادة ============
def test_only_one_initial_assessment(stay):
    """«الأول» واحد بالتعريف، وصفّين اسمهم «أول» بيخلّوا سؤال «اتعمل في
    وقته؟» مالوش إجابة واحدة."""
    from app.utils import nursing

    with stay["app"].app_context():
        nursing.record(_stay(stay), user=_user(stay))
        stay["db"].session.commit()

        with pytest.raises(ValueError):
            nursing.record(_stay(stay), user=_user(stay))


def test_a_reassessment_is_allowed_as_many_times_as_needed(stay):
    from app.utils import nursing

    with stay["app"].app_context():
        nursing.record(_stay(stay), user=_user(stay))
        stay["db"].session.commit()
        for _ in range(3):
            nursing.record(_stay(stay), kind="reassessment", user=_user(stay))
        stay["db"].session.commit()

        assert len(nursing.history(stay["stay"])) == 4
        assert nursing.initial_for(stay["stay"]).is_initial is True


def test_an_unknown_kind_is_refused(stay):
    from app.utils import nursing

    with stay["app"].app_context():
        with pytest.raises(ValueError):
            nursing.record(_stay(stay), kind="maybe")


def test_an_assessment_needs_a_stay(stay):
    """دليل ٣ بيقول *upon admission* — ومن غيرها مفيش لحظة نقيس منها."""
    from app.utils import nursing

    with stay["app"].app_context():
        with pytest.raises(ValueError):
            nursing.record(None)


# ============ الوقت: مهلتين مش واحدة ============
def test_a_stay_with_no_initial_assessment_is_found(stay):
    """**وبتشتغل من غير رقم العيادة**: تقييم محدّش عمله مايبقاش مخفي
    علشان المستشفى ما كتبتش مهلتها لسه."""
    from app.utils import nursing

    with stay["app"].app_context():
        assert nursing.initial_hours() is None
        assert [s.id for s in nursing.without_initial()] == [stay["stay"]]
        assert nursing.late_initial() == []


def test_once_the_window_is_written_the_late_ones_appear(stay):
    from app.models import Setting
    from app.utils import nursing

    with stay["app"].app_context():
        Setting.set("nursing_initial_hours", "1")
        stay["db"].session.commit()

        assert nursing.initial_hours() == 1
        assert [s.id for s in nursing.late_initial()] == [stay["stay"]]


def test_a_stay_still_inside_the_window_is_not_late(stay):
    from app.models import Setting
    from app.utils import nursing

    with stay["app"].app_context():
        Setting.set("nursing_initial_hours", "24")
        stay["db"].session.commit()

        assert nursing.late_initial() == []
        assert len(nursing.without_initial()) == 1


def test_the_two_windows_are_two_numbers(stay):
    """دليل ٣ *within the timeframe* ودليل ٤ *at the frequency* — رقمين
    بيوصفوا حاجتين، وواحد للاتنين كان هيخلّي واحد منهم يختفي."""
    from app.models import Setting
    from app.utils import nursing

    with stay["app"].app_context():
        Setting.set("nursing_initial_hours", "4")
        Setting.set("nursing_reassess_hours", "12")
        stay["db"].session.commit()

        assert nursing.initial_hours() == 4
        assert nursing.reassess_hours() == 12


def test_a_reassessment_that_is_overdue(stay):
    from app.models import Setting
    from app.utils import nursing

    with stay["app"].app_context():
        nursing.record(_stay(stay), user=_user(stay),
                       at=datetime.utcnow() - timedelta(hours=20))
        stay["db"].session.commit()
        Setting.set("nursing_reassess_hours", "8")
        stay["db"].session.commit()

        assert [s.id for s in nursing.overdue_reassessment()] == [stay["stay"]]


def test_a_fresh_reassessment_clears_it(stay):
    from app.models import Setting
    from app.utils import nursing

    with stay["app"].app_context():
        nursing.record(_stay(stay), user=_user(stay),
                       at=datetime.utcnow() - timedelta(hours=20))
        nursing.record(_stay(stay), kind="reassessment", user=_user(stay))
        stay["db"].session.commit()
        Setting.set("nursing_reassess_hours", "8")
        stay["db"].session.commit()

        assert nursing.overdue_reassessment() == []


def test_nothing_is_overdue_before_the_clinic_says_how_often(stay):
    from app.utils import nursing

    with stay["app"].app_context():
        nursing.record(_stay(stay), user=_user(stay),
                       at=datetime.utcnow() - timedelta(days=9))
        stay["db"].session.commit()

        assert nursing.reassess_hours() is None
        assert nursing.overdue_reassessment() == []


def test_a_nonsense_window_is_ignored(stay):
    from app.models import Setting
    from app.utils import nursing

    with stay["app"].app_context():
        for bad in ("", "  ", "ساعتين", "0", "-4"):
            Setting.set("nursing_initial_hours", bad)
            assert nursing.initial_hours() is None


def test_a_discharged_stay_is_not_asked_about(stay):
    from app.utils import nursing

    with stay["app"].app_context():
        _stay(stay).discharged_at = datetime.utcnow()
        stay["db"].session.commit()

        assert nursing.without_initial() == []


# ============ الشاشات ============
def test_the_stay_page_says_nobody_assessed_yet(stay):
    page = stay["sign_in"]("boss").get(
        f"/beds/admission/{stay['stay']}").get_data(as_text=True)

    assert "data-nursing-none" in page
    assert "data-nursing-form" in page


def test_the_stay_page_names_what_the_file_is_missing(stay):
    """**اللي البرنامج يعرفه بيتقال، واللي مايعرفوش بيتقال باسمه.**"""
    page = stay["sign_in"]("boss").get(
        f"/beds/admission/{stay['stay']}").get_data(as_text=True)

    assert "data-nursing-known" in page
    assert 'data-nursing-known-fall="0"' in page
    assert 'data-nursing-known-pain="0"' in page


def test_recording_from_the_screen_works(stay):
    from app.models import NursingAssessment

    client = stay["sign_in"]("boss")
    client.post(f"/beds/stay/{stay['stay']}/nursing", follow_redirects=True,
                data={"kind": "initial", **FULL})

    with stay["app"].app_context():
        row = NursingAssessment.query.one()
        assert row.is_initial is True
        assert row.skin == "سليم"


def test_the_gaps_get_their_own_boxes(stay):
    from app.utils import nursing

    with stay["app"].app_context():
        nursing.record(_stay(stay), user=_user(stay), airway="سالك")
        stay["db"].session.commit()

    page = stay["sign_in"]("boss").get(
        f"/beds/admission/{stay['stay']}").get_data(as_text=True)

    assert "data-nursing-complete" in page
    assert 'data-nursing-gap="skin"' in page
    assert 'data-nursing-gap="airway"' not in page


def test_the_second_press_records_a_reassessment(stay):
    from app.models import NursingAssessment

    client = stay["sign_in"]("boss")
    client.post(f"/beds/stay/{stay['stay']}/nursing", follow_redirects=True,
                data={"kind": "initial", **FULL})

    page = client.get(f"/beds/admission/{stay['stay']}").get_data(as_text=True)
    assert 'value="reassessment"' in page

    client.post(f"/beds/stay/{stay['stay']}/nursing", follow_redirects=True,
                data={"kind": "reassessment", **FULL})

    with stay["app"].app_context():
        assert NursingAssessment.query.count() == 2


def test_the_ward_board_shows_the_stay_and_says_no_window(stay):
    page = stay["sign_in"]("boss").get("/beds/watch").get_data(as_text=True)

    assert "data-nursing-watch" in page
    assert f'data-nursing-missing="{stay["stay"]}"' in page
    assert "data-nursing-no-window" in page


def test_every_word_of_the_screen_is_written_in_both_languages(clinic):
    import json

    ar = json.load(open("app/i18n/locales/ar.json", encoding="utf-8"))
    en = json.load(open("app/i18n/locales/en.json", encoding="utf-8"))

    assert set(ar["nursing"]) == set(en["nursing"])
    assert all((ar["nursing"][k] or "").strip() for k in ar["nursing"])
    assert all((en["nursing"][k] or "").strip() for k in en["nursing"])
