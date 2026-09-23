"""The stay sheet, in five tabs — and every door into it still opens.

Asked for from the clinic: *"الحته دي حلوه بس محتاجه شوية انيماشن وتبقى منظمة
اكثر واكثر احترافية وتبقى تجربة مستخدم سهلة"*. Twenty cards stacked became
five tabs under a header that says who, where, how long, and whose patient.

**The risk in that is the one the patient file already paid for.** Other
screens and the server's own redirects send people to sections of this page
by fragment — `#pain` from the watch board, `#medicines` from the file,
`#restraint` after saving one. On a page of tabs, a fragment that names no
tab hides every panel at once. So the page maps sections to their tabs, falls
back to the first tab for anything it does not know (checked in Chromium:
`#pain` opens nursing, `#nonsense` opens the stay), and this file holds the
map to what the program actually sends.
"""
import os
import re
from datetime import datetime, timedelta

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PAGE = os.path.join(ROOT, "app", "templates", "beds", "admission.html")


def _template():
    with open(PAGE, encoding="utf-8") as fh:
        return fh.read()


def _placed():
    source = _template()
    block = source[source.index("inside: {"):]
    block = block[:block.index("}") + 1]
    return dict(re.findall(r"'?([a-z_-]+)'?\s*:\s*'([a-z_]+)'", block))


def _tabs():
    return set(re.findall(r"\('([a-z_]+)', 'bi-", _template()))


def _fragments_sent_here():
    """Every `#fragment` the program sends to the stay page."""
    found = set()
    for folder in ("app/blueprints", "app/templates", "app/utils"):
        for base, _dirs, files in os.walk(os.path.join(ROOT, folder)):
            for name in files:
                if not name.endswith((".py", ".html")):
                    continue
                with open(os.path.join(base, name), encoding="utf-8") as fh:
                    text = fh.read()
                # Links: url_for('beds.admission', …) followed by a fragment.
                found |= set(re.findall(
                    r"beds\.admission['\"][^)]*\)\s*(?:\}\}|~|\+)?\s*['\"]?#([a-z_-]+)",
                    text))
                # Redirects through the stay's own helper.
                found |= set(re.findall(r"_stay_back\([^,]+,\s*\"#([a-z_-]+)\"",
                                        text))
    return found


def test_the_scan_finds_the_doors_it_was_written_for():
    doors = _fragments_sent_here()
    assert {"pain", "nursing", "medicines", "restraint", "arrest", "food",
            "lines"} <= doors


def test_every_door_opens_a_tab_that_exists():
    tabs, placed = _tabs(), _placed()
    lost = [f for f in _fragments_sent_here()
            if f not in tabs and placed.get(f) not in tabs]
    assert not lost, f"these would open nothing but the first tab: {lost}"


def test_every_mapped_section_is_an_element_on_the_page():
    """A map entry for an id nobody carries would open the right tab and
    scroll nowhere."""
    source = _template()
    for section in _placed():
        assert f'id="{section}"' in source, section


def test_unknown_fragments_fall_back_rather_than_hide_everything():
    assert "this.known.includes(wanted) ? wanted : 'overview'" in _template()


# --------------------------------------------------------- rendered ----
@pytest.fixture
def stay(clinic):
    from app.models import Admission, Setting

    with clinic["app"].app_context():
        Setting.set("mod_enabled:beds", "1")
        row = Admission(patient_id=clinic["ids"]["child"],
                        admitted_at=datetime.utcnow() - timedelta(hours=30))
        clinic["db"].session.add(row)
        clinic["db"].session.commit()
        clinic["ids"]["stay"] = row.id
    return clinic


def _page(stay):
    return stay["sign_in"]("boss").get(
        f"/beds/admission/{stay['ids']['stay']}").get_data(as_text=True)


def test_every_panel_has_its_tab_and_every_tab_its_panel(stay):
    page = _page(stay)
    panels = re.findall(r'data-stay-panel="([a-z_]+)"', page)
    tabs = re.findall(r'data-tab="([a-z_]+)"', page)
    assert panels == tabs == ["overview", "care", "treatment", "safety",
                              "discharge"]


def test_a_closed_stay_has_no_restraint_tab(stay):
    """Restraint and resuscitation are for a child in a bed now."""
    from app.models import Admission

    with stay["app"].app_context():
        row = stay["db"].session.get(Admission, stay["ids"]["stay"])
        row.discharged_at = datetime.utcnow()
        row.outcome = "home"
        stay["db"].session.commit()
    page = _page(stay)
    assert 'data-tab="safety"' not in page
    assert 'data-stay-panel="safety"' not in page
    assert "data-stay-closed" in page
    assert "data-stay-arrest" not in page


def test_the_header_answers_the_first_four_questions(stay):
    """Who, where, how long, whose patient — before any tab is opened."""
    page = _page(stay)
    for mark in ("data-stay-hero", "data-stay-length", "data-stay-mrp"):
        assert mark in page
    assert "data-stay-arrest" in page


def test_no_card_was_lost_in_the_move(stay):
    """The cards were moved, not rewritten: every section the old sheet
    carried is still on the page."""
    page = _page(stay)
    for mark in ("data-mrp", 'id="nursing"', 'id="pain"', 'id="medicines"',
                 'id="food"', 'id="lines"', 'id="restraint"', 'id="arrest"',
                 'id="discharge-summary"'):
        assert mark in page, mark
