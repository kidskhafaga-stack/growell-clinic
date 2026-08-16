"""What came off the printer, and what was supposed to.

Three faults, all reported with the PDF attached:

* the clinic's logo did not print, "even though it is in the program";
* a prescription that ran onto a second page put a section heading on one
  sheet and its single line on the next, with the copyright footer stamped
  across the heading;
* on pre-printed paper the date and the offset marker were printed one on top
  of the other.

The page geometry itself was checked by printing through Chromium and
measuring the PDF — that is not something the suite can do, so what is asserted
here is the arrangement the measurements proved right. Each of these fails on
the code as it was.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _paper(clinic, **tpl_kw):
    """A prescription rendered with one deliberately-configured template."""
    from datetime import date

    from app.extensions import db
    from app.models import (Patient, Prescription, PrescriptionItem,
                            RxPrintTemplate, Setting, User)

    with clinic["app"].app_context():
        Setting.set("clinic_logo", "clinic-badge.png")
        doc = User.query.filter_by(username="doc").first()
        kid = Patient.query.first()
        rx = Prescription(patient_id=kid.id, doctor_id=doc.id,
                          rx_date=date(2026, 8, 16), diagnosis="التهاب رئوي")
        db.session.add(rx)
        db.session.flush()
        db.session.add(PrescriptionItem(prescription_id=rx.id,
                                        drug_name="Augmentin", printed=True))
        flags = {f: f not in RxPrintTemplate.OFF_BY_DEFAULT
                 for f in RxPrintTemplate.BOOLS}
        flags.update(tpl_kw.pop("flags", {}))
        tpl = RxPrintTemplate(name="t", mode="white", page_size="A4",
                              font_size=14, margin_mm=12, top_offset_mm=0,
                              **flags, **tpl_kw)
        db.session.add(tpl)
        db.session.commit()
        rx_id, tpl_id = rx.id, tpl.id

    page = clinic["sign_in"]("boss").get(
        f"/prescriptions/{rx_id}?template={tpl_id}").data.decode()
    return page


def _header_imgs(page):
    """Every <img> src inside the letterhead block, in order."""
    import re

    start = page.index('class="print-header"')
    end = page.index("</div>", page.index("</div>", start) + 1)
    return re.findall(r'<img[^>]+src="([^"]+)"', page[start:end])


# ----------------------------------------------------------------- the logo

def test_a_doctor_with_no_personal_logo_still_gets_the_clinics(clinic):
    """The reported one: a template asking for a logo that does not exist.

    It printed *nothing* — not the personal logo, which was never uploaded,
    and not the clinic's, which was sitting in the program the whole time.
    """
    page = _paper(clinic, logo_source="personal")

    assert any("clinic-badge.png" in src for src in _header_imgs(page)), \
        "the letterhead came out with no logo at all"


def test_a_doctor_who_has_one_still_gets_their_own(clinic):
    """The fallback must not overrule the doctor who actually uploaded one."""
    from app.extensions import db
    from app.models import User

    with clinic["app"].app_context():
        User.query.filter_by(username="doc").first().personal_logo = "mine.png"
        db.session.commit()

    imgs = _header_imgs(_paper(clinic, logo_source="personal"))

    assert any("mine.png" in src for src in imgs), \
        "the doctor's own logo was replaced by the clinic's"
    assert not any("clinic-badge.png" in src for src in imgs)


def test_none_still_means_none(clinic):
    """The one value somebody chose on purpose. A fallback must not undo it."""
    page = _paper(clinic, logo_source="none")

    assert not _header_imgs(page), \
        "a template set to print no logo printed one anyway"


def test_the_clinic_logo_is_what_clinic_asks_for(clinic):
    """Unchanged behaviour, asserted so the rewrite above cannot lose it."""
    page = _paper(clinic, logo_source="clinic")

    assert any("clinic-badge.png" in src for src in _header_imgs(page))


# ------------------------------------------------- the footer and the breaks

def _shell():
    with open(os.path.join(ROOT, "app/templates/shell.html"),
              encoding="utf-8") as fh:
        return fh.read()


def _print_css():
    with open(os.path.join(ROOT, "app/static/css/print.css"),
              encoding="utf-8") as fh:
        return fh.read()


def test_the_copyright_line_is_not_taken_out_of_the_flow(clinic):
    """`position: fixed` is exactly why it printed across a heading.

    Measured through Chromium: fixed, it reserves no space on any page, and
    every offset that moved it clear of the text moved it onto the *next*
    page instead. In the flow it is drawn after the last thing on the page and
    can cover nothing.
    """
    shell = _shell()
    block = shell[shell.index(".print-footer { display:flex"):]
    block = block[:block.index("}")]

    assert "position:fixed" not in block.replace(" ", ""), \
        "the footer is out of the flow again and will print over the content"


def test_the_copyright_line_is_not_stranded_on_a_sheet_of_its_own(clinic):
    shell = _shell()
    block = shell[shell.index(".print-footer { display:flex"):]
    block = block[:block.index("}")]

    assert "break-before:avoid" in block.replace(" ", "")


@pytest.mark.parametrize("selector", ["#rxPaper .rx-block", "#rxPaper .rx-sign"])
def test_the_blocks_that_must_not_split_say_so(clinic, selector):
    css = _print_css()
    assert selector in css, f"{selector} has no page-break rule"
    rule = css[css.index(selector):]
    rule = rule[:rule.index("}")]
    assert "break-inside: avoid" in rule


def test_the_paper_marks_the_blocks_the_css_talks_about(clinic):
    """A rule naming a class nothing carries is a rule that does nothing.

    This is the half that would have been missed: the stylesheet can be
    perfect and the page still breaks wherever it likes.
    """
    page = _paper(clinic, logo_source="clinic")

    assert 'class="rx-block"' in page or "rx-block" in page, \
        "no block on the paper is marked as one that must stay whole"
    assert "rx-sign" in page, "the signature block is not marked"


def test_the_drug_table_is_still_allowed_to_split(clinic):
    """Twenty drugs cannot fit on one page and must not be forced to try."""
    css = _print_css()
    rx_block = css[css.index("#rxPaper .rx-block"):]
    rx_block = rx_block[:rx_block.index("}")]

    assert "table" not in rx_block, \
        "the drug table was swept into the do-not-split rule"

    page = _paper(clinic, logo_source="clinic")
    table_at = page.index('<table class="table">')
    line_start = page.rindex("\n", 0, table_at)
    assert "rx-block" not in page[line_start:table_at], \
        "the drug table itself is marked unsplittable"


# --------------------------------------------- pre-printed paper: the marker

def test_the_offset_marker_is_not_on_the_same_edge_as_the_date(clinic):
    """They were printed one across the other.

    On screen the label had an opaque background and hid the collision;
    print.css strips every background to save ink, so it only showed up on
    paper. Both were at the end edge — the fix is that they are not.
    """
    with open(os.path.join(ROOT, "app/templates/prescriptions/test_print.html"),
              encoding="utf-8") as fh:
        test_print = fh.read()
    with open(os.path.join(ROOT, "app/templates/prescriptions/_paper.html"),
              encoding="utf-8") as fh:
        paper = fh.read()

    marker = test_print[test_print.index(".rx-offset-rule span {"):]
    marker = marker[:marker.index("}")]

    # The date, in pre-printed mode, is the only thing on that line.
    date_row = paper[paper.index("{% if tpl.mode == 'preprinted' %}"):]
    date_row = date_row[:date_row.index("{% else %}")]
    assert "text-align:end" in date_row, \
        "this test is reading the wrong line — the date moved"

    assert "inset-inline-end" not in marker, \
        "the offset label is back on the same edge as the date"
    assert "inset-inline-start" in marker


def _test_print_html():
    with open(os.path.join(ROOT, "app/templates/prescriptions/test_print.html"),
              encoding="utf-8") as fh:
        return fh.read()


def _rule(css, selector):
    head = selector + " {"
    assert head in css, f"there is no {selector} rule at all"
    body = css[css.index(head) + len(head):]
    return body[:body.index("}")]


def test_the_page_the_prescription_sits_on_can_break(clinic):
    """`overflow: hidden` on it is what produced the blank sheet.

    In paged media that is not tidiness — it makes the element a fragmentation
    container, so whatever did not fit on the first sheet is clipped away
    instead of carried over, and the sheet reserved for it prints empty.
    """
    rule = _rule(_test_print_html(), ".rx-testwrap")

    assert "overflow" not in rule, \
        "the wrapper holding the prescription clips instead of breaking"
    assert "position: relative" in rule, \
        "the watermark and the offset rule are positioned against this"


def test_the_watermark_is_still_clipped_to_the_paper(clinic):
    """The other half. Losing this brings back "the whole left part vanishes".

    The mark is rotated, and a rotated box is wider than its own text — it hung
    116px off a 1280px page and the browser clipped the page to compensate. The
    clip has to live somewhere; it now lives on a layer that holds no content,
    so it can clip without fragmenting anything.
    """
    html = _test_print_html()
    layer = _rule(html, ".rx-testmark-clip")

    assert "overflow: hidden" in layer
    assert "position: absolute" in layer, \
        "the clipping layer is in the flow and will take up room"
    assert html.index('class="rx-testmark-clip"') < html.index('class="rx-testmark"'), \
        "the watermark is not inside the layer that clips it"
