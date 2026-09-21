"""خريطة اللي مركّب في الطفل — GAHAR `CSS.03`.

النية بتقول الخطر بالنص: *"these tubes and catheters may be **misconnected**,
leading to the administration of the wrong material via the **wrong route**,
resulting in **grave consequences**"*. ودليل ٤ بيقول إن إدارتها واستعمالها
**بيتسجّلوا في الملف**.

والملف ده بيثبّت تلات حاجات:

* **«عالية الخطورة» بتتحسب من النوع مش من علامة** — المعيار سمّى التلاتة
  بالنص، فعلامة كانت هتسمح لواحد يقول إن الإيبيدورال مش عالي الخطورة.
* **الخريطة قراية مش جدول** — خريطة متخزّنة بتفرق عن الصفوف أول مرة حد
  ينسى يحدّثها.
* **والشيل لحظة مش مسح** — مدة بقاء القسطرة سؤال الملف محتاج إجابته.
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
        clinic["db"].session.commit()
    return clinic


def _line(ward, kind="peripheral", patient_id=None, **fields):
    from app.models import Patient, User
    from app.utils import lines

    with ward["app"].app_context():
        patient = ward["db"].session.get(
            Patient, patient_id or ward["ids"]["child"])
        doc = ward["db"].session.get(User, ward["ids"]["doctor"])
        row = lines.insert(patient, kind, user=doc, **fields)
        ward["db"].session.commit()
        return row.id


def _row(ward, lid):
    from app.models import Line

    return ward["db"].session.get(Line, lid)


# ------------------------- عالية الخطورة من النوع مش من علامة ----
def test_the_three_the_standard_names_are_high_risk(ward):
    """`CSS.03` (ب) سمّاهم بالنص: شرياني · فوق الجافية · داخل القراب."""
    from app.models import LINE_HIGH_RISK

    assert LINE_HIGH_RISK == ("arterial", "epidural", "intrathecal")
    for kind in LINE_HIGH_RISK:
        lid = _line(ward, kind)
        with ward["app"].app_context():
            assert _row(ward, lid).high_risk


def test_an_ordinary_line_is_not(ward):
    for kind in ("peripheral", "urinary", "nasogastric", "oxygen"):
        lid = _line(ward, kind)
        with ward["app"].app_context():
            assert not _row(ward, lid).high_risk


def test_nobody_can_mark_an_epidural_as_low_risk(ward):
    """**دي الحتة.** لو كانت علامة، حد كان يقدر يشيلها — والفاحص اللي
    بيدوّر على الملصق الناقص ما بيشوفش القسطرة دي."""
    from app.models import Line

    lid = _line(ward, "epidural")

    with ward["app"].app_context():
        row = _row(ward, lid)
        assert row.high_risk
        # مفيش عمود يتكتب فيه العكس — الخاصية بتتحسب.
        assert not hasattr(Line, "is_high_risk")
        assert "high_risk" not in {c.name for c in Line.__table__.columns}


def test_a_kind_the_record_cannot_draw_is_refused(ward):
    from app.models import Patient
    from app.utils import lines

    with ward["app"].app_context():
        patient = ward["db"].session.get(Patient, ward["ids"]["child"])
        with pytest.raises(ValueError):
            lines.insert(patient, "whatever")


def test_a_line_with_no_child_is_refused(ward):
    from app.utils import lines

    with ward["app"].app_context():
        with pytest.raises(ValueError):
            lines.insert(None, "peripheral")


# ------------------------------------- الملصق، واللي من غيره ----
def test_a_high_risk_line_with_no_label_is_found(ward):
    """النية بتقول العاقبة بالنص: المادة الغلط من **الطريق الغلط**."""
    from app.utils import lines

    bare = _line(ward, "arterial")
    _line(ward, "epidural", label="إيبيدورال — مورفين")

    with ward["app"].app_context():
        assert [r.id for r in lines.unlabelled_high_risk()] == [bare]


def test_labelling_it_takes_it_off_the_list(ward):
    from app.utils import lines

    lid = _line(ward, "intrathecal")
    with ward["app"].app_context():
        lines.label(_row(ward, lid), "داخل القراب — ما يتحقنش")
        ward["db"].session.commit()

        assert lines.unlabelled_high_risk() == []
        assert _row(ward, lid).labelled


def test_an_ordinary_line_with_no_label_is_not_on_that_list(ward):
    """القايمة دي عن التلاتة اللي المعيار سمّاهم — كانيولا من غير ملصق
    مش نفس الخطر، وحشرها هناك بتغرق الصف اللي بجد خطر."""
    from app.utils import lines

    _line(ward, "peripheral")

    with ward["app"].app_context():
        assert lines.unlabelled_high_risk() == []


def test_a_removed_high_risk_line_is_not_reported(ward):
    """اللي اتشالت مش محتاجة ملصق."""
    from app.utils import lines

    lid = _line(ward, "arterial")
    with ward["app"].app_context():
        lines.remove(_row(ward, lid))
        ward["db"].session.commit()

        assert lines.unlabelled_high_risk() == []


def test_a_blank_label_is_not_a_label(ward):
    from app.utils import lines

    lid = _line(ward, "epidural", label="   ")

    with ward["app"].app_context():
        assert not _row(ward, lid).labelled
        assert [r.id for r in lines.unlabelled_high_risk()] == [lid]


# ------------------------------------------- الخريطة ----
def test_the_map_holds_only_what_is_in_now(ward):
    from app.utils import lines

    inn = _line(ward, "central", site="تحت الترقوة الشمال")
    out = _line(ward, "peripheral")
    with ward["app"].app_context():
        lines.remove(_row(ward, out))
        ward["db"].session.commit()

        assert [r.id for r in lines.map_for(ward["ids"]["child"])] == [inn]
        # وتاريخ الطفل لسه فيه الاتنين.
        assert len(lines.for_patient(ward["ids"]["child"])) == 2


def test_the_oldest_line_comes_first_on_the_map(ward):
    """القسطرة اللي بقالها أطول هي اللي السؤال عليها في التسليم."""
    from app.utils import lines

    old = _line(ward, "urinary", at=datetime.utcnow() - timedelta(days=6))
    new = _line(ward, "peripheral", at=datetime.utcnow() - timedelta(days=1))

    with ward["app"].app_context():
        assert [r.id for r in lines.map_for(ward["ids"]["child"])] == [old, new]


def test_the_map_is_not_a_stored_thing(ward):
    """**خريطة متخزّنة بتفرق عن الصفوف أول مرة حد ينسى يحدّثها.**"""
    from app.models import Line

    assert not hasattr(Line, "map")
    names = {c.name for c in Line.__table__.columns}
    assert "map" not in names and "catheter_map" not in names


def test_another_childs_line_is_not_on_this_map(ward):
    from app.models import Patient
    from app.utils import lines
    from app.utils.clock import local_today

    with ward["app"].app_context():
        other = Patient(patient_number="LN-2", full_name="طفل تاني",
                        gender="female", is_active=True,
                        date_of_birth=local_today() - timedelta(days=600))
        ward["db"].session.add(other)
        ward["db"].session.commit()
        other_id = other.id

    _line(ward, "central", patient_id=other_id)

    with ward["app"].app_context():
        assert lines.map_for(ward["ids"]["child"]) == []
        assert len(lines.map_for(other_id)) == 1


# ------------------------------------------- الشيل ----
def test_removing_a_line_is_a_moment_not_a_delete(ward):
    """مدة بقائها هي اللي بتقول كان فيه خطر عدوى قد إيه — وصف اتمسح
    بيشيل السؤال مش بيجاوبه."""
    from app.models import User
    from app.utils import lines

    lid = _line(ward, "central", at=datetime.utcnow() - timedelta(days=9))
    with ward["app"].app_context():
        doc = ward["db"].session.get(User, ward["ids"]["doctor"])
        lines.remove(_row(ward, lid), user=doc, reason="خلصت")
        ward["db"].session.commit()

        row = _row(ward, lid)
        assert not row.in_place
        assert row.removed_at is not None
        assert row.removed_by_id == doc.id
        assert row.removal_reason == "خلصت"
        assert row.days_in == 9


def test_a_second_press_keeps_the_first_moment(ward):
    from app.utils import lines

    lid = _line(ward, "peripheral")
    early = datetime.utcnow() - timedelta(hours=5)
    with ward["app"].app_context():
        lines.remove(_row(ward, lid), at=early, reason="اتسدّت")
        ward["db"].session.commit()
        lines.remove(_row(ward, lid), reason="حاجة تانية")
        ward["db"].session.commit()

        row = _row(ward, lid)
        assert row.removed_at == early
        assert row.removal_reason == "اتسدّت"


def test_a_line_still_in_counts_its_days_up_to_now(ward):
    lid = _line(ward, "urinary", at=datetime.utcnow() - timedelta(days=4))

    with ward["app"].app_context():
        assert _row(ward, lid).days_in == 4
        assert _row(ward, lid).in_place


# ------------------------------------------- اللي محدّش بيشوفه ----
def _admit(ward):
    from app.models import Patient
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
        return stay.id


def test_a_line_still_in_after_the_child_went_home_is_found(ward):
    """**سؤال مش اتهام**: يا حد نسي يسجّل الشيل، يا الطفل راح البيت وهي
    فيه — والاتنين محتاجين حد يبصّ."""
    from app.models import Admission, Patient, User
    from app.utils import lines

    stay_id = _admit(ward)
    with ward["app"].app_context():
        stay = ward["db"].session.get(Admission, stay_id)
        patient = ward["db"].session.get(Patient, ward["ids"]["child"])
        doc = ward["db"].session.get(User, ward["ids"]["doctor"])
        row = lines.insert(patient, "urinary", user=doc, admission=stay)
        ward["db"].session.commit()
        lid = row.id

        assert lines.still_in_after_discharge() == []   # لسه داخل

        stay.discharged_at = datetime.utcnow()
        ward["db"].session.commit()

        found = lines.still_in_after_discharge()
        assert [f["line"].id for f in found] == [lid]
        assert found[0]["stay"].id == stay_id


def test_and_stops_being_found_once_it_is_recorded_out(ward):
    from app.models import Admission, Patient, User
    from app.utils import lines

    stay_id = _admit(ward)
    with ward["app"].app_context():
        stay = ward["db"].session.get(Admission, stay_id)
        patient = ward["db"].session.get(Patient, ward["ids"]["child"])
        doc = ward["db"].session.get(User, ward["ids"]["doctor"])
        row = lines.insert(patient, "urinary", user=doc, admission=stay)
        stay.discharged_at = datetime.utcnow()
        ward["db"].session.commit()

        lines.remove(row)
        ward["db"].session.commit()

        assert lines.still_in_after_discharge() == []


def test_an_other_kind_with_no_description_is_found(ward):
    """صف مكتوب فيه «تاني» وبس مش بيقول حاجة لحد بيقرا خريطة تسليم."""
    from app.utils import lines

    bare = _line(ward, "other")
    _line(ward, "other", kind_note="أنبوبة فغر المعدة")

    with ward["app"].app_context():
        assert [r.id for r in lines.unnamed_other()] == [bare]


# ================================================ الباب ====
def test_the_stay_screen_draws_the_map(ward):
    """(د) بيطلب الخريطة كجزء من التسليم — فمكانها على الشاشة اللي
    الممرضة بتفتحها وهي بتسلّم."""
    from app.models import Admission, Patient, User
    from app.utils import lines

    stay_id = _admit(ward)
    with ward["app"].app_context():
        stay = ward["db"].session.get(Admission, stay_id)
        patient = ward["db"].session.get(Patient, ward["ids"]["child"])
        doc = ward["db"].session.get(User, ward["ids"]["doctor"])
        row = lines.insert(patient, "central", user=doc, admission=stay,
                           site="تحت الترقوة الشمال")
        ward["db"].session.commit()
        lid = row.id

    page = ward["sign_in"]("doc").get(
        f"/beds/admission/{stay_id}").get_data(as_text=True)

    assert "data-line-map" in page
    assert f'data-line="{lid}"' in page
    assert "تحت الترقوة الشمال" in page


def test_the_stay_screen_can_actually_insert_one(ward):
    from app.utils import lines

    stay_id = _admit(ward)
    client = ward["sign_in"]("doc")

    landed = client.post(f"/beds/stay/{stay_id}/line", data={
        "kind": "urinary", "site": "—", "label": "بولية"})

    assert f"/beds/admission/{stay_id}" in landed.headers["Location"]
    with ward["app"].app_context():
        rows = lines.map_for(ward["ids"]["child"])
        assert len(rows) == 1
        assert rows[0].kind == "urinary"


def test_a_kind_the_screen_cannot_draw_is_refused_at_the_route(ward):
    from app.utils import lines

    stay_id = _admit(ward)

    ward["sign_in"]("doc").post(f"/beds/stay/{stay_id}/line",
                                data={"kind": "teleporter"},
                                follow_redirects=True)

    with ward["app"].app_context():
        assert lines.map_for(ward["ids"]["child"]) == []


def test_the_screen_offers_a_label_box_only_where_it_is_missing(ward):
    """القايمة اللي بتلاقي الناقص هي اللي بتقفله."""
    from app.models import Admission, Patient, User
    from app.utils import lines

    stay_id = _admit(ward)
    with ward["app"].app_context():
        stay = ward["db"].session.get(Admission, stay_id)
        patient = ward["db"].session.get(Patient, ward["ids"]["child"])
        doc = ward["db"].session.get(User, ward["ids"]["doctor"])
        bare = lines.insert(patient, "arterial", user=doc, admission=stay)
        lines.insert(patient, "epidural", user=doc, admission=stay,
                     label="إيبيدورال")
        ward["db"].session.commit()
        bare_id = bare.id

    client = ward["sign_in"]("doc")
    page = client.get(f"/beds/admission/{stay_id}").get_data(as_text=True)

    assert 'data-missing="label"' in page
    assert page.count('data-missing="label"') == 1
    assert page.count("data-high-risk") == 2

    client.post(f"/beds/line/{bare_id}/label", data={"label": "شرياني"},
                follow_redirects=True)

    with ward["app"].app_context():
        assert lines.unlabelled_high_risk() == []


def test_the_screen_can_take_a_line_out(ward):
    from app.utils import lines

    stay_id = _admit(ward)
    client = ward["sign_in"]("doc")
    client.post(f"/beds/stay/{stay_id}/line", data={"kind": "peripheral"},
                follow_redirects=True)

    with ward["app"].app_context():
        lid = lines.map_for(ward["ids"]["child"])[0].id

    client.post(f"/beds/line/{lid}/remove", data={"reason": "اتسدّت"},
                follow_redirects=True)

    with ward["app"].app_context():
        assert lines.map_for(ward["ids"]["child"]) == []
        assert _row(ward, lid).removal_reason == "اتسدّت"
        assert len(lines.for_patient(ward["ids"]["child"])) == 1


def test_the_ward_board_shows_an_unlabelled_high_risk_line(ward):
    lid = _line(ward, "arterial")

    page = ward["sign_in"]("doc").get("/beds/watch").get_data(as_text=True)

    assert "data-lines-watch" in page
    assert f'data-line-unlabelled="{lid}"' in page


def test_a_labelled_one_leaves_the_board(ward):
    from app.utils import lines

    lid = _line(ward, "arterial")
    with ward["app"].app_context():
        lines.label(_row(ward, lid), "شرياني — ما يتحقنش")
        ward["db"].session.commit()

    page = ward["sign_in"]("doc").get("/beds/watch").get_data(as_text=True)

    assert "data-lines-watch" not in page


def test_a_child_with_no_lines_has_no_tab(ward):
    """**التبويب** هو اللي مشروط، مش البانل.

    أول نسخة من الاختبار ده كانت بتدوّر على `data-lines` — وده اسم
    الحاوية اللي بتترسم دايماً لأن Alpine هي اللي بتخبّيها. فالصف
    `data-line="…"` هو اللي بيقول إن فيه حاجة فعلاً.
    """
    page = ward["sign_in"]("doc").get(
        f"/patients/{ward['ids']['child']}").get_data(as_text=True)

    assert "'lines','tab_lines'" not in page
    assert 'data-line="' not in page


def test_the_file_keeps_the_ones_that_came_out(ward):
    """تاريخ الملف محتاج المدة — وصف اتمسح بيشيل السؤال مش بيجاوبه."""
    from app.utils import lines

    lid = _line(ward, "central", at=datetime.utcnow() - timedelta(days=7))
    with ward["app"].app_context():
        lines.remove(_row(ward, lid), reason="خلصت")
        ward["db"].session.commit()

    page = ward["sign_in"]("doc").get(
        f"/patients/{ward['ids']['child']}").get_data(as_text=True)

    assert f'data-line="{lid}"' in page
    assert "خلصت" in page


def test_every_word_of_the_map_is_written_in_both_languages(ward):
    from app.i18n import _load_translations, _lookup
    from app.models import LINE_KINDS

    tables = _load_translations()
    keys = [("lines", f"kind_{k}") for k in LINE_KINDS]
    keys += [("lines", k) for k in (
        "title", "none", "watch_hint", "kind", "kind_note", "site", "size",
        "label", "high_risk", "no_label", "left_in", "unnamed", "days",
        "add", "remove", "why_out", "inserted", "labelled", "removed",
        "not_saved")]
    keys += [("patients", "tab_lines")]
    for lang in ("ar", "en"):
        for group, key in keys:
            assert _lookup(tables, lang, f"{group}.{key}"), \
                f"{lang}: {group}.{key} is missing"
