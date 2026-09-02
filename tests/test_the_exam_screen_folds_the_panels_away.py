"""Folding the specialty section so the consultation screen is not crowded.

Asked for as: *"ماشى المقترح بس فى حاجه ممكن تطوي علشان شاشة الكشف متبقاش
زحمة"*. The screen is long, and a doctor who does not need the panel in this
consultation should be able to put it away.

Two things make a fold safe rather than a way to lose work, and both are what
this file tests:

**Folded is not hidden.** The head keeps saying how many panels already carry
something, so a folded box never conceals a filled one. A fold that hid what
was recorded would not be tidying, it would be hiding.

**Folding changes nothing that is submitted.** Every panel's boxes stay in the
form whether the box is open or shut — which is why the fold is `x-show` and
must never become `x-if`. `x-if` removes the nodes from the document, and nodes
that are not in the document are not posted: folding the box would then quietly
clear every reading in it on the next save. That is the one mistake here that
would destroy data, so it is asserted directly.

The state is remembered per browser, because folding this forty times a day is
not tidying, it is work — and per browser and nowhere else, because it is a
preference about one screen on one machine and has no business in the file.
"""
import os
import re
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(HERE, "..", "app", "templates", "visits", "record.html")


@pytest.fixture()
def page(clinic):
    from app.extensions import db
    from app.models import Setting, User, Visit

    with clinic["app"].app_context():
        Setting.set("mod_enabled:panels", "1")
        visit = db.session.get(Visit, clinic["ids"]["visit"])
        db.session.get(User, visit.doctor_id).specialty_panels = \
            "cardiology,dentistry"
        db.session.commit()
    return clinic["sign_in"]("doc").get(
        f"/visits/{clinic['ids']['visit']}/record").get_data(as_text=True)


def _panel_block():
    """The specialty section's own markup, from the `{% if %}` that gates it
    to the `</section>` that ends it. Read from the template rather than the
    rendered page so the Alpine directives are still there to look at."""
    with open(TEMPLATE, encoding="utf-8") as fh:
        source = fh.read()
    start = source.index("{% if panel_on and panel_all %}")
    return source[start:source.index("</section>", start)]


# ------------------------------------------------------------ it can be shut

def test_there_is_something_to_fold_it_with(page):
    assert "fold()" in page, "nothing on the screen puts the section away"
    assert 'x-on:click="fold()"' in page


def test_the_fold_says_which_way_it_is(page):
    """A chevron that never turns is a control nobody trusts."""
    assert "bi-chevron-down" in page and "bi-chevron-left" in page
    assert ':aria-expanded="open' in page


def test_it_is_remembered(page):
    """Forty times a day is not tidying, it is work."""
    assert "localStorage" in page and "gc.panels.open" in page


def test_and_remembered_nowhere_else(page):
    """A preference about one screen on one machine. If this ever reached the
    server it would be a clinical setting nobody asked for, syncing a doctor's
    folded box onto a colleague's screen."""
    from app.models import User

    assert not hasattr(User, "panels_folded")
    assert "panels_open" not in page


# ------------------------------------------- folded is not hidden, or deleted

def test_a_folded_box_still_says_what_is_in_it(page):
    """The head carries the count while the body is shut."""
    assert 'x-show="!open && filled.length"' in page, \
        "folding the box hides that anything was recorded in it"


def test_the_count_is_read_off_the_boxes_themselves(page):
    """Not a list of field names kept in the script. The fields come from a
    data file a clinic can extend, and a list here would go stale the day a
    panel gains one."""
    assert "data-panel-fields" in page
    assert "recount()" in page


def test_folding_never_takes_a_field_out_of_the_form(page):
    """The mistake that would destroy data. `x-if` removes nodes from the
    document and a removed input is not posted, so a folded box would clear
    every reading in it on the next save. The fold has to be `x-show`."""
    block = _panel_block()

    assert 'x-show="open"' in block, "the fold is not an x-show"
    assert "x-if" not in block, \
        "the specialty section uses x-if, which drops its inputs from the form"
    assert "<template" not in block, \
        "a <template> in the panel section keeps its inputs out of the form"


def test_every_panels_boxes_are_in_the_form_at_once(page):
    """The same property from the rendered page: a doctor who works two panels
    posts both, whichever one the chips are showing and whether or not the box
    is folded."""
    assert 'name="m_ef_pct"' in page          # cardiology
    assert 'name="m_overjet_mm"' in page      # dentistry


def test_a_warning_never_folds_away(page):
    """The one line that must stay visible: a visit recorded under a panel the
    catalogue no longer has. A warning that folds away is a warning nobody
    reads."""
    block = _panel_block()
    fold = block.index('<div x-show="open" x-cloak>')
    close = block.index('</div>{# /x-show="open" #}')
    unknown = block.index("{% if panel_key and not panel %}")

    assert not fold < unknown < close, \
        "the unknown-panel warning is inside the fold"


# ------------------------------------------------------- chips, not a menu

def test_the_panels_are_chips_and_not_a_dropdown(page):
    """A `<select>` says pick one, and a doctor may work three. It also could
    not promise that what was typed into one panel survives opening another,
    because only the chosen panel's fields were ever saved."""
    assert 'data-panel-key="cardiology"' in page
    assert 'data-panel-key="dentistry"' in page
    assert re.search(r'<select[^>]*name="specialty_panel"', page) is None, \
        "the specialty picker is still a dropdown"


def test_a_filled_panel_is_marked_on_its_chip(page):
    assert "chip-dot" in page
    assert "filled.includes(" in page
