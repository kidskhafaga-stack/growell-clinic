"""الطلب بيقول هو مين وليه — GAHAR `ICD.17`.

> a) Name of the ordering medical staff members. b) Date and time of order.
> c) Patient identification, age, and sex. d) Clinical reason for ordering.
> e) Site and laterality for medical imaging studies.
> f) Prompt authentication by the ordering medical staff members.

أربعة كانوا في السجل أصلاً (الوقت، والطفل، والسبب من تشخيص الزيارة، واللي
طلب من الزيارة). والاتنين اللي كانوا ناقصين فعلاً: **الناحية للأشعة**،
**ومين دخّل الطلب** — ومن غيره (و) ما كانش ينفع يتقال.
"""
import os
import sys
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


def _visit_id(clinic):
    return clinic["ids"]["visit"]


def _request(clinic, user="doc", **form):
    """طلب من الشاشة نفسها — علشان (أ) بيتقري من اللوج مش من فورم."""
    data = {"kind": "lab", "name": "CBC"}
    data.update(form)
    clinic["sign_in"](user).post(
        f"/visits/{_visit_id(clinic)}/investigations", data=data)
    from app.models import VisitInvestigation

    with clinic["app"].app_context():
        return (VisitInvestigation.query
                .order_by(VisitInvestigation.id.desc()).first().id)


def _row(clinic, inv_id):
    from app.models import VisitInvestigation

    return clinic["db"].session.get(VisitInvestigation, inv_id)


# ============ (أ) و(و) — مين طلب، ومتوثّق ولا لأ ============
def test_the_request_remembers_who_entered_it(clinic):
    inv_id = _request(clinic, "doc")
    from app.models import User

    with clinic["app"].app_context():
        row = _row(clinic, inv_id)
        assert row.ordered_by == User.query.filter_by(username="doc").one().id


def test_a_doctor_s_own_request_is_authenticated_as_it_is_written(clinic):
    """اتكتب بلوج الطبيب — **متوثّق ساعة ما اتكتب**، من غير زرار زيادة."""
    from app.utils import order_check

    inv_id = _request(clinic, "doc")
    with clinic["app"].app_context():
        row = _row(clinic, inv_id)
        assert order_check.authenticated(row) is True
        assert "authenticated" not in order_check.missing(row)


def test_someone_who_does_not_see_patients_leaves_it_awaiting_a_doctor(clinic):
    """أدمن مش بيكشف دخّل الطلب — ده مش طلب طبيب لسه."""
    from app.utils import order_check

    inv_id = _request(clinic, "boss")
    with clinic["app"].app_context():
        row = _row(clinic, inv_id)
        assert order_check.authenticated(row) is False
        assert "authenticated" in order_check.missing(row)


def test_a_doctor_confirms_it_and_it_is_complete(clinic):
    from app.models import User
    from app.utils import order_check

    inv_id = _request(clinic, "boss")
    with clinic["app"].app_context():
        row = _row(clinic, inv_id)
        doc = User.query.filter_by(username="doc").one()
        order_check.confirm(row, doc)
        clinic["db"].session.commit()
        assert row.confirmed_by == doc.id
        assert order_check.authenticated(row) is True


def test_the_one_who_entered_it_cannot_confirm_it(clinic):
    """نفس قاعدة `VerbalOrder`: لو اللي كتب هو اللي وقّع، مبقاش فيه حد
    تاني قال حاجة."""
    from app.models import User
    from app.utils import order_check

    inv_id = _request(clinic, "boss")
    with clinic["app"].app_context():
        row = _row(clinic, inv_id)
        boss = User.query.filter_by(username="boss").one()
        boss.is_practitioner = True          # حتى لو بقى بيكشف بعدين
        with pytest.raises(PermissionError):
            order_check.confirm(row, boss)


def test_only_a_practitioner_confirms(clinic):
    from app.models import User
    from app.utils import order_check

    inv_id = _request(clinic, "boss")
    with clinic["app"].app_context():
        row = _row(clinic, inv_id)
        desk = User.query.filter_by(username="desk").one()
        with pytest.raises(PermissionError):
            order_check.confirm(row, desk)


def test_an_old_request_nobody_recorded_is_not_called_incomplete(clinic):
    """**`None` = محدّش سجّل**، مش «ناقص». الصف ده من قبل ما السؤال يتسأل،
    وعدّه ناقص كان هيملّي القايمة بكل تاريخ العيادة."""
    from app.models import VisitInvestigation
    from app.utils import order_check

    with clinic["app"].app_context():
        row = VisitInvestigation(visit_id=_visit_id(clinic),
                                 patient_id=clinic["ids"]["child"],
                                 kind="lab", name="CRP")
        clinic["db"].session.add(row)
        clinic["db"].session.commit()

        assert order_check.authenticated(row) is None
        assert "authenticated" not in order_check.missing(row)
        # ومين طلب بيتقري من الزيارة — **وبيقول إنه اتقري منها**.
        who, source = order_check.orderer(row)
        assert who is not None and source == "visit"


# ============ (د) السبب ============
def test_the_note_is_the_reason_when_there_is_one(clinic):
    from app.utils import order_check

    inv_id = _request(clinic, "doc", request_notes="شك في أنيميا")
    with clinic["app"].app_context():
        assert order_check.reason(_row(clinic, inv_id)) == \
            ("شك في أنيميا", "note")


def test_otherwise_the_visit_s_own_diagnosis_is(clinic):
    """**البرنامج ما بيخترعش سبب** — بيقرا كلام الطبيب نفسه. طبيب كاتب
    «التهاب رئوي» فوق وطالب «أشعة صدر» تحت كتب السبب فعلاً."""
    from app.models import Diagnosis
    from app.utils import order_check

    inv_id = _request(clinic, "doc")
    with clinic["app"].app_context():
        clinic["db"].session.add(Diagnosis(visit_id=_visit_id(clinic),
                                           code="J18", title="التهاب رئوي",
                                           dx_type="working"))
        clinic["db"].session.commit()
        text, source = order_check.reason(_row(clinic, inv_id))
        assert text == "التهاب رئوي" and source == "diagnosis"


def test_the_final_diagnosis_beats_the_working_one(clinic):
    from app.models import Diagnosis
    from app.utils import order_check

    inv_id = _request(clinic, "doc")
    with clinic["app"].app_context():
        for title, kind in (("حرارة", "working"), ("التهاب لوز", "final")):
            clinic["db"].session.add(Diagnosis(visit_id=_visit_id(clinic),
                                               code="X", title=title,
                                               dx_type=kind))
        clinic["db"].session.commit()
        assert order_check.reason(_row(clinic, inv_id))[0] == "التهاب لوز"


def test_no_note_and_no_diagnosis_is_a_missing_reason(clinic):
    from app.utils import order_check

    inv_id = _request(clinic, "doc")
    with clinic["app"].app_context():
        assert "reason" in order_check.missing(_row(clinic, inv_id))


# ============ (هـ) الناحية ============
def test_an_x_ray_without_a_side_is_incomplete(clinic):
    from app.utils import order_check

    inv_id = _request(clinic, "doc", kind="imaging", name="X-ray forearm")
    with clinic["app"].app_context():
        assert "side" in order_check.missing(_row(clinic, inv_id))


def test_a_side_given_with_the_request_is_kept(clinic):
    inv_id = _request(clinic, "doc", kind="imaging", name="X-ray forearm",
                      laterality="left")
    with clinic["app"].app_context():
        assert _row(clinic, inv_id).laterality == "left"


def test_no_side_is_an_answer_not_a_gap(clinic):
    """أشعة صدر مالهاش ناحية — **وده مختلف عن «محدّش قال»**."""
    from app.utils import order_check

    inv_id = _request(clinic, "doc", kind="imaging", name="CXR",
                      laterality="none")
    with clinic["app"].app_context():
        assert "side" not in order_check.missing(_row(clinic, inv_id))


def test_a_lab_never_asks_for_a_side(clinic):
    from app.utils import order_check

    inv_id = _request(clinic, "doc", kind="lab", laterality="left")
    with clinic["app"].app_context():
        row = _row(clinic, inv_id)
        # اتبعتت، واتسابت — تحليل دم مالوش ناحية.
        assert row.laterality is None
        assert "side" not in order_check.missing(row)
        with pytest.raises(ValueError):
            order_check.set_side(row, "left")


def test_an_unknown_side_is_refused(clinic):
    from app.utils import order_check

    inv_id = _request(clinic, "doc", kind="imaging", name="US hip")
    with clinic["app"].app_context():
        with pytest.raises(ValueError):
            order_check.set_side(_row(clinic, inv_id), "up")


# ============ (ج) الطفل ============
def test_a_child_whose_sex_is_blank_makes_the_request_incomplete(clinic):
    """تاريخ الميلاد إجباري في قاعدة البيانات، فالسن دايماً موجود. النوع
    برضه `NOT NULL` — بس فاضي (`""`) بيعدّي، وده اللي بيتقري ناقص."""
    from app.models import Patient
    from app.utils import order_check

    inv_id = _request(clinic, "doc")
    with clinic["app"].app_context():
        clinic["db"].session.get(Patient, clinic["ids"]["child"]).gender = ""
        clinic["db"].session.commit()
        assert "patient" in order_check.missing(_row(clinic, inv_id))


# ============ دليل ٣ — القايمة ============
def test_the_list_holds_only_what_is_incomplete(clinic):
    from app.models import Diagnosis
    from app.utils import order_check

    with clinic["app"].app_context():
        clinic["db"].session.add(Diagnosis(visit_id=_visit_id(clinic),
                                           code="J18", title="التهاب رئوي",
                                           dx_type="working"))
        clinic["db"].session.commit()
    complete = _request(clinic, "doc")
    no_side = _request(clinic, "doc", kind="imaging", name="X-ray knee")

    with clinic["app"].app_context():
        ids = {row.id for row, _gaps in order_check.incomplete()}
        assert no_side in ids
        assert complete not in ids


def test_the_list_looks_back_thirty_days(clinic):
    from app.utils import order_check

    inv_id = _request(clinic, "doc", kind="imaging", name="X-ray knee")
    with clinic["app"].app_context():
        _row(clinic, inv_id).created_at = datetime.utcnow() - timedelta(days=45)
        clinic["db"].session.commit()
        assert inv_id not in {r.id for r, _g in order_check.incomplete()}


# ============ الشاشة ============
def test_the_visit_screen_says_who_ordered_it_and_what_is_missing(clinic):
    inv_id = _request(clinic, "doc", kind="imaging", name="X-ray forearm")
    html = clinic["sign_in"]("doc").get(
        f"/visits/{_visit_id(clinic)}/record").get_data(as_text=True)
    line = html.split(f'data-inv-order="{inv_id}"')[1].split("</div>")[0]
    assert "د. أحمد" in line
    assert 'data-inv-missing="side"' in line


def test_the_side_is_set_on_the_same_line(clinic):
    """اللي شاف الفجوة هو اللي بيقفلها — مش بيتبعت لشاشة تانية."""
    from app.utils import order_check

    inv_id = _request(clinic, "doc", kind="imaging", name="X-ray forearm")
    html = clinic["sign_in"]("doc").get(
        f"/visits/{_visit_id(clinic)}/record").get_data(as_text=True)
    assert f"/visits/investigations/{inv_id}/side" in html

    clinic["sign_in"]("doc").post(f"/visits/investigations/{inv_id}/side",
                                  data={"laterality": "right"})
    with clinic["app"].app_context():
        row = _row(clinic, inv_id)
        assert row.laterality == "right"
        assert "side" not in order_check.missing(row)


def test_a_doctor_sees_confirm_and_the_one_who_entered_it_does_not(clinic):
    inv_id = _request(clinic, "boss")
    for_doc = clinic["sign_in"]("doc").get(
        f"/visits/{_visit_id(clinic)}/record").get_data(as_text=True)
    for_boss = clinic["sign_in"]("boss").get(
        f"/visits/{_visit_id(clinic)}/record").get_data(as_text=True)
    button = f"/visits/investigations/{inv_id}/confirm"
    assert button in for_doc
    assert button not in for_boss


def test_confirming_from_the_screen(clinic):
    from app.utils import order_check

    inv_id = _request(clinic, "boss")
    clinic["sign_in"]("doc").post(f"/visits/investigations/{inv_id}/confirm")
    with clinic["app"].app_context():
        assert order_check.authenticated(_row(clinic, inv_id)) is True


def test_the_screen_refuses_the_enterer_s_own_confirmation(clinic):
    from app.utils import order_check

    inv_id = _request(clinic, "boss")
    clinic["sign_in"]("boss").post(f"/visits/investigations/{inv_id}/confirm")
    with clinic["app"].app_context():
        assert order_check.authenticated(_row(clinic, inv_id)) is False


def test_an_ecg_is_not_labelled_an_x_ray(clinic):
    """الشارة كانت بتقرا «تحليل، وإلا أشعة» — فالنوع التالت اتسمّى أشعة."""
    import json

    ar = json.load(open("app/i18n/locales/ar.json", encoding="utf-8"))
    inv_id = _request(clinic, "doc", kind="diagnostic", name="ECG")
    html = clinic["sign_in"]("doc").get(
        f"/visits/{_visit_id(clinic)}/record").get_data(as_text=True)
    card = html.split(f'data-inv-order="{inv_id}"')[0].rsplit("ECG", 1)[0]
    badge = card.rsplit('<span class="badge', 1)[1]
    assert ar["rx"]["inv_diagnostic"] in badge


def test_the_incomplete_list_screen(clinic):
    inv_id = _request(clinic, "doc", kind="imaging", name="X-ray knee")
    html = clinic["sign_in"]("doc").get(
        "/visits/requests/incomplete").get_data(as_text=True)
    assert f'data-incomplete="{inv_id}"' in html


def test_a_locked_doctor_sees_only_their_own_incomplete_requests(clinic):
    """نفس قفل قايمة الزيارات: الطلبات ناقصة ولا لأ، لسه بتاعة طبيب تاني."""
    from app.models import User, Visit

    with clinic["app"].app_context():
        other = User(username="doc2", full_name="د. منى", role="doctor",
                     is_active=True)
        other.set_password("secret")
        clinic["db"].session.add(other)
        clinic["db"].session.flush()
        theirs = Visit(patient_id=clinic["ids"]["child"], doctor_id=other.id,
                       visit_date=date.today())
        clinic["db"].session.add(theirs)
        clinic["db"].session.commit()
        their_visit = theirs.id

    clinic["sign_in"]("doc2").post(f"/visits/{their_visit}/investigations",
                                   data={"kind": "imaging", "name": "X-ray"})
    html = clinic["sign_in"]("doc").get(
        "/visits/requests/incomplete").get_data(as_text=True)
    assert "data-incomplete=" not in html


# ============ الروشتة ============
def test_the_side_travels_to_the_paper_the_family_carries(clinic):
    """**الورقة دي هي اللي بتروح مركز الأشعة.**"""
    from app.models import Prescription

    _request(clinic, "doc", kind="imaging", name="X-ray forearm",
             laterality="left")
    page = clinic["sign_in"]("doc").get(
        f"/prescriptions/new?patient_id={clinic['ids']['child']}"
        f"&visit_id={_visit_id(clinic)}").get_data(as_text=True)
    assert '"side": "left"' in page or "&#34;side&#34;: &#34;left&#34;" in page

    clinic["sign_in"]("doc").post(
        "/prescriptions/new",
        data={"patient_id": clinic["ids"]["child"],
              "visit_id": _visit_id(clinic), "diagnosis": "كسر",
              "inv_kind": ["imaging"], "inv_name": ["X-ray forearm"],
              "inv_notes": [""], "inv_id": [""], "inv_outside": ["0"],
              "inv_side": ["left"]})
    with clinic["app"].app_context():
        rx = Prescription.query.order_by(Prescription.id.desc()).first()
        assert rx is not None
        assert rx.investigations[0].laterality == "left"
        rx_id = rx.id

    paper = clinic["sign_in"]("doc").get(
        f"/prescriptions/{rx_id}").get_data(as_text=True)
    assert "data-paper-side" in paper


def test_every_word_is_written_in_both_languages():
    import json

    ar = json.load(open("app/i18n/locales/ar.json", encoding="utf-8"))
    en = json.load(open("app/i18n/locales/en.json", encoding="utf-8"))
    assert set(ar["orders"]) == set(en["orders"])
    for key in ar["orders"]:
        assert ar["orders"][key].strip(), key
        assert en["orders"][key].strip(), key
    from app.models.visit import SIDES
    from app.utils.order_check import ELEMENTS

    for side in SIDES:
        assert f"side_{side}" in ar["orders"], side
    for element in ELEMENTS:
        assert f"missing_{element}" in ar["orders"], element
