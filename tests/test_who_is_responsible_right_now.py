"""الطبيب المسؤول — GAHAR `ACT.07`.

النية بتسمّي العاقبة بالنص:

> **Misunderstandings about who** among the healthcare team **is responsible**
> for a patient's care may compromise that care and result in an adverse
> event and increased medico-legal risk.

**والبرنامج كان بيقول نص الإجابة.** `Admission.doctor_id` موجود وnullable،
يعني ممرضة بتدخّل طفل والعمود بيفضل فاضي طول الإقامة ومفيش شاشة بتقول.

**وحتى لو اتملا، العمود مش الشكل الصح.** المعيار بيقول *at a specific point
in time* — وعمود واحد بيتكتب فوقه أول ما المسؤولية تتنقل، فسؤال «مين كان
مسؤول يوم التلات» ما بقاش ليه إجابة. **والبرنامج خد القرار ده قبل كده**
في نفس الجدول: `BedStay` فترات مش عمود، وبنفس الحُجّة بالحرف.
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

MODULE = "beds"


@pytest.fixture()
def stay(clinic):
    """طفل داخل، ومعاه طبيبين في العيادة."""
    from app.models import Admission, Setting, User

    with clinic["app"].app_context():
        Setting.set(f"mod_enabled:{MODULE}", "1")
        second = User(username="doc2", full_name="د. تاني", role="doctor",
                      is_active=True)
        second.set_password("secret")
        clinic["db"].session.add(second)
        row = Admission(patient_id=clinic["ids"]["child"])
        clinic["db"].session.add(row)
        clinic["db"].session.commit()
        clinic["stay"] = row.id
        clinic["doc2"] = second.id
    return clinic


def _doc(clinic, key="doctor"):
    from app.models import User

    return User.query.get(clinic["ids"][key] if key in clinic["ids"]
                          else clinic[key])


def _stay(clinic):
    from app.models import Admission

    return Admission.query.get(clinic["stay"])


# ============ الفراغ اللي المصفوفة سمّته ============
def test_a_stay_admitted_by_a_nurse_has_nobody_responsible(stay):
    """**ودي مش حالة نظرية.** `beds.admit` بيبعت `doctor_id` بس لما
    اللي بيدخّل يكون دكتور — وممرضة بتدخّل طفل بتسيب الخانة فاضية."""
    from app.utils import responsibility as who

    with stay["app"].app_context():
        assert who.current(stay["stay"]) is None
        assert [s.id for s in who.without_mrp()] == [stay["stay"]]


def test_assigning_one_closes_the_gap(stay):
    from app.utils import responsibility as who

    with stay["app"].app_context():
        who.assign(_stay(stay), _doc(stay), user=_doc(stay))
        stay["db"].session.commit()

        assert who.current(stay["stay"]).doctor_id == stay["ids"]["doctor"]
        assert who.without_mrp() == []


def test_a_stay_written_before_this_table_is_not_a_gap(stay):
    """عيادة شغّالة عندها إقامات مكتوب فيها `Admission.doctor_id` —
    ودي مش ناقصة. عدّها كان هيملا الشاشة بصفوف اتعملت صح."""
    from app.utils import responsibility as who

    with stay["app"].app_context():
        row = _stay(stay)
        row.doctor_id = stay["ids"]["doctor"]
        stay["db"].session.commit()

        assert who.without_mrp() == []
        assert row.responsible_doctor.id == stay["ids"]["doctor"]


def test_a_discharged_stay_is_nobody_s_gap(stay):
    from app.utils import responsibility as who

    with stay["app"].app_context():
        _stay(stay).discharged_at = datetime.utcnow()
        stay["db"].session.commit()

        assert who.without_mrp() == []


def test_a_period_with_no_doctor_is_refused(stay):
    """صف مسؤولية من غير طبيب هو نفس الفراغ اللي الجدول اتعمل علشانه."""
    from app.utils import responsibility as who

    with stay["app"].app_context():
        with pytest.raises(ValueError):
            who.assign(_stay(stay), None)
        with pytest.raises(ValueError):
            who.assign(None, _doc(stay))


def test_assigning_twice_is_refused(stay):
    """نقل المسؤولية ليه باب تاني — بيطلب الخطوات المعلّقة وتوقيع الطرفين."""
    from app.utils import responsibility as who

    with stay["app"].app_context():
        who.assign(_stay(stay), _doc(stay))
        stay["db"].session.commit()

        with pytest.raises(ValueError):
            who.assign(_stay(stay), _doc(stay, "doc2"))


# ============ المسؤولية فترات، مش عمود ============
def test_the_record_says_who_was_responsible_on_a_given_day(stay):
    """**ودي السؤال اللي الجدول اتعمل علشانه.**

    عمود واحد بيتكتب فوقه بيجاوب «مين دلوقتي» وبس — والسؤال ده بيتسأل
    بعد شهور، ووقتها العمود بيقول اسم التاني على كل يوم في الإقامة.
    """
    from app.utils import responsibility as who

    start = datetime.utcnow() - timedelta(days=6)
    swap = datetime.utcnow() - timedelta(days=2)

    with stay["app"].app_context():
        who.assign(_stay(stay), _doc(stay), at=start)
        stay["db"].session.commit()
        who.hand_over(_stay(stay), _doc(stay, "doc2"), pending="مستني الصورة")
        who.accept(_stay(stay), _doc(stay, "doc2"), at=swap)
        stay["db"].session.commit()

        early = who.responsible_at(stay["stay"],
                                   datetime.utcnow() - timedelta(days=4))
        late = who.responsible_at(stay["stay"],
                                  datetime.utcnow() - timedelta(days=1))
        assert early.doctor_id == stay["ids"]["doctor"]
        assert late.doctor_id == stay["doc2"]
        assert who.current(stay["stay"]).doctor_id == stay["doc2"]


def test_the_history_is_oldest_first(stay):
    """ده سجل مش قايمة انتظار."""
    from app.utils import responsibility as who

    with stay["app"].app_context():
        who.assign(_stay(stay), _doc(stay))
        stay["db"].session.commit()
        who.hand_over(_stay(stay), _doc(stay, "doc2"))
        who.accept(_stay(stay), _doc(stay, "doc2"))
        stay["db"].session.commit()

        rows = who.history(stay["stay"])
        assert [r.doctor_id for r in rows] == [stay["ids"]["doctor"],
                                               stay["doc2"]]


def test_a_moment_before_anybody_was_responsible_has_no_answer(stay):
    """ومفيش اختراع: الوقت اللي محدّش كان مسؤول فيه بيرجّع لا حاجة."""
    from app.utils import responsibility as who

    with stay["app"].app_context():
        who.assign(_stay(stay), _doc(stay))
        stay["db"].session.commit()

        assert who.responsible_at(stay["stay"],
                                  datetime.utcnow() - timedelta(days=3)) is None


# ============ التسليم: طرفين مش واحد ============
def test_handing_over_does_not_move_the_responsibility_yet(stay):
    """**دي الحتة كلها.** (د) بيقول *between the transfer of responsibility
    **parties*** — بالجمع. والأول بيفضل مسؤول لحد ما التاني يقول خدتها،
    لأن إقامة من غير مسؤول بين التوقيعين هي بالظبط الفراغ اللي المعيار
    موجود علشانه."""
    from app.utils import responsibility as who

    with stay["app"].app_context():
        who.assign(_stay(stay), _doc(stay))
        stay["db"].session.commit()
        who.hand_over(_stay(stay), _doc(stay, "doc2"), pending="مستني الصورة")
        stay["db"].session.commit()

        live = who.current(stay["stay"])
        assert live.doctor_id == stay["ids"]["doctor"]   # لسه هو
        assert live.handed_at is not None
        assert live.handed_to_id == stay["doc2"]
        assert live.handed_over is False
        assert live.in_limbo is True


def test_a_handover_nobody_accepted_is_the_one_that_looks_done(stay):
    """فيه وقت، وفيه خطوات معلّقة، وفيه اسم اللي سلّم. اللي ناقصه إن
    التاني قال «خدتها»."""
    from app.utils import responsibility as who

    with stay["app"].app_context():
        who.assign(_stay(stay), _doc(stay))
        stay["db"].session.commit()
        who.hand_over(_stay(stay), _doc(stay, "doc2"))
        stay["db"].session.commit()

        assert [r.admission_id for r in who.in_limbo()] == [stay["stay"]]


def test_accepting_closes_the_first_period_and_opens_the_next(stay):
    from app.utils import responsibility as who

    with stay["app"].app_context():
        who.assign(_stay(stay), _doc(stay))
        stay["db"].session.commit()
        who.hand_over(_stay(stay), _doc(stay, "doc2"))
        who.accept(_stay(stay), _doc(stay, "doc2"))
        stay["db"].session.commit()

        rows = who.history(stay["stay"])
        assert len(rows) == 2
        assert rows[0].until is not None
        assert rows[0].handed_over is True
        assert rows[0].in_limbo is False
        assert rows[1].until is None
        assert who.in_limbo() == []


def test_the_outgoing_physician_cannot_accept_from_themselves(stay):
    """توقيع واحد على الطرفين مش تسليم — نفس قاعدة `VerbalOrder`."""
    from app.utils import responsibility as who

    with stay["app"].app_context():
        who.assign(_stay(stay), _doc(stay))
        stay["db"].session.commit()
        who.hand_over(_stay(stay), _doc(stay, "doc2"))
        stay["db"].session.commit()

        with pytest.raises(ValueError):
            who.accept(_stay(stay), _doc(stay))


def test_who_it_was_offered_to_and_who_took_it_are_two_columns(stay):
    """ورديّة بتتغيّر، والدكتور اللي اتعرضت عليه ممكن يبقى مش هو اللي
    استلم. عمود واحد كان هيخلّي السجل ينسب الاستلام للغلط."""
    from app.models import User
    from app.utils import responsibility as who

    with stay["app"].app_context():
        third = User(username="doc3", full_name="د. تالت", role="doctor",
                     is_active=True)
        third.set_password("secret")
        stay["db"].session.add(third)
        stay["db"].session.commit()

        who.assign(_stay(stay), _doc(stay))
        stay["db"].session.commit()
        who.hand_over(_stay(stay), _doc(stay, "doc2"))
        who.accept(_stay(stay), third)
        stay["db"].session.commit()

        closed = who.history(stay["stay"])[0]
        assert closed.handed_to_id == stay["doc2"]
        assert closed.accepted_by_id == third.id
        assert who.current(stay["stay"]).doctor_id == third.id


def test_handing_over_to_yourself_is_refused(stay):
    from app.utils import responsibility as who

    with stay["app"].app_context():
        who.assign(_stay(stay), _doc(stay))
        stay["db"].session.commit()

        with pytest.raises(ValueError):
            who.hand_over(_stay(stay), _doc(stay))


def test_handing_over_twice_is_refused(stay):
    from app.utils import responsibility as who

    with stay["app"].app_context():
        who.assign(_stay(stay), _doc(stay))
        stay["db"].session.commit()
        who.hand_over(_stay(stay), _doc(stay, "doc2"))
        stay["db"].session.commit()

        with pytest.raises(ValueError):
            who.hand_over(_stay(stay), _doc(stay, "doc2"))


def test_nothing_can_be_handed_over_before_anybody_is_responsible(stay):
    from app.utils import responsibility as who

    with stay["app"].app_context():
        with pytest.raises(ValueError):
            who.hand_over(_stay(stay), _doc(stay))
        with pytest.raises(ValueError):
            who.accept(_stay(stay), _doc(stay))


def test_the_pending_steps_travel_with_it(stay):
    """(ج) — **والخطوات المعلّقة هي الحاجة الوحيدة اللي مفيش جدول تاني
    بيعرفها.** التقييم والخطة في `CarePlan` وقايمة المشاكل."""
    from app.utils import responsibility as who

    with stay["app"].app_context():
        who.assign(_stay(stay), _doc(stay))
        stay["db"].session.commit()
        who.hand_over(_stay(stay), _doc(stay, "doc2"),
                      pending="مستني صورة الصدر وصورة الدم")
        who.accept(_stay(stay), _doc(stay, "doc2"))
        stay["db"].session.commit()

        assert who.history(stay["stay"])[0].pending.startswith("مستني صورة")


# ============ الشاشات ============
def test_the_stay_page_says_nobody_is_responsible_and_offers_the_box(stay):
    """اللي بيقرا الفراغ هو اللي بيقفله."""
    page = stay["sign_in"]("boss").get(
        f"/beds/admission/{stay['stay']}").get_data(as_text=True)

    assert "data-mrp-none" in page
    assert "data-mrp-assign" in page


def test_assigning_from_the_screen_works(stay):
    from app.utils import responsibility as who

    client = stay["sign_in"]("boss")
    client.post(f"/beds/stay/{stay['stay']}/responsible", follow_redirects=True,
                data={"doctor_id": stay["ids"]["doctor"]})

    with stay["app"].app_context():
        assert who.current(stay["stay"]).doctor_id == stay["ids"]["doctor"]


def test_the_screen_marks_a_handover_nobody_accepted(stay):
    from app.utils import responsibility as who

    with stay["app"].app_context():
        who.assign(_stay(stay), _doc(stay))
        stay["db"].session.commit()
        who.hand_over(_stay(stay), _doc(stay, "doc2"), pending="مستني الصورة")
        stay["db"].session.commit()

    page = stay["sign_in"]("boss").get(
        f"/beds/admission/{stay['stay']}").get_data(as_text=True)

    assert "data-mrp-limbo" in page
    assert "data-mrp-accept" in page
    assert "data-mrp-pending" in page
    assert "مستني الصورة" in page


def test_the_ward_board_shows_both(stay):
    from app.utils import responsibility as who
    from app.models import Admission, Patient

    with stay["app"].app_context():
        from datetime import date
        other = Patient(full_name="طفل تاني", patient_number="P-MRP",
                        gender="male", date_of_birth=date(2024, 1, 1))
        stay["db"].session.add(other)
        stay["db"].session.flush()
        second = Admission(patient_id=other.id)
        stay["db"].session.add(second)
        stay["db"].session.commit()
        sid = second.id

        who.assign(second, _doc(stay))
        stay["db"].session.commit()
        who.hand_over(second, _doc(stay, "doc2"))
        stay["db"].session.commit()

    page = stay["sign_in"]("boss").get("/beds/watch").get_data(as_text=True)

    assert "data-mrp-watch" in page
    assert f'data-mrp-missing="{stay["stay"]}"' in page
    assert "data-mrp-limbo-row" in page
    assert str(sid) in page


def test_the_history_is_on_the_stay_page(stay):
    from app.utils import responsibility as who

    with stay["app"].app_context():
        who.assign(_stay(stay), _doc(stay))
        stay["db"].session.commit()
        who.hand_over(_stay(stay), _doc(stay, "doc2"))
        who.accept(_stay(stay), _doc(stay, "doc2"))
        stay["db"].session.commit()

    page = stay["sign_in"]("boss").get(
        f"/beds/admission/{stay['stay']}").get_data(as_text=True)

    assert "data-mrp-history" in page
    assert "data-mrp-period" in page


def test_every_word_of_the_screen_is_written_in_both_languages(clinic):
    import json

    ar = json.load(open("app/i18n/locales/ar.json", encoding="utf-8"))
    en = json.load(open("app/i18n/locales/en.json", encoding="utf-8"))

    assert set(ar["mrp"]) == set(en["mrp"])
    assert all((ar["mrp"][k] or "").strip() for k in ar["mrp"])
    assert all((en["mrp"][k] or "").strip() for k in en["mrp"])


# ============ اللي كنس الطفرات مسكه ============
def test_accepting_when_nobody_handed_anything_over_is_refused(stay):
    """فيه مسؤول، بس محدّش سلّم — فمفيش حاجة تتستلم.

    والاختبار اللي فوق بيغطّي الحالة اللي مفيش فيها مسؤول خالص؛ دي
    الحالة التانية، واللي من غيرها طبيب يقدر ياخد مسؤولية طفل من إيد
    واحد تاني من غير ما الأول يقول حاجة.
    """
    from app.utils import responsibility as who

    with stay["app"].app_context():
        who.assign(_stay(stay), _doc(stay))
        stay["db"].session.commit()

        with pytest.raises(ValueError):
            who.accept(_stay(stay), _doc(stay, "doc2"))


def test_a_period_that_ended_is_not_the_current_one(stay):
    """**الفترة المقفولة مش إجابة «مين مسؤول دلوقتي».**

    الأبواب بتقفل وتفتح مع بعض، فالحالة دي ما بتتكتبش من الشاشة —
    بتيجي من استيراد أو تعديل مباشر. ولو `current` ردّت بيها، إقامة
    مسؤوليتها خلصت هتبان مغطّاة و`without_mrp` هتسكت عنها.
    """
    from app.utils import responsibility as who

    with stay["app"].app_context():
        row = who.assign(_stay(stay), _doc(stay))
        stay["db"].session.commit()
        row.until = datetime.utcnow()
        stay["db"].session.commit()

        assert who.current(stay["stay"]) is None
        assert [s.id for s in who.without_mrp()] == [stay["stay"]]


def test_the_stay_page_reads_the_same_way(stay):
    """**حارس من ناحية واحدة نص قاعدة.** `current` و`Admission.
    responsibility` بيجاوبوا نفس السؤال من مكانين، فالاتنين بيتسألوا."""
    from app.utils import responsibility as who

    with stay["app"].app_context():
        row = who.assign(_stay(stay), _doc(stay))
        stay["db"].session.commit()
        row.until = datetime.utcnow()
        stay["db"].session.commit()

        assert _stay(stay).responsibility is None
        assert _stay(stay).responsible_doctor is None


def test_the_latest_open_period_wins(stay):
    """ولو اتلاقى صفّين مفتوحين، الأحدث هو المسؤول — مش الأقدم."""
    from app.models import CareResponsibility
    from app.utils import responsibility as who

    with stay["app"].app_context():
        older = datetime.utcnow() - timedelta(days=3)
        stay["db"].session.add_all([
            CareResponsibility(admission_id=stay["stay"],
                               doctor_id=stay["ids"]["doctor"], since=older),
            CareResponsibility(admission_id=stay["stay"],
                               doctor_id=stay["doc2"],
                               since=datetime.utcnow()),
        ])
        stay["db"].session.commit()

        assert who.current(stay["stay"]).doctor_id == stay["doc2"]


def test_the_moment_of_the_handover_belongs_to_the_new_doctor(stay):
    """اللحظة نفسها مش بتاعة الاتنين.

    الفترة القديمة بتنتهي عندها والجديدة بتبدأ منها — ولو الحد مفتوح
    من الناحيتين، السؤال «مين كان مسؤول الساعة كذا» بيرجّع الاتنين،
    وأول واحد في السجل بيكسب: **اللي مشي**.
    """
    from app.utils import responsibility as who

    swap = datetime.utcnow() - timedelta(hours=2)

    with stay["app"].app_context():
        who.assign(_stay(stay), _doc(stay),
                   at=datetime.utcnow() - timedelta(days=1))
        stay["db"].session.commit()
        who.hand_over(_stay(stay), _doc(stay, "doc2"))
        who.accept(_stay(stay), _doc(stay, "doc2"), at=swap)
        stay["db"].session.commit()

        assert who.responsible_at(stay["stay"], swap).doctor_id == stay["doc2"]


def test_a_finished_period_is_not_in_limbo(stay):
    """الصف اللي اتقفل خلاص خرج من الحكاية — حتى لو كان فيه تسليم."""
    from app.utils import responsibility as who

    with stay["app"].app_context():
        who.assign(_stay(stay), _doc(stay))
        stay["db"].session.commit()
        who.hand_over(_stay(stay), _doc(stay, "doc2"))
        stay["db"].session.commit()
        # اتقفل من غير قبول — حالة بتيجي من استيراد، مش من الشاشة.
        closed = who.history(stay["stay"])[0]
        closed.until = datetime.utcnow()
        stay["db"].session.commit()

        assert who.in_limbo() == []


def test_the_oldest_handover_nobody_accepted_is_on_top(stay):
    """أقدم واحد فوق، زي كل قايمة انتظار في البرنامج."""
    from app.models import Admission, Patient
    from app.utils import responsibility as who

    with stay["app"].app_context():
        from datetime import date
        other = Patient(full_name="طفل تالت", patient_number="P-MRP2",
                        gender="female", date_of_birth=date(2024, 1, 1))
        stay["db"].session.add(other)
        stay["db"].session.flush()
        second = Admission(patient_id=other.id)
        stay["db"].session.add(second)
        stay["db"].session.commit()

        who.assign(_stay(stay), _doc(stay))
        who.assign(second, _doc(stay))
        stay["db"].session.commit()
        who.hand_over(second, _doc(stay, "doc2"),
                      at=datetime.utcnow() - timedelta(days=5))
        who.hand_over(_stay(stay), _doc(stay, "doc2"),
                      at=datetime.utcnow() - timedelta(days=1))
        stay["db"].session.commit()

        assert [r.admission_id for r in who.in_limbo()] == [second.id,
                                                            stay["stay"]]


def test_a_signature_with_nobody_behind_it_is_not_a_handover(stay):
    """*signed* بيقول مين. وقت لوحده مش توقيع — نفس قاعدة `Referral`."""
    from app.utils import responsibility as who

    with stay["app"].app_context():
        who.assign(_stay(stay), _doc(stay))
        stay["db"].session.commit()
        who.hand_over(_stay(stay), _doc(stay, "doc2"))
        stay["db"].session.commit()

        row = who.current(stay["stay"])
        row.accepted_at = datetime.utcnow()
        row.accepted_by_id = None
        stay["db"].session.commit()

        assert row.handed_over is False
        assert row.in_limbo is True


def test_the_new_table_wins_over_the_old_column(stay):
    """قارئ واحد، وترتيبه مقفول: الجدول الأول والعمود بعده.

    إقامة عندها الاتنين — عمود قديم وفترة شغّالة — لازم تقول اللي في
    الفترة، وإلا تسليم اتعمل في البرنامج ما بيبانش على الشاشة.
    """
    from app.utils import responsibility as who

    with stay["app"].app_context():
        row = _stay(stay)
        row.doctor_id = stay["ids"]["doctor"]
        stay["db"].session.commit()

        who.assign(row, _doc(stay, "doc2"))
        stay["db"].session.commit()

        assert _stay(stay).responsible_doctor.id == stay["doc2"]


# ============ الإقامة نفسها بتفتح الفترة ============
@pytest.fixture()
def ward(clinic):
    """سرير واحد يكفي: اللي بيتقاس هنا مين بيدخّل، مش شكل القسم."""
    from app.models import Bed, Setting, Space, Unit

    with clinic["app"].app_context():
        Setting.set(f"mod_enabled:{MODULE}", "1")
        unit = Unit(name="الداخلي", kind="ward")
        clinic["db"].session.add(unit)
        clinic["db"].session.flush()
        space = Space(unit_id=unit.id, name="غرفة ١", kind="room")
        clinic["db"].session.add(space)
        clinic["db"].session.flush()
        bed = Bed(space_id=space.id, name="سرير ١", kind="bed")
        clinic["db"].session.add(bed)
        clinic["db"].session.commit()
        clinic["bed"] = bed.id
    return clinic


def _put_in_bed(clinic, doctor_id=None):
    from app.models import Bed, Patient
    from app.utils import beds as ward_utils

    with clinic["app"].app_context():
        row = ward_utils.admit(Patient.query.get(clinic["ids"]["child"]),
                               Bed.query.get(clinic["bed"]),
                               doctor_id=doctor_id)
        clinic["db"].session.commit()
        return row.id


def test_a_doctor_admitting_becomes_responsible_from_that_minute(ward):
    """دليل ٣ — المسؤولية بتبدأ مع الإقامة، مش بخطوة تانية حد يفتكرها."""
    from app.utils import responsibility as who

    admission_id = _put_in_bed(ward, doctor_id=ward["ids"]["doctor"])

    with ward["app"].app_context():
        live = who.current(admission_id)
        assert live is not None
        assert live.doctor_id == ward["ids"]["doctor"]
        assert who.without_mrp() == []


def test_a_nurse_admitting_leaves_the_gap_visible(ward):
    """**ومفيش صف بيتكتب بطبيب فاضي.**

    صف مسؤولية من غير طبيب هو نفس الفراغ، وكان هيخلّي `without_mrp`
    تسكت عن الحالة اللي هي موجودة علشانها بالظبط.
    """
    from app.models import CareResponsibility
    from app.utils import responsibility as who

    admission_id = _put_in_bed(ward, doctor_id=None)

    with ward["app"].app_context():
        assert CareResponsibility.query.count() == 0
        assert [s.id for s in who.without_mrp()] == [admission_id]
