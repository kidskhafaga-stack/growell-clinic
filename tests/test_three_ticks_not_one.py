"""تلات حاجات مش علامة واحدة — GAHAR `ICD.18`.

السياسة (ب)–(د) بتقول تلات حاجات بيحصلوا واحدة ورا التانية: الأمر
**يتكتب** من اللي استلمه · **يتقرا بصوت عالي** · واللي قاله **يأكّده**.

**وعلامة واحدة بتقف مكان التلاتة هي بالظبط اللي المعيار موجود علشانه.**
فالملف ده بيثبّت إنهم تلاتة، وإن اللي استلم الأمر ما يقدرش يأكّد كتابته
هو نفسه — ودي الحتة اللي القراية بصوت عالي موجودة علشان تمسكها.
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def ward(clinic):
    from app.models import Setting, User

    with clinic["app"].app_context():
        Setting.set("mod_enabled:beds", "1")
        # دكتور تاني: التأكيد لازم ييجي من غير اللي كتب، فمن غير التاني
        # ده مفيش حالة سليمة نقدر نختبرها.
        other = User(username="doc2", full_name="دكتور تاني", role="doctor",
                     is_active=True)
        other.set_password("secret")
        clinic["db"].session.add(other)
        clinic["db"].session.commit()
        clinic["ids"]["other_doctor"] = other.id
    return clinic


def _order(ward, text="سيفوتاكسيم ٥٠٠ مجم وريد كل ٨ ساعات", channel="spoken",
           spoken_at=None, at=None):
    from app.models import Patient, User
    from app.utils import verbal_order as vo

    with ward["app"].app_context():
        patient = ward["db"].session.get(Patient, ward["ids"]["child"])
        nurse = ward["db"].session.get(User, ward["ids"]["doctor"])
        row = vo.record(patient, text, received_by=nurse, channel=channel,
                        spoken_at=spoken_at, at=at)
        ward["db"].session.commit()
        return row.id


def _row(ward, oid):
    from app.models import VerbalOrder

    return ward["db"].session.get(VerbalOrder, oid)


# ------------------------------------------ التلاتة مش واحدة ----
def test_writing_it_down_is_not_reading_it_back(ward):
    """الصف نفسه هو الكتابة — و(ج) لسه ما حصلتش."""
    oid = _order(ward)

    with ward["app"].app_context():
        row = _row(ward, oid)
        assert row.written_at is not None       # (ب) حصلت
        assert not row.read_back                # (ج) لأ
        assert not row.confirmed                # (د) لأ
        assert not row.closed


def test_reading_it_back_is_not_confirming_it(ward):
    """أمر اتقرا بصوت عالي ومحدّش أكّده لسه أمر مفتوح."""
    from app.utils import verbal_order as vo

    oid = _order(ward)
    with ward["app"].app_context():
        vo.read_back(_row(ward, oid))
        ward["db"].session.commit()

        row = _row(ward, oid)
        assert row.read_back
        assert not row.confirmed
        assert not row.closed
        assert vo.missing(row) == ["confirm"]


def test_confirming_it_is_not_reading_it_back(ward):
    """والعكس: أمر اتأكّد من غير قراية ما عدّاش على الحاجة اللي النية
    بتقول إنها بتمنع الغلط."""
    from app.models import User
    from app.utils import verbal_order as vo

    oid = _order(ward)
    with ward["app"].app_context():
        boss = ward["db"].session.get(User, ward["ids"]["other_doctor"])
        vo.confirm(_row(ward, oid), boss)
        ward["db"].session.commit()

        row = _row(ward, oid)
        assert row.confirmed
        assert not row.read_back
        assert not row.closed
        assert vo.missing(row) == ["read_back"]


def test_only_all_three_closes_it(ward):
    from app.models import User
    from app.utils import verbal_order as vo

    oid = _order(ward)
    with ward["app"].app_context():
        boss = ward["db"].session.get(User, ward["ids"]["other_doctor"])
        vo.read_back(_row(ward, oid))
        vo.confirm(_row(ward, oid), boss)
        ward["db"].session.commit()

        row = _row(ward, oid)
        assert row.closed
        assert vo.missing(row) == []
        assert vo.open_orders() == []


# --------------------------- اللي أكّد غير اللي كتب، بالضرورة ----
def test_the_receiver_cannot_confirm_their_own_write_down(ward):
    """**دي الحتة كلها.**

    المعيار بيقول *the ordering physician*، واللي استلم الأمر بيأكّد
    كتابته هو نفسه مش تأكيد — ده بالظبط اللي القراية بصوت عالي موجودة
    علشان تمسكه. ولو السجل قبلها، الأمر اللي اتكتب غلط واتأكّد من اللي
    كتبه غلط هيبان سليم.
    """
    from app.models import User
    from app.utils import verbal_order as vo

    oid = _order(ward)
    with ward["app"].app_context():
        nurse = ward["db"].session.get(User, ward["ids"]["doctor"])
        with pytest.raises(ValueError):
            vo.confirm(_row(ward, oid), nurse)

        # وما اتكتبش حاجة.
        assert _row(ward, oid).confirmed_at is None
        assert _row(ward, oid).confirmed_by_id is None


def test_a_confirmation_with_nobody_behind_it_is_refused(ward):
    """(هـ) «متطلبات التوثيق والتصديق» — مين أكّد مش بس إنه اتأكّد."""
    from app.utils import verbal_order as vo

    oid = _order(ward)
    with ward["app"].app_context():
        with pytest.raises(ValueError):
            vo.confirm(_row(ward, oid), None)


def test_the_confirmation_carries_who_gave_it(ward):
    from app.models import User
    from app.utils import verbal_order as vo

    oid = _order(ward)
    with ward["app"].app_context():
        boss = ward["db"].session.get(User, ward["ids"]["other_doctor"])
        vo.confirm(_row(ward, oid), boss)
        ward["db"].session.commit()

        assert _row(ward, oid).confirmed_by_id == boss.id


def test_a_second_press_keeps_the_first_moment(ward):
    """الأولى هي اللي حصلت فعلاً، والتانية حد بيدوس مرتين."""
    from app.models import User
    from app.utils import verbal_order as vo

    oid = _order(ward)
    early = datetime.utcnow() - timedelta(minutes=30)
    with ward["app"].app_context():
        boss = ward["db"].session.get(User, ward["ids"]["other_doctor"])
        vo.read_back(_row(ward, oid), at=early)
        vo.confirm(_row(ward, oid), boss, at=early)
        ward["db"].session.commit()

        vo.read_back(_row(ward, oid))
        vo.confirm(_row(ward, oid), boss)
        ward["db"].session.commit()

        row = _row(ward, oid)
        assert row.read_back_at == early
        assert row.confirmed_at == early


# ------------------------------------------ اللي بيترفض عند الباب ----
def test_an_order_with_no_text_is_not_an_order(ward):
    """وصف بيقول «فيه أمر شفهي» من غير ما يقول إيه هو بيجاوب إن فيه حاجة
    حصلت وما بيجاوبش المعيار — والنية بتقول *the **complete** order*."""
    from app.models import Patient, User
    from app.utils import verbal_order as vo

    with ward["app"].app_context():
        patient = ward["db"].session.get(Patient, ward["ids"]["child"])
        nurse = ward["db"].session.get(User, ward["ids"]["doctor"])
        for empty in ("", "   ", "\n"):
            with pytest.raises(ValueError):
                vo.record(patient, empty, received_by=nurse)


def test_an_order_with_no_receiver_is_refused(ward):
    """(ب) بتقول *documented **by the receiver*** — أمر مالوش مستلِم هو
    أمر محدّش مسؤول عنه."""
    from app.models import Patient
    from app.utils import verbal_order as vo

    with ward["app"].app_context():
        patient = ward["db"].session.get(Patient, ward["ids"]["child"])
        with pytest.raises(ValueError):
            vo.record(patient, "أي أمر", received_by=None)


def test_a_channel_the_record_cannot_draw_is_refused(ward):
    from app.models import Patient, User
    from app.utils import verbal_order as vo

    with ward["app"].app_context():
        patient = ward["db"].session.get(Patient, ward["ids"]["child"])
        nurse = ward["db"].session.get(User, ward["ids"]["doctor"])
        with pytest.raises(ValueError):
            vo.record(patient, "أي أمر", received_by=nurse, channel="fax")


def test_the_two_channels_are_kept_apart(ward):
    """(أ) السياسة بتفرّق بينهم فالسجل بيفرّق: مكالمة تليفون محدّش شايف
    فيها اللي بيكتب."""
    _order(ward, channel="spoken")
    oid = _order(ward, channel="phone")

    with ward["app"].app_context():
        assert _row(ward, oid).channel == "phone"


# ------------------------------------------------- المهلة ----
def test_nothing_is_late_until_the_clinic_writes_the_timeframe(ward):
    """دليل ٤ بيقول *predefined* — يعني المستشفى بتعرّفها، والبرنامج ما
    بيخترعش رقم."""
    from app.utils import verbal_order as vo

    _order(ward, spoken_at=datetime.utcnow() - timedelta(hours=8))

    with ward["app"].app_context():
        assert vo.timeframe_minutes() is None
        assert vo.late() == []


def test_writing_the_timeframe_is_what_turns_it_on(ward):
    from app.models import Setting
    from app.utils import verbal_order as vo

    oid = _order(ward, spoken_at=datetime.utcnow() - timedelta(hours=8))
    with ward["app"].app_context():
        Setting.set(vo.TIMEFRAME_SETTING, "60")
        ward["db"].session.commit()

        assert vo.timeframe_minutes() == 60
        assert [r.id for r in vo.late()] == [oid]


def test_an_order_written_inside_the_timeframe_is_not_late(ward):
    from app.models import Setting
    from app.utils import verbal_order as vo

    _order(ward, spoken_at=datetime.utcnow() - timedelta(minutes=10))
    with ward["app"].app_context():
        Setting.set(vo.TIMEFRAME_SETTING, "60")
        ward["db"].session.commit()

        assert vo.late() == []


def test_the_delay_is_between_speaking_and_writing_not_until_now(ward):
    """**عمود واحد كان هيخلّي القياس ده مستحيل.**

    الأمر اللي اتقال الساعة تلاتة واتكتب الساعة تسعة اتأخر ست ساعات،
    حتى لو بقاله أسبوع في الملف.
    """
    from app.utils import verbal_order as vo

    spoken = datetime.utcnow() - timedelta(days=7)
    written = spoken + timedelta(hours=6)
    oid = _order(ward, spoken_at=spoken, at=written)

    with ward["app"].app_context():
        assert _row(ward, oid).delay_minutes == 6 * 60


def test_an_order_with_no_spoken_time_has_no_delay_we_know_of(ward):
    """ما اتقالش إمتى يبقى اتقال ساعة ما اتكتب — والمهلة صفر، وهي فعلاً
    صفر: مفيش تأخير نعرفه."""
    from app.models import Setting
    from app.utils import verbal_order as vo

    oid = _order(ward)
    with ward["app"].app_context():
        Setting.set(vo.TIMEFRAME_SETTING, "1")
        ward["db"].session.commit()

        assert _row(ward, oid).delay_minutes == 0
        assert vo.late() == []


# ------------------------------------------------- القوايم ----
def test_the_open_list_holds_both_kinds_of_gap(ward):
    from app.models import User
    from app.utils import verbal_order as vo

    no_read = _order(ward, text="أمر أول")
    no_confirm = _order(ward, text="أمر تاني")
    with ward["app"].app_context():
        boss = ward["db"].session.get(User, ward["ids"]["other_doctor"])
        vo.confirm(_row(ward, no_read), boss)
        vo.read_back(_row(ward, no_confirm))
        ward["db"].session.commit()

        assert {r.id for r in vo.open_orders()} == {no_read, no_confirm}


def test_the_oldest_open_order_comes_first(ward):
    """أقدم أمر مفتوح هو اللي حد المفروض يسأل عنه."""
    from app.utils import verbal_order as vo

    old = _order(ward, spoken_at=datetime.utcnow() - timedelta(hours=5))
    new = _order(ward, spoken_at=datetime.utcnow() - timedelta(hours=1))

    with ward["app"].app_context():
        assert [r.id for r in vo.open_orders()] == [old, new]


def test_another_childs_order_is_not_this_ones(ward):
    from app.models import Patient, User
    from app.utils import verbal_order as vo
    from app.utils.clock import local_today

    with ward["app"].app_context():
        other = Patient(patient_number="VO-2", full_name="طفل تاني",
                        gender="male", is_active=True,
                        date_of_birth=local_today() - timedelta(days=900))
        ward["db"].session.add(other)
        ward["db"].session.flush()
        nurse = ward["db"].session.get(User, ward["ids"]["doctor"])
        vo.record(other, "أمر لطفل تاني", received_by=nurse)
        ward["db"].session.commit()

        assert vo.for_patient(ward["ids"]["child"]) == []
        assert len(vo.for_patient(other.id)) == 1


def test_the_ordering_name_survives_a_caller_who_is_not_a_user(ward):
    """استشاري من بره بيتصل بالليل موجود، وسطر فاضي مكانه بيخلّي الأمر
    مجهول المصدر."""
    from app.models import Patient, User
    from app.utils import verbal_order as vo

    with ward["app"].app_context():
        patient = ward["db"].session.get(Patient, ward["ids"]["child"])
        nurse = ward["db"].session.get(User, ward["ids"]["doctor"])
        row = vo.record(patient, "أمر بالتليفون", received_by=nurse,
                        channel="phone", ordered_by_name="د. استشاري بره")
        ward["db"].session.commit()

        assert row.ordering_name("ar") == "د. استشاري بره"
        assert row.ordered_by_id is None


# ================================================ الباب ====
def test_a_child_with_no_verbal_order_has_no_tab(ward):
    """تبويب لحاجة ما حصلتش أبداً أثاث."""
    page = ward["sign_in"]("doc").get(
        f"/patients/{ward['ids']['child']}").get_data(as_text=True)

    assert "'verbal','tab_verbal'" not in page
    assert "data-verbal-order" not in page


def test_the_file_shows_the_order_and_its_three_steps(ward):
    oid = _order(ward)

    page = ward["sign_in"]("doc").get(
        f"/patients/{ward['ids']['child']}").get_data(as_text=True)

    assert f'data-verbal-order="{oid}"' in page
    assert 'data-step="written"' in page          # (ب) حصلت
    assert 'data-missing="read_back"' in page     # (ج) لسه
    assert 'data-missing="confirm"' in page       # (د) لسه


def test_the_screen_does_not_offer_the_receiver_the_confirm_button(ward):
    """**الشاشة بتوفّر الضغطة، والسجل بيمنع اللي يوصل من أي طريق تاني.**

    والحتّتين مقصودين: حارس من ناحية واحدة نص قاعدة.
    """
    _order(ward)

    # اللي كتب الأمر هو `doc` نفسه.
    mine = ward["sign_in"]("doc").get(
        f"/patients/{ward['ids']['child']}").get_data(as_text=True)
    assert "verbal-order/" in mine
    assert "/confirm" not in mine

    theirs = ward["sign_in"]("doc2").get(
        f"/patients/{ward['ids']['child']}").get_data(as_text=True)
    assert "/confirm" in theirs


def test_the_route_refuses_the_receiver_even_when_the_button_is_hidden(ward):
    """الشاشة مش حارس. اللي بيعرف العنوان بيوصله."""
    from app.utils import verbal_order as vo

    oid = _order(ward)

    ward["sign_in"]("doc").post(f"/patients/verbal-order/{oid}/confirm",
                                follow_redirects=True)

    with ward["app"].app_context():
        assert not _row(ward, oid).confirmed
        assert vo.missing(_row(ward, oid)) == ["read_back", "confirm"]


def test_writing_one_down_from_the_file_works(ward):
    from app.utils import verbal_order as vo

    ward["sign_in"]("doc").post(
        f"/patients/{ward['ids']['child']}/verbal-order",
        data={"text": "باراسيتامول ١٥ مجم/كجم فموي عند اللزوم",
              "channel": "phone", "ordered_by_name": "د. مناوب"},
        follow_redirects=True)

    with ward["app"].app_context():
        rows = vo.for_patient(ward["ids"]["child"])
        assert len(rows) == 1
        assert rows[0].channel == "phone"
        assert rows[0].ordering_name("ar") == "د. مناوب"


def test_an_empty_order_from_the_screen_is_not_saved(ward):
    from app.utils import verbal_order as vo

    ward["sign_in"]("doc").post(
        f"/patients/{ward['ids']['child']}/verbal-order",
        data={"text": "   "}, follow_redirects=True)

    with ward["app"].app_context():
        assert vo.for_patient(ward["ids"]["child"]) == []


def test_the_two_buttons_do_their_own_step(ward):
    from app.utils import verbal_order as vo

    oid = _order(ward)

    ward["sign_in"]("doc").post(f"/patients/verbal-order/{oid}/read-back",
                                follow_redirects=True)
    with ward["app"].app_context():
        assert vo.missing(_row(ward, oid)) == ["confirm"]

    ward["sign_in"]("doc2").post(f"/patients/verbal-order/{oid}/confirm",
                                 follow_redirects=True)
    with ward["app"].app_context():
        assert vo.missing(_row(ward, oid)) == []
        assert _row(ward, oid).closed


def test_the_ward_board_shows_an_open_order(ward):
    oid = _order(ward)

    page = ward["sign_in"]("doc").get("/beds/watch").get_data(as_text=True)

    assert f'data-verbal-open="{oid}"' in page
    assert 'data-missing="read_back"' in page


def test_a_closed_order_leaves_the_board(ward):
    from app.models import User
    from app.utils import verbal_order as vo

    oid = _order(ward)
    with ward["app"].app_context():
        boss = ward["db"].session.get(User, ward["ids"]["other_doctor"])
        vo.read_back(_row(ward, oid))
        vo.confirm(_row(ward, oid), boss)
        ward["db"].session.commit()

    page = ward["sign_in"]("doc").get("/beds/watch").get_data(as_text=True)

    assert "data-verbal-watch" not in page


def test_the_board_stays_quiet_about_lateness_until_the_clinic_says(ward):
    _order(ward, spoken_at=datetime.utcnow() - timedelta(hours=9))

    page = ward["sign_in"]("doc").get("/beds/watch").get_data(as_text=True)

    assert "data-verbal-late" not in page


def test_and_says_it_once_the_clinic_does(ward):
    from app.models import Setting
    from app.utils import verbal_order as vo

    oid = _order(ward, spoken_at=datetime.utcnow() - timedelta(hours=9))
    with ward["app"].app_context():
        Setting.set(vo.TIMEFRAME_SETTING, "30")
        ward["db"].session.commit()

    page = ward["sign_in"]("doc").get("/beds/watch").get_data(as_text=True)

    assert f'data-verbal-late="{oid}"' in page


def test_the_timeframe_has_a_box_on_the_settings_screen(ward):
    page = ward["sign_in"]("boss").get("/settings/risks").get_data(as_text=True)

    assert "data-verbal-timeframe-policy" in page
    assert 'name="verbal_order_minutes"' in page


def test_writing_the_timeframe_from_the_screen_arms_it(ward):
    from app.utils import verbal_order as vo

    ward["sign_in"]("boss").post("/settings/risks", data={
        "verbal_order_minutes": "15"}, follow_redirects=True)

    with ward["app"].app_context():
        assert vo.timeframe_minutes() == 15


def test_the_local_hour_typed_on_the_screen_is_stored_as_utc(ward):
    """**الغلطة اللي البرنامج ده دفع تمنها أربع مرات في تقارير الفلوس.**

    اللي بيكتب بيبص في الساعة على الحيطة، والمخزّن UTC — ومقارنة
    الاتنين من غير تحويل بتطلع فرق ساعات كل ليلة.
    """
    from app.utils.clock import local_now, to_utc
    from app.utils import verbal_order as vo

    with ward["app"].app_context():
        wall = local_now().replace(second=0, microsecond=0)
        typed = wall.strftime("%Y-%m-%dT%H:%M")

    ward["sign_in"]("doc").post(
        f"/patients/{ward['ids']['child']}/verbal-order",
        data={"text": "أمر بوقت مكتوب", "spoken_at": typed},
        follow_redirects=True)

    with ward["app"].app_context():
        row = vo.for_patient(ward["ids"]["child"])[0]
        assert row.spoken_at.replace(second=0, microsecond=0) == \
            to_utc(wall).replace(second=0, microsecond=0, tzinfo=None)


def test_every_word_of_the_record_is_written_in_both_languages(ward):
    from app.i18n import _load_translations, _lookup
    from app.models import VERBAL_CHANNELS

    tables = _load_translations()
    keys = [("verbal", f"channel_{c}") for c in VERBAL_CHANNELS]
    keys += [("verbal", f"step_{s}") for s in ("written", "read_back",
                                               "confirm")]
    keys += [("verbal", k) for k in (
        "title", "sub", "text", "channel", "ordered_by", "spoken_at",
        "write_down", "do_read_back", "do_confirm", "closed", "late",
        "timeframe", "receiver_cannot_confirm", "waiting_for_other")]
    keys += [("patients", "tab_verbal")]
    for lang in ("ar", "en"):
        for group, key in keys:
            assert _lookup(tables, lang, f"{group}.{key}"), \
                f"{lang}: {group}.{key} is missing"


def test_a_timeframe_of_zero_is_not_a_timeframe(ward):
    """صفر مش «فوراً» — صفر يعني **كل** أمر اتأخر.

    والخانة على الشاشة بتحفظ فاضي لما تتكتب صفر، بس اللي بيكتب في
    الإعدادات على طول بيعدّي منها — والتاني هو اللي بيحصل لما حد
    بيصلّح داتابيز بايده.
    """
    from app.models import Setting
    from app.utils import verbal_order as vo

    _order(ward)
    with ward["app"].app_context():
        Setting.set(vo.TIMEFRAME_SETTING, "0")
        ward["db"].session.commit()

        assert vo.timeframe_minutes() is None
        assert vo.late() == []
