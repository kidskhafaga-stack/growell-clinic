"""Choosing a specialty shows its fields. It should not need a save first.

Reported the first time somebody used it: *"علشان ده يظهر لازم ادوس حفظ وده مش
منطقي — عايز حاجة أفضل، أقدر أحمّل الكارت، وخصوصاً لو على الأسنان والغدد"*.

The screen said *"choose one and save the visit to see its fields"*, which put a
round trip through the server between a question and its answer — on a screen
filled in forty times a day, and **before there is anything worth saving**. On a
new visit it is worse than a delay: the doctor has to save a half-empty record
to find out what the record is supposed to contain.

The catalogue is a small data file already read once per request, so the honest
fix is to hand the screen all of it and let the choice be a choice. Nothing is
fetched, nothing needs the network, and the save is unchanged — the server still
writes only the fields belonging to the panel the visit was recorded under, so a
hidden panel's boxes are ignored exactly as an invented field name is.

That last sentence is the one worth testing hardest. Rendering every panel means
every panel's inputs are in the form, and a browser posts what is in the form
whether it is visible or not.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def desk(clinic):
    """A visit whose doctor has no specialty at all — the case that used to
    show nothing until somebody saved."""
    clinic["url"] = f"/visits/{clinic['ids']['visit']}/record"
    return clinic


def _page(desk):
    return desk["sign_in"]("boss").get(desk["url"]).get_data(as_text=True)


def _save(desk, **form):
    data = {"chief_complaint": "متابعة"}
    data.update(form)
    return desk["sign_in"]("boss").post(desk["url"], data=data,
                                        follow_redirects=True)


def _readings(desk):
    from app.models import Measurement

    with desk["app"].app_context():
        return {m.code: m for m in
                Measurement.query.filter_by(visit_id=desk["ids"]["visit"]).all()}


# ------------------------------------------------- no save in the middle

def test_the_fields_are_on_the_page_before_anything_is_saved(desk):
    """The report itself. The cardiology boxes have to be in the document the
    moment the screen opens, whatever the menu currently says."""
    page = _page(desk)

    assert 'name="m_ef_pct"' in page, \
        "the panel's fields still need a save before they exist"


def test_the_screen_no_longer_asks_for_one(desk):
    """The sentence that described the old behaviour has to go with it, or the
    screen tells somebody to do something pointless."""
    from app.i18n import t  # noqa: F401

    page = _page(desk)

    assert "pick_then_save" not in page
    assert "واحفظ الزيارة" not in page and "save the visit to see" not in page


def test_every_panel_in_the_catalogue_is_rendered(desk):
    """Not just the doctor's own. The question named dentistry and endocrine —
    a doctor covering a colleague picks a specialty that is not theirs, and
    that is the case the old screen served worst."""
    from app.utils import panels

    page = _page(desk)

    with desk["app"].app_context():
        keys = list(panels.all_panels())
    assert keys, "the catalogue is empty, so this proves nothing"
    for key in keys:
        assert f'"{key}"' in page or f"'{key}'" in page


def test_choosing_one_is_client_side(desk):
    """No fetch, no route, nothing to fail on a clinic PC that is offline —
    which is most of them, most of the time."""
    page = _page(desk)

    assert "panelKey" in page and "x-show=" in page


# --------------------------- and the save is exactly as strict as before

def test_a_hidden_panels_boxes_are_not_written(desk):
    """The risk the whole change introduces, and the reason it is safe: a
    browser posts what is in the form whether it is visible or not. The server
    writes only what belongs to the panel the visit says it used."""
    _save(desk, specialty_panel="", m_ef_pct="58", m_lvedd_mm="34")

    assert _readings(desk) == {}, \
        "a panel that was not chosen wrote readings into the file"


def test_only_the_chosen_panels_fields_are_kept(desk):
    """Two panels' worth of boxes posted at once — which is what a form with
    every panel in it sends. Only one panel's readings may survive."""
    _save(desk, specialty_panel="cardiology", m_ef_pct="58",
          m_not_a_real_field="9", m_weight_kg="99")

    rows = _readings(desk)

    assert rows["ef_pct"].value_num == 58.0
    assert "not_a_real_field" not in rows
    assert "weight_kg" not in rows, "the panel wrote a vital sign"


def test_a_reading_stays_in_its_box_when_the_menu_comes_back(desk):
    """Every panel is rendered, so the readings handed to the screen are the
    visit's whole set rather than one panel's — otherwise flicking the menu
    back to cardiology would show empty boxes over a saved reading."""
    _save(desk, specialty_panel="cardiology", m_ef_pct="61")

    page = _page(desk)

    assert 'value="61.0"' in page or 'value="61"' in page, \
        "a saved reading is not in its box"


def test_a_reading_survives_the_visit_changing_its_panel(desk):
    """The case that proves the readings are not filtered by the *current*
    key. A visit that recorded an EF and then had its panel put away still
    holds that EF, and the box has to show it when the menu comes back —
    otherwise the screen says the reading is gone while the file still has it.

    Written after mutation testing: filtering the readings back to one panel
    passed every other test here, because in all of them the visit's panel and
    the panel being looked at were the same.
    """
    from app.extensions import db
    from app.models import Measurement, Visit

    with desk["app"].app_context():
        db.session.add(Measurement(patient_id=desk["ids"]["child"],
                                   visit_id=desk["ids"]["visit"],
                                   code="ef_pct", panel="cardiology",
                                   value_num=47.0, unit="%"))
        visit = db.session.get(Visit, desk["ids"]["visit"])
        visit.specialty_panel = None          # put away afterwards
        db.session.commit()

    page = _page(desk)

    assert 'value="47.0"' in page or 'value="47"' in page, \
        "the reading is in the file and not in its box"


# --------------------------------------------- and it is laid out in Material

def test_the_panel_is_laid_out_in_material(desk):
    """Asked for explicitly: *"خلي بالك احنا شغالين بطريقة UI Material 3"*."""
    page = _page(desk)

    assert "css/material.css" in page, "the stylesheet is not loaded"
    assert "md-section" in page and "md-field" in page
