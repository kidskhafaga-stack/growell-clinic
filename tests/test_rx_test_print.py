"""A prescription made of nothing, for aiming the printer at the paper.

Asked for so a clinic can check a layout **before** committing to it, and above
all on pre-printed letterhead — where the whole question is whether the text
lands under the printed header or across it. Three millimetres nobody would
notice on white paper is the doctor's name over the logo there, and the only
thing that answers it is putting ink on the real paper and looking.

Two decisions carry the feature, and this file exists to hold both.

**The sample child does not exist.** Aligning margins by reprinting the last
real prescription would put a named child's weight, allergy and medicines onto
sheet after sheet of paper that goes straight in the bin. So the data is
invented and reads as invented.

**The test page occupies exactly the space a real one does.** Anything that
adds a line — a banner reading "sample", a note at the top — moves everything
below it, and the page stops testing the thing it was printed for. The marking
is a watermark *over* the layout and a rule drawn *at* the offset; neither
takes part in the flow.

It renders through the real ``_paper.html``. A second, simpler mock-up of the
prescription would drift from the true one, and then the preview would agree
with itself and disagree with the printer — the exact failure this prevents.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


def _template(clinic, **fields):
    with clinic["app"].app_context():
        from app.models import RxPrintTemplate
        db = clinic["db"]
        base = {flag: flag not in RxPrintTemplate.OFF_BY_DEFAULT
                for flag in RxPrintTemplate.BOOLS}
        base.update(fields)
        tpl = RxPrintTemplate(name="t", page_size="A4", font_size=14,
                              margin_mm=12, **base)
        db.session.add(tpl)
        db.session.commit()
        return tpl.id


def _print(clinic, tpl_id, who="boss"):
    return clinic["sign_in"](who).get(
        f"/prescriptions/templates/{tpl_id}/test-print")


# --- it renders -----------------------------------------------------------

def test_the_test_page_opens(clinic):
    tpl_id = _template(clinic, mode="white")
    response = _print(clinic, tpl_id)
    assert response.status_code == 200


def test_it_is_the_real_prescription_markup(clinic):
    """Not a second drawing of a prescription.

    A separate mock-up would drift from the true layout, and then the screen
    would agree with itself and disagree with the printer — which is the whole
    thing this feature exists to catch.
    """
    tpl_id = _template(clinic, mode="white")
    body = _print(clinic, tpl_id).get_data(as_text=True)
    assert 'id="rxPaper"' in body, "the test page draws its own prescription"
    assert "℞" in body


def test_the_page_is_filled_not_skeletal(clinic):
    """A layout that fits only the tidiest child in the clinic is not tested.

    Weight, allergy, condition, three medicines and both investigation lists
    are all present on purpose: an empty sample would print short and prove
    nothing about where a real prescription ends.
    """
    tpl_id = _template(clinic, mode="white")
    body = _print(clinic, tpl_id).get_data(as_text=True)
    for probe in ("12.5", "بنسلين", "ربو", "Augmentin", "Brufen"):
        assert probe in body, f"{probe} missing — the sample prints short"


# --- no real patient ------------------------------------------------------

def test_no_real_patient_is_printed(clinic):
    """The privacy decision, checked with a real prescription on file.

    A real one is created first, and that is the whole point of the test: with
    an empty table, "reach for the latest prescription" and "build a sample"
    produce the same page, and this passes against either. It has to be
    possible for the wrong implementation to fail here.

    Aiming a printer is not a reason to put a named child's allergy and
    medicines onto sheet after sheet of paper headed for the bin.
    """
    with clinic["app"].app_context():
        from datetime import date

        from app.models import Patient, Prescription, PrescriptionItem
        db = clinic["db"]
        patient = db.session.get(Patient, clinic["ids"]["child"])
        patient.allergies = "حساسية سرية جداً"
        rx = Prescription(patient_id=patient.id,
                          doctor_id=clinic["ids"]["doctor"],
                          rx_date=date.today(), diagnosis="تشخيص حقيقي")
        db.session.add(rx)
        db.session.flush()
        db.session.add(PrescriptionItem(prescription_id=rx.id,
                                        drug_name="دواء حقيقي", printed=True))
        db.session.commit()

    tpl_id = _template(clinic, mode="white")
    body = _print(clinic, tpl_id).get_data(as_text=True)
    paper = body.split('id="rxPaper"')[1]
    for leak in ("P1", "حساسية سرية جداً", "تشخيص حقيقي", "دواء حقيقي"):
        assert leak not in paper, f"the real patient's {leak!r} reached the test page"


def test_nothing_is_written_to_the_database(clinic):
    """The sample is plain objects, not unsaved models.

    An unsaved ``Prescription`` sitting in the session is one ``commit()``
    elsewhere away from becoming a real prescription for a child who does not
    exist.
    """
    with clinic["app"].app_context():
        from app.models import Prescription
        before = Prescription.query.count()

    tpl_id = _template(clinic, mode="white")
    _print(clinic, tpl_id)

    with clinic["app"].app_context():
        from app.models import Patient, Prescription
        assert Prescription.query.count() == before
        assert Patient.query.filter(Patient.full_name.like("%نموذج%")).count() == 0


def test_the_sample_is_marked_as_one(clinic):
    tpl_id = _template(clinic, mode="white")
    body = _print(clinic, tpl_id).get_data(as_text=True)
    assert "rx-testmark" in body
    assert "نموذج" in body


def test_the_mark_does_not_take_part_in_the_layout(clinic):
    """The decision that keeps the test honest.

    A banner with height would push everything below it down, and the page
    would no longer be testing where a real prescription lands. So the mark is
    positioned out of the flow.
    """
    tpl_id = _template(clinic, mode="white")
    body = _print(clinic, tpl_id).get_data(as_text=True)
    style = body.split(".rx-testmark")[1][:220]
    assert "position: absolute" in style, (
        "the sample mark is in the flow and is moving the content")


# --- the pre-printed case, which is the point -----------------------------

def test_the_offset_rule_is_drawn_for_preprinted_paper(clinic):
    """Turns "try it and see" into "measure it and set a number"."""
    tpl_id = _template(clinic, mode="preprinted", top_offset_mm=45)
    body = _print(clinic, tpl_id).get_data(as_text=True)
    assert 'class="rx-offset-rule"' in body
    assert "top:45mm" in body, "the rule is not drawn at the template's offset"


def test_no_rule_on_plain_white_paper(clinic):
    """There is no letterhead to clear, so the line would mean nothing."""
    tpl_id = _template(clinic, mode="white", top_offset_mm=45)
    body = _print(clinic, tpl_id).get_data(as_text=True)
    # The stylesheet always carries the class; only the element must be
    # absent, so this looks for the element.
    assert 'class="rx-offset-rule"' not in body


def test_the_rule_costs_no_height_either(clinic):
    tpl_id = _template(clinic, mode="preprinted", top_offset_mm=30)
    body = _print(clinic, tpl_id).get_data(as_text=True)
    style = body.split(".rx-offset-rule")[1][:200]
    assert "position: absolute" in style


# --- the template's own switches are honoured -----------------------------

@pytest.mark.parametrize("flag,probe", [
    ("show_weight", "12.5"),
    ("show_allergies", "بنسلين"),
    ("show_conditions", "ربو"),
])
def test_turning_an_element_off_shows_in_the_test_print(clinic, flag, probe):
    """Otherwise it tests a layout the clinic is not going to print."""
    tpl_id = _template(clinic, mode="white", **{flag: False})
    body = _print(clinic, tpl_id).get_data(as_text=True)
    assert probe not in body, f"{flag}=False but {probe} still printed"


def test_the_growth_block_appears_when_the_template_asks(clinic):
    on = _template(clinic, mode="white", show_growth=True)
    off = _template(clinic, mode="white", show_growth=False)
    assert "87.0" in _print(clinic, on).get_data(as_text=True)
    assert "87.0" not in _print(clinic, off).get_data(as_text=True)


# --- who can reach it -----------------------------------------------------

def test_only_an_admin_can_open_it(clinic):
    """It sits on the templates screen, which is admin-only."""
    response = _print(clinic, _template(clinic, mode="white"), who="desk")
    assert response.status_code in (302, 403)


def test_it_is_offered_from_the_templates_screen(clinic):
    tpl_id = _template(clinic, mode="white")
    body = clinic["sign_in"]("boss").get(
        "/prescriptions/templates").get_data(as_text=True)
    assert f"/templates/{tpl_id}/test-print" in body


# --- whose paper is being previewed ---------------------------------------

def test_the_preview_shows_the_doctor_the_layout_belongs_to(clinic):
    """Reported as "the signature and stamp do not appear, though I saved them".

    They had. This screen is admin-only, so the person aiming the printer is
    almost never the doctor — and the preview was built from whoever was
    signed in. An administrator has no signature, no stamp and no licence, so
    a template named for a consultant previewed with all three missing and
    nothing to say why.
    """
    from app.extensions import db
    from app.models import User

    tpl_id = _template(clinic)
    with clinic["app"].app_context():
        doctor = db.session.get(User, clinic["ids"]["doctor"])
        doctor.rx_template_id = tpl_id
        doctor.signature_file = "sig-of-the-doctor.png"
        doctor.stamp_file = "stamp-of-the-doctor.png"
        doctor.license_no = "LIC-9876"
        db.session.commit()

    page = _print(clinic, tpl_id, who="boss").data.decode()

    assert "sig-of-the-doctor.png" in page, "the doctor's signature is missing"
    assert "stamp-of-the-doctor.png" in page, "the doctor's stamp is missing"
    assert "LIC-9876" in page, "the doctor's licence number is missing"


def test_a_layout_with_no_doctor_still_previews(clinic):
    """The case the original code was written for, and still right.

    With nobody on the layout there is no one else to show, so the viewer is
    the honest answer rather than an empty page.
    """
    tpl_id = _template(clinic)
    answer = _print(clinic, tpl_id, who="boss")

    assert answer.status_code == 200
    assert 'id="rxPaper"' in answer.data.decode()
