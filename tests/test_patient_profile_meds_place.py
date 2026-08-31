"""The ongoing-medicines block sat above the child's own name.

Reported from the screen with the area circled: it looks wrong up there.

It did, and the order was the reason — a form for editing a list, printed
before the identity of the person the list belongs to. It has moved into the
prescriptions tab, which is the same subject, the same permission, and what a
doctor about to write one needs to read first.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def _page(clinic, who="boss"):
    pid = clinic["ids"]["child"]
    return clinic["sign_in"](who).get(f"/patients/{pid}").data.decode()


def test_the_medicines_block_is_below_the_patient_header(clinic):
    """The whole complaint, as a position on the page."""
    page = _page(clinic)

    header = page.index("profile-header")
    meds = page.index('id="meds"')
    assert meds > header, \
        "the medicines form still comes before the child's own name"


def test_it_is_inside_the_prescriptions_tab(clinic):
    """Not merely moved down — moved somewhere that means something."""
    page = _page(clinic)

    # The panel, not the tab button — both carry ``tab==='prescriptions'``,
    # and the button comes first.
    #
    # Matched with a pattern rather than the exact class string. It used to
    # read `gc-tab-panel" x-show=…`, which pinned the panel's class attribute
    # to exactly one class: adding a second one to it — as the Material
    # roll-out did — broke a test about where the medicines block sits, which
    # is not a thing that had changed.
    import re

    found = re.search(r'class="[^"]*\bgc-tab-panel\b[^"]*"[^>]*'
                      r"x-show=\"tab==='prescriptions'\"", page)
    assert found is not None, "the prescriptions panel is not on the page"
    panel = found.start()
    meds = page.index('id="meds"')
    # Between this panel's opening and whichever panel opens next — the tabs
    # are not written in the order they are listed, so "after prescriptions"
    # alone would also be true of every panel that follows it.
    # From the end of *this* panel's opening tag. Searching from `panel + 1`
    # finds this panel's own class text again, because `panel` now points at
    # the start of the class attribute rather than at the word itself.
    following = page.find("gc-tab-panel", found.end())

    assert meds > panel, "the medicines block is not in the prescriptions tab"
    assert following == -1 or meds < following, \
        "it fell through into the next tab"


def test_saving_a_medicine_still_lands_somewhere_visible(clinic):
    """The redirect after adding one goes to ``#meds``.

    That is not a tab name, and the tab state is read from the hash — so
    without a mapping the person would land on a page with every panel
    hidden, immediately after saving. This is the same fault as an anchor
    that names a section rather than its tab, which is worth stating because
    it has now been met twice in this program.
    """
    page = _page(clinic)

    assert "inside:" in page, "no mapping from a section to its tab"
    assert "meds: 'prescriptions'" in page, \
        "#meds no longer resolves to a tab that exists"


def test_a_receptionist_is_shown_neither(clinic):
    """It carried a medical permission before the move and still does."""
    page = _page(clinic, who="desk")

    assert 'id="meds"' not in page
