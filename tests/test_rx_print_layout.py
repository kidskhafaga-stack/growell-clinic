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

    # Where the date sits in pre-printed mode — the only thing on that line,
    # because everything else the sheet would carry has moved to the foot
    # beside the signature. This guard has now caught two changes to that
    # line rather than letting the test quietly pass on markup it was no
    # longer reading, which is the whole reason it is here.
    date_row = paper[paper.index("{% if tpl.mode == 'preprinted' %}"):]
    date_row = date_row[:date_row.index("{% else %}")]
    assert "text-align:end" in date_row, \
        "this test is reading the wrong line — the date moved"
    assert "show_license" not in date_row, \
        "the letterhead fields are back at the top, on the clinic's own header"

    assert "inset-inline-end" not in marker, \
        "the offset label is back on the same edge as the date"
    assert "inset-inline-start" in marker

    # And above the rule, not below it. Moving it to the other edge was only
    # ever half a fix: it stopped colliding with the date and then collided
    # with the letterhead fields the moment those began printing on
    # pre-printed paper — measured in the PDF, the label at x 310–383 straight
    # through the doctor's name at 348–386. Every edge *below* the rule is an
    # edge something else can want. The band above it is the space reserved
    # for the clinic's own letterhead, which our ink never touches.
    assert "bottom:" in marker and "top:" not in marker, \
        "the offset label is below the rule again, where the content is"


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


# ------------------------------------------ the font size actually does work

def _paper_source():
    with open(os.path.join(ROOT, "app/templates/prescriptions/_paper.html"),
              encoding="utf-8") as fh:
        return fh.read()


def _theme_css():
    with open(os.path.join(ROOT, "app/static/css/theme.css"),
              encoding="utf-8") as fh:
        return fh.read()


def test_nothing_on_the_paper_is_sized_off_the_browser_root(clinic):
    """Reported as "only some things get smaller".

    The template stamps its size on `#rxPaper`, and `rem` is relative to the
    *browser's root*, not to the element it is written on — so every size
    declared that way ignored the setting completely. Measured at 9, 14 and
    20px, the date line stayed at 13.6, the table headings at 12.8, the badges
    at 11.8, the patient labels at 12.2 and the ℞ at 25.6, at every setting.
    """
    import re

    stray = re.findall(r"font-size:\s*[0-9.]+rem", _paper_source())

    assert not stray, \
        f"sizes on the prescription still ignore the template: {stray}"


@pytest.mark.parametrize("selector", [
    "#rxPaper .table th",
    "#rxPaper .badge",
    "#rxPaper .info-item .k",
    "#rxPaper .info-item .v",
])
def test_the_shared_classes_are_rescaled_for_the_paper(clinic, selector):
    """The other half: these sizes live in the shared stylesheet.

    Fixing only the inline sizes would have left the table headings and the
    badges frozen, which is most of what somebody notices.
    """
    css = _theme_css()
    assert selector in css, f"{selector} is not rescaled for the paper"
    rule = css[css.index(selector):]
    rule = rule[:rule.index("}")]
    assert "em;" in rule and "rem" not in rule, \
        f"{selector} is still sized off the browser root"


def test_the_gaps_shrink_with_the_type(clinic):
    """Type at 9px inside 12px of padding is not a smaller prescription.

    The point of turning the size down is to fit the page, and the spacing is
    most of the height. Measured: before this, 14px→9px took the paper from
    899px to 803px — 11%. After, 868px to 626px — 28%.
    """
    css = _theme_css()
    rule = css[css.index("#rxPaper .table th,"):]
    rule = rule[:rule.index("}")]
    assert "padding: 0.85em 1em" in rule, \
        "the table padding does not follow the font size"

    source = _paper_source()
    sign = source[source.index('class="rx-sign"'):]
    sign = sign[:sign.index(">")]
    assert "margin-top:2.4em" in sign, \
        "the gap above the signature is a fixed size again"


def test_the_page_does_not_stretch_to_the_height_of_the_sheet(clinic):
    """`min-height: 100vh` on `.layout`, on paper, means "one whole page".

    So every document was stretched to the full height of its first sheet and
    anything after it began below the bottom edge. Measured on an A5 page with
    703px of room: the prescription ended at 616, the layout at 702, and the
    copyright line started at 740 — a second sheet, carrying one grey line.
    With this it ends at 668 and the whole thing is one page.
    """
    css = _print_css()
    rule = css[css.index(".layout,\n  .main,\n  .content {"):]
    rule = rule[:rule.index("}")]

    assert "min-height: 0 !important" in rule, \
        "the layout still stretches to a full sheet and pushes the footer off"
    assert "height: auto !important" in rule
