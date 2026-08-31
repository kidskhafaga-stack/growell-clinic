"""The consultation screen, moved onto the clinic's visual language.

Fourth and last of the screens asked for, after the booking form, the till and
the patient file. It was already half here: the specialty panel had been built
in the Material grammar when it was added, so the stylesheet and one section
were in place and the other eleven panels were not. What this does is finish
it rather than start it.

**No step numbers, for the same reason as the patient file.** A consultation
has a rough order — you look before you prescribe — but a doctor does not
walk it. They write a diagnosis, go back to the vitals, add a drug, open the
consent tab, come back. Numbering eleven panels 1 to 11 would be describing a
march nobody does, and "attachments" is not step eleven of anything.

**`md-step` and `md-badge` are now different things.** The specialty panel was
hanging an icon on a class whose own comment says it is the step number and
that numbering is only honest where there is an order. The circle is the same;
the claim is not, and a vocabulary where the step class sometimes means "this
is a step" and sometimes means "here is a circle" is a vocabulary that has
stopped saying anything.
"""
import re

import pytest


@pytest.fixture
def exam(clinic):
    page = clinic["sign_in"]("doc").get(
        f"/visits/{clinic['ids']['visit']}/record")
    assert page.status_code == 200, f"the exam screen did not open: {page.status_code}"
    return page.get_data(as_text=True)


def _classes(page):
    return [value.split() for value in re.findall(r'class="([^"]*)"', page)]


def test_the_stylesheet_arrives(exam):
    assert "css/material.css" in exam


def test_the_scope_is_open_for_the_whole_screen(exam):
    """It was open for the specialty panel alone — one block of a screen with
    twelve. Every other field on the page was outside it, so the field grammar
    stopped at one section's edge."""
    scoped = [c for c in _classes(exam) if "md" in c]
    assert scoped, "no `.md` scope on the page"
    # The page's own container, not just the panel's inner one.
    assert exam.index('class="md"') < exam.index("md-section"), \
        "the scope opens after the first section, so that section is outside it"


def test_the_panels_are_surfaces(exam):
    """Counted. The screen had one Material section and eleven cards; "some
    section exists" was already true and said nothing."""
    sections = sum(1 for c in _classes(exam) if "md-section" in c)
    assert sections >= 8, f"only {sections} panels are surfaces"


def test_no_panel_is_left_as_a_card(exam):
    """A card beside a tinted surface is the join showing. The patient header
    and the two warning strips stay cards on purpose — a header and a warning
    bar are pinned above the consultation, not sections of it."""
    leftovers = [c for c in _classes(exam)
                 if "card" in c and "gc-scale-in" in c
                 and "profile-header" not in c and "no-print" not in c]
    assert leftovers == [], f"{len(leftovers)} panel(s) still drawn as cards"


def test_the_headings_moved_across(exam):
    """None left behind, not "at least one converted" — the one left behind is
    the heading that looks wrong on somebody's screen."""
    heads = sum(1 for c in _classes(exam) if "md-section-head" in c)
    assert heads >= 8, f"only {heads} headings use the shared grammar"
    stragglers = re.findall(r'<h[1-6][^>]*class="[^"]*\bsection-title\b', exam)
    assert stragglers == [], f"{len(stragglers)} heading(s) were not converted"


def test_the_consultation_is_not_numbered(exam):
    """The line this screen shares with the patient file.

    A doctor moves around this page rather than through it. A "1" on the
    vitals would be claiming the diagnoses panel comes fourth in something
    somebody does in order.
    """
    assert "md-step" not in exam


def test_a_circle_that_is_not_a_step_says_so(exam):
    """The specialty panel still gets its icon badge — under its own name.

    Same circle, different claim. If this ever fails because the badge is gone
    the panel lost its icon; if it fails because `md-step` is back, the step
    class is being used for decoration again.
    """
    assert "md-badge" in exam


def test_every_tab_still_exists(exam):
    """A restyle that quietly loses a panel is a restyle that lost a screen."""
    for tab in ("case", "dx", "inv", "meds", "consent", "proc", "files"):
        assert f"tab==='{tab}'" in exam, f"the {tab} panel is gone"


def test_the_screen_can_still_be_written_in(exam):
    """`.md` restyles every input and select it scopes. A stylesheet cannot
    break a form, but a botched wrapper can swallow one."""
    assert 'name="csrf_token"' in exam
    assert "<form" in exam
    assert 'name="chief_complaint"' in exam or "chief_complaint" in exam
