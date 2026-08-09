"""What comes out of the printer, and why eleven screens got it wrong.

Fifteen report screens. **Four had a print stylesheet and eleven had none** —
so printing one of the eleven put the sidebar, the top bar and the date-filter
toolbar on the paper, and the page came out at whatever size the browser
happened to default to. Measured before the fix, in Chromium with print media
emulated: on `reports/discounts` and `reports/vaccines` the sidebar, topbar and
toolbar were all still displayed, and the page was 216×279mm — US Letter.

The four that worked each carried their own copy of the same rules. So "does
this print properly" depended on which screen you were standing on, and every
new report started life broken until somebody noticed.

**One stylesheet, loaded globally.** After: all six sampled reports hide the
shell, and the page is 210×297mm. Nothing overflows the printable width at
either 794px (the full A4 width) or 703px (what is actually left inside the
12mm margins) — checked, because a table that runs off the right edge prints
with its last column missing and no indication that it existed.

**A4 is stated, not left to the browser.** A default is a default *of the
machine*: a clinic whose laptop is set to Letter loses the bottom 18mm of every
report, once, silently. Egypt uses A4.

It loads before `{% block head %}`, so a page with a real reason to differ
still wins — the prescription takes its page size and per-side margins from
the clinic's chosen print template, and A5 preprinted paper must keep working.
"""
import os
import re
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PRINT_CSS = os.path.join(ROOT, "app", "static", "css", "print.css")
BASE = os.path.join(ROOT, "app", "templates", "base.html")
REPORTS = os.path.join(ROOT, "app", "templates", "reports")


def _css():
    return open(PRINT_CSS, encoding="utf-8").read()


def test_the_page_is_a4_and_says_so():
    """Left to the browser this is a property of the machine, not the clinic."""
    css = _css()
    assert re.search(r"@page\s*\{[^}]*size:\s*A4", css)
    assert re.search(r"@page\s*\{[^}]*margin:", css)


def test_the_program_around_the_document_is_not_printed():
    """The sidebar and the date filter are not part of the report.

    Measured before this existed: on `reports/discounts` the sidebar, the top
    bar and the toolbar were all still displayed under print media.
    """
    import re

    # Comments stripped first. Checking that ".no-print" appeared *anywhere*
    # in the file passed on the comment that explains it while the selector
    # itself had been deleted — caught by removing it and watching the test
    # stay green.
    css = re.sub(r"/\*.*?\*/", "", _css(), flags=re.S)
    block = css[css.index("display: none"):]
    selectors = css[:css.index("display: none")]
    selectors = selectors[selectors.rindex("}") + 1:]
    for part in (".sidebar", ".topbar", ".no-print", ".flashes"):
        assert part in selectors, f"{part} is not in the display:none rule"
    assert "!important" in block[:40]


def test_it_is_loaded_for_every_screen_not_per_report():
    """The point of the change.

    Four reports carried their own copy of these rules and eleven carried
    none, so a new report started life printing the sidebar. One stylesheet in
    the base template means a screen has to *opt out* of printing properly
    rather than opt in.
    """
    base = open(BASE, encoding="utf-8").read()
    assert "css/print.css" in base
    assert 'media="print"' in base


def test_a_page_with_a_reason_to_differ_still_wins():
    """The prescription is not a report and must not be forced onto A4.

    Its page size and per-side margins come from the clinic's chosen print
    template — A5, or preprinted paper with a top offset. So the global sheet
    is loaded *before* ``{% block head %}``, where those rules are written.
    """
    base = open(BASE, encoding="utf-8").read()
    assert base.index("css/print.css") < base.index("{% block head %}")
    # And the prescription still sets its own.
    view = open(os.path.join(ROOT, "app", "templates", "prescriptions",
                             "view.html"), encoding="utf-8").read()
    assert "@page { size: {{ tpl.page_size" in view


def test_table_headings_repeat_on_every_page():
    """A report that runs to three pages is unreadable from page two.

    ``display: table-header-group`` is the whole of it, and it is the sort of
    rule nobody adds until they have printed a long report once.
    """
    css = _css()
    assert "thead" in css and "table-header-group" in css
    assert "break-inside: avoid" in css      # and no row split across a break


def test_scrolling_containers_unroll_on_paper():
    """An `overflow: auto` box prints the slice that was visible.

    Which is how a twenty-row table comes out with six rows and nothing to say
    the other fourteen exist. The catalogue and half the reports wrap their
    tables in one of these for narrow screens.
    """
    css = _css()
    assert "overflow: visible !important" in css
    assert "max-height: none !important" in css


def _forms_without_a_no_print_ancestor(html):
    """Every ``<form>`` on a rendered page that would still print.

    Ancestry, not string presence. The first version of this test searched the
    template source for "no-print" anywhere before the form and passed on
    `analytics` and `staff` while a browser under print media still showed
    their filters — in both, the marker was on the page heading and the form
    sat in a separate card below it. Reading nesting out of template text with
    a string search is the wrong tool; this walks the rendered document.
    """
    from html.parser import HTMLParser

    class Walk(HTMLParser):
        def __init__(self):
            super().__init__()
            self.stack = []
            self.bad = 0

        def handle_starttag(self, tag, attrs):
            classes = dict(attrs).get("class", "") or ""
            hidden = "no-print" in classes
            if tag == "form" and not (hidden or any(self.stack)):
                self.bad += 1
            if tag not in ("br", "img", "input", "hr", "meta", "link"):
                self.stack.append(hidden)

        def handle_endtag(self, tag):
            if self.stack and tag not in ("br", "img", "input", "hr"):
                self.stack.pop()

    walk = Walk()
    walk.feed(html)
    return walk.bad


@pytest.mark.parametrize("report", [
    "financial", "discounts", "vaccines", "inventory", "operational",
    "analytics", "income", "trial-balance", "vat", "balance-sheet",
    "staff", "ar-aging",
])
def test_no_report_prints_its_own_filter_toolbar(clinic, report):
    """The one thing the stylesheet cannot do for a report.

    It can hide `.no-print`; it cannot know which div is a date filter and
    which is the report. So each screen marks its own — and this checks that
    none was forgotten, which is exactly how four-out-of-fifteen happened.
    """
    page = clinic["sign_in"]("boss").get(f"/reports/{report}")
    # Not skipped on a non-200: a report that stopped rendering is a failure,
    # and an earlier version of this test skipped four of them on a mistyped
    # path while reporting itself green.
    assert page.status_code == 200, f"/reports/{report} returned {page.status_code}"
    assert _forms_without_a_no_print_ancestor(page.get_data(as_text=True)) == 0
