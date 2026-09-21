"""رفض مستنير — GAHAR `PCC.10`.

**البرنامج كان عارف إن الأهل رفضوا من زمان.** `self_discharge` موجودة في
مآلات الطوارئ وفي مخارج الإقامة. اللي مكانش موجود هو الإجابة على السؤال
اللي المعيار بيسأله فعلاً: **حد قالهم إيه اللي ممكن يحصل؟**

والسياسة بتعدّد أربعة، ودليل ٢ بيطلب إن الاستمارة تحتويهم **كلهم**:
حالته دلوقتي (أ) · عواقب القرار (ب) · بيرفضوا إيه بالظبط (ج) · والبدايل
(د). فالملف ده بيثبّت إنهم أربعة، وإن «رفض» من غيرهم مش «رفض مستنير» —
ده خروج، والبرنامج كان بيسجّل التاني وبيسمّيه الأول.
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def ward(clinic):
    from app.models import Setting

    with clinic["app"].app_context():
        Setting.set("mod_enabled:beds", "1")
        Setting.set("mod_enabled:emergency", "1")
        clinic["db"].session.commit()
    return clinic


def _refuse(ward, kind="step", **fields):
    from app.models import Patient, User
    from app.utils import refusal as no

    with ward["app"].app_context():
        patient = ward["db"].session.get(Patient, ward["ids"]["child"])
        doc = ward["db"].session.get(User, ward["ids"]["doctor"])
        row = no.record(patient, kind, user=doc, explained_by=doc, **fields)
        ward["db"].session.commit()
        return row.id


def _row(ward, rid):
    from app.models import Refusal

    return ward["db"].session.get(Refusal, rid)


def _full():
    return {"condition": "التهاب رئوي محتاج أكسجين",
            "consequences": "ممكن يتعب أكتر ويحتاج عناية",
            "refused": "رفضوا الدخول والمبيت",
            "alternatives": "متابعة يومية في العيادة + أكسجين بيتي"}


# ------------------------------------- الأربعة، وكل واحدة لوحدها ----
def test_a_refusal_with_nothing_written_is_missing_all_four(ward):
    from app.utils import refusal as no

    rid = _refuse(ward)

    with ward["app"].app_context():
        row = _row(ward, rid)
        assert no.missing(row) == ["condition", "consequences", "refused",
                                   "alternatives"]
        assert not row.informed


def test_each_element_answers_only_itself(ward):
    """علامة واحدة اسمها «رفضوا وعارفين» مش استمارة، دي جملة."""
    from app.utils import refusal as no

    for name in ("condition", "consequences", "refused", "alternatives"):
        rid = _refuse(ward, **{name: "اتقال"})
        with ward["app"].app_context():
            gaps = no.missing(_row(ward, rid))
            assert name not in gaps
            assert len(gaps) == 3


def test_all_four_is_what_makes_it_informed(ward):
    from app.utils import refusal as no

    rid = _refuse(ward, **_full())

    with ward["app"].app_context():
        row = _row(ward, rid)
        assert no.missing(row) == []
        assert row.informed
        assert no.incomplete() == []


def test_the_consequences_are_what_separate_a_refusal_from_an_informed_one(
        ward):
    """**دي الحتة كلها.** طفل خرج والأهل ما اتقالّهمش إيه اللي ممكن يحصل
    ده مش رفض مستنير — ده خروج."""
    from app.utils import refusal as no

    nearly = dict(_full())
    nearly.pop("consequences")
    rid = _refuse(ward, **nearly)

    with ward["app"].app_context():
        row = _row(ward, rid)
        assert not row.informed
        assert no.missing(row) == ["consequences"]


def test_no_alternative_is_an_answer_and_an_empty_box_is_not(ward):
    """«مفيش بديل» إجابة، و«محدّش سأل» إجابة تانية — والعمود الواحد
    اللي بيخلطهم بيخلّي التانية تبان زي الأولى."""
    from app.utils import refusal as no

    said = _refuse(ward, alternatives="مفيش بديل آمن غير الدخول")
    silent = _refuse(ward)

    with ward["app"].app_context():
        assert "alternatives" not in no.missing(_row(ward, said))
        assert "alternatives" in no.missing(_row(ward, silent))


def test_a_part_save_does_not_wipe_what_it_did_not_send(ward):
    from app.utils import refusal as no

    rid = _refuse(ward, **_full())

    with ward["app"].app_context():
        no.describe(_row(ward, rid), consequences="اتعدّلت")
        ward["db"].session.commit()

        row = _row(ward, rid)
        assert row.consequences == "اتعدّلت"
        assert row.condition == _full()["condition"]
        assert row.alternatives == _full()["alternatives"]


# ------------------------------------------- التلات أنواع ----
def test_the_three_kinds_the_intent_names_are_kept_apart(ward):
    """النية بتسمّيهم بالنص: رفض خطوة · خروج ضد النصيحة · سيبان الطوارئ.
    واللي بيتقال للأهل بيختلف في التلاتة."""
    from app.models import REFUSAL_KINDS

    assert REFUSAL_KINDS == ("step", "discharge", "emergency")
    for kind in REFUSAL_KINDS:
        rid = _refuse(ward, kind=kind)
        with ward["app"].app_context():
            assert _row(ward, rid).kind == kind


def test_a_kind_the_record_cannot_draw_is_refused(ward):
    from app.models import Patient
    from app.utils import refusal as no

    with ward["app"].app_context():
        patient = ward["db"].session.get(Patient, ward["ids"]["child"])
        with pytest.raises(ValueError):
            no.record(patient, "whatever")


def test_a_refusal_with_no_child_is_refused(ward):
    from app.utils import refusal as no

    with ward["app"].app_context():
        with pytest.raises(ValueError):
            no.record(None, "step")


# ------------------------------------------- مين رفض، والتوقيع ----
def test_in_paediatrics_the_one_who_refuses_is_the_guardian(ward):
    """دليل ٤: الاستمارة من حد غير المريض لازم تمشي مع القانون — وفي
    طب الأطفال دي الحالة العادية مش الاستثناء."""
    rid = _refuse(ward, guardian_name="أم الطفل", guardian_relation="mother",
                  guardian_id_no="2900101234567")

    with ward["app"].app_context():
        row = _row(ward, rid)
        assert row.guardian_name == "أم الطفل"
        assert row.guardian_relation == "mother"
        assert row.guardian_id_no == "2900101234567"


def test_the_two_kinds_of_signature_are_not_the_same_thing(ward):
    """نفس قاعدة `Consent`: ورقة موقّعة ومتصوّرة أقوى من توقيع على
    الشاشة، والسجل بيقول أنهي واحدة عنده بدل ما يخلطهم."""
    from app.utils import refusal as no

    rid = _refuse(ward, **_full())

    with ward["app"].app_context():
        row = _row(ward, rid)
        assert not row.has_signature
        assert rid in [r.id for r in no.unsigned()]

        no.sign(row, "paper", path="refusals/1.jpg")
        ward["db"].session.commit()

        row = _row(ward, rid)
        assert row.signature_kind == "paper"
        assert row.has_signature
        assert no.unsigned() == []


def test_a_signature_kind_the_record_does_not_know_is_refused(ward):
    from app.utils import refusal as no

    rid = _refuse(ward)
    with ward["app"].app_context():
        with pytest.raises(ValueError):
            no.sign(_row(ward, rid), "verbal")
        assert _row(ward, rid).signature_kind is None


def test_who_explained_is_not_who_typed_it(ward):
    """نفس فرق `Consent`: `recorded_by` الحساب اللي كتب الصف، و
    `explained_by` اللي قعد مع الأهل وقالهم."""
    from app.models import Patient, User
    from app.utils import refusal as no

    with ward["app"].app_context():
        patient = ward["db"].session.get(Patient, ward["ids"]["child"])
        doc = ward["db"].session.get(User, ward["ids"]["doctor"])
        desk = ward["db"].session.get(User, ward["ids"]["desk"])
        row = no.record(patient, "step", user=desk, explained_by=doc)
        ward["db"].session.commit()

        assert row.recorded_by_id == desk.id
        assert row.explained_by_id == doc.id


# ============================================================
# القراية اللي مكانش ينفع تتسأل قبل كده
# ============================================================
def _admit_and_self_discharge(ward):
    from app.models import Admission, Patient
    from app.models.place import Bed, Space, Unit
    from app.utils import beds as place

    with ward["app"].app_context():
        unit = Unit(name="الداخلي", kind="ward")
        ward["db"].session.add(unit)
        ward["db"].session.flush()
        space = Space(unit_id=unit.id, name="الصالة", kind="bay")
        ward["db"].session.add(space)
        ward["db"].session.flush()
        bed = Bed(space_id=space.id, name="سرير ١", kind="bed")
        ward["db"].session.add(bed)
        ward["db"].session.flush()
        stay = place.admit(
            ward["db"].session.get(Patient, ward["ids"]["child"]), bed)
        ward["db"].session.commit()
        stay = ward["db"].session.get(Admission, stay.id)
        stay.outcome = "self_discharge"
        ward["db"].session.commit()
        return stay.id


def test_a_child_who_left_against_advice_with_no_form_is_found(ward):
    """**السؤال اللي المعيار موجود علشانه.**

    البرنامج كان عارف إن الطفل مشي — `self_discharge` موجودة من زمان —
    وما كانش عنده الطرف التاني من المقارنة، فالسؤال ده مكانش ينفع
    يتسأل أصلاً.
    """
    from app.utils import refusal as no

    stay = _admit_and_self_discharge(ward)

    with ward["app"].app_context():
        gaps = no.undocumented()
        assert [g["row"].id for g in gaps] == [stay]
        assert gaps[0]["what"] == "discharge"
        assert gaps[0]["patient"].id == ward["ids"]["child"]


def test_and_stops_being_found_once_the_form_exists(ward):
    from app.models import Admission, Patient, User
    from app.utils import refusal as no

    stay_id = _admit_and_self_discharge(ward)

    with ward["app"].app_context():
        stay = ward["db"].session.get(Admission, stay_id)
        patient = ward["db"].session.get(Patient, ward["ids"]["child"])
        doc = ward["db"].session.get(User, ward["ids"]["doctor"])
        no.record(patient, "discharge", user=doc, admission=stay, **_full())
        ward["db"].session.commit()

        assert no.undocumented() == []


def test_an_ordinary_discharge_is_not_a_refusal(ward):
    """طفل خرج عادي مش ناقصه استمارة رفض."""
    from app.models import Admission
    from app.utils import refusal as no

    stay_id = _admit_and_self_discharge(ward)
    with ward["app"].app_context():
        ward["db"].session.get(Admission, stay_id).outcome = "home"
        ward["db"].session.commit()

        assert no.undocumented() == []


def _er(ward, disposition):
    from app.models import EmergencyVisit

    with ward["app"].app_context():
        row = EmergencyVisit(patient_id=ward["ids"]["child"],
                             disposition=disposition)
        ward["db"].session.add(row)
        ward["db"].session.commit()
        return row.id


def test_leaving_the_emergency_room_counts_too(ward):
    from app.utils import refusal as no

    rid = _er(ward, "self_discharge")

    with ward["app"].app_context():
        gaps = no.undocumented()
        assert [g["row"].id for g in gaps] == [rid]
        assert gaps[0]["what"] == "emergency"


def test_and_leaving_before_anybody_saw_them_counts_worst(ward):
    """محدّش حتى قابله علشان يقوله حاجة — ودي أوحش حالة في القايمة."""
    from app.utils import refusal as no

    rid = _er(ward, "left_unseen")

    with ward["app"].app_context():
        assert [g["row"].id for g in no.undocumented()] == [rid]


def test_an_admitted_child_is_not_on_the_list(ward):
    from app.utils import refusal as no

    _er(ward, "admitted")

    with ward["app"].app_context():
        assert no.undocumented() == []


def test_the_short_list_names_what_is_missing(ward):
    from app.utils import refusal as no

    rid = _refuse(ward, condition="التهاب رئوي")

    with ward["app"].app_context():
        short = no.incomplete()
        assert [i["record"].id for i in short] == [rid]
        assert short[0]["missing"] == ["consequences", "refused",
                                       "alternatives"]


def test_another_childs_refusal_is_not_this_ones(ward):
    from app.models import Patient, User
    from app.utils import refusal as no
    from app.utils.clock import local_today

    with ward["app"].app_context():
        other = Patient(patient_number="RF-2", full_name="طفل تاني",
                        gender="male", is_active=True,
                        date_of_birth=local_today() - timedelta(days=700))
        ward["db"].session.add(other)
        ward["db"].session.flush()
        doc = ward["db"].session.get(User, ward["ids"]["doctor"])
        no.record(other, "step", user=doc)
        ward["db"].session.commit()

        assert no.for_patient(ward["ids"]["child"]) == []
        assert len(no.for_patient(other.id)) == 1


def test_the_newest_refusal_comes_first(ward):
    from app.utils import refusal as no

    old = _refuse(ward, at=datetime.utcnow() - timedelta(days=3))
    new = _refuse(ward)

    with ward["app"].app_context():
        assert [r.id for r in no.for_patient(ward["ids"]["child"])] == \
            [new, old]


# ================================================ الباب ====
def test_a_child_with_no_refusal_has_no_tab(ward):
    page = ward["sign_in"]("doc").get(
        f"/patients/{ward['ids']['child']}").get_data(as_text=True)

    assert "'refusal','tab_refusal'" not in page
    assert "data-refusal=" not in page


def test_the_file_shows_the_form_and_names_what_is_missing(ward):
    rid = _refuse(ward, condition="التهاب رئوي")

    page = ward["sign_in"]("doc").get(
        f"/patients/{ward['ids']['child']}").get_data(as_text=True)

    assert f'data-refusal="{rid}"' in page
    assert "data-refusal-gaps" in page
    for gap in ("consequences", "refused", "alternatives"):
        assert f'data-missing="{gap}"' in page
    # واللي اتكتب مش خانة فاضية تاني.
    assert 'data-missing="condition"' not in page


def test_the_gap_is_a_box_not_a_badge_that_says_go_look(ward):
    """القراية اللي بتلاقي النقص لازم تكون هي نفسها اللي بتقفله."""
    from app.utils import refusal as no

    rid = _refuse(ward, condition="التهاب رئوي")
    client = ward["sign_in"]("doc")

    client.post(f"/patients/refusal/{rid}/fill", follow_redirects=True, data={
        "consequences": "ممكن يتعب أكتر", "refused": "المبيت",
        "alternatives": "متابعة يومية"})

    with ward["app"].app_context():
        row = _row(ward, rid)
        assert no.missing(row) == []
        assert row.informed
        assert row.condition == "التهاب رئوي"     # ما اتمسحش


def test_a_complete_form_shows_no_boxes(ward):
    _refuse(ward, **_full())

    page = ward["sign_in"]("doc").get(
        f"/patients/{ward['ids']['child']}").get_data(as_text=True)

    assert "data-refusal-gaps" not in page


def test_the_board_finds_the_child_who_left_with_no_form(ward):
    stay = _admit_and_self_discharge(ward)

    page = ward["sign_in"]("doc").get("/beds/watch").get_data(as_text=True)

    assert "data-refusal-watch" in page
    assert f'data-refusal-gap="discharge-{stay}"' in page


def test_the_board_starts_the_form_where_it_found_the_gap(ward):
    """**اللي بيلاقي النقص هو اللي بيقفله** — وإلا بتفضل قايمة بتتقرا
    وما بتتعملش."""
    from app.utils import refusal as no

    _admit_and_self_discharge(ward)
    client = ward["sign_in"]("doc")

    client.post(f"/patients/{ward['ids']['child']}/refusal",
                follow_redirects=True,
                data={"kind": "discharge", "refused": "المبيت",
                      "consequences": "ممكن يتعب أكتر"})

    with ward["app"].app_context():
        rows = no.for_patient(ward["ids"]["child"])
        assert len(rows) == 1
        assert rows[0].kind == "discharge"
        assert rows[0].consequences == "ممكن يتعب أكتر"


def test_an_unsigned_form_is_its_own_row_on_the_board(ward):
    """«ناقصها بند» عن المحتوى، و«من غير توقيع» عن الدليل — حقيقتين."""
    _refuse(ward, **_full())

    page = ward["sign_in"]("doc").get("/beds/watch").get_data(as_text=True)

    assert "data-refusal-unsigned" in page
    assert "data-refusal-short" not in page     # محتواها كامل


def test_a_signed_complete_form_leaves_the_board_entirely(ward):
    from app.utils import refusal as no

    rid = _refuse(ward, **_full())
    with ward["app"].app_context():
        no.sign(_row(ward, rid), "paper", path="refusals/1.jpg")
        ward["db"].session.commit()

    page = ward["sign_in"]("doc").get("/beds/watch").get_data(as_text=True)

    assert "data-refusal-watch" not in page


def test_every_word_of_the_form_is_written_in_both_languages(ward):
    from app.i18n import _load_translations, _lookup
    from app.models import REFUSAL_ELEMENTS, REFUSAL_KINDS

    tables = _load_translations()
    keys = [("refusal", f"kind_{k}") for k in REFUSAL_KINDS]
    keys += [("refusal", f"item_{i}") for i in REFUSAL_ELEMENTS]
    keys += [("refusal", k) for k in (
        "title", "sub", "missing_hint", "informed", "not_informed",
        "unsigned", "what_happened", "the_form", "left_discharge",
        "left_emergency", "start_form", "saved", "not_saved")]
    keys += [("patients", "tab_refusal")]
    for lang in ("ar", "en"):
        for group, key in keys:
            assert _lookup(tables, lang, f"{group}.{key}"), \
                f"{lang}: {group}.{key} is missing"
