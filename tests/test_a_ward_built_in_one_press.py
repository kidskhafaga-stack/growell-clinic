"""تجهيز الأقسام: ضغطة واحدة، وحذف بقاعدة.

**الشاشة كانت بتسأل السؤال الغلط.** «أضف قسم» → «أضف حيّز» → «أضف
سرير»، تلات دورات لكل سرير في المستشفى. والسؤال اللي المستشفى بتجاوبه
من غير ما تفكّر هو **«الطوارئ فيها كام بارتشن؟»**.

**والأسئلة مش واحدة لكل منشأة**: عيادة ماعلّمتش «عناية» ما تتسألش عن
بارتشناتها — نفس مبدأ التبويبات في ملف الطفل.

**والحذف مكانش موجود خالص**، وده سبب اللغبطة. والقاعدة سطرين: اللي عمره
ما اتستعمل يتمسح، واللي اتستعمل **يتوقف** — لأن سرير نام فيه طفل لو
اتمسح، صفوف `BedStay` تفضل بتشاور على حاجة مش موجودة.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

MODULE = "beds"


def _names(key, number=None):
    return f"{key}-{number}" if number else key


@pytest.fixture()
def hospital(clinic):
    """منشأة علّمت طوارئ وعناية وحضّانات وداخلي."""
    from app.models import Setting

    with clinic["app"].app_context():
        Setting.set(f"mod_enabled:{MODULE}", "1")
        import json as _json
        Setting.set("facility_capabilities", _json.dumps(
            ["general_consultation", "emergency_care", "icu", "nicu", "ward"]))
        clinic["db"].session.commit()
    return clinic


# ============ الأسئلة بتيجي من اللي اتعلّم ============
def test_only_what_the_facility_ticked_is_asked_about(clinic):
    from app.utils import ward_plan

    assert [p["cap"] for p in ward_plan.plans_for(["emergency_care"])] == \
        ["emergency_care"]
    assert ward_plan.plans_for([]) == []
    assert ward_plan.plans_for(["general_consultation"]) == []


def test_a_clinic_with_no_beds_gets_no_wizard(clinic):
    from app.models import Setting

    with clinic["app"].app_context():
        Setting.set(f"mod_enabled:{MODULE}", "1")
        clinic["db"].session.commit()

    page = clinic["sign_in"]("boss").get("/beds/setup").get_data(as_text=True)
    assert "data-ward-wizard" not in page


def test_the_hospital_is_asked_about_each_of_its_units(hospital):
    page = hospital["sign_in"]("boss").get("/beds/setup").get_data(as_text=True)

    assert "data-ward-wizard" in page
    for cap in ("emergency_care", "icu", "nicu", "ward"):
        assert f'data-ward-plan="{cap}"' in page
    assert 'data-ward-q="nicu-incubators"' in page
    assert 'data-ward-q="icu-isolation"' in page
    # ماعلّمتش رعاية نهارية، فما بتتسألش عنها.
    assert 'data-ward-plan="day_care"' not in page


def test_the_same_question_in_two_units_keeps_two_answers(hospital):
    """**«كام سرير» سؤال في العناية والرعاية النهارية والإفاقة.**

    لو التلاتة اتسمّوا `beds`، الفورم بتبعت واحدة والتانيتين بيضيعوا من
    غير ما حد ياخد باله — والمستشفى تفتكر إنها كتبت والبرنامج ما عملش.
    """
    from app.utils import ward_plan

    assert ward_plan.field("icu", "beds") != ward_plan.field("day_care", "beds")

    answers = {ward_plan.field("icu", "beds"): "4",
               ward_plan.field("day_care", "beds"): "9"}
    rows = ward_plan.preview(["icu", "day_care"], answers)
    by_cap = {row["cap"]: row["beds"] for row in rows}
    assert by_cap == {"icu": 4, "day_care": 9}


# ============ البناء ============
def test_emergency_is_one_bed_per_partition(hospital):
    """والتعليق في `utils/beds` بيقول ليه: *one bed per partition, which is
    what makes crowding countable as every partition occupied*."""
    from app.models import Bed, Space, Unit
    from app.utils import ward_plan

    with hospital["app"].app_context():
        ward_plan.build(["emergency_care"],
                        {ward_plan.field("emergency_care", "partitions"): "3"},
                        _names)
        hospital["db"].session.commit()

        unit = Unit.query.filter_by(kind="emergency").one()
        assert len(unit.spaces) == 3
        assert all(s.kind == "partition" for s in unit.spaces)
        assert Bed.query.join(Space).filter(
            Space.unit_id == unit.id).count() == 3
        assert {b.kind for b in Bed.query.join(Space).filter(
            Space.unit_id == unit.id).all()} == {"trolley"}


def test_the_nursery_holds_three_kinds_in_one_bay(hospital):
    """وده السبب اللي خلّى النوع يبقى على السرير مش على القسم."""
    from app.models import Bed, Space, Unit
    from app.utils import ward_plan

    with hospital["app"].app_context():
        ward_plan.build(["nicu"], {
            ward_plan.field("nicu", "incubators"): "4",
            ward_plan.field("nicu", "cots"): "2",
            ward_plan.field("nicu", "capsules"): "1"}, _names)
        hospital["db"].session.commit()

        unit = Unit.query.filter_by(kind="nicu").one()
        assert len(unit.spaces) == 1
        beds = Bed.query.join(Space).filter(Space.unit_id == unit.id).all()
        kinds = {}
        for bed in beds:
            kinds[bed.kind] = kinds.get(bed.kind, 0) + 1
        assert kinds == {"incubator": 4, "cot": 2, "capsule": 1}


def test_isolation_is_a_space_not_a_bed(hospital):
    """اللي بيعزل الطفل هو الحيطة اللي حواليه مش هيكل السرير — والتعليق
    ده مكتوب في الموديل نفسه."""
    from app.models import Space, Unit
    from app.utils import ward_plan

    with hospital["app"].app_context():
        ward_plan.build(["icu"], {
            ward_plan.field("icu", "beds"): "6",
            ward_plan.field("icu", "isolation"): "2"}, _names)
        hospital["db"].session.commit()

        unit = Unit.query.filter_by(kind="icu").one()
        iso = [s for s in unit.spaces if s.is_isolation]
        assert len(iso) == 2
        assert all(s.kind == "partition" for s in iso)
        assert all(len(s.beds) == 1 for s in iso)
        bay = [s for s in unit.spaces if not s.is_isolation]
        assert len(bay) == 1 and len(bay[0].beds) == 6


def test_a_ward_is_rooms_times_beds(hospital):
    from app.models import Unit
    from app.utils import ward_plan

    with hospital["app"].app_context():
        ward_plan.build(["ward"], {
            ward_plan.field("ward", "rooms"): "5",
            ward_plan.field("ward", "beds_per_room"): "2"}, _names)
        hospital["db"].session.commit()

        unit = Unit.query.filter_by(kind="ward").one()
        assert len(unit.spaces) == 5
        assert all(len(s.beds) == 2 for s in unit.spaces)


def test_building_twice_does_not_make_a_second_emergency(hospital):
    """«طوارئ» مرتين هي بالظبط اللغبطة اللي الشاشة دي موجودة علشانها."""
    from app.models import Unit
    from app.utils import ward_plan

    with hospital["app"].app_context():
        for _ in range(2):
            ward_plan.build(
                ["emergency_care"],
                {ward_plan.field("emergency_care", "partitions"): "2"}, _names)
            hospital["db"].session.commit()

        assert Unit.query.filter_by(kind="emergency").count() == 1
        assert len(Unit.query.filter_by(kind="emergency").one().spaces) == 4


def test_a_blank_form_builds_nothing(hospital):
    from app.models import Unit
    from app.utils import ward_plan

    with hospital["app"].app_context():
        made = ward_plan.build(["emergency_care", "icu"], {}, _names)
        hospital["db"].session.commit()

        assert made == {"units": 0, "spaces": 0, "beds": 0}
        assert Unit.query.count() == 0


def test_a_typo_of_six_hundred_is_capped(hospital):
    """**مش سياسة، حارس غلطة كتابة.** حد كتب ٦٠٠ بدل ٦ بيعمل ستمية سرير
    محدّش يقدر يشيلهم بسهولة."""
    from app.models import Unit
    from app.utils import ward_plan

    with hospital["app"].app_context():
        ward_plan.build(["emergency_care"],
                        {ward_plan.field("emergency_care", "partitions"):
                         "600"}, _names)
        hospital["db"].session.commit()

        assert len(Unit.query.filter_by(kind="emergency").one().spaces) == 200


def test_nonsense_in_a_box_builds_nothing(hospital):
    from app.models import Unit
    from app.utils import ward_plan

    with hospital["app"].app_context():
        for bad in ("", "  ", "تلاتة", "-4", None):
            ward_plan.build(["emergency_care"],
                            {ward_plan.field("emergency_care",
                                             "partitions"): bad}, _names)
        hospital["db"].session.commit()

        assert Unit.query.count() == 0


def test_building_from_the_screen(hospital):
    from app.models import Bed, Unit

    client = hospital["sign_in"]("boss")
    client.post("/beds/setup/build", follow_redirects=True, data={
        "emergency_care__partitions": "2",
        "nicu__incubators": "3",
    })

    with hospital["app"].app_context():
        assert Unit.query.count() == 2
        assert Bed.query.count() == 5


# ============ الحذف بقاعدة ============
def _ward(clinic):
    from app.utils import ward_plan

    with clinic["app"].app_context():
        ward_plan.build(["emergency_care"],
                        {ward_plan.field("emergency_care", "partitions"): "2"},
                        _names)
        clinic["db"].session.commit()


def _sleep_in(clinic, bed_id):
    """طفل نام في السرير ده — وخرج."""
    from app.models import Admission, BedStay
    from datetime import datetime

    with clinic["app"].app_context():
        stay = Admission(patient_id=clinic["ids"]["child"],
                         discharged_at=datetime.utcnow())
        clinic["db"].session.add(stay)
        clinic["db"].session.flush()
        clinic["db"].session.add(BedStay(admission_id=stay.id, bed_id=bed_id,
                                         since=datetime.utcnow(),
                                         until=datetime.utcnow()))
        clinic["db"].session.commit()


def test_a_bed_nobody_used_is_deleted(hospital):
    from app.models import Bed
    from app.utils import ward_plan

    _ward(hospital)

    with hospital["app"].app_context():
        bed = Bed.query.first()
        ward_plan.delete_bed(bed)
        hospital["db"].session.commit()

        assert Bed.query.count() == 1


def test_a_bed_a_child_slept_in_is_never_deleted(hospital):
    """صفوف `BedStay` تفضل بتشاور على حاجة مش موجودة — و«تقرير بيسقّط
    صفوف في الضلمة» زي ما `utils/lookups` بيسمّيه."""
    from app.models import Bed
    from app.utils import ward_plan

    _ward(hospital)
    with hospital["app"].app_context():
        bed_id = Bed.query.first().id
    _sleep_in(hospital, bed_id)

    with hospital["app"].app_context():
        with pytest.raises(ward_plan.InUse):
            ward_plan.delete_bed(Bed.query.get(bed_id))
        assert Bed.query.count() == 2


def test_the_screen_does_not_draw_a_button_that_would_refuse(hospital):
    """**زرار بيرفض كل مرة أسوأ من زرار مش موجود** — بيعلّم اللي قدام
    الشاشة إن الأزرار بتكدب."""
    from app.models import Bed

    _ward(hospital)
    with hospital["app"].app_context():
        used, spare = [b.id for b in Bed.query.order_by(Bed.id).all()]
    _sleep_in(hospital, used)

    page = hospital["sign_in"]("boss").get("/beds/setup").get_data(as_text=True)

    assert f'data-delete-bed="{spare}"' in page
    assert f'data-delete-bed="{used}"' not in page


def test_deleting_a_space_takes_its_beds_with_it(hospital):
    from app.models import Bed, Space
    from app.utils import ward_plan

    _ward(hospital)

    with hospital["app"].app_context():
        ward_plan.delete_space(Space.query.first())
        hospital["db"].session.commit()

        assert Space.query.count() == 1
        assert Bed.query.count() == 1


def test_a_space_with_one_used_bed_keeps_all_of_them(hospital):
    """**الكل أو لا حاجة**: مسح النص بيسيب غرفة فيها سرير واحد ومحدّش
    فاهم ليه."""
    from app.models import Bed, Space
    from app.utils import ward_plan

    with hospital["app"].app_context():
        ward_plan.build(["nicu"], {ward_plan.field("nicu", "cots"): "3"},
                        _names)
        hospital["db"].session.commit()
        bed_id = Bed.query.first().id
    _sleep_in(hospital, bed_id)

    with hospital["app"].app_context():
        with pytest.raises(ward_plan.InUse):
            ward_plan.delete_space(Space.query.first())
        assert Bed.query.count() == 3


def test_deleting_a_unit_clears_everything_under_it(hospital):
    from app.models import Bed, Space, Unit
    from app.utils import ward_plan

    _ward(hospital)

    with hospital["app"].app_context():
        ward_plan.delete_unit(Unit.query.first())
        hospital["db"].session.commit()

        assert Unit.query.count() == 0
        assert Space.query.count() == 0
        assert Bed.query.count() == 0


def test_a_unit_with_history_is_refused_and_says_why(hospital):
    from app.models import Bed, Unit

    _ward(hospital)
    with hospital["app"].app_context():
        bed_id = Bed.query.first().id
        unit_id = Unit.query.first().id
    _sleep_in(hospital, bed_id)

    client = hospital["sign_in"]("boss")
    page = client.post(f"/beds/unit/{unit_id}/delete",
                       follow_redirects=True).get_data(as_text=True)

    import json
    word = json.load(open("app/i18n/locales/ar.json", encoding="utf-8"))
    assert word["ward_wizard"]["refused_unit_has_used_beds"] in page

    with hospital["app"].app_context():
        assert Unit.query.count() == 1


def test_deleting_from_the_screen_works(hospital):
    from app.models import Bed

    _ward(hospital)
    with hospital["app"].app_context():
        bed_id = Bed.query.first().id

    client = hospital["sign_in"]("boss")
    client.post(f"/beds/bed/{bed_id}/delete", follow_redirects=True)

    with hospital["app"].app_context():
        assert Bed.query.get(bed_id) is None


def test_only_an_admin_builds_or_deletes(hospital):
    from app.models import Unit

    _ward(hospital)
    with hospital["app"].app_context():
        unit_id = Unit.query.first().id

    desk = hospital["sign_in"]("desk")
    assert desk.post("/beds/setup/build",
                     data={"emergency_care__partitions": "1"}).status_code == 403
    assert desk.post(f"/beds/unit/{unit_id}/delete").status_code == 403


def test_every_word_of_the_screen_is_written_in_both_languages(clinic):
    import json

    ar = json.load(open("app/i18n/locales/ar.json", encoding="utf-8"))
    en = json.load(open("app/i18n/locales/en.json", encoding="utf-8"))

    assert set(ar["ward_wizard"]) == set(en["ward_wizard"])
    assert all((ar["ward_wizard"][k] or "").strip() for k in ar["ward_wizard"])
    assert all((en["ward_wizard"][k] or "").strip() for k in en["ward_wizard"])
