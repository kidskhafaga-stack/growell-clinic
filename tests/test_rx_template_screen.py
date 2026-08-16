"""The template screen said things that were not true.

Two reports, from the screen itself:

* five settings were shown ticked and working on a pre-printed template —
  the doctor's name, the specialty, the contact line, the licence and the
  logo. A pre-printed template skips the letterhead entirely, because the
  paper already carries one, so none of the five does anything at all in
  that mode. Asked as: "why isn't the address showing, it's ticked?"
* the little live preview drew the offset twice — once as the grey
  letterhead band and again as padding on the content — so it put the text
  at `margin + 2 × offset`. Reported as "this part isn't real any more".

The geometry was checked in a browser: with a 12mm margin and a 30mm offset
the band starts at 15.3px, is 35.7px tall, and the content begins at 51 —
which is the two added once, not twice.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _screen(clinic, address=None, phone=None):
    from app.extensions import db
    from app.models import RxPrintTemplate, Setting

    with clinic["app"].app_context():
        Setting.set("clinic_address", address or "")
        Setting.set("clinic_phone", phone or "")
        if not RxPrintTemplate.query.first():
            db.session.add(RxPrintTemplate(
                name="pre", mode="preprinted", page_size="A5", font_size=14,
                margin_mm=12, top_offset_mm=30, logo_source="clinic",
                **{f: f not in RxPrintTemplate.OFF_BY_DEFAULT
                   for f in RxPrintTemplate.BOOLS}))
        db.session.commit()

    return clinic["sign_in"]("boss").get("/prescriptions/templates").data.decode()


def _block(page, marker, end="</div>"):
    start = page.index(marker)
    return page[start:page.index(end, start)]


# ------------------------------------- controls that only work in one mode

def test_the_letterhead_settings_say_when_they_do_nothing(clinic):
    """A control that is shown but does nothing is worse than one that is not."""
    page = _screen(clinic)

    assert "rxtpl.preprinted_inert" not in page, "the note is an untranslated key"
    assert 'class="rx-note"' in page, \
        "nothing on the screen says the letterhead settings are unused"
    assert "f.mode==='preprinted'" in page, \
        "the note is not tied to the mode that makes them unused"


def test_the_letterhead_settings_work_in_both_paper_modes(clinic):
    """They were dimmed here, and dimming them was the wrong half of the fix.

    A pre-printed template used to skip the whole letterhead, so the four
    settings really did nothing and the honest thing was to say so. Then:
    "the ones that are ticked I might still want printed, like the licence on
    pre-printed paper" — which is right. A letterhead printed last year does
    not carry this doctor's licence, and a pad shared by three doctors does
    not carry a name either. So they print in both modes and the group is
    live in both.
    """
    page = _screen(clinic)
    group = page[page.index("rxtpl.letterhead_group") if "rxtpl.letterhead_group" in page
                 else page.index('class="rx-legend"'):]
    group = group[:group.index('class="rx-legend"', 40)]

    assert "is-inert" not in group, \
        "the letterhead settings are dimmed again on a mode that now uses them"


def test_dimming_them_does_not_quietly_clear_them(clinic):
    """`disabled` would have been the obvious way, and it loses data.

    A disabled checkbox is not posted, so every save on a pre-printed
    template would have turned the doctor's name, the specialty, the contact
    line and the licence off — silently, and only visible on the day the
    clinic switched the template back to white paper.
    """
    page = _screen(clinic)

    for field in ("show_doctor", "show_specialty", "show_contact",
                  "show_license", "logo_source"):
        at = page.index('name="%s"' % field)
        tag = page[page.rindex("<", 0, at):page.index(">", at)]
        assert "disabled" not in tag, \
            f"{field} is disabled, so saving would clear it: {tag}"


def test_every_switch_still_reaches_the_form(clinic):
    """Splitting them into two groups must not drop one on the floor."""
    page = _screen(clinic)

    for field in ("show_doctor", "show_specialty", "show_contact",
                  "show_license", "show_patient", "show_weight",
                  "show_allergies", "show_conditions", "show_vaccines",
                  "show_growth", "show_diagnosis", "show_investigations",
                  "show_signature", "show_stamp"):
        assert 'name="%s"' % field in page, f"{field} is no longer on the screen"


def test_the_offset_says_it_is_for_pre_printed_paper_only(clinic):
    """It is read off `top_offset_mm` only in pre-printed mode."""
    page = _screen(clinic)
    at = page.index('name="top_offset_mm"')
    row = page[page.rindex('<div class="form-row', 0, at):page.index("</div></div>", at)]

    assert "f.mode!=='preprinted'" in row, \
        "the offset is not marked inert on white paper: " + row[:200]


# --------------------------------------------- a tick with nothing behind it

def test_a_clinic_with_no_address_is_told_the_tick_prints_nothing(clinic):
    """What the box prints lives in the settings, not on this screen."""
    page = _screen(clinic, address="", phone="")

    # Not just the string: the stylesheet on this page defines the class.
    assert 'class="rx-note rx-note--warn"' in page, \
        "nothing warns that the contact line has no contact details to print"


def test_a_clinic_that_has_them_is_not_nagged(clinic):
    """A warning that is always on is a warning nobody reads."""
    page = _screen(clinic, address="القاهرة", phone="01000000000")

    assert 'class="rx-note rx-note--warn"' not in page, \
        "the clinic has an address and is still being warned about it"


# ------------------------------------------------- the preview is to scale

def _script(page):
    return page[page.index("const RX_PAPER"):]


def test_the_offset_is_not_counted_twice(clinic):
    """The band drew it, and the content's padding drew it again.

    Measured after the fix, at 12mm margin and 30mm offset: band top 15.3,
    band height 35.7, content top 51.0 — the two added once.
    """
    script = _script(_screen(clinic))
    inner = script[script.index("get innerStyle()"):]
    inner = inner[:inner.index("},")]

    assert "top_offset" not in inner, \
        "the content padding still adds the offset the band already drew"
    assert "padding" not in inner, \
        "the margins belong to the page, not to the content inside it"

    page_inset = script[script.index("get pageInset()"):]
    page_inset = page_inset[:page_inset.index("},")]
    assert "padding" in page_inset and "f.mt" in page_inset, \
        "the margins are not drawn anywhere"


def test_a5_is_drawn_smaller_than_a4(clinic):
    """They used to be the same rectangle with a different label on it."""
    script = _script(_screen(clinic))

    assert "RX_PAPER" in script and "A5: [148, 210]" in script, \
        "the preview does not know one paper size from another"
    style = script[script.index("get pageStyle()"):]
    style = style[:style.index("},")]
    assert "this.paper" in style, "the sheet is drawn at a fixed size"


def test_the_type_in_the_preview_is_at_the_same_scale_as_the_paper(clinic):
    """It was `max(6, size × 0.62)`, so 6px and 9px drew identically.

    Which is precisely the range somebody is in when they are trying to make
    a prescription fit one page.
    """
    script = _script(_screen(clinic))
    inner = script[script.index("get innerStyle()"):]
    inner = inner[:inner.index("},")]

    assert "0.62" not in inner, "the preview type is at an invented scale"
    assert "pxPerMm" in inner, "the type does not follow the sheet's scale"
