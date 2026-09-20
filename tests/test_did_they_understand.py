"""اتقالهم إيه، وإزاي، وفهموا ولا لأ — GAHAR PCC.07.

المعيار (د) بيطلب تلات حاجات في جملة واحدة: **المحتوى**، و**الطريقة**، و**تأكيد
إن الأهل فهموا**. وعمود واحد كان هيشيل واحدة ويسيب التانيتين — وأهمهم التالتة،
لأن أهل ما فهموش هما أهل اتقالهم ومفيش حاجة حصلت.

اللي بيتختبر هنا، بالترتيب اللي بيهمّ:

1. **التلات مواضيع مطلوبة لكل مريض.** (أ) بيقول *"for **all** patients"* —
   التشخيص، خطة الرعاية، تعليمات الخروج. مش مشروطين بحاجة.
2. **والباقي مشروط بالسجل.** طفل محدّش لقاه معرّض للسقوط مش محتاج تثقيف سقوط،
   وقايمة بتطلبه منه برضه هي قايمة بتتداس من غير ما تتقرا. والشرط بيتقرا من
   اللي حصل فعلاً — مش من علامة حد لازم يفتكر يحطها.
3. **وفهموا ولا لأ تلات حالات.** «محدّش سأل» مش زي «سألنا وما فهموش»، والتانية
   مهمة لحد يرجع يشرح تاني.
4. **وأحسن صف بيكسب، مش آخر واحد.** أهل اتشرحلهم مرتين — مرة من غير سؤال ومرة
   بتأكيد — دول اتشرحلهم؛ وقراية آخر صف بس كانت هتخلّي إدخال مستعجل يلغي
   تأكيد قبله.
5. **واللي محدّش كان يشوفه:** علامة «الأهل عارفين» على تقييم أو طلب دم، ومفيش
   ولا صف تثقيف. العلامة بتجاوب معيارها هي؛ `PCC.07` عايز حاجة تانية.
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def file_of(clinic):
    """The clinic, plus a second child so a missing filter cannot pass."""
    from app.models import Patient
    from app.utils.clock import local_today

    with clinic["app"].app_context():
        other = Patient(patient_number="ED-OTHER", full_name="طفل تاني",
                        gender="female", is_active=True,
                        date_of_birth=local_today() - timedelta(days=700))
        clinic["db"].session.add(other)
        clinic["db"].session.commit()
        clinic["ids"]["other_child"] = other.id
    return clinic


def _teach(clinic, patient_id=None, topic="diagnosis", **form):
    who = patient_id or clinic["ids"]["child"]
    return clinic["sign_in"]("doc").post(
        f"/patients/{who}/education", data={"topic": topic, **form},
        follow_redirects=True)


def _owed(clinic, patient_id=None):
    from app.utils import education

    with clinic["app"].app_context():
        return education.owed(patient_id or clinic["ids"]["child"])


def _state_of(owed, topic):
    return next((i["state"] for i in owed if i["topic"] == topic), None)


def _topics(owed):
    return [i["topic"] for i in owed]


def _at_risk(clinic, kind, patient_id=None, told=None):
    from app.models.risk_assessment import RiskAssessment

    with clinic["app"].app_context():
        clinic["db"].session.add(RiskAssessment(
            patient_id=patient_id or clinic["ids"]["child"], kind=kind,
            at=datetime.utcnow(), at_risk=True, family_told=told))
        clinic["db"].session.commit()


# ---------------------------------------- الثلاثة المطلوبة من كل ملف ----
def test_the_three_the_standard_asks_of_every_file(file_of):
    """(أ) بيسمّيهم *"for **all** patients"* — مش لبعضهم."""
    from app.models.patient_education import REQUIRED_TOPICS

    assert REQUIRED_TOPICS == ("diagnosis", "care_plan", "discharge")
    assert _topics(_owed(file_of)) == ["diagnosis", "care_plan", "discharge"]


def test_a_file_with_nothing_taught_says_so_for_each_of_them(file_of):
    owed = _owed(file_of)

    assert {i["state"] for i in owed} == {"none"}


def test_teaching_one_leaves_the_other_two_owed(file_of):
    from app.utils import education

    _teach(file_of, topic="diagnosis", understood="yes")

    with file_of["app"].app_context():
        assert education.missing(file_of["ids"]["child"]) == ["care_plan",
                                                              "discharge"]


# ----------------------------------------------- والباقي مشروط بالسجل ----
def test_a_child_nobody_found_at_risk_is_not_asked_for_falls_teaching(file_of):
    """قايمة بتطلب تثقيف سقوط من طفل محدّش قال إنه معرّض هي قايمة الورديّة
    بتتعلّم تدوس عليها من غير ما تقراها."""
    assert "fall" not in _topics(_owed(file_of))


def test_being_found_at_risk_is_what_asks_for_it(file_of):
    """*"The families of patients who are **at higher risk**"* — التقييم اللي
    لقى إن الطفل معرّض هو اللي بيطلب، مش وجود التقييم."""
    _at_risk(file_of, "fall")

    owed = _owed(file_of)
    assert "fall" in _topics(owed)
    assert _state_of(owed, "fall") == "none"


def test_an_assessment_that_found_nothing_asks_for_nothing(file_of):
    from app.models.risk_assessment import RiskAssessment

    with file_of["app"].app_context():
        file_of["db"].session.add(RiskAssessment(
            patient_id=file_of["ids"]["child"], kind="fall",
            at=datetime.utcnow(), at_risk=False))
        file_of["db"].session.commit()

    assert "fall" not in _topics(_owed(file_of))


def test_an_unanswered_assessment_asks_for_nothing_either(file_of):
    """«محدّش قال» مش «معرّض». التقييم اللي محدّش جاوب فيه مش بيطلب تثقيف."""
    from app.models.risk_assessment import RiskAssessment

    with file_of["app"].app_context():
        file_of["db"].session.add(RiskAssessment(
            patient_id=file_of["ids"]["child"], kind="vte",
            at=datetime.utcnow(), at_risk=None))
        file_of["db"].session.commit()

    assert "vte" not in _topics(_owed(file_of))


def test_another_childs_risk_does_not_ask_this_child_for_teaching(file_of):
    _at_risk(file_of, "pressure", patient_id=file_of["ids"]["other_child"])

    assert "pressure" not in _topics(_owed(file_of))
    assert "pressure" in _topics(_owed(file_of, file_of["ids"]["other_child"]))


def test_a_blood_request_asks_for_transfusion_teaching(file_of):
    """`ICD.20` (ب) — *"Education of patient and family about proposed
    transfusion."* من الطلب، لأن الشرح مكانه **قبل** ما الكيس يتعلّق."""
    from app.models import Patient
    from app.utils import blood

    with file_of["app"].app_context():
        blood.request(Patient.query.get(file_of["ids"]["child"]), "prbc",
                      "هيموجلوبين ٥")
        file_of["db"].session.commit()

    assert "blood" in _topics(_owed(file_of))


def test_a_consent_asks_for_teaching_about_what_it_covers(file_of):
    """توقيع على حاجة محدّش شرحها هو اللي الموافقة المستنيرة موجودة تمنعه."""
    from app.models import Consent

    with file_of["app"].app_context():
        file_of["db"].session.add(Consent(
            patient_id=file_of["ids"]["child"], consent_type="general",
            guardian_name="الأب"))
        file_of["db"].session.commit()

    assert "consent" in _topics(_owed(file_of))


# ------------------------------------------------ فهموا ولا لأ: تلاتة ----
def test_nobody_asked_is_not_they_did_not_understand(file_of):
    """الفرق بين الاتنين هو اللي بيقول لحد يرجع يشرح تاني."""
    from app.models import PatientEducation

    _teach(file_of, topic="diagnosis", understood="")

    with file_of["app"].app_context():
        assert PatientEducation.query.one().understood is None
    assert _state_of(_owed(file_of), "diagnosis") == "unchecked"


def test_taught_and_not_understood_is_its_own_state(file_of):
    _teach(file_of, topic="diagnosis", understood="no")

    assert _state_of(_owed(file_of), "diagnosis") == "again"


def test_taught_and_understood_is_the_finished_one(file_of):
    _teach(file_of, topic="diagnosis", understood="yes")

    assert _state_of(_owed(file_of), "diagnosis") == "done"


def test_a_confirmed_teaching_is_not_undone_by_a_later_blank_one(file_of):
    """أحسن صف بيكسب مش آخر واحد: إدخال مستعجل بعدين مينفعش يلغي تأكيد."""
    _teach(file_of, topic="care_plan", understood="yes")
    _teach(file_of, topic="care_plan", understood="")

    assert _state_of(_owed(file_of), "care_plan") == "done"


def test_a_failed_one_outranks_an_unchecked_one(file_of):
    """«ما فهموش» مهمة لحد، و«محدّش سأل» فجوة — فالأولى بتكسب."""
    _teach(file_of, topic="discharge", understood="")
    _teach(file_of, topic="discharge", understood="no")

    assert _state_of(_owed(file_of), "discharge") == "again"


def test_the_topics_needing_somebody_to_go_back_are_listed_apart(file_of):
    from app.utils import education

    _teach(file_of, topic="diagnosis", understood="no")
    _teach(file_of, topic="care_plan", understood="yes")

    with file_of["app"].app_context():
        assert education.not_understood(file_of["ids"]["child"]) == ["diagnosis"]


# ------------------------------------------ المحتوى والطريقة اتحفظوا ----
def test_what_was_said_is_kept_in_the_words_it_was_said_in(file_of):
    from app.models import PatientEducation

    _teach(file_of, topic="medication", detail="وريته إزاي يهزّ البخاخة",
           method="demonstration", understood="yes", interpreter="1")

    with file_of["app"].app_context():
        row = PatientEducation.query.one()
        assert row.detail == "وريته إزاي يهزّ البخاخة"
        assert row.method == "demonstration"
        assert row.interpreter is True
        assert row.by_id == file_of["ids"]["doctor"]
        assert row.understood is True


def test_teaching_with_no_words_is_still_teaching(file_of):
    """ممرّضة ورّت أم إزاي تستعمل البخاخة ودوست «فهمت» سجّلت حاجة صح؛ رفضها من
    غير فقرة كان هيبعت أكتر تثقيف بيحصل في العيادة على لا حاجة."""
    from app.models import PatientEducation

    _teach(file_of, topic="medication", method="demonstration",
           understood="yes")

    with file_of["app"].app_context():
        row = PatientEducation.query.one()
        assert row.detail is None
        assert row.understood is True


def test_a_method_the_screen_cannot_draw_is_refused(file_of):
    from app.models import PatientEducation

    _teach(file_of, topic="diagnosis", method="بالتخاطر")

    with file_of["app"].app_context():
        assert PatientEducation.query.count() == 0


def test_a_topic_that_is_not_one_of_the_list_is_refused(file_of):
    from app.models import PatientEducation

    _teach(file_of, topic="astrology")

    with file_of["app"].app_context():
        assert PatientEducation.query.count() == 0


def test_the_default_method_is_the_commonest_one(file_of):
    """أغلب التثقيف بيحصل بالكلام، ومحدّش بيختار من قايمة علشان يقول كده."""
    from app.models import PatientEducation

    _teach(file_of, topic="diagnosis")

    with file_of["app"].app_context():
        assert PatientEducation.query.one().method == "verbal"


# ------------------------------------- اللي محدّش كان يشوفه قبل كده ----
def test_a_tick_with_no_teaching_behind_it_is_a_finding(file_of):
    """علامة «الأهل عارفين» على تقييم بتجاوب معيارها هي — و`PCC.07` (د) عايز
    المحتوى والطريقة والتأكيد. علامة من غير صف تثقيف هي فجوة حقيقية محدّش كان
    يقدر يشوفها."""
    from app.utils import education

    _at_risk(file_of, "fall", told=True)

    with file_of["app"].app_context():
        assert education.said_told_but_never_taught(
            file_of["ids"]["child"]) == ["fall"]


def test_teaching_it_clears_the_finding(file_of):
    from app.utils import education

    _at_risk(file_of, "fall", told=True)
    _teach(file_of, topic="fall", understood="yes")

    with file_of["app"].app_context():
        assert education.said_told_but_never_taught(
            file_of["ids"]["child"]) == []


def test_a_tick_that_says_no_is_not_a_finding(file_of):
    """«لأ ما اتقالهمش» تسجيل صح، مش ادّعاء من غير سند."""
    from app.utils import education

    _at_risk(file_of, "fall", told=False)

    with file_of["app"].app_context():
        assert education.said_told_but_never_taught(
            file_of["ids"]["child"]) == []


def test_a_blood_tick_with_no_teaching_is_a_finding_too(file_of):
    from app.models import Patient
    from app.utils import blood, education

    with file_of["app"].app_context():
        blood.request(Patient.query.get(file_of["ids"]["child"]), "prbc",
                      "نزيف", family_told=True)
        file_of["db"].session.commit()
        assert "blood" in education.said_told_but_never_taught(
            file_of["ids"]["child"])


def test_another_childs_tick_is_not_this_childs_finding(file_of):
    from app.utils import education

    _at_risk(file_of, "fall", patient_id=file_of["ids"]["other_child"],
             told=True)

    with file_of["app"].app_context():
        assert education.said_told_but_never_taught(
            file_of["ids"]["child"]) == []


# -------------------------------------------------------------- الشاشة ----
def test_the_file_always_carries_the_tab(file_of):
    """`PCC.07` (أ) بيطلب تلاتة من **كل** ملف، فملف من غير تثقيف هو ملف ناقص
    — مش ملف الموضوع مالوش علاقة بيه. وده الاستثناء الوحيد من قاعدة «التبويب
    لازم يستاهل مكانه»."""
    body = file_of["sign_in"]("doc").get(
        f"/patients/{file_of['ids']['child']}").get_data(as_text=True)

    assert 'data-tab="education"' in body
    assert "data-education" in body


def test_the_screen_counts_the_gaps_and_the_ones_needing_a_second_go(file_of):
    _teach(file_of, topic="diagnosis", understood="no")

    body = file_of["sign_in"]("doc").get(
        f"/patients/{file_of['ids']['child']}").get_data(as_text=True)
    assert "data-education-again=" in body
    assert "data-education-gaps=" in body
    assert 'data-education-topic-state="again"' in body


def test_the_screen_shows_the_tick_without_teaching(file_of):
    _at_risk(file_of, "fall", told=True)

    body = file_of["sign_in"]("doc").get(
        f"/patients/{file_of['ids']['child']}").get_data(as_text=True)
    assert "data-education-ticked" in body


def test_a_finished_file_says_so_rather_than_showing_nothing(file_of):
    for topic in ("diagnosis", "care_plan", "discharge"):
        _teach(file_of, topic=topic, understood="yes")

    body = file_of["sign_in"]("doc").get(
        f"/patients/{file_of['ids']['child']}").get_data(as_text=True)
    assert 'data-education-state="done"' in body
    assert "data-education-gaps=" not in body


def test_the_three_answers_are_drawn_apart_on_the_row(file_of):
    _teach(file_of, topic="diagnosis", understood="")

    body = file_of["sign_in"]("doc").get(
        f"/patients/{file_of['ids']['child']}").get_data(as_text=True)
    assert 'data-education-understood="unsaid"' in body


def test_nothing_here_stands_between_a_child_and_a_visit(file_of):
    """بتقول، وعمرها ما بتمنع."""
    page = file_of["sign_in"]("doc").get(
        f"/patients/{file_of['ids']['child']}")

    assert page.status_code == 200


# ------------------------------- اللي طلع من مسح الطفرات (سبع فجوات) ----
# كل اختبار تحت ده كان **طفرة عاشت**: غيّرت سطر في الكود والـ٣٣ اختبار فضلوا
# خُضر. اللي بينهم أربعة من نفس الشكل — فلتر المريض — وده الشكل اللي بيعيش في
# كل مِلَفّ اتكتب في المشروع ده، لأن فيكستشر بطفل واحد بتخلّي «هات كل الصفوف»
# و«هات صفوف الطفل ده» نفس الجواب.
def test_a_confirmed_teaching_is_not_undone_by_a_failed_one_either(file_of):
    """أحسن صف بيكسب في الاتجاهين.

    الاختبار اللي فوق بيغطّي تأكيد بعده فاضي. ودي الحالة التانية: أهل ما
    فهموش أول مرة، ورجعنا شرحنا وفهموا. الموضوع ده **خلص** — وقراية بتقول
    «محتاج إعادة» بترجّع حد لباب اتقفل خلاص.
    """
    _teach(file_of, topic="care_plan", understood="no")
    _teach(file_of, topic="care_plan", understood="yes")

    assert _state_of(_owed(file_of), "care_plan") == "done"


def test_another_childs_blood_request_does_not_ask_this_child(file_of):
    from app.models import Patient
    from app.utils import blood

    with file_of["app"].app_context():
        blood.request(Patient.query.get(file_of["ids"]["other_child"]),
                      "prbc", "هيموجلوبين ٥")
        file_of["db"].session.commit()

    assert "blood" not in _topics(_owed(file_of))
    assert "blood" in _topics(_owed(file_of, file_of["ids"]["other_child"]))


def test_another_childs_consent_does_not_ask_this_child(file_of):
    from app.models import Consent

    with file_of["app"].app_context():
        file_of["db"].session.add(Consent(
            patient_id=file_of["ids"]["other_child"],
            consent_type="general", guardian_name="الأم"))
        file_of["db"].session.commit()

    assert "consent" not in _topics(_owed(file_of))
    assert "consent" in _topics(_owed(file_of, file_of["ids"]["other_child"]))


def test_one_childs_education_is_not_read_into_another_file(file_of):
    """أخطر الأربعة: من غير الفلتر ده، ملف طفل بيعرض تثقيف طفل تاني — ويقول
    إن المطلوب اتعمل وهو ما اتعملش."""
    from app.utils import education

    _teach(file_of, patient_id=file_of["ids"]["other_child"],
           topic="diagnosis", understood="yes")

    with file_of["app"].app_context():
        assert education.given(file_of["ids"]["child"]) == []
        assert len(education.given(file_of["ids"]["other_child"])) == 1
    assert _state_of(_owed(file_of), "diagnosis") == "none"


def test_a_topic_taught_without_a_check_is_not_counted_as_untaught(file_of):
    """`missing` هي الفجوات اللي **مفيش فيها ولا حاجة**.

    وموضوع اتشرح ومحدّش سأل فهموا ولا لأ مش فاضي — ده شغل اتعمل وناقصه سؤال،
    وحطّه في قايمة «ما اتقالش» بيخلّي حد يشرح تاني من الأول بدل ما يسأل.
    """
    from app.utils import education

    _teach(file_of, topic="diagnosis", understood="")
    _teach(file_of, topic="care_plan", understood="no")

    with file_of["app"].app_context():
        assert education.missing(file_of["ids"]["child"]) == ["discharge"]


def test_teaching_about_the_blood_clears_the_blood_finding(file_of):
    from app.models import Patient
    from app.utils import blood, education

    with file_of["app"].app_context():
        blood.request(Patient.query.get(file_of["ids"]["child"]), "prbc",
                      "نزيف", family_told=True)
        file_of["db"].session.commit()
    _teach(file_of, topic="blood", understood="yes")

    with file_of["app"].app_context():
        assert education.said_told_but_never_taught(
            file_of["ids"]["child"]) == []


def test_a_blood_request_with_no_tick_on_it_is_not_this_finding(file_of):
    """الملاحظة دي اسمها «اتقال إنه اتبلّغ من غير ما يتعلّم» — فمن غير «اتقال»
    مفيش ملاحظة. طلب دم لسه محدّش كلّم أهله فجوة في `owed`، **مش** تناقض."""
    from app.models import Patient
    from app.utils import blood, education

    with file_of["app"].app_context():
        blood.request(Patient.query.get(file_of["ids"]["child"]), "prbc",
                      "نزيف")
        file_of["db"].session.commit()
        assert education.said_told_but_never_taught(
            file_of["ids"]["child"]) == []
        assert "blood" in education.missing(file_of["ids"]["child"])


def test_no_topic_is_asked_for_twice_however_many_reasons_it_has(file_of):
    """طفرتان عاشتا **وهما مكافئتان**، ومكتوبين هنا علشان محدّش يدوّر عليهم
    تاني: (١) شيل الـ`if topic not in topics` في `owed`، و(٢) شيل
    `if not patient_id` في `given`.

    الأولى: المواضيع المشروطة مالهاش تقاطع لا مع بعضها ولا مع التلاتة
    الواجبين، فمفيش طريق بيكرّر موضوع النهاردة — والـ`if` دفاع عن بكرة.
    والتانية: `patient_id == None` في SQL بيرجع صفر صفوف أصلاً، فالحارس
    بيوفّر استعلام مش بيغيّر جواب.

    واللي بيتختبر هو **الخاصية** اللي الاتنين موجودين علشانها.
    """
    from app.models import Consent, Patient
    from app.utils import blood, education

    _at_risk(file_of, "fall", told=True)
    _at_risk(file_of, "vte")
    with file_of["app"].app_context():
        blood.request(Patient.query.get(file_of["ids"]["child"]), "prbc",
                      "نزيف")
        file_of["db"].session.add(Consent(
            patient_id=file_of["ids"]["child"], consent_type="general",
            guardian_name="الأب"))
        file_of["db"].session.commit()

    topics = _topics(_owed(file_of))
    assert len(topics) == len(set(topics))
    with file_of["app"].app_context():
        assert education.given(None) == []


# ------------------------------------------- وباب من برّة الملف الواحد ----
# «بتعمل الشغل وتنسى تحط باب ليه». التبويب بيجاوب عن الطفل اللي قدّامك، والحاجتين
# اللي بيطلّعهم مهمّتين على حد **مش في الأوضة** — فمحتاجين شاشة للعيادة كلها.
def _board(clinic):
    return clinic["sign_in"]("doc").get("/patients/education")


def test_the_clinic_can_see_who_did_not_understand(file_of):
    _teach(file_of, topic="diagnosis", understood="no")

    page = _board(file_of)

    assert page.status_code == 200
    assert b"data-education-again-row" in page.data


def test_the_board_leaves_out_the_ones_that_landed(file_of):
    _teach(file_of, topic="diagnosis", understood="yes")
    _teach(file_of, topic="care_plan", understood="")

    assert b"data-education-again-row" not in _board(file_of).data


def test_the_clinic_can_see_the_ticks_with_nothing_behind_them(file_of):
    _at_risk(file_of, "fall", told=True)

    page = _board(file_of)

    assert b"data-education-ticked-row" in page.data
    assert "طفل".encode() in page.data


def test_teaching_takes_the_child_off_the_ticked_board(file_of):
    _at_risk(file_of, "fall", told=True)
    _teach(file_of, topic="fall", understood="yes")

    assert b"data-education-ticked-row" not in _board(file_of).data


def test_the_board_scans_the_ticks_not_every_file_in_the_clinic(file_of):
    """الفرق بين شاشة بتشتغل في عيادة فيها عشرة آلاف ملف وشاشة بتقفل.

    الأطفال اللي ممكن تظهر عليهم الملاحظة دي هُمّا بالظبط اللي عليهم علامة
    «الأهل اتقالهم» — فالمسح على العلامات، مش على المرضى. وطفل مالوش أي علامة
    ما بيتقراش أصلاً.
    """
    from app.utils import education

    _at_risk(file_of, "fall", told=True)
    _at_risk(file_of, "vte", patient_id=file_of["ids"]["other_child"],
             told=False)

    with file_of["app"].app_context():
        found = education.ticked_but_never_taught()

    assert [item["patient"].id for item in found] == [file_of["ids"]["child"]]
    assert found[0]["topics"] == ["fall"]


def test_a_tick_that_says_no_is_never_even_looked_at(file_of):
    """حارس على مستويين، والاتنين بيتختبروا.

    الفلتر اللي على المسح (`family_told.is_(True)`) والفلتر اللي جوّه
    (`said_told_but_never_taught`) بيقولوا نفس الحاجة — فطفرة بتوسّع الأول
    عاشت، لأن التاني بيرجع فاضي والطفل بيتشال. **وده مش سبب نشيل واحد فيهم:
    «حارس من ناحية واحدة نص قاعدة».** الجوّاني بيتختبر فوق
    (`test_a_tick_that_says_no_is_not_a_finding`)، والبرّاني هو اللي بيخلّي
    الشاشة تفتح في عيادة كبيرة — فبيتقاس بالتكلفة، لأن ده اللي هو موجود
    علشانه.
    """
    from sqlalchemy import event
    from sqlalchemy.engine import Engine

    from app.models.risk_assessment import RiskAssessment
    from app.utils import education

    def cost():
        seen = []

        def note(conn, cursor, statement, params, context, many):
            seen.append(statement)

        event.listen(Engine, "before_cursor_execute", note)
        try:
            found = education.ticked_but_never_taught()
        finally:
            event.remove(Engine, "before_cursor_execute", note)
        return found, len(seen)

    _at_risk(file_of, "fall", told=True)
    with file_of["app"].app_context():
        education.ticked_but_never_taught()      # أول مرة بتدفع تمن الإعداد
        one_tick, one_cost = cost()
        for kind in ("pressure", "vte"):
            file_of["db"].session.add(RiskAssessment(
                patient_id=file_of["ids"]["other_child"], kind=kind,
                at=datetime.utcnow(), at_risk=True, family_told=False))
        file_of["db"].session.commit()
        two_no, two_cost = cost()

    assert [i["patient"].id for i in one_tick] == [file_of["ids"]["child"]]
    assert [i["patient"].id for i in two_no] == [file_of["ids"]["child"]]
    assert two_cost == one_cost, (
        f"{one_cost} استعلام مع علامة واحدة و{two_cost} بعد تلات علامات "
        "«لأ» — المسح بيقرا أطفال محدّش قال عنهم حاجة")


def test_the_board_needs_the_medical_capability(file_of):
    """الشاشة بتعرض أسامي أطفال ومواضيع تثقيفهم — دي نفس الداتا اللي في الملف،
    فبتاخد نفس الباب."""
    page = file_of["sign_in"]("desk").get("/patients/education")

    assert page.status_code in (302, 403)


# --------------------------------------------------------------- الكلام ----
def test_every_education_word_is_written_in_both_languages(file_of):
    from app.i18n import _load_translations, _lookup
    from app.models.patient_education import METHODS, TOPICS
    from app.utils.education import TOPIC_STATES

    tables = _load_translations()
    keys = ["title", "none_yet", "add", "saved", "not_saved", "topic",
            "detail", "detail_ph", "method", "interpreter", "interpreter_q",
            "understood", "n_missing", "n_again", "all_done",
            "ticked_not_taught", "by", "at", "yes", "no", "unsaid",
            "board_title", "board_sub", "board_again", "board_again_hint",
            "board_again_clear", "board_ticked", "board_ticked_hint",
            "board_ticked_clear", "board_topics", "board_open", "when"]
    keys += [f"topic_{t}" for t in TOPICS]
    keys += [f"method_{m}" for m in METHODS]
    keys += [f"state_{s}" for s in TOPIC_STATES]
    for key in keys:
        for lang in ("ar", "en"):
            assert _lookup(tables, lang, f"education.{key}"), f"{lang}:{key}"
    for lang in ("ar", "en"):
        assert _lookup(tables, lang, "patients.tab_education")
