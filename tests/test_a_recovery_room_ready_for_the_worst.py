"""The recovery room's own equipment — GAHAR SAS.19.

*"The post-anesthesia care unit is equipped according to applicable laws,
regulations, and professional practice guidelines."*

1. a recovery room, *"at least one bed for each operating room"* — the
   standard's own number, read against the hospital's own layout;
2. equipped — under the standard's five headings, with the hospital's list;
3. *"identified, available, and checked"* — a check answers every item, and
   a problem stays open until a later check finds the thing there.

The list is the hospital's and starts empty. Nothing refuses a case.
"""
from datetime import datetime, timedelta

import pytest


@pytest.fixture()
def room(clinic):
    from app.models import Bed, Setting, Space, Theatre, Unit

    with clinic["app"].app_context():
        db = clinic["db"]
        Setting.set("mod_enabled:theatres", "1")
        db.session.add_all([Theatre(name="غرفة ١", is_active=True),
                            Theatre(name="غرفة ٢", is_active=True)])
        unit = Unit(name="الإفاقة", kind="recovery", is_active=True)
        db.session.add(unit)
        db.session.flush()
        space = Space(unit_id=unit.id, name="الصالة", kind="bay",
                      is_active=True)
        db.session.add(space)
        db.session.flush()
        db.session.add(Bed(space_id=space.id, name="١", is_active=True))
        db.session.commit()
        clinic["ids"].update(unit=unit.id, space=space.id)
    return clinic


def _unit(room):
    from app.models import Unit

    return room["db"].session.get(Unit, room["ids"]["unit"])


def _add(room, category, name):
    from app.utils import recovery_room as rr

    with room["app"].app_context():
        row = rr.add_item(_unit(room), category, name)
        room["db"].session.commit()
        return row.id


def _full_list(room):
    return {c: _add(room, c, n) for c, n in (
        ("monitoring", "جهاز مونيتور"), ("crash_cart", "جهاز صدمات"),
        ("oxygen", "أكسجين حائطي"), ("medication", "أدرينالين"),
        ("supply", "أمبو أطفال"))}


# --------------------------------------------------- EOC 1: enough beds ----
def test_one_bed_for_two_rooms_is_short(room):
    from app.utils import recovery_room as rr

    with room["app"].app_context():
        assert rr.capacity() == {"rooms": 2, "beds": 1, "units": 1,
                                 "enough": False}
    page = room["sign_in"]("boss").get("/theatres/recovery/equipment"
                                       ).get_data(as_text=True)
    assert "data-beds-short" in page


def test_a_bed_out_of_service_is_not_a_bed(room):
    from app.models import Bed
    from app.utils import recovery_room as rr

    with room["app"].app_context():
        room["db"].session.add(Bed(space_id=room["ids"]["space"], name="٢",
                                   is_active=False))
        room["db"].session.commit()
        assert rr.capacity()["enough"] is False
        room["db"].session.add(Bed(space_id=room["ids"]["space"], name="٣",
                                   is_active=True))
        room["db"].session.commit()
        assert rr.capacity()["enough"] is True


def test_no_operating_room_is_nothing_to_measure(room):
    """Neither enough nor short: with no theatre to count, the number the
    standard gives has nothing to be measured against."""
    from app.models import Theatre
    from app.utils import recovery_room as rr

    with room["app"].app_context():
        for row in Theatre.query.all():
            row.is_active = False
        room["db"].session.commit()
        assert rr.capacity()["enough"] is None


def test_no_recovery_room_is_said(clinic):
    from app.models import Setting

    with clinic["app"].app_context():
        Setting.set("mod_enabled:theatres", "1")
        clinic["db"].session.commit()
    page = clinic["sign_in"]("boss").get("/theatres/recovery/equipment"
                                         ).get_data(as_text=True)
    assert "data-no-recovery-room" in page


# ------------------------------------------------- EOC 2: the headings ----
def test_every_heading_is_named_until_something_is_under_it(room):
    from app.utils import recovery_room as rr

    with room["app"].app_context():
        assert rr.empty_categories(_unit(room)) == [
            "monitoring", "crash_cart", "oxygen", "medication", "supply"]
    _add(room, "crash_cart", "جهاز صدمات")
    with room["app"].app_context():
        assert "crash_cart" not in rr.empty_categories(_unit(room))
    page = room["sign_in"]("boss").get("/theatres/recovery/equipment"
                                       ).get_data(as_text=True)
    assert 'data-empty-heading="oxygen"' in page
    assert 'data-empty-heading="crash_cart"' not in page


@pytest.mark.parametrize("category, name", [("toys", "كورة"),
                                            ("oxygen", "  ")])
def test_what_a_line_cannot_be(room, category, name):
    from app.utils import recovery_room as rr

    with room["app"].app_context(), pytest.raises(ValueError):
        rr.add_item(_unit(room), category, name)


def test_only_a_recovery_room_gets_a_list(room):
    from app.models import Unit
    from app.utils import recovery_room as rr

    with room["app"].app_context():
        ward = Unit(name="عنبر", kind="ward", is_active=True)
        room["db"].session.add(ward)
        room["db"].session.flush()
        with pytest.raises(ValueError):
            rr.add_item(ward, "oxygen", "أكسجين")


def test_the_same_thing_twice_is_one_line(room):
    from app.utils import recovery_room as rr

    first = _add(room, "medication", "Adrenaline")
    with room["app"].app_context():
        rr.retire_item(rr.items(_unit(room))[0])
        room["db"].session.commit()
        again = rr.add_item(_unit(room), "medication", "adrenaline")
        room["db"].session.commit()
        assert again.id == first and again.is_active
        assert len(rr.items(_unit(room), active_only=False)) == 1


def test_only_an_administrator_writes_the_list(room):
    from app.models import RecoveryItem

    data = {"action": "add", "unit_id": room["ids"]["unit"],
            "category": "oxygen", "name": "أكسجين"}
    room["sign_in"]("doc").post("/theatres/recovery/equipment", data=data)
    with room["app"].app_context():
        assert RecoveryItem.query.count() == 0
    room["sign_in"]("boss").post("/theatres/recovery/equipment", data=data)
    with room["app"].app_context():
        assert RecoveryItem.query.count() == 1


# ------------------------------------------------- EOC 3: the check ----
def test_a_check_must_answer_every_item(room):
    from app.utils import recovery_room as rr

    ids = _full_list(room)
    with room["app"].app_context():
        partial = {ids["oxygen"]: ("ok", None)}
        with pytest.raises(ValueError):
            rr.record_check(_unit(room), partial)
        assert rr.latest_check(_unit(room)) is None


def test_a_problem_stays_open_until_a_check_finds_it_fixed(room):
    from app.utils import recovery_room as rr

    ids = _full_list(room)
    with room["app"].app_context():
        found = {i: ("ok", None) for i in ids.values()}
        found[ids["crash_cart"]] = ("faulty", "البطارية فاضية")
        rr.record_check(_unit(room), found,
                        now=datetime.utcnow() - timedelta(hours=2))
        room["db"].session.commit()
        problems = rr.open_problems(_unit(room))
        assert [(i.id, l.finding) for i, l in problems] == [
            (ids["crash_cart"], "faulty")]
        assert not rr.ready(_unit(room))
        found[ids["crash_cart"]] = ("ok", None)
        rr.record_check(_unit(room), found)
        room["db"].session.commit()
        assert rr.open_problems(_unit(room)) == []
        assert rr.ready(_unit(room))


def test_an_item_added_after_the_last_check_is_unchecked(room):
    from app.utils import recovery_room as rr

    ids = _full_list(room)
    with room["app"].app_context():
        rr.record_check(_unit(room), {i: ("ok", None) for i in ids.values()})
        room["db"].session.commit()
    late = _add(room, "medication", "أتروبين")
    with room["app"].app_context():
        assert [i.id for i in rr.never_checked(_unit(room))] == [late]
        assert not rr.ready(_unit(room))


def test_how_often_is_the_hospitals_and_overdue_is_named(room):
    from app.utils import recovery_room as rr

    ids = _full_list(room)
    with room["app"].app_context():
        rr.record_check(_unit(room), {i: ("ok", None) for i in ids.values()},
                        now=datetime.utcnow() - timedelta(hours=30))
        room["db"].session.commit()
        assert rr.due(_unit(room)) is None     # nobody said how often
        assert rr.ready(_unit(room))
        rr.set_check_hours(24)
        room["db"].session.commit()
        assert rr.due(_unit(room)) is True
        assert not rr.ready(_unit(room))


def test_a_room_never_checked_is_due_once_the_hospital_says_how_often(room):
    from app.utils import recovery_room as rr

    _full_list(room)
    with room["app"].app_context():
        assert rr.due(_unit(room)) is None
        rr.set_check_hours(12)
        room["db"].session.commit()
        assert rr.due(_unit(room)) is True


@pytest.mark.parametrize("value", ["0", "-1", "يوم", "1.5"])
def test_a_frequency_that_is_not_one(room, value):
    from app.utils import recovery_room as rr

    with room["app"].app_context(), pytest.raises(ValueError):
        rr.set_check_hours(value)


@pytest.mark.parametrize("stored", ["0", "abc"])
def test_a_stored_frequency_that_is_not_one_reads_as_unset(room, stored):
    from app.models import Setting
    from app.utils import recovery_room as rr

    with room["app"].app_context():
        Setting.set("recovery_check_hours", stored)
        room["db"].session.commit()
        assert rr.check_hours() is None


def test_a_retired_item_is_not_asked_and_stays_in_history(room):
    from app.utils import recovery_room as rr

    ids = _full_list(room)
    with room["app"].app_context():
        rr.record_check(_unit(room), {i: ("ok", None) for i in ids.values()})
        room["db"].session.commit()
        item = [i for i in rr.items(_unit(room)) if i.id == ids["supply"]][0]
        rr.retire_item(item)
        room["db"].session.commit()
        rest = {i: ("ok", None) for k, i in ids.items() if k != "supply"}
        rr.record_check(_unit(room), rest)
        room["db"].session.commit()
        first = rr.checks(_unit(room))[-1]
        assert ids["supply"] in {line.item_id for line in first.lines}


def test_the_screen_records_a_check(room):
    ids = _full_list(room)
    nurse = room["sign_in"]("doc")
    data = {f"found_{i}": "ok" for i in ids.values()}
    data[f"found_{ids['medication']}"] = "expired"
    nurse.post(f"/theatres/recovery/equipment/{room['ids']['unit']}/check",
               data=data)
    page = nurse.get("/theatres/recovery/equipment").get_data(as_text=True)
    assert 'data-open-problems="1"' in page
    assert 'data-last-finding="expired"' in page


def test_the_recovery_board_links_to_it_and_says_not_ready(room):
    page = room["sign_in"]("boss").get("/theatres/recovery"
                                       ).get_data(as_text=True)
    assert "/theatres/recovery/equipment" in page
    assert 'data-pacu-ready="no"' in page
