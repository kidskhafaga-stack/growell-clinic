"""احتياجات الطفل والأسرة وتفضيلاتهم — GAHAR `PCC.12`.

> 1. Healthcare providers identify patients' emotional, religious, and
>    spiritual needs.
> 2. Patient needs and preferences are documented in the patient's medical
>    record.
> 3. Plans of care consider emotional, religious, and spiritual needs.

**كانت بتتكتب في مكانين غلط**: `Patient.notes` (نص حر محدّش بيدوّر فيه على
احتياج)، وخانة في خطة الرعاية (بتروح مع الخطة، والطفل اللي بيجي العيادة
مالوش خطة أصلاً). والاحتياج **حقيقة عن الطفل** — بيتقال مرة ويتشاف كل مرة.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


def _kid(clinic):
    from app.models import Patient

    return clinic["db"].session.get(Patient, clinic["ids"]["child"])


def _doc(clinic):
    from app.models import User

    return User.query.filter_by(username="doc").one()


# ============ التلات حالات ============
def test_a_child_nobody_asked_about_is_unasked(clinic):
    """**دي اللي المعيار بيدوّر عليها** — دليل ١ بيقول *identify*."""
    from app.utils import needs

    with clinic["app"].app_context():
        assert needs.state(_kid(clinic)) == needs.UNASKED


def test_asked_and_none_is_an_answer_not_a_gap(clinic):
    """قايمة فاضية لوحدها بتقول حاجتين مختلفتين — والختم بيفرّق بينهم."""
    from app.utils import needs

    with clinic["app"].app_context():
        needs.asked_none(_kid(clinic), user=_doc(clinic))
        clinic["db"].session.commit()
        kid = _kid(clinic)
        assert needs.state(kid) == needs.NONE
        assert kid.needs_asked_by == _doc(clinic).id


def test_a_recorded_need_makes_it_some_and_stamps_the_asking(clinic):
    from app.utils import needs

    with clinic["app"].app_context():
        needs.add(_kid(clinic), "emotional", "بيخاف من الإبر", user=_doc(clinic))
        clinic["db"].session.commit()
        kid = _kid(clinic)
        assert needs.state(kid) == needs.SOME
        assert kid.needs_asked_at is not None


def test_asked_none_refuses_when_needs_are_on_file(clinic):
    """«مفيش» غلط لو فيه — والرفض أحسن من زرار بيمسح كلام الأسرة بصمت."""
    from app.utils import needs

    with clinic["app"].app_context():
        needs.add(_kid(clinic), "religious", "صايمين رمضان", user=_doc(clinic))
        with pytest.raises(ValueError):
            needs.asked_none(_kid(clinic), user=_doc(clinic))
        assert needs.state(_kid(clinic)) == needs.SOME


def test_ending_the_last_need_does_not_make_the_child_unasked(clinic):
    """الاحتياج خلص، بس السؤال اتسأل — الطفل مبقاش «محدّش سأل»."""
    from app.utils import needs

    with clinic["app"].app_context():
        row = needs.add(_kid(clinic), "emotional", "قلقان", user=_doc(clinic))
        needs.end(row, user=_doc(clinic), reason="كبر")
        clinic["db"].session.commit()
        assert needs.state(_kid(clinic)) == needs.NONE


# ============ اللي بيتمنع ============
def test_a_need_without_words_is_refused(clinic):
    from app.utils import needs

    with clinic["app"].app_context():
        for text in ("", "   "):
            with pytest.raises(ValueError):
                needs.add(_kid(clinic), "other", text)


def test_the_kinds_are_the_standard_s_own_words(clinic):
    """نفسي، ديني، روحي، وغيره — **مش قايمة اخترعناها**."""
    from app.models.patient_need import KINDS
    from app.utils import needs

    assert KINDS == ("emotional", "religious", "spiritual", "other")
    with clinic["app"].app_context():
        with pytest.raises(ValueError):
            needs.add(_kid(clinic), "dietary", "نباتي")


# ============ بيتقفل مش بيتمسح ============
def test_ending_keeps_the_row_and_says_why(clinic):
    """«بيخاف من الإبر» عند سنتين ممكن ما تبقاش صح عند ست — والملف لازم
    يقول إيه اللي كان صح الشهر اللي فات."""
    from app.models import PatientNeed
    from app.utils import needs

    with clinic["app"].app_context():
        row = needs.add(_kid(clinic), "emotional", "بيخاف من الإبر",
                        user=_doc(clinic))
        needs.end(row, user=_doc(clinic), reason="اتعوّد")
        clinic["db"].session.commit()
        kept = clinic["db"].session.get(PatientNeed, row.id)
        assert kept is not None
        assert kept.end_reason == "اتعوّد"
        assert needs.current(_kid(clinic)) == []


# ============ دليل ١ للإقامة ============
def test_an_admitted_child_nobody_asked_is_listed(clinic):
    from app.models import Admission
    from app.utils import needs

    with clinic["app"].app_context():
        stay = Admission(patient_id=clinic["ids"]["child"])
        clinic["db"].session.add(stay)
        clinic["db"].session.commit()
        assert [s.id for s in needs.unasked_stays()] == [stay.id]

        needs.asked_none(_kid(clinic), user=_doc(clinic))
        clinic["db"].session.commit()
        assert needs.unasked_stays() == []


# ============ الشاشات ============
def _file(clinic, user="doc"):
    page = clinic["sign_in"](user).get(f"/patients/{clinic['ids']['child']}")
    assert page.status_code == 200
    return page.get_data(as_text=True)


def test_the_file_says_nobody_has_asked(clinic):
    html = _file(clinic)
    assert 'data-needs-state="unasked"' in html
    assert "data-needs-none" in html


def test_adding_from_the_file(clinic):
    from app.utils import needs

    clinic["sign_in"]("doc").post(
        f"/patients/{clinic['ids']['child']}/needs",
        data={"kind": "religious", "text": "مفيش جيلاتين خنزير"})
    with clinic["app"].app_context():
        assert [n.text for n in needs.current(_kid(clinic))] == \
            ["مفيش جيلاتين خنزير"]
    html = _file(clinic)
    assert "مفيش جيلاتين خنزير" in html
    # والزرار «سألنا — مفيش» اختفى: الإجابة اتقالت.
    assert "data-needs-none" not in html


def test_asked_none_from_the_file(clinic):
    clinic["sign_in"]("doc").post(
        f"/patients/{clinic['ids']['child']}/needs/none")
    assert 'data-needs-state="none"' in _file(clinic)


def test_the_visit_shows_them_where_the_doctor_is(clinic):
    """**متسجّلة في الملف مرة، وبتتشاف في الزيارة كل مرة.**"""
    from app.utils import needs

    with clinic["app"].app_context():
        needs.add(_kid(clinic), "other", "الأم عايزة دكتورة", user=_doc(clinic))
        clinic["db"].session.commit()
    html = clinic["sign_in"]("doc").get(
        f"/visits/{clinic['ids']['visit']}/record").get_data(as_text=True)
    line = html.split("data-needs-line")[1].split("</div>")[0]
    assert "الأم عايزة دكتورة" in line


def test_an_ended_need_is_not_shown_at_the_visit(clinic):
    from app.utils import needs

    with clinic["app"].app_context():
        row = needs.add(_kid(clinic), "emotional", "بيخاف", user=_doc(clinic))
        needs.end(row, user=_doc(clinic))
        clinic["db"].session.commit()
    html = clinic["sign_in"]("doc").get(
        f"/visits/{clinic['ids']['visit']}/record").get_data(as_text=True)
    assert "data-needs-line" not in html


def test_the_care_plan_is_written_with_them_in_view(clinic):
    """دليل ٣ — *plans of care consider … needs*. الخطة ما تتكتبش
    والاحتياجات مش قدامها."""
    from app.models import CarePlan
    from app.utils import needs

    with clinic["app"].app_context():
        clinic["db"].session.add(CarePlan(patient_id=clinic["ids"]["child"],
                                          written_by=_doc(clinic).id))
        needs.add(_kid(clinic), "spiritual", "عايزين شيخ يزوره",
                  user=_doc(clinic))
        clinic["db"].session.commit()
    html = _file(clinic)
    assert 'id="cp_preferences"' in html
    before_box = html.split('id="cp_preferences"')[0].rsplit('<div class="form-row"', 1)[1]
    assert "عايزين شيخ يزوره" in before_box


def test_the_front_desk_neither_sees_nor_writes_them(clinic):
    """دين الأسرة ومخاوف الطفل مش معلومات للاستقبال."""
    from app.utils import needs

    with clinic["app"].app_context():
        needs.add(_kid(clinic), "religious", "صايمين", user=_doc(clinic))
        clinic["db"].session.commit()
    assert "صايمين" not in _file(clinic, "desk")
    page = clinic["sign_in"]("desk").post(
        f"/patients/{clinic['ids']['child']}/needs",
        data={"kind": "other", "text": "x"})
    assert page.status_code == 403


def test_every_word_is_written_in_both_languages():
    import json

    from app.models.patient_need import KINDS

    ar = json.load(open("app/i18n/locales/ar.json", encoding="utf-8"))
    en = json.load(open("app/i18n/locales/en.json", encoding="utf-8"))
    assert set(ar["needs"]) == set(en["needs"])
    for key in ar["needs"]:
        assert ar["needs"][key].strip(), key
        assert en["needs"][key].strip(), key
    for kind in KINDS:
        assert f"kind_{kind}" in ar["needs"], kind
