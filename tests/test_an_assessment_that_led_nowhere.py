"""التغذية — GAHAR `ICD.13`.

النية بتقول الرابط بالنص: *"The assessment **leads to a plan of care, or
intervention**"*. **فتقييم ما أدّاش لحاجة هو الفشل اللي المعيار موجود
علشانه** — وهو أسوأ من تقييم ناقص، لأنه بيبان **مكتمل** في أي جرد: مفيش
خانة فاضية فيه.

والملف ده بيثبّت كمان إن **البرنامج ما بيكتبش قايمة الأنظمة الغذائية**.
(د)(١) بيقول إن القايمة بتاعة المستشفى، و«حمية سكري» مفردة إكلينيكية —
اختراعها هنا نفس غلطة اختراع مقياس فرز.
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def ward(clinic):
    """عيادة كتبت قايمة أنظمتها — زي أي عيادة شغّالة."""
    from app.models import Lookup, Setting

    with clinic["app"].app_context():
        Setting.set("mod_enabled:beds", "1")
        for order, (key, ar, en) in enumerate((
                ("d1", "حمية سكري", "Diabetic"),
                ("d2", "قليل الملح", "Low salt"),
                ("d3", "صائم", "Nil by mouth"))):
            clinic["db"].session.add(Lookup(
                domain="special_diet", key=key, name_ar=ar, name_en=en,
                sort_order=order))
        clinic["db"].session.commit()
    return clinic


@pytest.fixture()
def bare(clinic):
    """وعيادة لسه ما كتبتش قايمتها."""
    from app.models import Setting

    with clinic["app"].app_context():
        Setting.set("mod_enabled:beds", "1")
        clinic["db"].session.commit()
    return clinic


def _assess(ward, needs=None, **fields):
    from app.models import Patient, User
    from app.utils import nutrition

    with ward["app"].app_context():
        patient = ward["db"].session.get(Patient, ward["ids"]["child"])
        doc = ward["db"].session.get(User, ward["ids"]["doctor"])
        row = nutrition.assess(patient, user=doc, needs=needs, **fields)
        ward["db"].session.commit()
        return row.id


def _order(ward, diet="d1", **fields):
    from app.models import Patient, User
    from app.utils import nutrition

    with ward["app"].app_context():
        patient = ward["db"].session.get(Patient, ward["ids"]["child"])
        doc = ward["db"].session.get(User, ward["ids"]["doctor"])
        row = nutrition.order(patient, diet, user=doc, **fields)
        ward["db"].session.commit()
        return row.id


def _ord_row(ward, oid):
    from app.models import DietOrder

    return ward["db"].session.get(DietOrder, oid)


# ============ القايمة بتاعة المستشفى، مش بتاعتنا ============
def test_the_program_ships_no_diet_names(bare):
    """**(د)(١) بيقول إن القايمة بتاعة المستشفى.**

    باقي قوايم `Lookup` تشغيلية — «علبة» و«ثلاجة» — والبرنامج يقدر
    يبدأها. أسماء الأنظمة الغذائية إكلينيكية، فبتبدأ فاضية.
    """
    from app.models import DIET_DOMAIN
    from app.utils import lookups, nutrition

    assert DIET_DOMAIN not in lookups.BUILT_IN

    with bare["app"].app_context():
        lookups.ensure_seeded()
        bare["db"].session.commit()
        assert nutrition.diet_list() == []


def test_but_the_list_has_a_screen_to_be_written_on(bare):
    """فاضية مش يعني مخفية — لازم يكون ليها مكان تتكتب فيه."""
    from app.models import DIET_DOMAIN
    from app.utils import lookups

    assert DIET_DOMAIN in lookups.DOMAINS


def test_a_diet_nobody_defined_is_refused(ward):
    """صف بيشاور على نظام محدّش عرّفه، وشاشة التسليم هتعرضه فاضي."""
    from app.models import Patient
    from app.utils import nutrition

    with ward["app"].app_context():
        patient = ward["db"].session.get(Patient, ward["ids"]["child"])
        with pytest.raises(ValueError):
            nutrition.order(patient, "keto")
        with pytest.raises(ValueError):
            nutrition.order(patient, "   ")


def test_the_name_is_read_from_the_clinics_list(ward):
    """فتغيير التسمية بيغيّرها في كل مكان، والصفوف القديمة تفضل مقروءة."""
    from app.models import Lookup

    oid = _order(ward, "d1")

    with ward["app"].app_context():
        assert _ord_row(ward, oid).diet_name("ar") == "حمية سكري"
        assert _ord_row(ward, oid).diet_name("en") == "Diabetic"

        row = Lookup.query.filter_by(domain="special_diet", key="d1").one()
        row.name_ar = "حمية سكري (معدّلة)"
        ward["db"].session.commit()

        assert _ord_row(ward, oid).diet_name("ar") == "حمية سكري (معدّلة)"


# ============ التلات حالات ============
def test_assessed_and_fine_is_not_the_same_as_never_assessed(ward):
    """**أبعد حاجتين عن بعض في الباب ده.**"""
    from app.models import NutritionAssessment
    from app.utils import nutrition

    fine = _assess(ward, needs=False)

    with ward["app"].app_context():
        row = ward["db"].session.get(NutritionAssessment, fine)
        assert row.needs_special_diet is False
        assert nutrition.latest_assessment(ward["ids"]["child"]) is not None


def test_nobody_said_stays_none(ward):
    from app.models import NutritionAssessment

    oid = _assess(ward)

    with ward["app"].app_context():
        row = ward["db"].session.get(NutritionAssessment, oid)
        assert row.needs_special_diet is None


def test_a_needs_value_that_is_not_three_state_is_refused(ward):
    from app.models import Patient
    from app.utils import nutrition

    with ward["app"].app_context():
        patient = ward["db"].session.get(Patient, ward["ids"]["child"])
        with pytest.raises(ValueError):
            nutrition.assess(patient, needs="yes")


def test_family_food_has_the_same_three(ward):
    """**وممنوع غير محدّش سأل** — والتانية هي اللي بتحصل فعلاً."""
    from app.utils import nutrition

    silent = _order(ward, "d1")
    with ward["app"].app_context():
        assert _ord_row(ward, silent).family_food_allowed is None
        assert [r.id for r in nutrition.unanswered_family_food()] == [silent]

        nutrition.stop(_ord_row(ward, silent))
        ward["db"].session.commit()

    banned = _order(ward, "d2", family_food=False, family_note="سكري")
    with ward["app"].app_context():
        assert _ord_row(ward, banned).family_food_allowed is False
        assert nutrition.unanswered_family_food() == []


def test_a_family_food_value_that_is_not_three_state_is_refused(ward):
    from app.models import Patient
    from app.utils import nutrition

    with ward["app"].app_context():
        patient = ward["db"].session.get(Patient, ward["ids"]["child"])
        with pytest.raises(ValueError):
            nutrition.order(patient, "d1", family_food="maybe")


# ============ القراية اللي المعيار موجود علشانها ============
def test_an_assessment_that_led_nowhere_is_found(ward):
    """*"The assessment **leads to** a plan of care, or intervention"* —
    وتقييم ما أدّاش لحاجة **بيبان مكتمل** في أي جرد."""
    from app.utils import nutrition

    aid = _assess(ward, needs=True, findings="نقص وزن واضح")

    with ward["app"].app_context():
        found = nutrition.assessed_but_nothing_ordered()
        assert [r.id for r in found] == [aid]


def test_and_stops_being_found_once_food_is_ordered(ward):
    from app.utils import nutrition

    _assess(ward, needs=True)
    _order(ward, "d1")

    with ward["app"].app_context():
        assert nutrition.assessed_but_nothing_ordered() == []


def test_a_child_assessed_as_fine_is_not_on_that_list(ward):
    """أكله عادي مش نقص."""
    from app.utils import nutrition

    _assess(ward, needs=False)

    with ward["app"].app_context():
        assert nutrition.assessed_but_nothing_ordered() == []


def test_nor_one_nobody_has_answered_for(ward):
    from app.utils import nutrition

    _assess(ward)

    with ward["app"].app_context():
        assert nutrition.assessed_but_nothing_ordered() == []


def test_an_old_needs_that_a_newer_assessment_cleared_is_not_a_gap(ward):
    """**أحدث تقييم هو اللي بيحكم.** واحد قديم قال «محتاج» واتعالج بعده
    مش نقص — وعدّه بيخلّي القايمة تفضل حمرا للأبد."""
    from app.utils import nutrition

    _assess(ward, needs=True, at=datetime.utcnow() - timedelta(days=5))
    _assess(ward, needs=False)

    with ward["app"].app_context():
        assert nutrition.assessed_but_nothing_ordered() == []


def test_a_stopped_order_leaves_the_gap_open_again(ward):
    """الأمر وقف والتقييم لسه بيقول محتاج — يبقى محتاج تاني."""
    from app.utils import nutrition

    aid = _assess(ward, needs=True)
    oid = _order(ward, "d1")

    with ward["app"].app_context():
        assert nutrition.assessed_but_nothing_ordered() == []

        nutrition.stop(_ord_row(ward, oid))
        ward["db"].session.commit()

        assert [r.id for r in nutrition.assessed_but_nothing_ordered()] == [aid]


def test_food_ordered_with_nobody_having_assessed_is_found(ward):
    """(ب) «معايير معرّفة لإشراك خدمات التغذية» — ونظام خاص من غير تقييم
    يعني المعايير دي محدّش عدّى عليها."""
    from app.utils import nutrition

    oid = _order(ward, "d2")

    with ward["app"].app_context():
        assert [r.id for r in nutrition.ordered_without_assessment()] == [oid]

        _inner_assess(ward)
        assert nutrition.ordered_without_assessment() == []


def _inner_assess(ward):
    from app.models import Patient
    from app.utils import nutrition

    patient = ward["db"].session.get(Patient, ward["ids"]["child"])
    nutrition.assess(patient, needs=False)
    ward["db"].session.commit()


# ============ الأمر ============
def test_stopping_an_order_is_a_moment_not_a_delete(ward):
    """الطفل كان على النظام ده فترة، والملف محتاج يعرفها."""
    from app.models import User
    from app.utils import nutrition

    oid = _order(ward, "d1")
    with ward["app"].app_context():
        doc = ward["db"].session.get(User, ward["ids"]["doctor"])
        nutrition.stop(_ord_row(ward, oid), user=doc)
        ward["db"].session.commit()

        row = _ord_row(ward, oid)
        assert not row.running
        assert row.stopped_by_id == doc.id
        assert len(nutrition.orders_for(ward["ids"]["child"])) == 1
        assert nutrition.current_diet(ward["ids"]["child"]) is None


def test_a_second_stop_keeps_the_first_moment(ward):
    from app.utils import nutrition

    oid = _order(ward, "d1")
    early = datetime.utcnow() - timedelta(hours=6)
    with ward["app"].app_context():
        nutrition.stop(_ord_row(ward, oid), at=early)
        ward["db"].session.commit()
        nutrition.stop(_ord_row(ward, oid))
        ward["db"].session.commit()

        assert _ord_row(ward, oid).stopped_at == early


def test_the_current_diet_is_the_newest_running_one(ward):
    from app.utils import nutrition

    first = _order(ward, "d1", at=datetime.utcnow() - timedelta(days=2))
    with ward["app"].app_context():
        nutrition.stop(_ord_row(ward, first))
        ward["db"].session.commit()
    second = _order(ward, "d2")

    with ward["app"].app_context():
        assert nutrition.current_diet(ward["ids"]["child"]).id == second


def test_meal_times_are_the_clinics_words(ward):
    """(د)(٤) «مواعيد الوجبات بتراعي تفضيلات المريض» — و«بعد المغرب»
    حاجة البرنامج ما يعرفهاش."""
    oid = _order(ward, "d1", meal_times="بعد المغرب · مش قبل الجلسة")

    with ward["app"].app_context():
        assert _ord_row(ward, oid).meal_times == "بعد المغرب · مش قبل الجلسة"


def test_an_order_with_no_child_is_refused(ward):
    from app.utils import nutrition

    with ward["app"].app_context():
        with pytest.raises(ValueError):
            nutrition.order(None, "d1")
        with pytest.raises(ValueError):
            nutrition.assess(None)


def test_another_childs_diet_is_not_this_ones(ward):
    from app.models import Patient
    from app.utils import nutrition
    from app.utils.clock import local_today

    with ward["app"].app_context():
        other = Patient(patient_number="NU-2", full_name="طفل تاني",
                        gender="female", is_active=True,
                        date_of_birth=local_today() - timedelta(days=1100))
        ward["db"].session.add(other)
        ward["db"].session.flush()
        nutrition.order(other, "d1")
        ward["db"].session.commit()
        other_id = other.id

    with ward["app"].app_context():
        assert nutrition.current_diet(ward["ids"]["child"]) is None
        assert nutrition.current_diet(other_id) is not None


# ================================================ الباب ====
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


def test_the_stay_screen_offers_the_clinics_diets_only(ward):
    stay = _admit(ward)

    page = ward["sign_in"]("doc").get(
        f"/beds/admission/{stay}").get_data(as_text=True)

    assert "data-food" in page
    assert "حمية سكري" in page
    assert "data-no-diet-list" not in page


def test_a_clinic_with_no_list_is_told_to_write_one(bare):
    """**مش بنعرض أسماء من عندنا.** الشاشة بتقولهم يكتبوها."""
    stay = _admit(bare)

    page = bare["sign_in"]("doc").get(
        f"/beds/admission/{stay}").get_data(as_text=True)

    assert "data-no-diet-list" in page
    assert 'name="diet_key"' not in page


def test_the_screen_records_an_assessment(ward):
    from app.utils import nutrition

    stay = _admit(ward)
    client = ward["sign_in"]("doc")

    landed = client.post(f"/beds/stay/{stay}/nutrition", data={
        "findings": "نقص وزن", "needs": "yes", "plan": "تحويل للتغذية"})

    assert f"/beds/admission/{stay}" in landed.headers["Location"]
    with ward["app"].app_context():
        row = nutrition.latest_assessment(ward["ids"]["child"])
        assert row.needs_special_diet is True
        assert row.findings == "نقص وزن"


def test_the_screen_shows_the_gap_before_the_board_does(ward):
    """التقييم اللي ما أدّاش لحاجة بيبان جنب الطفل نفسه، مش بس على
    لوحة القسم."""
    stay = _admit(ward)
    client = ward["sign_in"]("doc")
    client.post(f"/beds/stay/{stay}/nutrition", data={"needs": "yes"},
                follow_redirects=True)

    page = client.get(f"/beds/admission/{stay}").get_data(as_text=True)
    assert "data-food-gap" in page

    client.post(f"/beds/stay/{stay}/diet", data={"diet_key": "d1"},
                follow_redirects=True)

    page = client.get(f"/beds/admission/{stay}").get_data(as_text=True)
    assert "data-food-gap" not in page


def test_the_route_refuses_a_diet_that_is_not_on_the_list(ward):
    from app.utils import nutrition

    stay = _admit(ward)

    ward["sign_in"]("doc").post(f"/beds/stay/{stay}/diet",
                                data={"diet_key": "keto"},
                                follow_redirects=True)

    with ward["app"].app_context():
        assert nutrition.current_diet(ward["ids"]["child"]) is None


def test_the_screen_can_stop_an_order(ward):
    from app.utils import nutrition

    stay = _admit(ward)
    client = ward["sign_in"]("doc")
    client.post(f"/beds/stay/{stay}/diet", data={"diet_key": "d2"},
                follow_redirects=True)

    with ward["app"].app_context():
        oid = nutrition.current_diet(ward["ids"]["child"]).id

    client.post(f"/beds/diet/{oid}/stop", follow_redirects=True)

    with ward["app"].app_context():
        assert nutrition.current_diet(ward["ids"]["child"]) is None
        assert len(nutrition.orders_for(ward["ids"]["child"])) == 1


def test_the_three_state_reaches_the_record_from_the_screen(ward):
    """«محدّش قال» من الشاشة لازم توصل ``None``، مش ``False``."""
    from app.utils import nutrition

    stay = _admit(ward)
    client = ward["sign_in"]("doc")

    client.post(f"/beds/stay/{stay}/diet",
                data={"diet_key": "d1", "family_food": ""},
                follow_redirects=True)

    with ward["app"].app_context():
        assert nutrition.current_diet(
            ward["ids"]["child"]).family_food_allowed is None


def test_the_board_shows_the_assessment_that_led_nowhere(ward):
    _assess(ward, needs=True)

    page = ward["sign_in"]("doc").get("/beds/watch").get_data(as_text=True)

    assert "data-food-watch" in page
    assert "data-food-nothing" in page


def test_and_it_leaves_once_food_is_ordered(ward):
    _assess(ward, needs=True)
    _order(ward, "d1", family_food=False)

    page = ward["sign_in"]("doc").get("/beds/watch").get_data(as_text=True)

    assert "data-food-watch" not in page


def test_a_child_with_no_nutrition_record_has_no_tab(ward):
    page = ward["sign_in"]("doc").get(
        f"/patients/{ward['ids']['child']}").get_data(as_text=True)

    assert "'food','tab_food'" not in page
    assert "data-food-assessment=" not in page
    assert "data-diet-order=" not in page


def test_the_file_keeps_both_the_assessment_and_the_orders(ward):
    aid = _assess(ward, needs=True, findings="نقص وزن")
    oid = _order(ward, "d1")

    page = ward["sign_in"]("doc").get(
        f"/patients/{ward['ids']['child']}").get_data(as_text=True)

    assert f'data-food-assessment="{aid}"' in page
    assert f'data-diet-order="{oid}"' in page
    assert "نقص وزن" in page


def test_every_word_of_the_record_is_written_in_both_languages(ward):
    from app.i18n import _load_translations, _lookup

    tables = _load_translations()
    keys = [("food", k) for k in (
        "title", "sub", "watch_hint", "assess", "assessed", "assessed_on",
        "never_assessed", "findings", "plan", "needs", "needs_yes",
        "needs_no", "needs_unknown", "diet", "detail", "meal_times",
        "order", "ordered", "stop", "stopped", "nothing_ordered",
        "family_food", "family_yes", "family_no", "family_unknown",
        "family_unanswered", "no_list", "write_list", "not_saved")]
    keys += [("patients", "tab_food"), ("lookups", "d_special_diet")]
    for lang in ("ar", "en"):
        for group, key in keys:
            assert _lookup(tables, lang, f"{group}.{key}"), \
                f"{lang}: {group}.{key} is missing"
