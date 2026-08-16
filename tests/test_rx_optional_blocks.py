"""Everything on the paper is a tick, and a tick means it prints.

Three things, all asked for together:

* the complaint had no switch — it simply printed whenever it was filled in;
* the letterhead fields were skipped on pre-printed paper whatever the ticks
  said, and *"the ones that are ticked I might still want printed, like the
  licence on pre-printed paper"*;
* an insurance company or a club membership is part of a patient's data and
  belongs on the paper when the clinic wants it there.

The last one needed no new data: ``Patient.active_coverage`` has been the
patient's current, unexpired card all along.
"""
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

RX_DATE = date(2026, 8, 16)


def _cover(clinic, name="شركة مصر للتأمين", number="INS-9931",
           expiry=None, active=True):
    from app.extensions import db
    from app.models import Patient
    from app.models.payer import PatientCoverage, PayerEntity

    payer = PayerEntity(name=name, entity_type="insurance")
    db.session.add(payer)
    db.session.flush()
    db.session.add(PatientCoverage(patient_id=Patient.query.first().id,
                                   payer_id=payer.id,
                                   membership_number=number,
                                   expiry_date=expiry, is_active=active))


def _paper(clinic, setup=None, **tpl_kw):
    from app.extensions import db
    from app.models import (Patient, Prescription, PrescriptionItem,
                            RxPrintTemplate, User)

    with clinic["app"].app_context():
        doc = User.query.filter_by(username="doc").first()
        doc.license_no = "LIC-4477"
        kid = Patient.query.first()
        if setup:
            setup(clinic)
        rx = Prescription(patient_id=kid.id, doctor_id=doc.id, rx_date=RX_DATE,
                          complaint="كحة وحرارة", diagnosis="التهاب رئوي")
        db.session.add(rx)
        db.session.flush()
        db.session.add(PrescriptionItem(prescription_id=rx.id,
                                        drug_name="Augmentin", printed=True))
        flags = {f: f not in RxPrintTemplate.OFF_BY_DEFAULT
                 for f in RxPrintTemplate.BOOLS}
        flags.update(tpl_kw.pop("flags", {}))
        flags.update(tpl_kw)
        tpl = RxPrintTemplate(name="t", page_size="A5", font_size=10,
                              margin_mm=12, **flags)
        tpl.mode = flags.get("mode", "white")
        db.session.add(tpl)
        db.session.commit()
        rx_id, tpl_id = rx.id, tpl.id

    return clinic["sign_in"]("boss").get(
        f"/prescriptions/{rx_id}?template={tpl_id}").data.decode()


# ------------------------------------------------------------ the complaint

def test_the_complaint_can_be_switched_off(clinic):
    """It was the last block on the page with no switch at all."""
    assert "كحة وحرارة" in _paper(clinic), "this test is reading the wrong field"
    assert "كحة وحرارة" not in _paper(clinic, show_complaint=False), \
        "the complaint printed on a template that switched it off"


def test_turning_the_complaint_off_does_not_take_the_diagnosis(clinic):
    """They share a line now, so one has to be able to go without the other."""
    page = _paper(clinic, show_complaint=False)

    assert "التهاب رئوي" in page, "the diagnosis left with the complaint"


def test_turning_both_off_leaves_no_empty_run(clinic):
    page = _paper(clinic, show_complaint=False, show_diagnosis=False)

    assert "الشكوى" not in page and "التشخيص" not in page, \
        "an empty labelled run printed with nothing in it"


# ------------------------- the letterhead fields, on pre-printed paper too

def test_the_licence_prints_on_pre_printed_paper_when_it_is_ticked(clinic):
    """The one that was asked for by name.

    A letterhead printed last year does not carry this doctor's licence.
    """
    page = _paper(clinic, mode="preprinted", top_offset_mm=20,
                  show_license=True)

    assert "LIC-4477" in page, \
        "the licence is still dropped on pre-printed paper"


def test_the_doctors_name_prints_on_pre_printed_paper_too(clinic):
    """A pad shared by three doctors does not carry any one of their names."""
    page = _paper(clinic, mode="preprinted", top_offset_mm=20,
                  show_doctor=True)

    assert "أحمد" in page, "the doctor's name is dropped on pre-printed paper"


def test_and_unticking_them_still_leaves_them_off(clinic):
    """Which is the whole point of the tick: paper that already says it."""
    page = _paper(clinic, mode="preprinted", top_offset_mm=20,
                  show_license=False, show_doctor=False, show_specialty=False,
                  show_contact=False)

    assert "LIC-4477" not in page, "the licence printed with its tick off"


def test_the_date_prints_on_pre_printed_paper_whatever_is_ticked(clinic):
    """It is the one thing a pre-printed letterhead can never carry."""
    page = _paper(clinic, mode="preprinted", top_offset_mm=20,
                  show_doctor=False, show_specialty=False,
                  show_contact=False, show_license=False)

    assert "2026-08-16" in page, "a pre-printed prescription lost its date"


def test_the_offset_still_comes_first(clinic):
    """Everything this mode prints goes *below* the space kept for the paper."""
    page = _paper(clinic, mode="preprinted", top_offset_mm=20,
                  show_license=True)
    paper = page[page.index('id="rxPaper"'):]

    assert "height:20mm" in paper[:400], \
        "the offset is no longer the first thing inside the paper"
    assert paper.index("height:20mm") < paper.index("LIC-4477"), \
        "the licence printed above the space reserved for the letterhead"


# ----------------------------------------------- insurance / club membership

def test_the_membership_prints_when_it_is_asked_for(clinic):
    page = _paper(clinic, setup=_cover, show_coverage=True)

    assert "شركة مصر للتأمين" in page, "the payer's name is not on the paper"
    assert "INS-9931" in page, "the membership number is not on the paper"


def test_it_is_off_until_a_clinic_asks(clinic):
    """Most clinics are cash. An empty concept on every prescription is noise."""
    from app.models import RxPrintTemplate

    assert "show_coverage" in RxPrintTemplate.OFF_BY_DEFAULT

    page = _paper(clinic, setup=_cover)  # flags built from OFF_BY_DEFAULT
    assert "INS-9931" not in page, "the membership printed unasked"


def test_an_expired_card_is_not_printed(clinic):
    """Printing one sends a family to a desk that will turn them away."""
    def expired(c):
        _cover(c, expiry=RX_DATE - timedelta(days=1))

    page = _paper(clinic, setup=expired, show_coverage=True)

    assert "INS-9931" not in page, "an expired membership was printed"


def test_a_deactivated_card_is_not_printed(clinic):
    def off(c):
        _cover(c, active=False)

    page = _paper(clinic, setup=off, show_coverage=True)

    assert "INS-9931" not in page, "a cancelled membership was printed"


def test_a_patient_with_no_card_prints_no_label(clinic):
    """An empty "Insurance:" is worse than no insurance line."""
    page = _paper(clinic, show_coverage=True)

    assert "التأمين/العضوية" not in page, \
        "an empty membership label printed for a patient with no card"


# --------------------------------------------------- the migration and screen

def test_both_new_columns_are_in_the_additive_migration(clinic):
    from app.utils.schema import ADDITIONS

    for column in ("show_complaint", "show_coverage"):
        assert any(t == "rx_print_templates" and c == column
                   for t, c, _sql in ADDITIONS), \
            f"{column} will be missing on every clinic that already has a database"


def test_both_are_switches_on_the_template_screen(clinic):
    from app.extensions import db
    from app.models import RxPrintTemplate

    with clinic["app"].app_context():
        db.session.add(RxPrintTemplate(
            name="t", mode="white", page_size="A4", font_size=14, margin_mm=12,
            **{f: f not in RxPrintTemplate.OFF_BY_DEFAULT
               for f in RxPrintTemplate.BOOLS}))
        db.session.commit()

    page = clinic["sign_in"]("boss").get("/prescriptions/templates").data.decode()

    for field in ("show_complaint", "show_coverage"):
        assert 'name="%s"' % field in page, f"no tick for {field}"
