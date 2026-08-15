"""The family tab stacked three full sections on top of each other.

Asked for in these words: the screens shouldn't look crowded, people get lost
— and, pointing at the settings screen, that fold looks good.

Parents stays open: it is what the tab is opened for. Siblings and coverage
fold away, and are one click back.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def _page(clinic, who="boss"):
    pid = clinic["ids"]["child"]
    return clinic["sign_in"](who).get(f"/patients/{pid}").data.decode()


def test_the_long_sections_fold_away(clinic):
    page = _page(clinic)

    assert page.count("gc-fold") >= 2, "nothing on this screen folds"


def test_parents_is_not_folded(clinic):
    """The one section the tab is opened for stays where it is.

    Written without a "give up quietly if the label is not found" branch: I
    put one in first, and a test that passes when it cannot locate its own
    subject is a test that will keep passing after somebody deletes the thing.
    The label is asserted, then the position is.
    """
    page = _page(clinic)

    assert "أولياء" in page, "the parents section is not on the page at all"
    before = page[:page.index("أولياء")]
    assert before.count("<details") == before.count("</details>"), \
        "the parents section was put inside a fold"


def test_a_folded_section_is_still_in_the_page(clinic):
    """Folded, not dropped — find-in-page and the printout both need it.

    This is why it is ``<details>`` and not a div hidden from script: the
    browser's own search opens a closed ``<details>``, and cannot see into
    something JavaScript has removed.
    """
    page = _page(clinic)

    assert "<details" in page
    assert 'id="coverage"' in page, "the coverage section left the page"


def test_a_link_to_a_folded_section_opens_it(clinic):
    """The trap, caught before it bit this time.

    ``#coverage`` is linked to. A link that lands on a shut section is the
    same fault as an anchor naming a section while the code reading it wants
    a tab — met twice already in this branch, with ``#icd11`` and ``#meds``.
    """
    page = _page(clinic)

    assert "window.location.hash === '#coverage'" in page, \
        "following #coverage would land on a section that stays shut"


def test_the_marker_is_drawn_for_both_directions(clinic):
    """The default triangle points the wrong way in Arabic, which is the
    entire reason it is drawn here instead of being left alone."""
    css = open(os.path.join(os.path.dirname(__file__), "..", "app", "static",
                            "css", "theme.css"), encoding="utf-8").read()

    assert '[dir="rtl"] .gc-fold' in css
