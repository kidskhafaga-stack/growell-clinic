"""The visit screen, for a dentist.

Asked as *"فين قالب الاسنان"* — and the answer was that the program had
exactly one specialty panel, cardiology, so the dropdown offered nothing else.

The panel is **data, not code**. The file says so itself: *"إضافة تخصص =
إضافة هنا، من غير أي تعديل برمجي"*. This adds a paediatric dental panel to it
and changes no Python at all.

**What it holds is what the tooth chart does not.** No count of decayed or
filled teeth: the chart knows those tooth by tooth, and writing them here
again is two screens holding one fact and disagreeing about it — the thing
already fixed once between the chart and the plan. What the chart cannot know
is the history and the risk: the habits, the night bottle, the fluoride, and
whether the child will sit in the chair at all.
"""
import json
import os

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))


def _panels():
    with open(os.path.join(HERE, "..", "app", "data",
                           "specialty_panels.json"), encoding="utf-8") as fh:
        return json.load(fh)["panels"]


@pytest.fixture
def dental(clinic):
    from app.models import Setting

    with clinic["app"].app_context():
        Setting.set("mod_enabled:dentistry", "1")
        clinic["db"].session.commit()
    return clinic


@pytest.fixture
def screen(dental):
    return dental["sign_in"]("doc").get(
        f"/visits/{dental['ids']['visit']}/record").get_data(as_text=True)


# ------------------------------------------------------------- it exists ---
def test_the_dropdown_offers_it(screen):
    assert 'value="dentistry"' in screen
    assert "أسنان الأطفال" in screen


def test_it_did_not_take_the_other_panel_with_it(screen):
    """Adding a specialty must not cost the one already there."""
    assert 'value="cardiology"' in screen


def test_it_is_data_and_not_code():
    """The file's own promise, and the reason this was cheap. If a panel ever
    needs Python to exist, the next specialty costs a release."""
    fields = _panels()["dentistry"]["fields"]
    assert len(fields) >= 8
    for field in fields:
        assert field["type"] in ("number", "choice", "date"), field["code"]
        assert field.get("label_ar") and field.get("label_en")
        if field["type"] == "choice":
            assert field.get("options"), field["code"]


# ------------------------------------------- what it holds, and what not ---
def test_it_does_not_ask_for_what_the_chart_knows():
    """No dmft, no count of decayed or filled teeth.

    The chart holds every finding tooth by tooth. A number typed here as well
    is two screens holding one fact, and the one that is wrong is whichever
    was not updated — the same trap already closed between the chart and the
    treatment plan.
    """
    codes = " ".join(f["code"] for f in _panels()["dentistry"]["fields"])
    labels = " ".join(f["label_en"].lower()
                      for f in _panels()["dentistry"]["fields"])
    for banned in ("dmft", "decay", "caries", "filled_teeth", "missing_teeth"):
        assert banned not in codes, banned
    for banned in ("decayed", "filled teeth", "caries count"):
        assert banned not in labels, banned


def test_it_asks_the_things_the_chart_cannot_know(screen):
    """History and risk: the habits, the feeding, the fluoride — and whether
    the child will sit in the chair at all, which decides whether any of the
    rest happens today."""
    for asked in ("تعاون الطفل", "رضاعة ليلية", "مص إصبع", "تنفّس من الفم",
                  "مصدر الفلورايد", "الإطباق", "آخر زيارة أسنان"):
        assert asked in screen, asked


def test_it_puts_the_weight_in_front_of_whoever_injects():
    """Not decoration. The largest safe dose of local anaesthetic for a child
    is worked out from their weight, and the number has to be on the screen
    of the person about to give it."""
    assert _panels()["dentistry"]["reads"] == ["weight_kg"]


def test_the_cooperation_scale_is_the_published_one(screen):
    """Frankl, 1 to 4. A clinic's own words for "difficult child" do not
    travel to the next dentist who reads the file."""
    field = next(f for f in _panels()["dentistry"]["fields"]
                 if f["code"] == "cooperation")
    assert "Frankl" in field["label_ar"] or "Frankl" in field["label_en"]
    assert len(field["options"]) == 4
