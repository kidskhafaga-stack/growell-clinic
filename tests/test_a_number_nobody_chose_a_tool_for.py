"""الألم — GAHAR `ICD.09`.

النية بتبدأ بجملة مش إجرائية، وهي اللي بتشرح ليه البند موجود:

> Each patient has the **right to a pain-free life**.

**والبرنامج كان عنده رقم واحد.** `Observation.pain_score` مكتوب جنبه
`0–10, the faces/numeric scale` — يعني المقياس **مفترض من البرنامج**،
واللي المعيار بيطلبه أداة *valid and approved* بتاعة المستشفى.

**والفرق بين الفرز والتقييم هو التصميم كله.** الفرز لكل طفل، والتقييم
لما يطلع ألم بس — وبخمس بنود. **وأوحش صف هو «اتفرز وطلع فيه ألم ومحدّش
قيّمه»**، لأنه بيبان مكتمل: فيه أداة، وفيه رقم، وفيه وقت، وفيه اسم.
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

MODULE = "beds"


@pytest.fixture()
def clinic_with_tools(clinic):
    """عيادة كتبت أدواتها."""
    from app.models import Lookup, Setting

    with clinic["app"].app_context():
        Setting.set(f"mod_enabled:{MODULE}", "1")
        clinic["db"].session.add_all([
            Lookup(domain="pain_tool", key="flacc", name_ar="FLACC",
                   name_en="FLACC"),
            Lookup(domain="pain_tool", key="faces", name_ar="وجوه",
                   name_en="FACES"),
        ])
        clinic["db"].session.commit()
    return clinic


def _patient(clinic):
    from app.models import Patient

    return Patient.query.get(clinic["ids"]["child"])


def _user(clinic):
    from app.models import User

    return User.query.get(clinic["ids"]["doctor"])


def _screened(clinic, has_pain=True, tool="flacc", **kw):
    from app.utils import pain

    with clinic["app"].app_context():
        row = pain.screen(_patient(clinic), has_pain, tool_key=tool,
                          user=_user(clinic), **kw)
        clinic["db"].session.commit()
        return row.id


# ============ الأداة بتاعة المستشفى ============
def test_the_program_ships_no_pain_tool(clinic):
    """FLACC وFACES وNIPS مقاييس منشورة، واختيار أنهي واحدة تنفع لأنهي
    سن قرار المستشفى — زي مقياس الفرز وسلّم التسكين بالظبط."""
    from app.models import Lookup
    from app.utils import pain

    with clinic["app"].app_context():
        assert Lookup.query.filter_by(domain="pain_tool").count() == 0
        assert pain.tool_list() == []


def test_before_the_clinic_writes_its_list_a_screening_needs_no_tool(clinic):
    """عيادة لسه ما كتبتش أدواتها مش ممنوعة من تسجيل ألم — الشاشة
    بتقولها تكتب القايمة، والسجل ما بيضيعش في الوقت اللي بينهم."""
    from app.utils import pain

    with clinic["app"].app_context():
        row = pain.screen(_patient(clinic), True, user=_user(clinic))
        clinic["db"].session.commit()
        assert row.tool_key is None
        assert row.has_pain is True


def test_once_the_list_exists_a_tool_is_required(clinic_with_tools):
    """دليل ٣: *screened … using a **valid and approved tool***. فرز من
    غير أداة والقايمة موجودة هو رأي مش فرز."""
    from app.utils import pain

    with clinic_with_tools["app"].app_context():
        with pytest.raises(ValueError):
            pain.screen(_patient(clinic_with_tools), True)


def test_a_tool_that_is_not_on_the_list_is_refused(clinic_with_tools):
    from app.utils import pain

    with clinic_with_tools["app"].app_context():
        with pytest.raises(ValueError):
            pain.screen(_patient(clinic_with_tools), True, tool_key="nips")


def test_the_tool_list_counts_its_use_so_nobody_deletes_it(clinic_with_tools):
    """نفس فخ `special_diet`: دومين من غير فرع في `usage_counts` بيبان
    «مش مستعمل» — يعني يتمسح، وكل فرز يشاور على حاجة مش موجودة."""
    from app.utils import lookups

    _screened(clinic_with_tools, tool="flacc")

    with clinic_with_tools["app"].app_context():
        counts = lookups.usage_counts("pain_tool")
        assert counts["flacc"] == 1
        assert counts["faces"] == 0


# ============ الحكم بيتكتب، مش بيتحسب ============
def test_the_program_never_turns_a_score_into_a_verdict(clinic_with_tools):
    """«٤ فأكتر يبقى ألم» رقم إكلينيكي.

    كل أداة ليها مداها وقراءتها، واللي ماسكها بيقراها ويقول — والعمود
    بيسجّل قوله. فرقم عالي مع «مفيش ألم» بيتسجّل زي ما اتقال.
    """
    from app.models import PainScreen
    from app.utils import pain

    with clinic_with_tools["app"].app_context():
        row = pain.screen(_patient(clinic_with_tools), False,
                          tool_key="flacc", score=9, user=_user(clinic_with_tools))
        clinic_with_tools["db"].session.commit()

        assert PainScreen.query.get(row.id).has_pain is False
        assert PainScreen.query.get(row.id).score == 9
        assert pain.positive_without_assessment() == []


def test_an_answer_is_required(clinic_with_tools):
    from app.utils import pain

    with clinic_with_tools["app"].app_context():
        with pytest.raises(ValueError):
            pain.screen(_patient(clinic_with_tools), None, tool_key="flacc")


def test_the_chart_number_is_pointed_at_not_copied(clinic_with_tools):
    """`Observation.pain_score` مكانه الشارت، والفرز بيشاور عليه.

    نسخه كان هيخلّي الشارت وسجل الألم يقولوا رقمين لنفس الساعة — نفس
    غلطة نسخ الدوا على ورقة الإحالة.
    """
    from app.models import Observation, PainScreen
    from app.utils import pain

    with clinic_with_tools["app"].app_context():
        obs = Observation(patient_id=clinic_with_tools["ids"]["child"],
                          pain_score=6)
        clinic_with_tools["db"].session.add(obs)
        clinic_with_tools["db"].session.commit()

        row = pain.screen(_patient(clinic_with_tools), True, tool_key="flacc",
                          score=6, observation=obs, user=_user(clinic_with_tools))
        clinic_with_tools["db"].session.commit()

        assert PainScreen.query.get(row.id).observation_id == obs.id
        assert PainScreen.query.get(row.id).observation.pain_score == 6


# ============ أوحش صف: بيبان مكتمل ============
def test_pain_found_and_nobody_assessed_it(clinic_with_tools):
    """دليل ٤: *A comprehensive pain assessment is performed **when pain
    is identified from the screening***."""
    from app.utils import pain

    sid = _screened(clinic_with_tools, has_pain=True)

    with clinic_with_tools["app"].app_context():
        assert [r.id for r in pain.positive_without_assessment()] == [sid]


def test_a_screening_that_found_nothing_is_not_a_gap(clinic_with_tools):
    from app.utils import pain

    _screened(clinic_with_tools, has_pain=False)

    with clinic_with_tools["app"].app_context():
        assert pain.positive_without_assessment() == []


def test_assessing_it_clears_it(clinic_with_tools):
    from app.models import PainScreen
    from app.utils import pain

    sid = _screened(clinic_with_tools, has_pain=True)

    with clinic_with_tools["app"].app_context():
        pain.assess(PainScreen.query.get(sid), user=_user(clinic_with_tools),
                    intensity="٧", character="واخز", location="بطن",
                    frequency="مستمر", duration="ساعتين",
                    plan="باراسيتامول ومتابعة")
        clinic_with_tools["db"].session.commit()

        assert pain.positive_without_assessment() == []


def test_the_oldest_one_is_on_top(clinic_with_tools):
    """طفل عنده ألم من امبارح ومحدّش بصّ له أهم من واحد من نص ساعة."""
    from app.utils import pain

    old = _screened(clinic_with_tools, at=datetime.utcnow() - timedelta(days=1))
    new = _screened(clinic_with_tools, at=datetime.utcnow() - timedelta(hours=1))

    with clinic_with_tools["app"].app_context():
        assert [r.id for r in pain.positive_without_assessment()] == [old, new]


def test_an_assessment_on_a_negative_screening_is_refused(clinic_with_tools):
    """تقييم على فرز قال «مفيش ألم» بيخلّي كلمة «اتقيّم» مالهاش معنى."""
    from app.models import PainScreen
    from app.utils import pain

    sid = _screened(clinic_with_tools, has_pain=False)

    with clinic_with_tools["app"].app_context():
        with pytest.raises(ValueError):
            pain.assess(PainScreen.query.get(sid))


def test_assessing_the_same_screening_twice_is_refused(clinic_with_tools):
    from app.models import PainScreen
    from app.utils import pain

    sid = _screened(clinic_with_tools)

    with clinic_with_tools["app"].app_context():
        pain.assess(PainScreen.query.get(sid), plan="خطة")
        clinic_with_tools["db"].session.commit()
        with pytest.raises(ValueError):
            pain.assess(PainScreen.query.get(sid))


# ============ (ب) الخمسة، و(د) الخطة ============
def test_the_missing_elements_are_named(clinic_with_tools):
    """«تقييم غير مكتمل» مش معلومة. «ناقص: مكانه» معلومة."""
    from app.models import PainScreen
    from app.utils import pain

    sid = _screened(clinic_with_tools)

    with clinic_with_tools["app"].app_context():
        row = pain.assess(PainScreen.query.get(sid), intensity="٧",
                          character="واخز", plan="باراسيتامول")
        clinic_with_tools["db"].session.commit()

        assert set(pain.missing(row)) == {"location", "frequency", "duration"}


def test_an_assessment_with_no_plan_is_incomplete(clinic_with_tools):
    """*assessed … **and managed accordingly*** — والكلمة التانية مش زينة."""
    from app.models import PainScreen
    from app.utils import pain

    sid = _screened(clinic_with_tools)

    with clinic_with_tools["app"].app_context():
        row = pain.assess(PainScreen.query.get(sid), intensity="٧",
                          character="واخز", location="بطن",
                          frequency="مستمر", duration="ساعتين")
        clinic_with_tools["db"].session.commit()

        assert row.managed is False
        assert pain.missing(row) == ["plan"]
        assert [r.id for r in pain.incomplete()] == [row.id]


def test_a_complete_assessment_has_no_gaps(clinic_with_tools):
    from app.models import PainScreen
    from app.utils import pain

    sid = _screened(clinic_with_tools)

    with clinic_with_tools["app"].app_context():
        row = pain.assess(PainScreen.query.get(sid), intensity="٧",
                          character="واخز", location="بطن",
                          frequency="مستمر", duration="ساعتين", plan="خطة")
        clinic_with_tools["db"].session.commit()

        assert pain.missing(row) == []
        assert pain.incomplete() == []


def test_the_rest_is_written_from_the_same_row(clinic_with_tools):
    from app.models import PainScreen
    from app.utils import pain

    sid = _screened(clinic_with_tools)

    with clinic_with_tools["app"].app_context():
        row = pain.assess(PainScreen.query.get(sid), intensity="٧")
        clinic_with_tools["db"].session.commit()
        pain.describe(row, character="واخز", location="بطن",
                      frequency="مستمر", duration="ساعتين", plan="خطة")
        clinic_with_tools["db"].session.commit()

        assert pain.missing(row) == []
        assert row.intensity == "٧"


# ============ (ج) إعادة الفرز ============
def test_a_reassessment_is_just_a_later_screening(clinic_with_tools):
    """**مش عمود.** «اتعاد فرزه» كعلامة بيبقى حاجة حد لازم يفتكر يحطّها."""
    from app.models import PainScreen
    from app.utils import pain

    sid = _screened(clinic_with_tools, at=datetime.utcnow() - timedelta(hours=8))

    with clinic_with_tools["app"].app_context():
        row = pain.assess(PainScreen.query.get(sid), plan="خطة",
                          at=datetime.utcnow() - timedelta(hours=8))
        clinic_with_tools["db"].session.commit()
        assert [r.id for r in pain.awaiting_reassessment()] == [row.id]

    _screened(clinic_with_tools, has_pain=False)

    with clinic_with_tools["app"].app_context():
        assert pain.awaiting_reassessment() == []


def test_nobody_is_late_until_the_clinic_says_how_often(clinic_with_tools):
    """(ج) *frequency of pain reassessments* — سياسة المستشفى.

    وزي `ACT.10` بالظبط: «محدّش رجع له» بتبان من غير رقم، و«اتأخر» لأ.
    """
    from app.models import PainScreen
    from app.utils import pain

    sid = _screened(clinic_with_tools, at=datetime.utcnow() - timedelta(days=3))

    with clinic_with_tools["app"].app_context():
        pain.assess(PainScreen.query.get(sid), plan="خطة",
                    at=datetime.utcnow() - timedelta(days=3))
        clinic_with_tools["db"].session.commit()

        assert pain.reassess_hours() is None
        assert pain.overdue_reassessment() == []
        assert len(pain.awaiting_reassessment()) == 1


def test_once_it_does_the_late_ones_appear(clinic_with_tools):
    from app.models import PainScreen, Setting
    from app.utils import pain

    sid = _screened(clinic_with_tools, at=datetime.utcnow() - timedelta(days=3))

    with clinic_with_tools["app"].app_context():
        row = pain.assess(PainScreen.query.get(sid), plan="خطة",
                          at=datetime.utcnow() - timedelta(days=3))
        clinic_with_tools["db"].session.commit()
        Setting.set("pain_reassess_hours", "4")

        assert pain.reassess_hours() == 4
        assert [r.id for r in pain.overdue_reassessment()] == [row.id]


def test_a_nonsense_window_is_ignored(clinic_with_tools):
    from app.models import Setting
    from app.utils import pain

    with clinic_with_tools["app"].app_context():
        for bad in ("", "  ", "صفر", "0", "-3"):
            Setting.set("pain_reassess_hours", bad)
            assert pain.reassess_hours() is None


# ============ دليل ٣: كل طفل ============
def test_a_stay_nobody_screened_is_found(clinic_with_tools):
    """*All inpatients … are screened for pain*."""
    from app.models import Admission
    from app.utils import pain

    with clinic_with_tools["app"].app_context():
        stay = Admission(patient_id=clinic_with_tools["ids"]["child"])
        clinic_with_tools["db"].session.add(stay)
        clinic_with_tools["db"].session.commit()
        sid = stay.id

        assert [s.id for s in pain.unscreened_stays()] == [sid]


def test_a_screening_before_the_stay_does_not_count(clinic_with_tools):
    """فرز من زيارة الشهر اللي فات مش فرز الإقامة دي."""
    from app.models import Admission
    from app.utils import pain

    _screened(clinic_with_tools, has_pain=False,
              at=datetime.utcnow() - timedelta(days=30))

    with clinic_with_tools["app"].app_context():
        stay = Admission(patient_id=clinic_with_tools["ids"]["child"])
        clinic_with_tools["db"].session.add(stay)
        clinic_with_tools["db"].session.commit()

        assert [s.id for s in pain.unscreened_stays()] == [stay.id]


def test_screening_during_the_stay_clears_it(clinic_with_tools):
    from app.models import Admission
    from app.utils import pain

    with clinic_with_tools["app"].app_context():
        stay = Admission(patient_id=clinic_with_tools["ids"]["child"])
        clinic_with_tools["db"].session.add(stay)
        clinic_with_tools["db"].session.commit()

    _screened(clinic_with_tools, has_pain=False)

    with clinic_with_tools["app"].app_context():
        assert pain.unscreened_stays() == []


def test_a_discharged_stay_is_not_asked_about(clinic_with_tools):
    from app.models import Admission
    from app.utils import pain

    with clinic_with_tools["app"].app_context():
        stay = Admission(patient_id=clinic_with_tools["ids"]["child"],
                         discharged_at=datetime.utcnow())
        clinic_with_tools["db"].session.add(stay)
        clinic_with_tools["db"].session.commit()

        assert pain.unscreened_stays() == []


# ============ الشاشات ============
def _stay(clinic):
    from app.models import Admission

    with clinic["app"].app_context():
        row = Admission(patient_id=clinic["ids"]["child"])
        clinic["db"].session.add(row)
        clinic["db"].session.commit()
        return row.id


def test_the_stay_page_says_the_clinic_has_no_tools_yet(clinic):
    from app.models import Setting

    with clinic["app"].app_context():
        Setting.set(f"mod_enabled:{MODULE}", "1")
        clinic["db"].session.commit()

    sid = _stay(clinic)
    page = clinic["sign_in"]("boss").get(
        f"/beds/admission/{sid}").get_data(as_text=True)

    assert "data-pain-no-tools" in page
    assert "data-pain-screen" not in page


def test_the_stay_page_offers_the_screening(clinic_with_tools):
    sid = _stay(clinic_with_tools)
    page = clinic_with_tools["sign_in"]("boss").get(
        f"/beds/admission/{sid}").get_data(as_text=True)

    assert "data-pain-screen" in page
    assert 'value="flacc"' in page


def test_screening_from_the_screen_records_the_answer(clinic_with_tools):
    from app.models import PainScreen

    sid = _stay(clinic_with_tools)
    client = clinic_with_tools["sign_in"]("boss")
    client.post(f"/beds/stay/{sid}/pain-screen", follow_redirects=True,
                data={"tool_key": "flacc", "score": "7", "has_pain": "yes"})

    with clinic_with_tools["app"].app_context():
        row = PainScreen.query.one()
        assert row.has_pain is True
        assert row.score == 7
        assert row.admission_id == sid


def test_the_screen_that_found_pain_offers_the_assessment(clinic_with_tools):
    from app.utils import pain

    sid = _stay(clinic_with_tools)
    with clinic_with_tools["app"].app_context():
        from app.models import Admission
        pain.screen(_patient(clinic_with_tools), True, tool_key="flacc",
                    admission=Admission.query.get(sid),
                    user=_user(clinic_with_tools))
        clinic_with_tools["db"].session.commit()

    page = clinic_with_tools["sign_in"]("boss").get(
        f"/beds/admission/{sid}").get_data(as_text=True)

    assert "data-pain-assess" in page
    assert 'name="location"' in page


def test_the_gaps_get_their_own_boxes(clinic_with_tools):
    """**اللي بيقرا الناقص هو اللي بيكمّله.**"""
    from app.models import Admission, PainScreen
    from app.utils import pain

    sid = _stay(clinic_with_tools)
    with clinic_with_tools["app"].app_context():
        row = pain.screen(_patient(clinic_with_tools), True, tool_key="flacc",
                          admission=Admission.query.get(sid),
                          user=_user(clinic_with_tools))
        clinic_with_tools["db"].session.commit()
        pain.assess(PainScreen.query.get(row.id), intensity="٧", plan="خطة")
        clinic_with_tools["db"].session.commit()

    page = clinic_with_tools["sign_in"]("boss").get(
        f"/beds/admission/{sid}").get_data(as_text=True)

    assert "data-pain-complete" in page
    assert 'data-pain-gap="location"' in page
    assert 'data-pain-gap="intensity"' not in page


def test_the_ward_board_shows_the_three_states(clinic_with_tools):
    from app.models import Admission
    from app.utils import pain

    sid = _stay(clinic_with_tools)
    with clinic_with_tools["app"].app_context():
        row = pain.screen(_patient(clinic_with_tools), True, tool_key="flacc",
                          admission=Admission.query.get(sid),
                          user=_user(clinic_with_tools))
        clinic_with_tools["db"].session.commit()
        rid = row.id

    page = clinic_with_tools["sign_in"]("boss").get(
        "/beds/watch").get_data(as_text=True)

    assert "data-pain-watch" in page
    assert f'data-pain-unassessed="{rid}"' in page
    # والمهلة مش مكتوبة، فالشاشة بتقول كده بدل ما تتهم حد بالتأخير.
    assert "data-pain-no-window" in page


def test_every_word_of_the_screen_is_written_in_both_languages(clinic):
    import json

    ar = json.load(open("app/i18n/locales/ar.json", encoding="utf-8"))
    en = json.load(open("app/i18n/locales/en.json", encoding="utf-8"))

    assert set(ar["pain"]) == set(en["pain"])
    assert all((ar["pain"][k] or "").strip() for k in ar["pain"])
    assert all((en["pain"][k] or "").strip() for k in en["pain"])
