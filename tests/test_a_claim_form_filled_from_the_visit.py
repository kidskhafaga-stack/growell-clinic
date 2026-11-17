"""A claim form filled from the visit — the AXA reimbursement form and its kind.

The owner sent AXA's «Reimbursement claim form»: the doctor fills the
medical sections (symptoms, diagnosis, investigations, the drugs with dose,
frequency and duration, procedures, further treatment), signs and stamps.
The company's form could already be laid out once and printed filled; it
could not carry most of that page. These hold the facts it can carry now:

* the card's «Policy/Group no» and «Group/Company name», written on the card
  without renewing it;
* the encounter's own words, the treatment line by line and in four columns
  whose rows stay level, the procedures, the plan, the bill, the guardian's
  phone and the clinic's address;
* nothing guessed: what the file has not is an empty string — and the date
  the symptoms began, which the program does not keep, is not a fact at all.
"""
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tests.test_the_payers_own_form import insured  # noqa: E402,F401


def _treated(c):
    """The visit with a prescription, a procedure, a test, a bill, a plan."""
    from app.models import (Invoice, InvoiceItem, Prescription, PrescriptionItem,
                            Service, Setting, Visit, VisitInvestigation)

    db = c["db"]
    with c["app"].app_context():
        visit = db.session.get(Visit, c["ids"]["visit"])
        visit.chief_complaint = "Fever and ear pain for 3 days"
        visit.plan = "Review in 48 hours"
        db.session.get(Service, c["ids"]["echo"]).service_type = "procedure"
        rx = Prescription(patient_id=visit.patient_id, doctor_id=visit.doctor_id,
                          visit_id=visit.id)
        db.session.add(rx)
        db.session.flush()
        db.session.add_all([
            PrescriptionItem(prescription_id=rx.id, drug_name="Amoxicillin 250mg/5ml",
                             dose="7.5 ml", frequency="every 12 hours", duration="7 days"),
            PrescriptionItem(prescription_id=rx.id, drug_name="Paracetamol 120mg/5ml",
                             dose="7 ml", duration="3 days"),
        ])
        db.session.add(VisitInvestigation(visit_id=visit.id, patient_id=visit.patient_id,
                                          name="صورة دم كاملة", name_en="CBC"))
        bill = Invoice(invoice_number="INV-CLAIM-1", patient_id=visit.patient_id, visit_id=visit.id)
        db.session.add(bill)
        db.session.flush()
        db.session.add(InvoiceItem(invoice_id=bill.id, description="كشف",
                                   quantity=1, unit_price=450))
        Setting.set("clinic_address", "١٢ شارع الجيش، طنطا")
        Setting.set("clinic_phone", "0403334444")
        db.session.commit()


def _facts(c, lang="en"):
    from app.models import Patient, PayerEntity, Visit
    from app.utils import payer_forms as pf

    # ``facts`` speaks the screen's language (``t``): a request is needed.
    with c["app"].test_request_context():
        db = c["db"]
        return pf.facts(db.session.get(Patient, c["ids"]["child"]),
                        payer=db.session.get(PayerEntity, c["ids"]["payer"]),
                        visit=db.session.get(Visit, c["ids"]["visit"]), lang=lang)


def test_the_medical_sections_come_from_the_visit(insured):
    _treated(insured)
    got = _facts(insured)
    assert got["symptoms"] == "Fever and ear pain for 3 days"
    assert got["investigations"] == "CBC"
    assert got["procedures"] == "إيكو على القلب"
    assert got["plan"] == "Review in 48 hours"
    assert got["drugs"].splitlines() == [
        "Amoxicillin 250mg/5ml — 7.5 ml — every 12 hours — 7 days",
        "Paracetamol 120mg/5ml — 7 ml — 3 days"]
    # The four columns keep their rows level: the frequency the doctor did
    # not write is an empty line, not the next drug's.
    assert got["drug_names"].split("\n") == ["Amoxicillin 250mg/5ml",
                                              "Paracetamol 120mg/5ml"]
    assert got["drug_frequencies"].split("\n") == ["every 12 hours", ""]
    assert got["drug_durations"].split("\n") == ["7 days", "3 days"]
    assert got["amount"] == "450"
    assert got["clinic_address"] == "١٢ شارع الجيش، طنطا"
    assert got["clinic_phone"] == "0403334444"


def test_nothing_is_guessed(insured):
    from app.utils import payer_forms as pf

    got = _facts(insured)
    for key in ("symptoms", "investigations", "drugs", "procedures", "plan",
                "amount", "policy_number", "group_name", "admission_date"):
        assert got[key] == "", key
    # The day the symptoms began is not kept anywhere; the doctor writes it.
    assert not [k for k in pf.FIELDS if "onset" in k or "first" in k]


def test_the_card_carries_the_policy_and_the_group(insured):
    from app.models import PatientCoverage

    with insured["app"].app_context():
        cov = PatientCoverage.query.filter_by(patient_id=insured["ids"]["child"]).one()
        cov_id = cov.id
    boss = insured["sign_in"]("boss")
    page = boss.get(f"/patients/{insured['ids']['child']}").get_data(as_text=True)
    assert f'data-claim-details="{cov_id}"' in page
    boss.post(f"/patients/coverage/{cov_id}/claim-details",
              data={"policy_number": "GRP-2231", "group_name": "شركة الدلتا للسكر"})
    with insured["app"].app_context():
        cov = insured["db"].session.get(PatientCoverage, cov_id)
        assert (cov.policy_number, cov.group_name, cov.is_active) == \
            ("GRP-2231", "شركة الدلتا للسكر", True), "written on the card, not renewed"
    got = _facts(insured)
    assert (got["policy_number"], got["group_name"]) == ("GRP-2231", "شركة الدلتا للسكر")
    page = boss.get(f"/patients/{insured['ids']['child']}").get_data(as_text=True)
    assert "data-card-policy" in page and "GRP-2231" in page


def test_the_designer_offers_them_and_the_form_prints_them(insured):
    from app.models import PayerForm

    _treated(insured)
    with insured["app"].app_context():
        row = PayerForm(payer_id=insured["ids"]["payer"], name="AXA claim", fields=json.dumps([
            {"key": "symptoms", "x": 20, "y": 80, "w": 120, "size": 10, "align": "left"},
            {"key": "drug_doses", "x": 130, "y": 150, "w": 25, "size": 9, "align": "left"}]))
        insured["db"].session.add(row)
        insured["db"].session.commit()
        fid = row.id
    boss = insured["sign_in"]("boss")
    design = boss.get(f"/finance/payer-forms/{fid}").get_data(as_text=True)
    for key in ("policy_number", "symptoms", "drug_doses", "amount", "clinic_address"):
        assert f'data-add-field="{key}"' in design, key
    printed = boss.get(f"/payer-forms/{fid}/print?visit={insured['ids']['visit']}") \
        .get_data(as_text=True)
    assert "Fever and ear pain for 3 days" in printed
    assert "7.5 ml" in printed
