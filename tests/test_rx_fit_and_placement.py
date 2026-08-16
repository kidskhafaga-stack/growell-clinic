"""Two answers to the same question: how do I stop fighting the page?

**Where the doctor's details go** depends on the paper, not on a second set of
switches. On white paper they are the letterhead. On pre-printed paper the
letterhead is already on the sheet, so they move to the foot beside the
signature — which is where a prescription puts a licence number anyway, and
the one part of that sheet guaranteed to be empty. Same ticks, different
place. Asked for as: leave them as they are on white paper, and on pre-printed
paper give them somewhere else.

**Fit to one page** is one switch and no second number. The floor lives in the
page, because "how small is too small" is the point where a pharmacist
misreads a dose, and that is not a number to put on a form next to the
margins.

Measured through Chromium on the A5 that prompted it: the same prescription
that needed two sheets at 14px was fitted to 10.00px and came out on one, with
its last line at y=516 of a 561pt column.
"""
import os
import re
import sys
from datetime import date

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

RX_DATE = date(2026, 8, 16)
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _paper(clinic, **tpl_kw):
    from app.extensions import db
    from app.models import (Patient, Prescription, PrescriptionItem,
                            RxPrintTemplate, User)

    with clinic["app"].app_context():
        doc = User.query.filter_by(username="doc").first()
        doc.license_no = "LIC-4477"
        rx = Prescription(patient_id=Patient.query.first().id, doctor_id=doc.id,
                          rx_date=RX_DATE, diagnosis="التهاب رئوي")
        db.session.add(rx)
        db.session.flush()
        db.session.add(PrescriptionItem(prescription_id=rx.id,
                                        drug_name="Augmentin", printed=True))
        flags = {f: f not in RxPrintTemplate.OFF_BY_DEFAULT
                 for f in RxPrintTemplate.BOOLS}
        flags.update(tpl_kw)
        mode = flags.pop("mode", "white")
        page_size = flags.pop("page_size", "A5")
        tpl = RxPrintTemplate(name="t", page_size=page_size, font_size=14,
                              margin_mm=12, mode=mode, **flags)
        db.session.add(tpl)
        db.session.commit()
        rx_id, tpl_id = rx.id, tpl.id

    return clinic["sign_in"]("boss").get(
        f"/prescriptions/{rx_id}?template={tpl_id}").data.decode()


def _paper_only(page):
    """Just the prescription, from `#rxPaper` to the end of the document."""
    return page[page.index('id="rxPaper"'):]


# -------------------------------------- white paper is left exactly as it was

def test_white_paper_still_puts_them_in_the_letterhead(clinic):
    page = _paper_only(_paper(clinic, mode="white"))
    head = page[page.index('class="print-header"'):]
    head = head[:head.index("{% endif %}") if "{% endif %}" in head[:4000]
                else head.index("</div>", head.index("</div>") + 1)]

    assert "LIC-4477" in head, "the licence left the letterhead on white paper"


def test_white_paper_does_not_repeat_them_at_the_foot(clinic):
    """They are already at the top. Twice is printing the same line twice."""
    page = _paper(clinic, mode="white")

    assert page.count("LIC-4477") == 1, \
        f"the licence prints {page.count('LIC-4477')} times on white paper"


# ------------------------------ pre-printed paper gives them somewhere else

def test_pre_printed_paper_moves_them_to_the_signature(clinic):
    page = _paper_only(_paper(clinic, mode="preprinted", top_offset_mm=20))

    assert "LIC-4477" in page, "the licence is missing from pre-printed paper"
    sign_at = page.index("rx-sign")
    assert page.index("LIC-4477") > sign_at, \
        "the licence is above the signature, where the printed letterhead is"


def test_the_top_of_pre_printed_paper_carries_only_the_date(clinic):
    """Anything else there lands on the letterhead already on the sheet."""
    page = _paper_only(_paper(clinic, mode="preprinted", top_offset_mm=20))
    above_the_fold = page[:page.index("rx-block")]

    assert "2026-08-16" in above_the_fold, "the date left the top of the sheet"
    assert "LIC-4477" not in above_the_fold, \
        "the licence is printed over the clinic's own letterhead"


def test_the_ticks_still_govern_what_arrives_there(clinic):
    """Moving them is not the same as printing them regardless."""
    page = _paper(clinic, mode="preprinted", top_offset_mm=20,
                  show_license=False)

    assert "LIC-4477" not in page, \
        "the licence printed at the foot with its tick off"


def test_the_signature_is_still_the_signature(clinic):
    """The doctor's name under the rule is not one of the movable fields."""
    page = _paper(clinic, mode="preprinted", top_offset_mm=20,
                  show_license=False, show_specialty=False,
                  show_contact=False, show_doctor=False)

    assert "أحمد" in page, "the name over the signature line disappeared"


# --------------------------------------------------------- fit to one page

def _fit_script(page):
    start = page.index("var MIN_PX")
    return page[start:page.index("</script>", start)]


def test_the_fit_pass_is_absent_until_it_is_asked_for(clinic):
    """Resizing a medical document unasked is not a default."""
    from app.models import RxPrintTemplate

    assert "fit_page" in RxPrintTemplate.OFF_BY_DEFAULT

    page = _paper(clinic, fit_page=False)
    assert "MIN_PX" not in page, "the fit pass ran on a template that never asked"


def test_it_measures_the_printed_width_not_the_screen(clinic):
    """A narrower column wraps more lines and is taller.

    Measuring the page as the window shows it answers a question nobody asked.
    """
    script = _fit_script(_paper(clinic, fit_page=True, page_size="A5"))

    assert "148" in script and "210" in script, \
        "the fit pass does not know what size the paper is"
    assert "availW" in script and "width:' + availW" in script, \
        "the probe is not held at the printed width"


def test_it_leaves_room_for_the_copyright_line(clinic):
    """It is in the flow at the end, so it is part of what has to fit."""
    script = _fit_script(_paper(clinic, fit_page=True))

    assert "FOOT_MM" in script and "FOOT_MM" in script.split("availH")[1][:80], \
        "the fit pass fills the page and pushes the footer onto a second sheet"


def test_it_does_not_measure_what_will_not_be_printed(clinic):
    """`.no-print` is on the page and has height. On paper it has none."""
    script = _fit_script(_paper(clinic, fit_page=True))

    assert "no-print" in script, \
        "the probe counts screen-only blocks against the height of the paper"


def test_it_has_a_floor_and_the_floor_is_not_on_the_form(clinic):
    """"How small is too small" is where a pharmacist misreads a dose."""
    script = _fit_script(_paper(clinic, fit_page=True))

    assert re.search(r"MIN_PX\s*=\s*8", script), \
        "the fit pass has no legibility floor"
    assert "size > MIN_PX" in script, "the floor is declared and never used"

    page = clinic["sign_in"]("boss").get("/prescriptions/templates").data.decode()
    assert 'name="min_font_size"' not in page, \
        "the floor was put on the settings form after all"


def test_it_only_ever_goes_smaller(clinic):
    """The number on the template is what the clinic asked for."""
    script = _fit_script(_paper(clinic, fit_page=True))

    assert "Math.min(base, size)" in script, \
        "the fit pass can grow the type past what the template asked for"


def test_it_waits_for_the_page_to_finish_loading(clinic):
    """An image that has not arrived has no height yet."""
    script = _fit_script(_paper(clinic, fit_page=True))

    assert "'load'" in script or '"load"' in script, \
        "the fit is computed before the logo has a height"


def test_it_is_one_switch_on_the_screen(clinic):
    from app.extensions import db
    from app.models import RxPrintTemplate

    with clinic["app"].app_context():
        db.session.add(RxPrintTemplate(
            name="t", mode="white", page_size="A4", font_size=14, margin_mm=12,
            **{f: f not in RxPrintTemplate.OFF_BY_DEFAULT
               for f in RxPrintTemplate.BOOLS}))
        db.session.commit()

    page = clinic["sign_in"]("boss").get("/prescriptions/templates").data.decode()

    assert 'name="fit_page"' in page, "there is no switch for it"


def test_the_new_column_is_in_the_additive_migration(clinic):
    from app.utils.schema import ADDITIONS

    assert any(t == "rx_print_templates" and c == "fit_page"
               for t, c, _sql in ADDITIONS), \
        "fit_page will be missing on every clinic that already has a database"


def test_the_paper_knows_its_own_measurements(clinic):
    """The millimetres are on the model, not copied into the page."""
    from app.models import RxPrintTemplate

    tpl = RxPrintTemplate(page_size="A5")
    assert tpl.page_mm == (148, 210)

    tpl.page_size = "A4"
    assert tpl.page_mm == (210, 297)

    tpl.page_size = None
    assert tpl.page_mm == (210, 297), "an unset size has to fall back, not raise"
