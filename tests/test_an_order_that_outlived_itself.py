"""أمر تقييد خلص والطفل لسه مربوط — GAHAR `CSS.12` و`CSS.05`.

**أخطر حاجة في المعيارين دول مش إن حد ينسى يكتب ورقة.**

`CSS.12` (ز) بيقول إن تجديد أمر التقييد بيبقى *"based on continuing needs"*
— يعني الأمر بيخلص. وأمر خلص والطفل لسه مربوط هو تقييد **من غير إذن**،
وبيعدّي من غير ما حد يلاحظ لأن مفيش حاجة بتتغيّر على أي شاشة لما ساعة
تعدّي. ودي الشغلانة اللي `expired()` موجودة علشانها.

و`CSS.05` دليل ٣ فيه **رقم مكتوب في الكتاب**:

> Staff with basic life support start the process immediately, while those
> with advanced life support will start **within a maximum of 5 minutes**.

فالبرنامج بيقيس عليه — وده الاستثناء الوحيد لقاعدة «ما بيخترعش رقم»،
والاختبار بيثبت إن الرقم من مكان واحد.
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def ward(clinic):
    """عيادة بأسرّة، وطفلين — علشان فلتر ناقص ما يعديش."""
    from app.models import Patient, Setting
    from app.utils.clock import local_today

    with clinic["app"].app_context():
        Setting.set("mod_enabled:beds", "1")
        other = Patient(patient_number="WD-2", full_name="طفل تاني",
                        gender="female", is_active=True,
                        date_of_birth=local_today() - timedelta(days=2000))
        clinic["db"].session.add(other)
        clinic["db"].session.commit()
        clinic["ids"]["other_child"] = other.id
    return clinic


def _tie(ward, patient_id=None, hours=2, reason="خطر على نفسه", at=None):
    from app.models import Patient, User
    from app.utils import restraint as tied

    with ward["app"].app_context():
        patient = ward["db"].session.get(
            Patient, patient_id or ward["ids"]["child"])
        doc = ward["db"].session.get(User, ward["ids"]["doctor"])
        row = tied.start(patient, "physical", reason, doc,
                         method="حزام صدر", alternatives="تهدئة لفظية",
                         valid_until=(datetime.utcnow() + timedelta(hours=hours)
                                      if hours is not None else None), at=at)
        ward["db"].session.commit()
        return row.id


def _row(ward, rid):
    from app.models import Restraint

    return ward["db"].session.get(Restraint, rid)


# ------------------------------- الأمر اللي عاش أطول من نفسه ----
def test_an_order_past_its_limit_with_the_child_still_tied(ward):
    """**السطر اللي الملف ده موجود علشانه.** مش ورقة ناقصة — تقييد من غير
    إذن."""
    from app.utils import restraint as tied

    rid = _tie(ward, hours=2)

    with ward["app"].app_context():
        later = datetime.utcnow() + timedelta(hours=3)
        assert [r.id for r in tied.expired(now=later)] == [rid]
        assert _row(ward, rid).expired_at(now=later) is not None


def test_an_order_still_inside_its_limit_is_not_on_that_list(ward):
    from app.utils import restraint as tied

    _tie(ward, hours=6)

    with ward["app"].app_context():
        assert tied.expired() == []


def test_a_restraint_already_removed_cannot_expire(ward):
    """التقييد اتفكّ. الأمر عدّى مدته بعد كده ومالوش معنى — والعدّ لو شمله
    كان هيخلّي رقم بيعلا بمرور الوقت على حاجات خلصت."""
    from app.models import User
    from app.utils import restraint as tied

    rid = _tie(ward, hours=2)
    with ward["app"].app_context():
        doc = ward["db"].session.get(User, ward["ids"]["doctor"])
        tied.end(_row(ward, rid), doc, reason="هدى وقعد مع أمه")
        ward["db"].session.commit()
        later = datetime.utcnow() + timedelta(hours=5)

        assert tied.expired(now=later) == []
        assert _row(ward, rid).expired_at(now=later) is None


def test_no_limit_at_all_is_counted_apart_from_expired(ward):
    """**الاتنين مش نفس الحاجة.** أمر عدّى مدته حاجة حصلت ولازم تتصرّف فيها
    دلوقتي، وأمر من غير مدة ورقة ناقصة من ساعة ما اتكتبت. خلطهم في رقم
    واحد بيخلّي الاتنين يتأجّلوا."""
    from app.utils import restraint as tied

    open_ended = _tie(ward, hours=None)
    _tie(ward, patient_id=ward["ids"]["other_child"], hours=2)

    with ward["app"].app_context():
        later = datetime.utcnow() + timedelta(hours=3)
        assert [r.id for r in tied.no_limit_set()] == [open_ended]
        assert open_ended not in [r.id for r in tied.expired(now=later)]


# ------------------------------------------ التجديد قرار جديد ----
def test_renewing_opens_a_new_order_and_closes_the_old(ward):
    """تمديد `valid_until` على نفس الصف كان هيمسح إن حد قرّر مرتين."""
    from app.models import User
    from app.utils import restraint as tied

    rid = _tie(ward, hours=2)
    with ward["app"].app_context():
        doc = ward["db"].session.get(User, ward["ids"]["doctor"])
        fresh = tied.renew(_row(ward, rid), doc,
                           valid_until=datetime.utcnow() + timedelta(hours=4))
        ward["db"].session.commit()

        assert _row(ward, rid).is_on is False
        assert fresh.renews_id == rid
        assert fresh.is_on
        assert [r.id for r in tied.on_now()] == [fresh.id]


def test_the_renewal_keeps_the_reason_and_the_place(ward):
    from app.models import User
    from app.utils import restraint as tied

    rid = _tie(ward, hours=2, reason="نزع القسطرة مرتين")
    with ward["app"].app_context():
        doc = ward["db"].session.get(User, ward["ids"]["doctor"])
        fresh = tied.renew(_row(ward, rid), doc)
        ward["db"].session.commit()

        assert fresh.reason == "نزع القسطرة مرتين"
        assert fresh.patient_id == _row(ward, rid).patient_id


# ------------------------------ اللي المعيار بيطلبه في الملف ----
def test_a_restraint_without_a_reason_is_refused(ward):
    from app.models import Patient, User
    from app.utils import restraint as tied

    with ward["app"].app_context():
        patient = ward["db"].session.get(Patient, ward["ids"]["child"])
        doc = ward["db"].session.get(User, ward["ids"]["doctor"])
        with pytest.raises(ValueError):
            tied.start(patient, "physical", "   ", doc)


def test_a_restraint_without_a_physician_order_is_refused(ward):
    """(ب) بيقول *clear physician order* — فصف من غير أمر بيخلّي الملف
    يقول إن التقييد اتعمل صح وهو مش عارف مين سمح بيه."""
    from app.models import Patient
    from app.utils import restraint as tied

    with ward["app"].app_context():
        patient = ward["db"].session.get(Patient, ward["ids"]["child"])
        with pytest.raises(ValueError):
            tied.start(patient, "physical", "خطر على نفسه", None)


def test_the_missing_elements_are_named(ward):
    from app.utils import restraint as tied

    rid = _tie(ward, hours=2)

    with ward["app"].app_context():
        gaps = tied.missing(_row(ward, rid))

    assert "monitoring" in gaps
    assert "order" not in gaps and "reason" not in gaps


def test_a_child_still_tied_is_not_missing_a_removal_reason(ward):
    """سبب الفكّ بيتكتب وهو بيتفكّ. عدّه ناقص وهو مربوط بيخلّي كل تقييد
    شغّال يبان ملف ناقص."""
    from app.utils import restraint as tied

    rid = _tie(ward, hours=2)

    with ward["app"].app_context():
        assert "end" not in tied.missing(_row(ward, rid))


def test_monitoring_is_the_childs_own_readings_tagged(ward):
    """**مش جدول تاني** — نفس اللي نقل الدم عمله، وللسبب نفسه: قراءات
    التقييد لازم تبان على شارت الطفل."""
    from app.models import Observation
    from app.utils import restraint as tied

    rid = _tie(ward, hours=2)
    with ward["app"].app_context():
        assert "monitoring" in tied.missing(_row(ward, rid))
        ward["db"].session.add(Observation(
            patient_id=ward["ids"]["child"], restraint_id=rid,
            taken_at=datetime.utcnow(), pulse_bpm=104))
        ward["db"].session.commit()

        assert "monitoring" not in tied.missing(_row(ward, rid))
        assert tied.last_check(rid) is not None


def test_another_childs_reading_does_not_count_as_this_ones_check(ward):
    from app.models import Observation
    from app.utils import restraint as tied

    rid = _tie(ward, hours=2)
    other = _tie(ward, patient_id=ward["ids"]["other_child"], hours=2)
    with ward["app"].app_context():
        ward["db"].session.add(Observation(
            patient_id=ward["ids"]["other_child"], restraint_id=other,
            taken_at=datetime.utcnow(), pulse_bpm=100))
        ward["db"].session.commit()

        assert tied.last_check(rid) is None


def test_nothing_is_called_unwatched_until_the_clinic_writes_the_interval(ward):
    """**الغلطة اللي عملتها وأنا بكتب الدالة دي**: حطّيت ٣٠ دقيقة كقيمة
    افتراضية. المعيار (و) بيقول «مراقبة وإعادة تقييم» وما بيقولش كل قد
    إيه، وقيمة افتراضية هنا هي رقم إكلينيكي مخترع."""
    from app.utils import restraint as tied

    _tie(ward, hours=6, at=datetime.utcnow() - timedelta(hours=5))

    with ward["app"].app_context():
        assert tied.interval_minutes() is None
        assert tied.unwatched() == []


def test_writing_the_interval_is_what_turns_it_on(ward):
    from app.models import Setting
    from app.utils import restraint as tied

    _tie(ward, hours=6, at=datetime.utcnow() - timedelta(hours=5))

    with ward["app"].app_context():
        Setting.set(tied.INTERVAL_SETTING, "30")
        ward["db"].session.commit()

        assert len(tied.unwatched()) == 1


def test_a_child_only_just_tied_is_not_overdue_for_a_check(ward):
    from app.models import Setting
    from app.utils import restraint as tied

    _tie(ward, hours=6)

    with ward["app"].app_context():
        Setting.set(tied.INTERVAL_SETTING, "30")
        ward["db"].session.commit()

        assert tied.unwatched() == []


# ------------------------------------------------- الإنعاش ----
def _arrest(ward, patient_id=None, at=None):
    from app.models import Patient, User
    from app.utils import resuscitation as cpr

    with ward["app"].app_context():
        patient = ward["db"].session.get(
            Patient, patient_id or ward["ids"]["child"])
        user = ward["db"].session.get(User, ward["ids"]["doctor"])
        row = cpr.start(patient, user=user, place="أشعة", at=at)
        ward["db"].session.commit()
        return row.id


def _resus(ward, rid):
    from app.models import Resuscitation

    return ward["db"].session.get(Resuscitation, rid)


def test_the_five_minutes_comes_from_the_standard_not_from_us(ward):
    """الرقم مكتوب في `CSS.05` دليل ٣، وبيتقرا من مكان واحد علشان الشاشة
    والقارئ والاختبار يقولوا نفس الحاجة."""
    from app.models import ALS_MINUTES
    from app.utils import resuscitation as cpr

    assert cpr.standard_minutes() == ALS_MINUTES == 5


def test_a_team_that_took_longer_than_the_standard_is_named(ward):
    from app.utils import resuscitation as cpr

    t0 = datetime.utcnow() - timedelta(hours=1)
    rid = _arrest(ward, at=t0)
    with ward["app"].app_context():
        cpr.team_arrived(_resus(ward, rid), at=t0 + timedelta(minutes=7))
        ward["db"].session.commit()

        assert _resus(ward, rid).to_team == 7
        assert _resus(ward, rid).late_team is True
        assert [r.id for r in cpr.late_responses()] == [rid]


def test_a_team_inside_the_standard_is_not(ward):
    from app.utils import resuscitation as cpr

    t0 = datetime.utcnow() - timedelta(hours=1)
    rid = _arrest(ward, at=t0)
    with ward["app"].app_context():
        cpr.team_arrived(_resus(ward, rid), at=t0 + timedelta(minutes=3))
        ward["db"].session.commit()

        assert _resus(ward, rid).late_team is False
        assert cpr.late_responses() == []


def test_a_team_that_never_arrived_is_its_own_answer_not_on_time(ward):
    """**تلات حالات مش اتنين.** «ما وصلش» مع «وصل بدري» كان هيخلّي إنعاش
    الفريق ما جاش فيه خالص يبان سليم."""
    from app.utils import resuscitation as cpr

    rid = _arrest(ward)

    with ward["app"].app_context():
        assert _resus(ward, rid).late_team is None
        assert cpr.late_responses() == []
        assert [r.id for r in cpr.never_answered()] == [rid]


def test_the_call_and_the_arrival_are_two_different_delays(ward):
    """عمود واحد كان هيخلّي «تأخير النداء» و«تأخير الوصول» نفس الحاجة."""
    from app.utils import resuscitation as cpr

    t0 = datetime.utcnow() - timedelta(hours=1)
    rid = _arrest(ward, at=t0)
    with ward["app"].app_context():
        cpr.called(_resus(ward, rid), at=t0 + timedelta(minutes=4))
        cpr.team_arrived(_resus(ward, rid), at=t0 + timedelta(minutes=6))
        ward["db"].session.commit()
        row = _resus(ward, rid)

    assert (row.to_call, row.to_team) == (4, 6)


def test_an_open_resuscitation_is_not_an_incomplete_record(ward):
    from app.utils import resuscitation as cpr

    rid = _arrest(ward)

    with ward["app"].app_context():
        assert "outcome" not in cpr.missing(_resus(ward, rid))
        assert [r.id for r in cpr.running()] == [rid]


def test_closing_it_is_what_makes_the_outcome_count(ward):
    from app.utils import resuscitation as cpr

    rid = _arrest(ward)
    with ward["app"].app_context():
        cpr.finish(_resus(ward, rid), "rosc", management="ضغط صدر وأدرينالين")
        ward["db"].session.commit()

        assert cpr.missing(_resus(ward, rid)) == ["called", "team"]
        assert cpr.running() == []


def test_an_outcome_the_record_does_not_know_is_refused(ward):
    from app.utils import resuscitation as cpr

    rid = _arrest(ward)
    with ward["app"].app_context():
        with pytest.raises(ValueError):
            cpr.finish(_resus(ward, rid), "improved")


def test_starting_an_arrest_asks_for_nothing_but_the_child(ward):
    """شاشة بتطلب عشر خانات قبل ما تفتح السجل هي شاشة هتتملّى بعد ساعة من
    الذاكرة — والأوقات اللي المعيار بيقيس عليها هي اللي الذاكرة بتضيّعها."""
    from app.models import Patient
    from app.utils import resuscitation as cpr

    with ward["app"].app_context():
        patient = ward["db"].session.get(Patient, ward["ids"]["child"])
        row = cpr.start(patient)
        ward["db"].session.commit()

        assert row.recognised_at is not None
        assert row.is_running


def test_another_childs_arrest_is_not_this_ones(ward):
    from app.utils import resuscitation as cpr

    _arrest(ward, patient_id=ward["ids"]["other_child"])

    with ward["app"].app_context():
        assert cpr.for_patient(ward["ids"]["child"]) == []
        assert len(cpr.for_patient(ward["ids"]["other_child"])) == 1


# ------------------------------------------------------- الأبواب ----
def test_the_ward_board_names_the_order_that_outlived_itself(ward):
    from app.models import Restraint

    rid = _tie(ward, hours=2)
    with ward["app"].app_context():
        row = ward["db"].session.get(Restraint, rid)
        row.valid_until = datetime.utcnow() - timedelta(hours=1)
        ward["db"].session.commit()

    page = ward["sign_in"]("doc").get("/beds/watch").get_data(as_text=True)

    assert "data-restraints-expired" in page
    assert f'data-expired-restraint="{rid}"' in page


def test_the_board_is_quiet_when_every_order_is_inside_its_limit(ward):
    _tie(ward, hours=6)

    page = ward["sign_in"]("doc").get("/beds/watch").get_data(as_text=True)

    assert "data-restraints-expired" not in page


def test_the_board_shows_an_open_resuscitation(ward):
    rid = _arrest(ward)

    page = ward["sign_in"]("doc").get("/beds/watch").get_data(as_text=True)

    assert f'data-resus-running="{rid}"' in page


def test_the_interval_has_a_box_on_the_settings_screen(ward):
    page = ward["sign_in"]("boss").get("/settings/risks").get_data(as_text=True)

    assert "data-restraint-watch-policy" in page
    assert 'name="restraint_watch_minutes"' in page


def test_writing_the_interval_from_the_screen_arms_it(ward):
    from app.utils import restraint as tied

    ward["sign_in"]("boss").post("/settings/risks", data={
        "restraint_watch_minutes": "45"}, follow_redirects=True)

    with ward["app"].app_context():
        assert tied.interval_minutes() == 45


def test_every_word_of_both_records_is_written_in_both_languages(ward):
    from app.i18n import _load_translations, _lookup
    from app.models import RESTRAINT_KINDS, RESUS_OUTCOMES
    from app.utils.restraint import ELEMENTS as R_ITEMS
    from app.utils.resuscitation import ELEMENTS as C_ITEMS

    tables = _load_translations()
    keys = [("restraint", f"kind_{k}") for k in RESTRAINT_KINDS]
    keys += [("restraint", f"item_{i}") for i in R_ITEMS]
    keys += [("restraint", k) for k in ("title", "expired", "no_limit",
                                        "unwatched", "watch_minutes",
                                        "needs_reason_and_order")]
    keys += [("resus", f"out_{o}") for o in RESUS_OUTCOMES]
    keys += [("resus", f"item_{i}") for i in C_ITEMS]
    keys += [("resus", k) for k in ("title", "running", "unanswered", "late")]
    for section, key in keys:
        for lang in ("ar", "en"):
            assert _lookup(tables, lang, f"{section}.{key}"), f"{lang}:{key}"
