"""The printed prescription: the clinic's standing words, and the order of
its parts.

The owner, on what was left of the printed prescription: the custom header
line was already there («ألقاب الطباعة»), and two things were not —

* **standing instructions**: words a clinic types once on the template and
  that print at the end of every prescription it prints, in Arabic and in
  English; a page in English with no English words prints the Arabic rather
  than nothing;
* **the order of the parts**: any part moves up or down, the letterhead stays
  at the top and the signature at the foot, and a template that never chose
  an order prints exactly as it always did.
"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

RX_DATE = date(2026, 8, 16)
STANDING_AR = "لو الحرارة فوق ٣٩ توجّه للطوارئ"
STANDING_EN = "Fever above 39 C: go to the emergency room"


def _rx(clinic, **tpl_kw):
    from app.extensions import db
    from app.models import (Patient, Prescription, PrescriptionItem,
                            RxPrintTemplate, User)

    with clinic["app"].app_context():
        doc = User.query.filter_by(username="doc").first()
        kid = Patient.query.first()
        rx = Prescription(patient_id=kid.id, doctor_id=doc.id, rx_date=RX_DATE,
                          complaint="كحة وحرارة", diagnosis="التهاب رئوي",
                          notes="ملاحظة الطفل ده")
        db.session.add(rx)
        db.session.flush()
        db.session.add(PrescriptionItem(prescription_id=rx.id,
                                        drug_name="Augmentin", printed=True))
        flags = {f: f not in RxPrintTemplate.OFF_BY_DEFAULT
                 for f in RxPrintTemplate.BOOLS}
        tpl = RxPrintTemplate(name="t", page_size="A5", font_size=10,
                              margin_mm=12, mode="white", **flags, **tpl_kw)
        db.session.add(tpl)
        db.session.commit()
        return rx.id, tpl.id


def _paper(clinic, rx_id, tpl_id, lang=None):
    client = clinic["sign_in"]("boss")
    if lang:
        client.get(f"/lang/{lang}")
    page = client.get(f"/prescriptions/{rx_id}?template={tpl_id}").data.decode()
    return page[page.index('id="rxPaper"'):]


def _where(page, *marks):
    return [page.index(m) for m in marks]


# ------------------------------------------------------------- the order

def test_a_template_that_never_chose_prints_as_it_always_did(clinic):
    from app.models import RxPrintTemplate

    assert RxPrintTemplate.clean_order(None) == RxPrintTemplate.BLOCKS
    page = _paper(clinic, *_rx(clinic))
    patient, complaint, meds, notes, signed = _where(
        page, "كحة وحرارة", "التهاب رئوي", "Augmentin", "ملاحظة الطفل ده", 'class="rx-sign"')
    assert patient < complaint < meds < notes < signed, "the old order"
    assert "data-paper-general" not in page, "no standing words, nothing printed"


def test_a_part_moved_up_prints_up(clinic):
    rx_id, tpl_id = _rx(clinic, block_order="meds,notes,patient,complaint")
    page = _paper(clinic, rx_id, tpl_id)
    meds, notes, complaint = _where(page, "Augmentin", "ملاحظة الطفل ده", "كحة وحرارة")
    assert meds < notes < complaint


def test_the_signature_stays_at_the_foot(clinic):
    rx_id, tpl_id = _rx(clinic, block_order="general_note,meds,notes",
                        general_note_ar=STANDING_AR)
    page = _paper(clinic, rx_id, tpl_id)
    standing, meds = _where(page, STANDING_AR, "Augmentin")
    assert standing < meds, "moved to the top"
    assert page.index("ملاحظة الطفل ده") < page.index('class="rx-sign"'), "the signature is last"


def test_an_unknown_or_repeated_part_is_ignored_and_none_is_lost():
    from app.models import RxPrintTemplate as R

    order = R.clean_order("notes,nonsense,notes,meds")
    assert sorted(order) == sorted(R.BLOCKS), "every part is still there"
    assert order.index("notes") < order.index("meds")
    assert "nonsense" not in order


# ------------------------------------------------------ the standing words

def test_the_standing_words_print_on_every_prescription(clinic):
    rx_id, tpl_id = _rx(clinic, general_note_ar=STANDING_AR)
    page = _paper(clinic, rx_id, tpl_id)
    assert STANDING_AR in page and "data-paper-general" in page
    assert page.index("ملاحظة الطفل ده") < page.index(STANDING_AR), \
        "after this child's own notes"


def test_english_page_prints_the_english_words_or_the_arabic(clinic):
    rx_id, tpl_id = _rx(clinic, general_note_ar=STANDING_AR, general_note_en=STANDING_EN)
    page = _paper(clinic, rx_id, tpl_id, lang="en")
    assert STANDING_EN in page and STANDING_AR not in page

    rx_id, tpl_id = _rx(clinic, general_note_ar=STANDING_AR)
    assert STANDING_AR in _paper(clinic, rx_id, tpl_id, lang="en"), \
        "no English words: the Arabic rather than nothing"


# ---------------------------------------------------------- the screen

def test_the_screen_saves_the_words_and_the_order(clinic):
    from app.extensions import db
    from app.models import RxPrintTemplate

    _rx_id, tpl_id = _rx(clinic)
    boss = clinic["sign_in"]("boss")
    page = boss.get("/prescriptions/templates").data.decode()
    assert "data-rx-order" in page and "data-rx-general" in page
    assert 'name="block_order"' in page and 'name="general_note_ar"' in page

    form = {"name": "t", "mode": "white", "page_size": "A5", "font_size": "10",
            "show_patient": "1", "block_order": "meds,patient,bogus",
            "general_note_ar": "  " + STANDING_AR + "\r\nسطر تاني  ",
            "general_note_en": "x" * 1500}
    assert boss.post(f"/prescriptions/templates/{tpl_id}/edit", data=form).status_code == 302
    with clinic["app"].app_context():
        tpl = db.session.get(RxPrintTemplate, tpl_id)
        order = tpl.block_order_list
        assert order[0] == "meds" and order.index("meds") < order.index("patient")
        assert "bogus" not in tpl.block_order
        assert tpl.general_note_ar == STANDING_AR + "\nسطر تاني"
        assert len(tpl.general_note_en) == RxPrintTemplate.GENERAL_NOTE_MAX

    form.update(block_order=",".join(RxPrintTemplate.BLOCKS), general_note_ar="", general_note_en="")
    boss.post(f"/prescriptions/templates/{tpl_id}/edit", data=form)
    with clinic["app"].app_context():
        tpl = db.session.get(RxPrintTemplate, tpl_id)
        assert tpl.block_order is None, "the default order is stored as no choice"
        assert tpl.general_note_ar is None and tpl.general_note_en is None


def test_an_older_form_without_the_fields_leaves_them_alone(clinic):
    from app.extensions import db
    from app.models import RxPrintTemplate

    _rx_id, tpl_id = _rx(clinic, block_order="meds,patient", general_note_ar=STANDING_AR)
    clinic["sign_in"]("boss").post(f"/prescriptions/templates/{tpl_id}/edit",
                                   data={"name": "t", "show_patient": "1"})
    with clinic["app"].app_context():
        tpl = db.session.get(RxPrintTemplate, tpl_id)
        assert tpl.block_order == "meds,patient" and tpl.general_note_ar == STANDING_AR


def test_the_test_print_shows_both(clinic):
    rx_id, tpl_id = _rx(clinic, block_order="general_note", general_note_ar=STANDING_AR)
    page = clinic["sign_in"]("boss").get(f"/prescriptions/templates/{tpl_id}/test-print").data.decode()
    assert STANDING_AR in page
