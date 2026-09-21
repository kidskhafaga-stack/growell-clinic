"""الاستشارة والرأي التاني — GAHAR `ACT.10` و`ACT.09`.

**وتالت مرة الكتاب بيعدّد نفس القايمة مرتين** بعد قايمة الطوارئ وقايمتي
التخدير والتسكين. حطّ سياسة المعيارين جنب بعض: معايير · توصيل الطلب ·
مهلة الرد · تفاصيل الرد — نفس القايمة، **والفرق بندين بالظبط**: الاستشارة
فيها العجلة، والرأي التاني فيه «اللي بيتعمل لما المستشفى ما تقدرش».

ونية `ACT.10` بتسمّي أشكال الفشل بالنص — طلب **متأخّر** · من غير
**خلفية كافية** · **السبب مش مكتوب بوضوح** · **رد متأخّر** — والملف ده
بيثبّت إن كل واحد فيهم ليه إجابة.
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
        other = User(username="doc2", full_name="استشاري", role="doctor",
                     is_active=True)
        other.set_password("secret")
        clinic["db"].session.add(other)
        clinic["db"].session.commit()
        clinic["ids"]["consultant"] = other.id
    return clinic


def _ask(ward, kind="consultation", reason="تشنّج متكرر محتاج رأي مخ وأعصاب",
         **fields):
    from app.models import Patient, User
    from app.utils import opinions

    with ward["app"].app_context():
        patient = ward["db"].session.get(Patient, ward["ids"]["child"])
        doc = ward["db"].session.get(User, ward["ids"]["doctor"])
        row = opinions.ask(patient, kind, reason, user=doc, **fields)
        ward["db"].session.commit()
        return row.id


def _row(ward, oid):
    from app.models import Opinion

    return ward["db"].session.get(Opinion, oid)


# ------------------------- القايمتين نفس القايمة، والفرق بندين ----
def test_the_two_lists_differ_by_exactly_two_items(ward):
    """اللي المعيارين بيقولوه لما تحطّهم جنب بعض — والسبب اللي خلّى ده
    سجل واحد مش اتنين."""
    from app.models import opinion_items

    consult = set(opinion_items("consultation"))
    second = set(opinion_items("second_opinion"))

    assert consult - second == {"urgency"}
    assert second - consult == {"alternative"}
    assert len(consult & second) == 4


def test_a_consultation_is_asked_for_its_own_one(ward):
    from app.utils import opinions

    oid = _ask(ward, "consultation")

    with ward["app"].app_context():
        assert "urgency" in opinions.missing(_row(ward, oid))
        assert "alternative" not in opinions.missing(_row(ward, oid))


def test_a_second_opinion_is_never_asked_about_urgency(ward):
    """العجلة بند الاستشارة لوحدها — وعمود معناه «مش منطبق» بيبان زي
    «محدّش قال» لو اتحسب."""
    from app.utils import opinions

    oid = _ask(ward, "second_opinion")

    with ward["app"].app_context():
        assert "urgency" not in opinions.missing(_row(ward, oid))


def test_urgency_written_on_a_second_opinion_is_dropped(ward):
    oid = _ask(ward, "second_opinion", urgency="urgent")

    with ward["app"].app_context():
        assert _row(ward, oid).urgency is None


def test_a_kind_the_record_cannot_draw_is_refused(ward):
    from app.models import Patient
    from app.utils import opinions

    with ward["app"].app_context():
        patient = ward["db"].session.get(Patient, ward["ids"]["child"])
        with pytest.raises(ValueError):
            opinions.ask(patient, "third_opinion", "أي سبب")


def test_an_urgency_the_record_cannot_draw_is_refused(ward):
    from app.models import Patient
    from app.utils import opinions

    with ward["app"].app_context():
        patient = ward["db"].session.get(Patient, ward["ids"]["child"])
        with pytest.raises(ValueError):
            opinions.ask(patient, "consultation", "سبب", urgency="whenever")


# --------------------- السبب مطلوب، لأن النية سمّت غيابه ----
def test_a_request_with_no_reason_is_refused(ward):
    """*"the reason for consultation is **not clearly stated**"* — شكل
    فشل مسمّى بالنص، فالطلب من غيره مرفوض عند الباب."""
    from app.models import Patient
    from app.utils import opinions

    with ward["app"].app_context():
        patient = ward["db"].session.get(Patient, ward["ids"]["child"])
        for empty in ("", "   ", "\n"):
            with pytest.raises(ValueError):
                opinions.ask(patient, "consultation", empty)


def test_a_request_with_no_child_is_refused(ward):
    from app.utils import opinions

    with ward["app"].app_context():
        with pytest.raises(ValueError):
            opinions.ask(None, "consultation", "سبب")


def test_the_missing_background_is_named(ward):
    """*"not accompanied by sufficient **background information**"* —
    تاني شكل فشل مسمّى، والشاشة بتقوله باسمه."""
    from app.utils import opinions

    oid = _ask(ward, "consultation")

    with ward["app"].app_context():
        assert "background" in opinions.missing(_row(ward, oid))

        opinions.describe(_row(ward, oid), background="تشنّج من ٣ شهور")
        ward["db"].session.commit()
        assert "background" not in opinions.missing(_row(ward, oid))


# ------------------------------------------- الرد ----
def test_a_time_with_no_words_is_not_an_answer(ward):
    """دليل ٥ بيطلب تبادل **comprehensive** — وصف بيقول «اترد عليه
    الساعة تلاتة» ومفيش كلام مش بيجاوب حاجة."""
    from app.utils import opinions

    oid = _ask(ward)

    with ward["app"].app_context():
        with pytest.raises(ValueError):
            opinions.answer(_row(ward, oid), "   ")
        assert _row(ward, oid).responded_at is None
        assert not _row(ward, oid).answered


def test_an_answer_needs_both_the_time_and_the_words(ward):
    from app.models import User
    from app.utils import opinions

    oid = _ask(ward)
    with ward["app"].app_context():
        who = ward["db"].session.get(User, ward["ids"]["consultant"])
        opinions.answer(_row(ward, oid), "رسم مخ وبدء علاج", user=who)
        ward["db"].session.commit()

        row = _row(ward, oid)
        assert row.answered
        assert row.responded_at is not None
        assert row.responded_by_id == who.id


def test_a_responder_from_outside_keeps_their_name(ward):
    from app.utils import opinions

    oid = _ask(ward, "second_opinion")
    with ward["app"].app_context():
        opinions.answer(_row(ward, oid), "رأي مطابق", name="د. من بره")
        ward["db"].session.commit()

        row = _row(ward, oid)
        assert row.responder_name("ar") == "د. من بره"
        assert row.responded_by_id is None


def test_a_second_answer_keeps_the_first_moment(ward):
    from app.utils import opinions

    oid = _ask(ward)
    early = datetime.utcnow() - timedelta(hours=2)
    with ward["app"].app_context():
        opinions.answer(_row(ward, oid), "أول رد", at=early)
        ward["db"].session.commit()
        opinions.answer(_row(ward, oid), "تفصيل زيادة")
        ward["db"].session.commit()

        row = _row(ward, oid)
        assert row.responded_at == early
        assert row.response == "تفصيل زيادة"


# ------------------- البديل بند اللي ما جاش، مش بند دايماً ----
def test_a_second_opinion_that_came_back_is_not_missing_an_alternative(ward):
    """**(و) شرطية.** نصّها *when the hospital **can't** provide* —
    فطلب رجع برأي مش ناقصه بديل، وعدّه دايماً كان هيخلّي كل رأي تاني
    كامل يبان ناقص."""
    from app.utils import opinions

    oid = _ask(ward, "second_opinion", asked_of="جراحة أطفال",
               background="حالة معروفة من سنة")
    with ward["app"].app_context():
        opinions.answer(_row(ward, oid), "الرأي التاني بيأكّد التشخيص")
        ward["db"].session.commit()

        assert opinions.missing(_row(ward, oid)) == []


def test_but_one_that_never_came_back_is_missing_both(ward):
    """ما جاش رأي ومفيش بديل اتقال — **ودي بالظبط الحالة اللي المعيار
    عايز حد يشوفها.**"""
    from app.utils import opinions

    oid = _ask(ward, "second_opinion", asked_of="جراحة أطفال",
               background="حالة معروفة")

    with ward["app"].app_context():
        gaps = opinions.missing(_row(ward, oid))
        assert "response" in gaps
        assert "alternative" in gaps


def test_telling_the_family_the_alternative_answers_that_half(ward):
    """دليل ٤: لما المستشفى ما تقدرش، الأهل بيتقالهم على البدايل."""
    from app.utils import opinions

    oid = _ask(ward, "second_opinion", asked_of="جراحة أطفال",
               background="حالة معروفة")
    with ward["app"].app_context():
        opinions.describe(_row(ward, oid),
                          alternative="اتحوّلوا لمستشفى الجامعة")
        ward["db"].session.commit()

        assert opinions.missing(_row(ward, oid)) == ["response"]


# ------------------------------------------- المهلة ----
def test_nothing_is_overdue_until_the_clinic_writes_the_timeframe(ward):
    """نص المعيار بيقول *within a **predefined** time frame* — فالمستشفى
    بتعرّفها والبرنامج ما بيخترعش رقم."""
    from app.utils import opinions

    _ask(ward, at=datetime.utcnow() - timedelta(hours=9))

    with ward["app"].app_context():
        assert opinions.timeframe_minutes() is None
        assert opinions.overdue() == []


def test_writing_the_timeframe_is_what_turns_it_on(ward):
    from app.models import Setting
    from app.utils import opinions

    oid = _ask(ward, at=datetime.utcnow() - timedelta(hours=9))
    with ward["app"].app_context():
        Setting.set(opinions.TIMEFRAME_SETTING, "120")
        ward["db"].session.commit()

        assert opinions.timeframe_minutes() == 120
        assert [r.id for r in opinions.overdue()] == [oid]


def test_a_zero_timeframe_is_not_a_timeframe(ward):
    """صفر يعني **كل** طلب اتأخر."""
    from app.models import Setting
    from app.utils import opinions

    _ask(ward)
    with ward["app"].app_context():
        Setting.set(opinions.TIMEFRAME_SETTING, "0")
        ward["db"].session.commit()

        assert opinions.timeframe_minutes() is None
        assert opinions.overdue() == []


def test_an_answered_request_is_never_overdue(ward):
    from app.models import Setting
    from app.utils import opinions

    oid = _ask(ward, at=datetime.utcnow() - timedelta(hours=9))
    with ward["app"].app_context():
        Setting.set(opinions.TIMEFRAME_SETTING, "60")
        opinions.answer(_row(ward, oid), "اترد عليه")
        ward["db"].session.commit()

        assert opinions.overdue() == []


def test_a_request_inside_the_timeframe_is_not_overdue(ward):
    from app.models import Setting
    from app.utils import opinions

    _ask(ward, at=datetime.utcnow() - timedelta(minutes=10))
    with ward["app"].app_context():
        Setting.set(opinions.TIMEFRAME_SETTING, "60")
        ward["db"].session.commit()

        assert opinions.overdue() == []


def test_the_waiting_time_stops_at_the_answer(ward):
    from app.utils import opinions

    oid = _ask(ward, at=datetime.utcnow() - timedelta(hours=10))
    with ward["app"].app_context():
        opinions.answer(_row(ward, oid), "رد",
                        at=datetime.utcnow() - timedelta(hours=7))
        ward["db"].session.commit()

        assert _row(ward, oid).waiting_minutes == 3 * 60


# ------------------------------------------- القوايم ----
def test_the_oldest_waiting_request_comes_first(ward):
    """أطول واحد مستنّي هو اللي المعيار قلقان منه."""
    from app.utils import opinions

    old = _ask(ward, at=datetime.utcnow() - timedelta(hours=6))
    new = _ask(ward, at=datetime.utcnow() - timedelta(hours=1))

    with ward["app"].app_context():
        assert [r.id for r in opinions.waiting()] == [old, new]


def test_an_unanswered_request_is_not_on_the_incomplete_list(ward):
    """طلب لسه مستنّي ناقصه الرد بالبداهة — وعدّه هناك بيخلط «لسه»
    بـ«ناقص»، وبيغرق القايمة اللي المفروض تتقفل."""
    from app.utils import opinions

    _ask(ward)

    with ward["app"].app_context():
        assert opinions.incomplete() == []
        assert len(opinions.waiting()) == 1


def test_an_answered_request_with_a_gap_is(ward):
    from app.utils import opinions

    oid = _ask(ward, "consultation")
    with ward["app"].app_context():
        opinions.answer(_row(ward, oid), "الرد")
        ward["db"].session.commit()

        short = opinions.incomplete()
        assert [i["record"].id for i in short] == [oid]
        assert set(short[0]["missing"]) == {"background", "asked_of",
                                            "urgency"}


def test_a_complete_one_is_not(ward):
    from app.utils import opinions

    oid = _ask(ward, "consultation", asked_of="مخ وأعصاب",
               background="تشنّج من ٣ شهور", urgency="urgent")
    with ward["app"].app_context():
        opinions.answer(_row(ward, oid), "رسم مخ وبدء علاج")
        ward["db"].session.commit()

        assert opinions.missing(_row(ward, oid)) == []
        assert opinions.incomplete() == []


def test_another_childs_request_is_not_this_ones(ward):
    from app.models import Patient, User
    from app.utils import opinions
    from app.utils.clock import local_today

    with ward["app"].app_context():
        other = Patient(patient_number="OP-2", full_name="طفل تاني",
                        gender="male", is_active=True,
                        date_of_birth=local_today() - timedelta(days=800))
        ward["db"].session.add(other)
        ward["db"].session.flush()
        doc = ward["db"].session.get(User, ward["ids"]["doctor"])
        opinions.ask(other, "consultation", "سبب", user=doc)
        ward["db"].session.commit()

        assert opinions.for_patient(ward["ids"]["child"]) == []
        assert len(opinions.for_patient(other.id)) == 1


def test_a_part_save_does_not_wipe_what_it_did_not_send(ward):
    from app.utils import opinions

    oid = _ask(ward, "consultation", asked_of="مخ وأعصاب",
               background="تشنّج من ٣ شهور")
    with ward["app"].app_context():
        opinions.describe(_row(ward, oid), urgency="urgent")
        ward["db"].session.commit()

        row = _row(ward, oid)
        assert row.urgency == "urgent"
        assert row.asked_of == "مخ وأعصاب"
        assert row.background == "تشنّج من ٣ شهور"


# ================================================ الباب ====
def test_a_child_with_no_request_has_no_tab(ward):
    page = ward["sign_in"]("doc").get(
        f"/patients/{ward['ids']['child']}").get_data(as_text=True)

    assert "'opinions','tab_opinions'" not in page
    assert 'data-opinion="' not in page


def test_the_file_shows_the_request_and_what_it_is_waiting_for(ward):
    oid = _ask(ward, "consultation")

    page = ward["sign_in"]("doc").get(
        f"/patients/{ward['ids']['child']}").get_data(as_text=True)

    assert f'data-opinion="{oid}"' in page
    assert "data-waiting" in page
    assert 'data-missing="response"' in page


def test_the_screen_asks_and_the_reason_is_required(ward):
    from app.utils import opinions

    client = ward["sign_in"]("doc")
    client.post(f"/patients/{ward['ids']['child']}/opinion", data={
        "kind": "consultation", "reason": "تشنّج متكرر",
        "asked_of": "مخ وأعصاب", "urgency": "urgent"},
        follow_redirects=True)

    with ward["app"].app_context():
        rows = opinions.for_patient(ward["ids"]["child"])
        assert len(rows) == 1
        assert rows[0].urgency == "urgent"

    # ومن غير سبب ما بيتسجّلش.
    client.post(f"/patients/{ward['ids']['child']}/opinion", data={
        "kind": "consultation", "reason": "   "}, follow_redirects=True)

    with ward["app"].app_context():
        assert len(opinions.for_patient(ward["ids"]["child"])) == 1


def test_the_screen_refuses_a_response_with_no_words(ward):
    """الشاشة والسجل الاتنين — حارس من ناحية واحدة نص قاعدة."""
    from app.utils import opinions

    oid = _ask(ward)

    ward["sign_in"]("doc").post(f"/patients/opinion/{oid}/answer",
                                data={"response": "  "},
                                follow_redirects=True)

    with ward["app"].app_context():
        assert not _row(ward, oid).answered
        assert "response" in opinions.missing(_row(ward, oid))


def test_answering_from_the_screen_closes_that_half(ward):
    from app.utils import opinions

    oid = _ask(ward)

    ward["sign_in"]("doc").post(
        f"/patients/opinion/{oid}/answer",
        data={"response": "رسم مخ وبدء علاج", "responded_by_name": "د. بره"},
        follow_redirects=True)

    with ward["app"].app_context():
        row = _row(ward, oid)
        assert row.answered
        assert row.responder_name("ar") == "د. بره"
        assert "response" not in opinions.missing(row)


def test_the_gap_boxes_fill_the_named_items(ward):
    from app.utils import opinions

    oid = _ask(ward, "consultation")
    client = ward["sign_in"]("doc")

    page = client.get(f"/patients/{ward['ids']['child']}").get_data(
        as_text=True)
    assert "data-opinion-gaps" in page
    for gap in ("background", "asked_of", "urgency"):
        assert f'data-missing="{gap}"' in page

    client.post(f"/patients/opinion/{oid}/fill", follow_redirects=True, data={
        "background": "تشنّج من ٣ شهور", "asked_of": "مخ وأعصاب",
        "urgency": "routine"})

    with ward["app"].app_context():
        assert opinions.missing(_row(ward, oid)) == ["response"]


def test_the_urgency_box_never_appears_on_a_second_opinion(ward):
    """خانة معناها «مش منطبق» بتتملّى غلط."""
    _ask(ward, "second_opinion")

    page = ward["sign_in"]("doc").get(
        f"/patients/{ward['ids']['child']}").get_data(as_text=True)

    assert 'data-missing="urgency"' not in page
    assert 'data-missing="background"' in page


def test_the_board_shows_a_waiting_request_even_with_no_timeframe(ward):
    """**طلب محدّش رد عليه مايبقاش مخفي علشان المستشفى ما كتبتش
    سياستها لسه.**"""
    oid = _ask(ward, at=datetime.utcnow() - timedelta(hours=4))

    page = ward["sign_in"]("doc").get("/beds/watch").get_data(as_text=True)

    assert "data-opinions-watch" in page
    assert f'data-opinion-waiting="{oid}"' in page
    assert "data-opinion-overdue" not in page       # مفيش مهلة لسه


def test_and_marks_it_late_once_the_clinic_sets_one(ward):
    from app.models import Setting
    from app.utils import opinions

    oid = _ask(ward, at=datetime.utcnow() - timedelta(hours=4))
    with ward["app"].app_context():
        Setting.set(opinions.TIMEFRAME_SETTING, "60")
        ward["db"].session.commit()

    page = ward["sign_in"]("doc").get("/beds/watch").get_data(as_text=True)

    assert f'data-opinion-overdue="{oid}"' in page
    assert f'data-opinion-waiting="{oid}"' in page


def test_an_answered_request_leaves_the_board(ward):
    from app.utils import opinions

    oid = _ask(ward, "consultation", asked_of="مخ وأعصاب",
               background="تشنّج", urgency="routine")
    with ward["app"].app_context():
        opinions.answer(_row(ward, oid), "رسم مخ")
        ward["db"].session.commit()

    page = ward["sign_in"]("doc").get("/beds/watch").get_data(as_text=True)

    assert "data-opinions-watch" not in page


def test_the_timeframe_has_a_box_on_the_settings_screen(ward):
    page = ward["sign_in"]("boss").get("/settings/risks").get_data(
        as_text=True)

    assert "data-consultation-timeframe-policy" in page
    assert 'name="consultation_minutes"' in page


def test_writing_the_timeframe_from_the_screen_arms_it(ward):
    from app.utils import opinions

    ward["sign_in"]("boss").post("/settings/risks", data={
        "consultation_minutes": "90"}, follow_redirects=True)

    with ward["app"].app_context():
        assert opinions.timeframe_minutes() == 90


def test_every_word_of_both_lists_is_written_in_both_languages(ward):
    from app.i18n import _load_translations, _lookup
    from app.models import (OPINION_KINDS, OPINION_URGENCIES, opinion_items)

    tables = _load_translations()
    keys = [("opinions", f"kind_{k}") for k in OPINION_KINDS]
    keys += [("opinions", f"urgency_{u}") for u in OPINION_URGENCIES]
    items = set(opinion_items("consultation")) | set(
        opinion_items("second_opinion"))
    keys += [("opinions", i) for i in sorted(items)]
    keys += [("opinions", k) for k in (
        "title", "sub", "overdue_hint", "answered_badge", "waiting", "ask",
        "answer", "asked", "answered", "saved", "needs_words", "not_saved",
        "timeframe")]
    keys += [("patients", "tab_opinions")]
    for lang in ("ar", "en"):
        for group, key in keys:
            assert _lookup(tables, lang, f"{group}.{key}"), \
                f"{lang}: {group}.{key} is missing"


def test_who_gave_the_opinion_is_not_who_typed_it(ward):
    """**نسبة رأي بره لدكتور جوّه.**

    ممرضة بتكتب رد استشاري من بره مش هي اللي قالت الرأي — وعمود واحد
    للاتنين بيخلّي الملف يقول إن اللي جوّه هو اللي قال. نفس الفرق اللي
    `Consent` بيعمله بين «مين شرح» و«مين كتب الصف».
    """
    from app.models import User
    from app.utils import opinions

    oid = _ask(ward, "second_opinion")
    with ward["app"].app_context():
        nurse = ward["db"].session.get(User, ward["ids"]["doctor"])
        opinions.answer(_row(ward, oid), "الرأي التاني بيأكّد",
                        user=nurse, name="د. استشاري من بره")
        ward["db"].session.commit()

        row = _row(ward, oid)
        assert row.responder_name("ar") == "د. استشاري من بره"
        assert row.responded_by_id is None      # مش هو اللي قال
        assert row.recorded_by_id == nurse.id   # هو اللي كتب


def test_a_consultant_inside_answers_as_themselves(ward):
    """ولما اللي رد مستخدم في البرنامج، هو اللي قال وهو اللي كتب."""
    from app.models import User
    from app.utils import opinions

    oid = _ask(ward)
    with ward["app"].app_context():
        who = ward["db"].session.get(User, ward["ids"]["consultant"])
        opinions.answer(_row(ward, oid), "رسم مخ", user=who)
        ward["db"].session.commit()

        row = _row(ward, oid)
        assert row.responded_by_id == who.id
        assert row.recorded_by_id == who.id
        assert row.responded_by_name is None


def test_a_time_written_straight_onto_the_row_is_still_not_an_answer(ward):
    """**حارس من ناحية واحدة نص قاعدة.**

    `answer` بترفض رد فاضي، فالخاصية عمرها ما بتشوف وقت من غير نص من
    الشاشة. بس صف بيتكتب من استيراد أو تصليح في الداتابيز ممكن يوصلها
    — والخاصية هي التانية لازم تمسكها.
    """
    from app.utils import opinions

    oid = _ask(ward)

    with ward["app"].app_context():
        row = _row(ward, oid)
        row.responded_at = datetime.utcnow()      # مش من الشاشة
        ward["db"].session.commit()

        assert not _row(ward, oid).answered
        assert "response" in opinions.missing(_row(ward, oid))


def test_and_such_a_row_is_still_on_the_waiting_list(ward):
    """**تعريفين لنفس الكلمة بيفرقوا.**

    القايمة كانت بتفلتر على الوقت لوحده، فصف زي ده كان بيختفي منها وهو
    مش مردود عليه بحسب الخاصية — يعني بيقع من الشقّين.
    """
    from app.utils import opinions

    oid = _ask(ward, at=datetime.utcnow() - timedelta(hours=3))

    with ward["app"].app_context():
        row = _row(ward, oid)
        row.responded_at = datetime.utcnow()
        ward["db"].session.commit()

        assert [r.id for r in opinions.waiting()] == [oid]
        assert opinions.incomplete() == []          # ولا كامل ولا مردود
