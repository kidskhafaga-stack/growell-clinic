"""الإحالة وتغذيتها الراجعة — GAHAR `ACT.14`.

**البرنامج كان عارف نص الدايرة.** `Visit.referred_at/_to/referral_note`
موجودين من زمان: زرار، وبادچ على أربع شاشات. الورقة بتمشي. اللي مكانش
موجود إن حد يقفل الدايرة — والنية كاتباها بالنص: *Recording and
**responding to referral feedback** … completes the cycle of referral*.

**وأوحش صف في الملف ده هو اللي بيبان مكتمل**: ورقة راحت، ورد رجع، وكلام
مكتوب — ومحدّش قراه. الاستقبال بياخد الورقة من الأهل ويحطّها في الملف،
والطبيب اللي المفروض يبني عليها ما شفهاش. وأي جرد بيعدّ «الردود» بيعدّه
رد.
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


def _patient(clinic):
    from app.models import Patient

    return Patient.query.get(clinic["ids"]["child"])


def _user(clinic, role="doctor"):
    from app.models import User

    return User.query.get(clinic["ids"][role])


def _sent(clinic, **fields):
    """ورقة راحت. بترجّع الـid."""
    from app.utils import referrals as refs

    with clinic["app"].app_context():
        fields.setdefault("reason", "تشنّج متكرر")
        row = refs.refer(_patient(clinic), user=_user(clinic), **fields)
        clinic["db"].session.commit()
        return row.id


# ============ الباب: السبب مطلوب ============
def test_a_sheet_with_no_reason_is_refused(clinic):
    """ورقة رايحة لمستشفى تانية من غير سبب هي طفل بيوصل لحد ما يعرف
    ليه جه."""
    from app.utils import referrals as refs

    with clinic["app"].app_context():
        for bad in (None, "", "   "):
            with pytest.raises(ValueError):
                refs.refer(_patient(clinic), bad)


def test_an_unknown_kind_is_refused(clinic):
    from app.utils import referrals as refs

    with clinic["app"].app_context():
        with pytest.raises(ValueError):
            refs.refer(_patient(clinic), "سبب", kind="maybe")


# ============ (viii) مين قرّر — في السجل مش في اللوج ============
def test_the_sheet_says_who_decided(clinic):
    """`ActivityLog` بيقول مين ضغط الزرار، وده أثر تدقيق. واللي بيستقبل
    الطفل بيقرا **الورقة**، وما بيفتحش لوج البرنامج."""
    from app.models import Referral

    rid = _sent(clinic)

    with clinic["app"].app_context():
        row = Referral.query.get(rid)
        assert row.decided_by_id == clinic["ids"]["doctor"]
        assert row.decided_by is not None
        assert "decided_by" not in __import__(
            "app.utils.referrals", fromlist=["x"]).missing(row)


def test_a_sheet_nobody_signed_names_that_gap_too(clinic):
    from app.models import Referral
    from app.utils import referrals as refs

    rid = _sent(clinic)

    with clinic["app"].app_context():
        row = Referral.query.get(rid)
        row.decided_by_id = None
        clinic["db"].session.commit()
        assert "decided_by" in refs.missing(row)


# ============ دليل ٤: التمن بنود ============
def test_the_missing_elements_are_named_not_counted(clinic):
    """«ورقة غير مكتملة» مش معلومة. «ناقص: وسيلة النقل» معلومة."""
    from app.models import Referral
    from app.utils import referrals as refs

    rid = _sent(clinic, sent_to="مستشفى الأطفال")

    with clinic["app"].app_context():
        gaps = refs.missing(Referral.query.get(rid))
        assert set(gaps) == {"transport", "monitoring", "condition"}


def test_a_complete_sheet_has_no_gaps(clinic):
    from app.models import Referral
    from app.utils import referrals as refs

    rid = _sent(clinic, sent_to="مستشفى الأطفال", transport="إسعاف",
                monitoring="أكسچين ومونيتور", condition="واعي، نبض ١٢٠")

    with clinic["app"].app_context():
        assert refs.missing(Referral.query.get(rid)) == []


def test_transport_and_monitoring_are_two_facts(clinic):
    """«راح بإسعاف» و«محتاج أكسچين في الطريق» مش نفس الحاجة — وخانة
    واحدة بتخلّي الأولى تنوب عن التانية."""
    from app.models import Referral
    from app.utils import referrals as refs

    rid = _sent(clinic, sent_to="مستشفى", transport="إسعاف",
                condition="مستقر")

    with clinic["app"].app_context():
        assert refs.missing(Referral.query.get(rid)) == ["monitoring"]


def test_the_rest_of_the_sheet_is_written_from_its_own_row(clinic):
    from app.models import Referral
    from app.utils import referrals as refs

    rid = _sent(clinic)

    with clinic["app"].app_context():
        row = Referral.query.get(rid)
        refs.describe(row, sent_to="مستشفى الأطفال", transport="إسعاف",
                      monitoring="مونيتور", condition="مستقر")
        clinic["db"].session.commit()
        assert refs.missing(row) == []


def test_a_field_not_sent_is_not_wiped(clinic):
    """الشاشة بتعرض خانات الناقص بس، فالمبعوت جزء من الورقة مش كلها."""
    from app.models import Referral
    from app.utils import referrals as refs

    rid = _sent(clinic, sent_to="مستشفى الأطفال")

    with clinic["app"].app_context():
        row = Referral.query.get(rid)
        refs.describe(row, transport="إسعاف")
        clinic["db"].session.commit()
        assert row.sent_to == "مستشفى الأطفال"


# ============ (iii) و(iv): بيتجمّعوا، مش بيتخزّنوا ============
def test_the_medicines_come_from_the_prescription(clinic):
    """نسخهم على الورقة معناه إجابتين لنفس السؤال — ونسخة بتقدم أول ما
    الروشتة تتعدّل."""
    from app.models import Prescription, PrescriptionItem
    from app.utils import referrals as refs
    from app.models import Referral

    rid = _sent(clinic)

    with clinic["app"].app_context():
        row = Referral.query.get(rid)
        rx = Prescription(patient_id=row.patient_id,
                          doctor_id=clinic["ids"]["doctor"])
        clinic["db"].session.add(rx)
        clinic["db"].session.flush()
        clinic["db"].session.add(PrescriptionItem(
            prescription_id=rx.id, drug_name="كيبرا", dose="٥ مل",
            frequency="مرتين"))
        clinic["db"].session.commit()

        sheet = refs.sheet(row)
        assert [m["name"] for m in sheet["medicines"]] == ["كيبرا"]
        assert sheet["medicines"][0]["dose"] == "٥ مل"


def test_a_child_on_nothing_is_not_an_incomplete_sheet(clinic):
    """**مفيش دوا مش نقص.** عدّها نقص كان هيخلّي القايمة تصرخ على كل
    ورقة، واللي بيقراها يتعلّم يتجاهلها."""
    from app.models import Referral
    from app.utils import referrals as refs

    rid = _sent(clinic, sent_to="مستشفى", transport="إسعاف",
                monitoring="مونيتور", condition="مستقر")

    with clinic["app"].app_context():
        sheet = refs.sheet(Referral.query.get(rid))
        assert sheet["medicines"] == []
        assert sheet["missing"] == []


def test_the_assessments_come_from_the_visit(clinic):
    from app.models import Referral, Visit
    from app.utils import referrals as refs
    from app.utils.clock import local_today

    with clinic["app"].app_context():
        visit = Visit(patient_id=clinic["ids"]["child"],
                      visit_date=local_today(),
                      doctor_id=clinic["ids"]["doctor"],
                      chief_complaint="تشنّج", plan="تحويل لمخ وأعصاب")
        clinic["db"].session.add(visit)
        clinic["db"].session.commit()
        row = refs.refer(_patient(clinic), "تشنّج متكرر",
                         user=_user(clinic), visit=visit)
        clinic["db"].session.commit()
        rid = row.id

    with clinic["app"].app_context():
        sheet = refs.sheet(Referral.query.get(rid))
        assert sheet["assessments"]["complaint"] == "تشنّج"
        assert sheet["assessments"]["plan"] == "تحويل لمخ وأعصاب"


# ============ دليل ٥: الدايرة ============
def test_a_sheet_with_no_answer_is_waiting(clinic):
    from app.utils import referrals as refs

    rid = _sent(clinic, sent_to="مستشفى الأطفال")

    with clinic["app"].app_context():
        assert [r.id for r in refs.waiting()] == [rid]


def test_a_transfer_is_never_waiting_for_a_reply(clinic):
    """الطفل مشي فيه خلاص. وقايمة فيها صفوف مستحيلة بتعلّم اللي بيقراها
    إنه يتجاهلها."""
    from app.utils import referrals as refs

    _sent(clinic, kind="transfer", sent_to="مستشفى الصدر")

    with clinic["app"].app_context():
        assert refs.waiting() == []


def test_the_oldest_letter_is_on_top(clinic):
    """اللي بتحطّ النهاردة فوق هي اللي بتاعة الشهر اللي فات لسه فيها
    آخر السنة."""
    from app.utils import referrals as refs

    old = _sent(clinic, sent_to="أ", at=datetime.utcnow() - timedelta(days=40))
    new = _sent(clinic, sent_to="ب", at=datetime.utcnow() - timedelta(days=2))

    with clinic["app"].app_context():
        assert [r.id for r in refs.waiting()] == [old, new]


def test_recording_a_reply_is_not_signing_it(clinic):
    """**دي الحتة كلها.** الاستقبال بيحطّ الورقة في الملف؛ ده
    *recorded*. والمعيار كاتب *reviewed, **signed*** جنبها."""
    from app.models import Referral
    from app.utils import referrals as refs

    rid = _sent(clinic, sent_to="مستشفى الأطفال")

    with clinic["app"].app_context():
        row = Referral.query.get(rid)
        refs.answer(row, "اتعمل رنين، النتيجة سليمة", user=_user(clinic))
        clinic["db"].session.commit()

        assert row.answered is True
        assert row.signed is False
        assert row.closed is False
        # خرج من قايمة الانتظار…
        assert refs.waiting() == []
        # …ودخل القايمة اللي بتبان مكتملة.
        assert [r.id for r in refs.unsigned()] == [rid]


def test_and_signing_closes_the_circle(clinic):
    from app.models import Referral
    from app.utils import referrals as refs

    rid = _sent(clinic, sent_to="مستشفى الأطفال")

    with clinic["app"].app_context():
        row = Referral.query.get(rid)
        refs.answer(row, "اتعمل رنين", user=_user(clinic))
        refs.review(row, user=_user(clinic))
        clinic["db"].session.commit()

        assert row.closed is True
        assert refs.waiting() == []
        assert refs.unsigned() == []


def test_a_reply_with_no_words_is_not_a_reply(clinic):
    """دليل ٥ بيقول *recorded* — وصف بيقول «رد يوم الخميس» ومفيش كلام
    مش استمرارية رعاية."""
    from app.models import Referral
    from app.utils import referrals as refs

    rid = _sent(clinic)

    with clinic["app"].app_context():
        row = Referral.query.get(rid)
        for bad in (None, "", "   "):
            with pytest.raises(ValueError):
                refs.answer(row, bad)


def test_signing_nothing_is_refused(clinic):
    """توقيع على لا حاجة بيخلّي الصف يبان «الدايرة اتقفلت» وهي ما
    اتقفلتش."""
    from app.models import Referral
    from app.utils import referrals as refs

    rid = _sent(clinic)

    with clinic["app"].app_context():
        with pytest.raises(ValueError):
            refs.review(Referral.query.get(rid), user=_user(clinic))


def test_the_one_who_filed_it_and_the_one_who_signed_are_kept_apart(clinic):
    """**والاتنين دول مش نفس الوظيفة.** الاستقبال بياخد الورقة من الأهل
    ويحطّها في الملف، والطبيب هو اللي بيقراها ويبني عليها."""
    from app.models import Referral
    from app.utils import referrals as refs

    rid = _sent(clinic)

    with clinic["app"].app_context():
        row = Referral.query.get(rid)
        refs.answer(row, "الورقة وصلت", user=_user(clinic, "desk"))
        refs.review(row, user=_user(clinic, "doctor"))
        clinic["db"].session.commit()

        assert row.recorded_by_id == clinic["ids"]["desk"]
        assert row.reviewed_by_id == clinic["ids"]["doctor"]
        assert row.recorded_by_id != row.reviewed_by_id


def test_the_days_are_counted_from_the_day_it_left(clinic):
    from app.models import Referral

    rid = _sent(clinic, at=datetime.utcnow() - timedelta(days=9, hours=2))

    with clinic["app"].app_context():
        assert Referral.query.get(rid).waiting_days == 9


def test_no_deadline_is_invented(clinic):
    """`ACT.10` بيقول *within a **predefined** time frame* فالبرنامج عمل
    إعداد. `ACT.14` **ما بيقولش** — فمفيش خط أحمر من عندنا."""
    from app.utils import referrals as refs

    source = open("app/utils/referrals.py", encoding="utf-8").read()
    assert "SETTING" not in source
    assert not hasattr(refs, "overdue")


# ============ الإلغاء: مش مسح ============
def test_cancelling_keeps_the_row(clinic):
    from app.models import Referral
    from app.utils import referrals as refs

    rid = _sent(clinic)

    with clinic["app"].app_context():
        refs.cancel(Referral.query.get(rid))
        clinic["db"].session.commit()

        assert Referral.query.get(rid) is not None
        assert refs.waiting() == []
        assert refs.for_patient(clinic["ids"]["child"]) == []


# ============ السجل القديم لسه بيبان ============
def test_a_referral_written_before_this_table_still_shows(clinic):
    """`utils/schema` **مش بيرحّل داتا** — additive only, never rewrites.
    فعيادة شغّالة عندها إحالات في الأعمدة القديمة، ولازم تفضل بتبان زي
    ما كانت بالظبط."""
    from app.models import Visit
    from app.utils.clock import local_today

    with clinic["app"].app_context():
        visit = Visit(patient_id=clinic["ids"]["child"],
                      visit_date=local_today(),
                      doctor_id=clinic["ids"]["doctor"],
                      referred_at=datetime(2026, 3, 1, 10, 0),
                      referred_to="مستشفى قديمة",
                      referral_note="سبب قديم")
        clinic["db"].session.add(visit)
        clinic["db"].session.commit()

        assert visit.is_referred is True
        assert visit.referral_where == "مستشفى قديمة"
        assert visit.referral_why == "سبب قديم"
        assert visit.referral_when.year == 2026


def test_a_new_referral_wins_over_the_old_column(clinic):
    """قارئ واحد، مش إجابتين."""
    from app.models import Visit
    from app.utils import referrals as refs
    from app.utils.clock import local_today

    with clinic["app"].app_context():
        visit = Visit(patient_id=clinic["ids"]["child"],
                      visit_date=local_today(),
                      doctor_id=clinic["ids"]["doctor"],
                      referred_at=datetime(2026, 3, 1, 10, 0),
                      referred_to="مستشفى قديمة")
        clinic["db"].session.add(visit)
        clinic["db"].session.commit()

        refs.refer(_patient(clinic), "سبب جديد", user=_user(clinic),
                   visit=visit, sent_to="مستشفى جديدة")
        clinic["db"].session.commit()

        assert visit.referral_where == "مستشفى جديدة"
        assert visit.referral_why == "سبب جديد"


# ============ الشاشات ============
def test_the_button_writes_a_sheet(clinic):
    from app.models import Referral, Visit
    from app.utils.clock import local_today

    with clinic["app"].app_context():
        visit = Visit(patient_id=clinic["ids"]["child"],
                      visit_date=local_today(),
                      doctor_id=clinic["ids"]["doctor"])
        clinic["db"].session.add(visit)
        clinic["db"].session.commit()
        vid = visit.id

    client = clinic["sign_in"]("boss")
    client.post(f"/visits/{vid}/refer", follow_redirects=True,
                data={"referred_to": "مستشفى الأطفال",
                      "referral_note": "تشنّج متكرر", "kind": "referral"})

    with clinic["app"].app_context():
        row = Referral.query.one()
        assert row.sent_to == "مستشفى الأطفال"
        assert row.reason == "تشنّج متكرر"
        assert row.decided_by_id is not None


def test_the_button_refuses_a_sheet_with_no_reason(clinic):
    from app.models import Referral, Visit
    from app.utils.clock import local_today

    with clinic["app"].app_context():
        visit = Visit(patient_id=clinic["ids"]["child"],
                      visit_date=local_today(),
                      doctor_id=clinic["ids"]["doctor"])
        clinic["db"].session.add(visit)
        clinic["db"].session.commit()
        vid = visit.id

    client = clinic["sign_in"]("boss")
    client.post(f"/visits/{vid}/refer", follow_redirects=True,
                data={"referred_to": "مستشفى الأطفال", "referral_note": " "})

    with clinic["app"].app_context():
        assert Referral.query.count() == 0


def test_the_screen_puts_the_unsigned_replies_first(clinic):
    """اللي بيبان مكتمل محتاج يبقى فوق؛ اللي بيبان ناقص بيبان لوحده."""
    from app.models import Referral
    from app.utils import referrals as refs

    waiting_id = _sent(clinic, sent_to="مستشفى أ")
    answered_id = _sent(clinic, sent_to="مستشفى ب")

    with clinic["app"].app_context():
        refs.answer(Referral.query.get(answered_id), "النتيجة سليمة",
                    user=_user(clinic))
        clinic["db"].session.commit()

    page = clinic["sign_in"]("boss").get("/visits/referrals").get_data(as_text=True)

    assert f'data-unsigned="{answered_id}"' in page
    assert f'data-waiting="{waiting_id}"' in page
    assert page.index("data-referrals-unsigned") < page.index("data-referrals-waiting")


def test_the_screen_names_the_gaps_and_gives_a_box_for_each(clinic):
    """**اللي بيقرا هو اللي بيقفل** — مش بادچ بيقول «روح شوف»."""
    rid = _sent(clinic, sent_to="مستشفى أ", transport="إسعاف")

    page = clinic["sign_in"]("boss").get("/visits/referrals").get_data(as_text=True)

    assert f'data-gaps="{rid}"' in page
    assert 'data-gap="monitoring"' in page
    assert 'data-gap="condition"' in page
    assert 'data-gap="transport"' not in page
    assert f'data-complete="{rid}"' in page
    assert 'name="monitoring"' in page


def test_signing_from_the_screen_closes_it(clinic):
    from app.models import Referral
    from app.utils import referrals as refs

    rid = _sent(clinic, sent_to="مستشفى أ")

    with clinic["app"].app_context():
        refs.answer(Referral.query.get(rid), "النتيجة سليمة",
                    user=_user(clinic))
        clinic["db"].session.commit()

    client = clinic["sign_in"]("boss")
    client.post(f"/visits/referrals/{rid}/review", follow_redirects=True)

    with clinic["app"].app_context():
        assert Referral.query.get(rid).closed is True


def test_a_clinic_with_nothing_out_is_told_so(clinic):
    page = clinic["sign_in"]("boss").get("/visits/referrals").get_data(as_text=True)

    assert "data-waiting-empty" in page
    assert "data-unsigned-empty" in page


def test_every_word_of_the_screen_is_written_in_both_languages(clinic):
    import json

    ar = json.load(open("app/i18n/locales/ar.json", encoding="utf-8"))
    en = json.load(open("app/i18n/locales/en.json", encoding="utf-8"))

    assert set(ar["referrals"]) == set(en["referrals"])
    assert all((ar["referrals"][k] or "").strip() for k in ar["referrals"])
    assert all((en["referrals"][k] or "").strip() for k in en["referrals"])


# ============ اللي كنس الطفرات مسكه ============
def test_a_box_with_only_spaces_is_still_empty(clinic):
    """مسافة مش إجابة.

    **والبابين بيقفلوا ده أصلاً**: `refer` و`describe` الاتنين بيعملوا
    `.strip() or None`، فمسافة مكتوبة على الشاشة بتوصل `None`. اللي
    بيفضل هو الصف اللي مجاش من الشاشة — استيراد، أو تعديل مباشر على
    القاعدة — و`missing` هي آخر حارس قبل ما ورقة فيها مسافة تبان كاملة.

    وده هو نفس السبب اللي خلّى الاختبار ده يتكتب بكتابة على العمود
    مباشرة: كنس الطفرات مسك إن الحارس مش متغطّي من الناحية دي.
    """
    from app.models import Referral
    from app.utils import referrals as refs

    rid = _sent(clinic, sent_to="مستشفى أ", condition="مستقر")

    with clinic["app"].app_context():
        row = Referral.query.get(rid)
        # لا `refer` ولا `describe` بيقدروا يكتبوا ده — وصف من بره يقدر.
        row.transport = "   "
        row.monitoring = ""
        clinic["db"].session.commit()

        assert set(refs.missing(row)) == {"transport", "monitoring"}


def test_a_sheet_that_does_not_say_where_is_incomplete(clinic):
    """(vii) الجهة بند من التمانية زيّها زي غيره.

    والاختبارات اللي فوق كلها بتبعت `sent_to`، فمحدّش كان بيسأل عنه —
    وورقة من غير جهة هي ورقة الطفل بيوصل بيها فين؟
    """
    from app.models import Referral
    from app.utils import referrals as refs

    rid = _sent(clinic, transport="إسعاف", monitoring="مونيتور",
                condition="مستقر")

    with clinic["app"].app_context():
        assert refs.missing(Referral.query.get(rid)) == ["sent_to"]


def test_the_long_boxes_are_not_wiped_either(clinic):
    """**حارس من ناحية واحدة نص قاعدة.**

    `describe` بتمشي على مجموعتين: النصوص القصيرة (بتتقص على ١٢٠) والطويلة.
    والاختبار اللي فوق كان بيحرس المجموعة الأولى بس — والتانية كانت
    بتتمسح لما الشاشة تبعت خانة منها بس.
    """
    from app.models import Referral
    from app.utils import referrals as refs

    rid = _sent(clinic, monitoring="أكسچين", condition="واعي")

    with clinic["app"].app_context():
        row = Referral.query.get(rid)
        refs.describe(row, sent_to="مستشفى الأطفال")
        clinic["db"].session.commit()

        assert row.monitoring == "أكسچين"
        assert row.condition == "واعي"


def test_correcting_the_words_does_not_move_the_day_it_came_back(clinic):
    """رجعت يوم الخميس وحد صحّح صياغتها الاتنين — رجعت الخميس برضه.

    والتاريخ ده هو اللي `waiting_days` بتقيس عليه، فتحريكه بيخلّي ورقة
    استنّت شهر تبان رجعت في يومها.
    """
    from app.models import Referral
    from app.utils import referrals as refs

    came_back = datetime.utcnow() - timedelta(days=12)
    rid = _sent(clinic, at=datetime.utcnow() - timedelta(days=20))

    with clinic["app"].app_context():
        row = Referral.query.get(rid)
        refs.answer(row, "رنين سليم", user=_user(clinic), at=came_back)
        clinic["db"].session.commit()
        first = row.feedback_at

        refs.answer(row, "رنين سليم — والتقرير مرفق", user=_user(clinic))
        clinic["db"].session.commit()

        assert row.feedback_at == first
        assert row.feedback.endswith("مرفق")


def test_the_sheet_carries_this_visits_medicines_only(clinic):
    """الطفل عنده روشتات قديمة، والورقة بتاعة الحضور ده.

    ورقة بتحمل كل دوا الطفل من أول يوم هي ورقة اللي بيستقبله بيقرا فيها
    حاجات اتوقفت من سنة.
    """
    from app.models import Prescription, PrescriptionItem, Referral, Visit
    from app.utils import referrals as refs
    from app.utils.clock import local_today

    with clinic["app"].app_context():
        kid = clinic["ids"]["child"]
        old = Visit(patient_id=kid, visit_date=local_today(),
                    doctor_id=clinic["ids"]["doctor"])
        now = Visit(patient_id=kid, visit_date=local_today(),
                    doctor_id=clinic["ids"]["doctor"])
        clinic["db"].session.add_all([old, now])
        clinic["db"].session.flush()
        for visit, drug in ((old, "دوا قديم"), (now, "كيبرا")):
            rx = Prescription(patient_id=kid, visit_id=visit.id,
                              doctor_id=clinic["ids"]["doctor"])
            clinic["db"].session.add(rx)
            clinic["db"].session.flush()
            clinic["db"].session.add(PrescriptionItem(
                prescription_id=rx.id, drug_name=drug))
        row = refs.refer(_patient(clinic), "تشنّج", user=_user(clinic),
                         visit=now)
        clinic["db"].session.commit()
        rid = row.id

    with clinic["app"].app_context():
        sheet = refs.sheet(Referral.query.get(rid))
        assert [m["name"] for m in sheet["medicines"]] == ["كيبرا"]


def test_a_time_with_no_words_is_not_an_answer(clinic):
    """`answer` بترفض النص الفاضي، فالصف ده ما بيتكتبش من الشاشة — بس
    بيتكتب من استيراد أو تصحيح مباشر، **والخاصية هي الحارس**.

    ونفس شكل `Opinion.answered` بالظبط.
    """
    from app.models import Referral

    rid = _sent(clinic)

    with clinic["app"].app_context():
        row = Referral.query.get(rid)
        row.feedback_at = datetime.utcnow()
        row.feedback = "   "
        clinic["db"].session.commit()

        assert row.answered is False
        assert row.closed is False


def test_a_signature_with_nobody_behind_it_is_not_a_signature(clinic):
    """*signed* بيقول مين. وقت لوحده مش توقيع."""
    from app.models import Referral
    from app.utils import referrals as refs

    rid = _sent(clinic)

    with clinic["app"].app_context():
        row = Referral.query.get(rid)
        refs.answer(row, "رد", user=_user(clinic))
        row.reviewed_at = datetime.utcnow()
        row.reviewed_by_id = None
        clinic["db"].session.commit()

        assert row.signed is False
        assert [r.id for r in refs.unsigned()] == []  # الوقت اتحطّ فعلاً


def test_a_sheet_with_no_stated_kind_is_the_one_that_gets_chased(clinic):
    """**الافتراض الآمن هو اللي بيتسأل عنه.**

    صف اتكتب من غير نوع لو بقى «تحويل» بيختفي من قايمة الانتظار للأبد —
    والورقة اللي محدّش قال نوعها هي بالظبط اللي محتاجة حد يسأل عليها.
    """
    from app.models import Referral

    with clinic["app"].app_context():
        row = Referral(patient_id=clinic["ids"]["child"], reason="سبب")
        clinic["db"].session.add(row)
        clinic["db"].session.commit()

        assert row.kind == "referral"

        from app.utils import referrals as refs
        assert [r.id for r in refs.waiting()] == [row.id]
