"""القسم داخل صيانة — فترة، مش مفتاح.

*"فى مستشفى القسم فى الصيانة… لازم يكون فى اضافة فترة الاغلاق وكده لازم
نراعيه، حضانة فى فترة صيانة و وحدة كاملة مش شغالة علشان داخله صيانة او
جزء."*

**واللي كان موجود يجاوب تلت السؤال**: مفتاح على السرير بس، من غير مدة
ولا سبب ولا تاريخ — والقسم والحيّز ماكانش ليهم حاجة خالص.
"""
import os
import sys
from datetime import timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: F401,E402

from app.utils.clock import local_today  # noqa: E402


def _ward(clinic):
    """قسم فيه حيّز فيه سريرين."""
    from app.models import Bed, Space, Unit

    unit = Unit(name="الحضّانات", kind="nicu")
    clinic["db"].session.add(unit)
    clinic["db"].session.flush()
    space = Space(unit_id=unit.id, name="صالة ١", kind="bay")
    clinic["db"].session.add(space)
    clinic["db"].session.flush()
    beds = [Bed(space_id=space.id, name=f"حضّانة {i}", kind="incubator")
            for i in (1, 2)]
    for bed in beds:
        clinic["db"].session.add(bed)
    clinic["db"].session.commit()
    return unit, space, beds


# ============ الفترة ============
def test_closing_writes_a_period_not_just_a_flag(clinic):
    from app.models import Closure
    from app.utils import closures

    with clinic["app"].app_context():
        _unit, _space, beds = _ward(clinic)
        closures.close(beds[0], "maintenance", note="فلتر")
        clinic["db"].session.commit()

        row = Closure.query.one()
        assert row.bed_id == beds[0].id
        assert row.reason == "maintenance"
        assert row.closed_at is not None
        assert row.is_open


def test_the_flag_flips_too_so_nothing_working_breaks(clinic):
    """`free_beds` و`board` بيفلتروا على `is_active` من قبل الميزة دي،
    وكل شاشة إقامة ماشية عليهم."""
    from app.utils import closures

    with clinic["app"].app_context():
        _unit, _space, beds = _ward(clinic)
        closures.close(beds[0], "maintenance")
        clinic["db"].session.commit()

        assert beds[0].is_active is False


def test_a_closed_bed_is_not_offered_as_free(clinic):
    from app.utils import beds as ward
    from app.utils import closures

    with clinic["app"].app_context():
        _unit, _space, made = _ward(clinic)
        assert len(ward.free_beds()) == 2

        closures.close(made[0], "disinfection")
        clinic["db"].session.commit()

        free = ward.free_beds()
        assert len(free) == 1
        assert free[0].id == made[1].id


def test_closing_a_whole_unit_closes_every_bed_under_it(clinic):
    """*"وحدة كاملة مش شغالة علشان داخله صيانة"* — والأسرّة تحتها مالهاش
    صف بنفسها."""
    from app.utils import beds as ward
    from app.utils import closures

    with clinic["app"].app_context():
        unit, _space, _beds = _ward(clinic)
        closures.close(unit, "refurbishment")
        clinic["db"].session.commit()

        assert ward.free_beds() == []


def test_a_bed_in_a_closed_unit_knows_it_is_closed(clinic):
    """شاشة بتسأل السرير لوحده بتقول «شغّال» عن سرير في عنبر مقفول — رقم
    غلط في تقرير الإشغال، ودعوة لحد يحطّ فيه طفل."""
    from app.utils import closures

    with clinic["app"].app_context():
        unit, _space, beds = _ward(clinic)
        closures.close(unit, "maintenance")
        clinic["db"].session.commit()

        assert closures.current(beds[0]) is None
        found = closures.covering(beds[0])
        assert found is not None
        assert found.unit_id == unit.id


def test_the_nearest_closure_wins(clinic):
    """السرير الأول، بعدين الحيّز، بعدين القسم."""
    from app.utils import closures

    with clinic["app"].app_context():
        unit, _space, beds = _ward(clinic)
        closures.close(unit, "refurbishment")
        closures.close(beds[0], "equipment")
        clinic["db"].session.commit()

        assert closures.covering(beds[0]).reason == "equipment"
        assert closures.covering(beds[1]).reason == "refurbishment"


def test_nobody_is_admitted_into_a_closed_unit(clinic):
    """**الفعل نفسه، مش القايمة بس.** `free_beds` بتسيب السرير بره، بس
    `admit` بتتنده كمان من غير القايمة — والسرير نفسه `is_active` بتاعه
    لسه `True`، لأن القسم هو اللي اتقفل مش هو."""
    from app.models import Patient
    from app.utils import beds as ward
    from app.utils import closures

    with clinic["app"].app_context():
        unit, _space, beds = _ward(clinic)
        closures.close(unit, "refurbishment")
        clinic["db"].session.commit()
        assert beds[0].is_active is True

        with pytest.raises(ward.BedTaken):
            ward.admit(Patient.query.first(), beds[0])


def test_nobody_is_moved_into_a_closed_space(clinic):
    from app.models import Bed, Patient, Space
    from app.utils import beds as ward
    from app.utils import closures

    with clinic["app"].app_context():
        unit, space, beds = _ward(clinic)
        other = Space(unit_id=unit.id, name="صالة ٢", kind="bay")
        clinic["db"].session.add(other)
        clinic["db"].session.flush()
        spare = Bed(space_id=other.id, name="حضّانة ٣", kind="incubator")
        clinic["db"].session.add(spare)
        clinic["db"].session.commit()

        stay = ward.admit(Patient.query.first(), spare)
        closures.close(space, "disinfection")
        clinic["db"].session.commit()

        with pytest.raises(ward.BedTaken):
            ward.move(stay, beds[0])


def test_reopening_puts_the_beds_back(clinic):
    from app.utils import beds as ward
    from app.utils import closures

    with clinic["app"].app_context():
        unit, _space, _beds = _ward(clinic)
        closures.close(unit, "maintenance")
        closures.reopen(unit)
        clinic["db"].session.commit()

        assert len(ward.free_beds()) == 2


def test_a_closure_survives_clear_data_like_the_ward_it_belongs_to(clinic):
    """«امسح البيانات» بيسيب العنابر — **المبنى مش الشغل اللي حصل فيه**.
    وفترات صيانة المبنى من تاريخ المبنى، فبتعيش معاه."""
    from app.utils import wipe

    with clinic["app"].app_context():
        assert "care_closures" not in wipe.wiped_tables()


# ============ المخطط غير اللي حصل ============
def test_the_plan_and_what_happened_are_two_columns(clinic):
    """`until` هو الكلام، و`reopened_at` هو اللي حصل. عمود واحد بيمسح
    الفرق، وساعتها مفيش شاشة تقدر تقول «الصيانة دي عدّت ميعادها»."""
    from app.utils import closures

    with clinic["app"].app_context():
        _unit, _space, beds = _ward(clinic)
        planned = local_today() + timedelta(days=3)
        row = closures.close(beds[0], "maintenance", until=planned)
        clinic["db"].session.commit()

        closures.reopen(beds[0])
        clinic["db"].session.commit()

        assert row.until == planned
        assert row.reopened_at is not None
        assert row.reopened_at != row.until


def test_no_end_date_is_a_real_answer(clinic):
    """«مش عارفين هيخلص امتى» إجابة حقيقية، وتاريخ مخترع أسوأ من فراغ."""
    from app.utils import closures

    with clinic["app"].app_context():
        _unit, _space, beds = _ward(clinic)
        row = closures.close(beds[0], "equipment")
        clinic["db"].session.commit()

        assert row.until is None
        # ومش متأخر — ده قرار اتاخد صح مش تأخير.
        assert row.overdue is False
        assert closures.overdue() == []


def test_a_closure_past_its_date_is_listed(clinic):
    from app.utils import closures

    with clinic["app"].app_context():
        _unit, _space, beds = _ward(clinic)
        row = closures.close(beds[0], "maintenance",
                             until=local_today() - timedelta(days=2))
        clinic["db"].session.commit()

        assert row.overdue is True
        assert [c.id for c in closures.overdue()] == [row.id]


def test_a_closure_due_today_is_not_late_yet(clinic):
    """**يوم مش لحظة.** «هيخلص النهارده» مش متأخر النهارده — لو الميعاد
    اتخزّن ساعة نص الليل، كان هيبقى «متأخر» من أول دقيقة في اليوم اللي
    المفروض يخلص فيه."""
    from app.utils import closures

    with clinic["app"].app_context():
        _unit, _space, beds = _ward(clinic)
        row = closures.close(beds[0], "maintenance", until=local_today())
        clinic["db"].session.commit()

        assert row.overdue is False
        assert closures.overdue() == []


def test_a_reopened_closure_is_never_overdue(clinic):
    from app.utils import closures

    with clinic["app"].app_context():
        _unit, _space, beds = _ward(clinic)
        row = closures.close(beds[0], "maintenance",
                             until=local_today() - timedelta(days=2))
        closures.reopen(beds[0])
        clinic["db"].session.commit()

        assert row.overdue is False
        assert closures.overdue() == []


# ============ اللي بيتمنع ============
def test_a_closure_without_a_reason_is_refused(clinic):
    """صف من غير سبب هو اللي حد هيبصّ عليه بعد شهر ومش هيعرف يفتحه."""
    from app.utils import closures

    with clinic["app"].app_context():
        _unit, _space, beds = _ward(clinic)
        with pytest.raises(ValueError):
            closures.close(beds[0], "")
        with pytest.raises(ValueError):
            closures.close(beds[0], "   ")


def test_closing_twice_does_not_make_a_second_row(clinic):
    """صفّين مفتوحين على نفس المكان بيخلّوا «مقفول من امتى» سؤال
    بإجابتين."""
    from app.models import Closure
    from app.utils import closures

    with clinic["app"].app_context():
        _unit, _space, beds = _ward(clinic)
        first = closures.close(beds[0], "maintenance")
        again = closures.close(beds[0], "disinfection")
        clinic["db"].session.commit()

        assert again.id == first.id
        assert Closure.query.count() == 1


def test_a_bed_under_a_closed_unit_cannot_be_reopened_alone(clinic):
    """زرار بيفتح سرير في عنبر داخل صيانة بيخلّيه يبان فاضي وهو مش
    شغّال — يعني زرار بيكدب."""
    from app.utils import closures

    with clinic["app"].app_context():
        unit, _space, beds = _ward(clinic)
        closures.close(beds[0], "equipment")
        closures.close(unit, "refurbishment")
        clinic["db"].session.commit()

        with pytest.raises(closures.Stuck):
            closures.reopen(beds[0])


def test_reopening_something_that_was_never_closed_says_so(clinic):
    from app.utils import closures

    with clinic["app"].app_context():
        _unit, _space, beds = _ward(clinic)
        assert closures.reopen(beds[0]) is None


def test_a_place_is_one_of_three_levels(clinic):
    from app.models import Patient
    from app.utils import closures

    with clinic["app"].app_context():
        with pytest.raises(ValueError):
            closures.level(Patient())


# ============ الطفل اللي لسه جوّه ============
def test_closing_a_unit_with_a_child_in_it_is_allowed(clinic):
    """الصيانة بتحصل والطفل موجود، ورفض بيخلّي اللي قدام الشاشة يسيب
    القسم مفتوح وهو مش شغّال — يعني السجل يكدب علشان البرنامج كان
    مؤدّب."""
    from app.models import Patient
    from app.utils import beds as ward
    from app.utils import closures

    with clinic["app"].app_context():
        unit, _space, made = _ward(clinic)
        kid = Patient.query.first()
        ward.admit(kid, made[0])
        clinic["db"].session.commit()

        row = closures.close(unit, "maintenance")
        clinic["db"].session.commit()
        assert row.is_open


def test_but_the_child_is_named_so_somebody_moves_them(clinic):
    from app.models import Patient
    from app.utils import beds as ward
    from app.utils import closures

    with clinic["app"].app_context():
        unit, _space, made = _ward(clinic)
        kid = Patient.query.first()
        ward.admit(kid, made[0])
        closures.close(unit, "maintenance")
        clinic["db"].session.commit()

        left = closures.stranded()
        assert len(left) == 1
        closure, stays = left[0]
        assert closure.unit_id == unit.id
        assert [s.admission.patient_id for s in stays] == [kid.id]


def test_closing_an_occupied_bed_is_still_refused(clinic):
    """**القاعدة القديمة زي ما هي**، ومكتوبة في الراوت من زمان: سرير فيه
    طفل مش متاح أصلاً، وإخراجه من الخدمة بيخفيه هو والطفل اللي فيه."""
    from app.models import Patient
    from app.utils import beds as ward
    from app.utils import closures

    with clinic["app"].app_context():
        _unit, _space, made = _ward(clinic)
        kid = Patient.query.first()
        ward.admit(kid, made[0])
        clinic["db"].session.commit()

        with pytest.raises(closures.Occupied):
            closures.close(made[0], "maintenance")
        # والسرير التاني عادي.
        assert closures.close(made[1], "maintenance") is not None


def test_an_empty_closed_unit_strands_nobody(clinic):
    from app.utils import closures

    with clinic["app"].app_context():
        unit, _space, _beds = _ward(clinic)
        closures.close(unit, "maintenance")
        clinic["db"].session.commit()

        assert closures.stranded() == []


# ============ التاريخ ============
def test_the_history_keeps_every_period(clinic):
    """مفتاح بيجاوب «مقفول دلوقتي؟». وأول ما يفتح، «كان مقفول كام يوم
    الشهر اللي فات؟» ما بقاش ليه إجابة."""
    from app.utils import closures

    with clinic["app"].app_context():
        _unit, _space, beds = _ward(clinic)
        closures.close(beds[0], "maintenance")
        closures.reopen(beds[0])
        closures.close(beds[0], "disinfection")
        clinic["db"].session.commit()

        rows = closures.history(beds[0])
        assert len(rows) == 2
        assert {r.reason for r in rows} == {"maintenance", "disinfection"}


def test_the_reasons_are_the_clinic_s_list(clinic):
    """أسباب تشغيلية زي «علبة» و«ثلاجة» — والمستشفى تزوّد عليها."""
    from app.models.closure import REASON_DOMAIN
    from app.utils import closures, lookups

    with clinic["app"].app_context():
        closures.ensure_reasons()
        clinic["db"].session.commit()

        keys = {row.key for row in lookups.options(REASON_DOMAIN)}
        assert "maintenance" in keys
        assert "disinfection" in keys
        # واتنده تاني ما بيكرّرش.
        assert closures.ensure_reasons() == 0


# ============ الشاشة ============
@pytest.fixture(autouse=True)
def _ward_module_on(request):
    """موديول الأقسام مقفول في العيادة الافتراضية — والشاشة بترجّع 404
    من غيره. بيتفتح هنا لكل اختبار بيستعمل العيادة."""
    if "clinic" not in request.fixturenames:
        return
    from app.blueprints.beds.routes import MODULE
    from app.models import Setting

    clinic = request.getfixturevalue("clinic")
    with clinic["app"].app_context():
        Setting.set(f"mod_enabled:{MODULE}", "1")
        clinic["db"].session.commit()


def _setup(clinic, user="boss"):
    page = clinic["sign_in"](user).get("/beds/setup")
    assert page.status_code == 200
    return page.get_data(as_text=True)


def test_the_screen_offers_to_close_a_unit(clinic):
    with clinic["app"].app_context():
        unit, _space, _beds = _ward(clinic)
        unit_id = unit.id
    assert f'data-close-unit="{unit_id}"' in _setup(clinic)


def test_closing_and_reopening_from_the_screen(clinic):
    from app.models import Unit

    with clinic["app"].app_context():
        unit, _space, _beds = _ward(clinic)
        unit_id = unit.id

    client = clinic["sign_in"]("boss")
    client.post("/beds/close", data={"level": "unit", "target_id": unit_id,
                                     "reason": "maintenance",
                                     "until": "2099-01-01"})
    with clinic["app"].app_context():
        assert clinic["db"].session.get(Unit, unit_id).is_active is False

    html = _setup(clinic)
    # **القسم المقفول بيفضل على الشاشة** — لو اختفى، زرار الفتح يختفي معاه.
    assert f'data-reopen-unit="{unit_id}"' in html

    client.post("/beds/reopen", data={"level": "unit", "target_id": unit_id})
    with clinic["app"].app_context():
        assert clinic["db"].session.get(Unit, unit_id).is_active is True


def test_the_screen_refuses_a_closure_without_a_reason(clinic):
    from app.models import Closure

    with clinic["app"].app_context():
        unit, _space, _beds = _ward(clinic)
        unit_id = unit.id
    clinic["sign_in"]("boss").post(
        "/beds/close", data={"level": "unit", "target_id": unit_id,
                             "reason": ""})
    with clinic["app"].app_context():
        assert Closure.query.count() == 0


def test_the_screen_keeps_the_old_rule_for_an_occupied_bed(clinic):
    import json

    from app.models import Closure, Patient
    from app.utils import beds as ward

    ar = json.load(open("app/i18n/locales/ar.json", encoding="utf-8"))
    with clinic["app"].app_context():
        _unit, _space, made = _ward(clinic)
        ward.admit(Patient.query.first(), made[0])
        clinic["db"].session.commit()
        bed_id = made[0].id

    page = clinic["sign_in"]("boss").post(
        "/beds/close", data={"level": "bed", "target_id": bed_id,
                             "reason": "maintenance"},
        follow_redirects=True).get_data(as_text=True)
    assert ar["beds"]["occupied_bed"] in page
    with clinic["app"].app_context():
        assert Closure.query.count() == 0


def test_a_child_left_in_a_closed_unit_is_named_on_the_screen(clinic):
    from app.models import Patient
    from app.utils import beds as ward
    from app.utils import closures

    with clinic["app"].app_context():
        unit, _space, made = _ward(clinic)
        kid = Patient.query.first()
        ward.admit(kid, made[0])
        closures.close(unit, "maintenance")
        clinic["db"].session.commit()
        name = kid.full_name

    html = _setup(clinic)
    banner = html.split("data-stranded")[1].split("</ul>")[0]
    assert name in banner


def test_the_board_still_shows_the_child_in_a_closed_unit(clinic):
    """**مرسوم مش متشال.** البورد كانت بتسيب أي قسم مش شغّال — وده كان
    هيخفي الطفل اللي لسه جوّه، نفس السبب اللي بيمنع إخراج سرير فيه طفل
    من الخدمة."""
    from app.models import Patient
    from app.utils import beds as ward
    from app.utils import closures

    with clinic["app"].app_context():
        unit, _space, made = _ward(clinic)
        kid = Patient.query.first()
        ward.admit(kid, made[0])
        closures.close(unit, "maintenance")
        clinic["db"].session.commit()

        rows = [r for r in ward.board() if r["unit"].id == unit.id]
        assert len(rows) == 1 and rows[0]["closed"] is True
        cells = rows[0]["spaces"][0]["beds"]
        assert [c["state"] for c in cells] == ["taken", "off"]
        assert rows[0]["free"] == 0 and rows[0]["taken"] == 1

    page = clinic["sign_in"]("boss").get("/beds/").get_data(as_text=True)
    assert "data-unit-closed" in page
    assert kid.full_name in page


def test_the_dashboard_count_does_not_subtract_a_child_from_the_wrong_beds(clinic):
    """«فاضي» = السراير الشغّالة اللي محدّش فيها — مش «الشغّالة ناقص كل
    الناس». طفل لسه في قسم اتقفل للصيانة كان هيتطرح من سراير هو مش
    فيها، والعنبر يبان أمليا بسرير."""
    from app.models import Bed, Patient, Space, Unit
    from app.utils import beds as ward
    from app.utils import closures

    with clinic["app"].app_context():
        unit, _space, made = _ward(clinic)
        ward.admit(Patient.query.first(), made[0])
        closures.close(unit, "maintenance")
        open_unit = Unit(name="الداخلي", kind="ward")
        clinic["db"].session.add(open_unit)
        clinic["db"].session.flush()
        room = Space(unit_id=open_unit.id, name="غرفة ١", kind="room")
        clinic["db"].session.add(room)
        clinic["db"].session.flush()
        for i in range(3):
            clinic["db"].session.add(Bed(space_id=room.id, name=f"سرير {i}"))
        clinic["db"].session.commit()

        got = ward.counts()
        assert got == {"free": 3, "taken": 1, "total": 3}


def test_the_reasons_are_there_the_first_time_the_screen_opens(clinic):
    """القايمة بتتحط **قبل** ما تتقري — وإلا أول فتحة بتلاقي الاختيارات
    فاضية، والفورم بيطلب سبب مش موجود."""
    with clinic["app"].app_context():
        _ward(clinic)
    html = _setup(clinic)
    form = html.split("data-close-unit")[1].split("</form>")[0]
    assert 'value="maintenance"' in form


def test_the_screen_asks_once_not_once_per_bed(clinic):
    """**استعلام واحد للشاشة كلها.** نفس المستشفى بسريرين أو بعشرين لازم
    تكلّف نفس عدد الاستعلامات — وإلا ستين سرير يبقوا ستين سؤال."""
    from sqlalchemy import event

    from app.models import Bed

    def count_queries():
        seen = []
        with clinic["app"].app_context():
            engine = clinic["db"].engine
        listener = lambda *a, **k: seen.append(1)  # noqa: E731
        event.listen(engine, "before_cursor_execute", listener)
        try:
            _setup(clinic)
        finally:
            event.remove(engine, "before_cursor_execute", listener)
        return len(seen)

    with clinic["app"].app_context():
        _unit, space, _beds = _ward(clinic)
        space_id = space.id
    # أول فتحة بتدفع حاجات مرة واحدة (زرع الأسباب، الدخول) — مش هي اللي
    # بنقيسها.
    count_queries()
    small = count_queries()

    with clinic["app"].app_context():
        for i in range(20):
            clinic["db"].session.add(Bed(space_id=space_id, name=f"زيادة {i}",
                                         kind="incubator"))
        clinic["db"].session.commit()
    big = count_queries()

    assert big == small, (small, big)


def test_only_an_admin_closes_a_place(clinic):
    with clinic["app"].app_context():
        unit, _space, _beds = _ward(clinic)
        unit_id = unit.id
    page = clinic["sign_in"]("desk").post(
        "/beds/close", data={"level": "unit", "target_id": unit_id,
                             "reason": "maintenance"})
    assert page.status_code == 403


def test_every_word_is_written_in_both_languages():
    import json

    ar = json.load(open("app/i18n/locales/ar.json", encoding="utf-8"))
    en = json.load(open("app/i18n/locales/en.json", encoding="utf-8"))
    assert set(ar["closures"]) == set(en["closures"])
    for key in ar["closures"]:
        assert ar["closures"][key].strip(), key
        assert en["closures"][key].strip(), key
