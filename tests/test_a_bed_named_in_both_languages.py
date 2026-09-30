"""«ليه العربي فى الشاشة الانجليزي» — the names of units, rooms and beds.

The ward wizard wrote each name once, in whatever language the screen was in,
into the one column there was; a screen in English went on showing
«العناية المركزة · الصالة · سرير 1». What is held here:

* the wizard writes the Arabic name and the English one, whichever language
  the person running it had on;
* each screen shows the name in its own language, and the one name there is
  when there is no English;
* on update, only a name that is exactly the program's own gets its English
  — a name somebody typed is never translated;
* the English name can be written and cleared from the units screen.
"""
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def hospital(clinic):
    from app.models import Setting

    with clinic["app"].app_context():
        Setting.set("mod_enabled:beds", "1")
        Setting.set("facility_capabilities", json.dumps(
            ["general_consultation", "emergency_care", "icu", "nicu", "ward"]))
        clinic["db"].session.commit()
    return clinic


def _english(client):
    client.get("/lang/en")
    return client


def test_the_wizard_writes_both_names_whatever_the_screen_says(hospital):
    from app.models import Bed, Space, Unit

    client = _english(hospital["sign_in"]("boss"))
    client.post("/beds/setup/build", data={"icu__beds": "2",
                                           "nicu__incubators": "1"})
    with hospital["app"].app_context():
        icu = Unit.query.filter_by(kind="icu").one()
        assert (icu.name, icu.name_en) == ("العناية المركزة", "Intensive care")
        names = {(b.name, b.name_en) for b in Bed.query.all()}
        assert ("سرير 1", "Bed 1") in names and ("حضّانة 1", "Incubator 1") in names
        assert all(s.name_en for s in Space.query.all())


def test_each_screen_shows_its_own_language(hospital):
    client = hospital["sign_in"]("boss")
    client.post("/beds/setup/build", data={"icu__beds": "2"})
    arabic = client.get("/beds/").get_data(as_text=True)
    assert "العناية المركزة" in arabic and "سرير 1" in arabic
    english = _english(client).get("/beds/").get_data(as_text=True)
    assert "Intensive care" in english and "Bed 1" in english
    assert "العناية المركزة" not in english and "سرير 1" not in english


def test_a_place_with_no_english_shows_the_one_name_it_has(hospital):
    from app.models import Unit

    with hospital["app"].app_context():
        hospital["db"].session.add(Unit(name="قسم الدكتور حسن", kind="ward"))
        hospital["db"].session.commit()
    page = _english(hospital["sign_in"]("boss")).get("/beds/").get_data(as_text=True)
    assert "قسم الدكتور حسن" in page


def test_only_the_programs_own_names_get_their_english_on_update(hospital):
    from app.models import Bed, Space, Unit
    from app.utils.ward_plan import fill_english_names

    with hospital["app"].app_context():
        db = hospital["db"]
        # What a clinic built before this change looks like: one name each.
        nicu = Unit(name="الحضانات", kind="nicu")          # no shadda
        mine = Unit(name="قسم د. حسن", kind="ward")
        db.session.add_all([nicu, mine])
        db.session.flush()
        bay = Space(unit_id=nicu.id, name="الصالة", kind="bay")
        room = Space(unit_id=mine.id, name="غرفة ٤", kind="room")
        odd = Space(unit_id=mine.id, name="غرفة كبار الزوار", kind="room")
        # The program's word and then a word of the clinic's: not a number,
        # so not the program's name — «Room العزل» is nobody's English.
        iso = Space(unit_id=mine.id, name="غرفة العزل", kind="room")
        db.session.add_all([bay, room, odd, iso])
        db.session.flush()
        cot = Bed(space_id=bay.id, name="سرير 3", kind="cot")
        caps = Bed(space_id=bay.id, name="كبسولة", kind="capsule")
        typed = Bed(space_id=room.id, name="Bed A", kind="bed")
        named = Bed(space_id=room.id, name="سرير 2", kind="bed", name_en="Window bed")
        db.session.add_all([cot, caps, typed, named])
        db.session.commit()

        assert fill_english_names() == 5
        db.session.commit()
        got = {r.name: r.name_en for r in Unit.query.all() + Space.query.all()
               + Bed.query.all()}
        assert got["الحضانات"] == "Neonatal unit"
        assert got["الصالة"] == "Bay"
        assert got["غرفة ٤"] == "Room 4"
        # «سرير» is a bed, a cot and a trolley at once; the row's own kind
        # decides which English it is.
        assert got["سرير 3"] == "Cot 3"
        assert got["كبسولة"] == "Capsule"
        # Typed by the clinic: never translated, never touched.
        assert got["قسم د. حسن"] is None
        assert got["غرفة كبار الزوار"] is None
        assert got["غرفة العزل"] is None
        assert got["Bed A"] is None
        assert got["سرير 2"] == "Window bed"
        # And a second run changes nothing.
        assert fill_english_names() == 0


def test_the_english_name_is_written_and_cleared_from_the_units_screen(hospital):
    from app.models import Unit

    with hospital["app"].app_context():
        unit = Unit(name="قسم د. حسن", kind="ward")
        hospital["db"].session.add(unit)
        hospital["db"].session.commit()
        unit_id = unit.id
    client = hospital["sign_in"]("boss")
    page = client.get("/beds/setup").get_data(as_text=True)
    assert f'id="rne-unit-{unit_id}"' in page
    client.post("/beds/rename", data={"level": "unit", "target_id": unit_id,
                                      "name": "قسم د. حسن", "name_en": "Dr Hassan's ward"})
    with hospital["app"].app_context():
        assert hospital["db"].session.get(Unit, unit_id).name_en == "Dr Hassan's ward"
    client.post("/beds/rename", data={"level": "unit", "target_id": unit_id,
                                      "name": "قسم د. حسن", "name_en": ""})
    with hospital["app"].app_context():
        assert hospital["db"].session.get(Unit, unit_id).name_en is None


def test_a_new_unit_can_be_given_its_english_name(hospital):
    from app.models import Unit

    hospital["sign_in"]("boss").post("/beds/unit", data={
        "name": "الطوارئ الجراحية", "name_en": "Surgical emergency", "kind": "emergency"})
    with hospital["app"].app_context():
        row = Unit.query.filter_by(name="الطوارئ الجراحية").one()
        assert row.name_en == "Surgical emergency"
