"""استمارة كل شركة، والموافقة بدري، والإرسال للشركة — CONTRACTS_PLAN.md ع-٣/ع-٤/ع-٥.

صاحب العيادة: *«دروب اند دراج للبيانات فى صفحة التعاقد بحيث يطبع الاستمارة مع
كل كشف او حجز، طلب الموافقة لو الاجراء محتاج موافقة وارفاق الموافقة، وممكن يبعت
طلب الموافقة للشركة»*.

* **الاستمارة**: صورة الاستمارة الفاضية، والبيانات متحطة عليها بالمليمتر —
  البيانات المعروفة بس، وجوه الورقة؛ وبتطلع مليانة من الكارت والكشف والحجز
  والموافقة، والبيان اللي البرنامج مش عارفه بيطلع فاضي مش متخمّن؛
* **بدري**: الكشف بيقول «الخدمة دي محتاجة موافقة من الشركة» وزرار يفتح الطلب
  (مرة واحدة)؛ والحجز بيفتحه لوحده ويقول للاستقبال — والفتح مش بيبعت حاجة؛
* **الإرسال**: لإيميل أو واتساب الموافقات بتاع الشركة، بالاستمارة ملف؛ ومن غير
  عنوان ما بيتبعتش؛ والرد بيسجّله شخص زي ما هو.
"""
import json
import os
import sys
from datetime import date

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def insured(clinic):
    from app.models import (Diagnosis, PatientCoverage, PayerContract, PayerContractRule,
                            PayerEntity, Service, Visit, VisitService)

    db = clinic["db"]
    with clinic["app"].app_context():
        payer = PayerEntity(name="شركة النيل للتأمين", entity_type="insurance", is_active=True)
        db.session.add(payer)
        db.session.flush()
        contract = PayerContract(payer_id=payer.id, number="C-1", is_active=True)
        db.session.add(contract)
        db.session.flush()
        echo = Service(name="إيكو على القلب", category="procedure", price=900, is_active=True)
        db.session.add(echo)
        db.session.flush()
        db.session.add(PayerContractRule(contract_id=contract.id, setting="any", scope="service",
                                         service_id=echo.id, coverage_type="percent",
                                         coverage_value=80, needs_approval=True))
        db.session.add(PatientCoverage(patient_id=clinic["ids"]["child"], payer_id=payer.id,
                                       membership_number="NL-7781", plan_name="ذهبي",
                                       holder_name="عمر حسن", is_active=True))
        visit = db.session.get(Visit, clinic["ids"]["visit"])
        db.session.add(VisitService(visit_id=visit.id, service_id=echo.id, name=echo.name))
        db.session.add(Diagnosis(visit_id=visit.id, code="I51.7", title="تضخم القلب", dx_type="final"))
        db.session.commit()
        clinic["ids"].update(payer=payer.id, echo=echo.id)
    return clinic


def _form(c, **extra):
    from app.models import PayerForm

    with c["app"].app_context():
        row = PayerForm(payer_id=c["ids"]["payer"], name="استمارة العيادات", fields=json.dumps([
            {"key": "patient_name", "x": 20, "y": 30, "w": 80, "size": 11, "align": "right"},
            {"key": "membership_number", "x": 120, "y": 30, "w": 50, "size": 11, "align": "left"},
            {"key": "diagnosis_code", "x": 20, "y": 60, "w": 40, "size": 10, "align": "right"}]),
            **extra)
        c["db"].session.add(row)
        c["db"].session.commit()
        return row.id


def test_the_layout_keeps_known_facts_inside_the_page():
    from app.utils import payer_forms as pf

    out = pf.clean_layout(json.dumps([
        {"key": "patient_name", "x": -5, "y": 400, "w": 2, "size": 99},
        {"key": "made_up", "x": 1, "y": 1},
        {"key": "date", "x": "x"},
        {"key": "membership_number", "x": 10, "y": 10, "w": 40, "size": 9, "align": "sideways"}]), 210, 297)
    assert [f["key"] for f in out] == ["patient_name", "membership_number"]
    assert out[0] == {"key": "patient_name", "x": 0, "y": 297, "w": 5, "size": 28, "align": "right"}
    assert out[1]["align"] == "right"
    with pytest.raises(pf.FormError):
        pf.clean_layout("{not json", 210, 297)


def test_the_form_is_made_designed_and_printed_filled(insured):
    from app.models import PayerForm

    boss = insured["sign_in"]("boss")
    page = boss.get("/finance/payer-forms").get_data(as_text=True)
    assert "data-payer-form-new" in page
    boss.post("/finance/payer-forms", data={"payer_id": insured["ids"]["payer"],
                                            "name": "استمارة العيادات", "page": "A5"})
    with insured["app"].app_context():
        row = PayerForm.query.one()
        assert (row.width_mm, row.height_mm, row.print_background) == (148, 210, False)
        fid = row.id
    design = boss.get(f"/finance/payer-forms/{fid}").get_data(as_text=True)
    assert "data-payer-form-design" in design and 'data-add-field="membership_number"' in design
    boss.post(f"/finance/payer-forms/{fid}", data={
        "name": "استمارة العيادات", "page": "A5", "print_background": "1",
        "layout": json.dumps([{"key": "patient_name", "x": 10, "y": 20, "w": 60, "size": 12},
                              {"key": "membership_number", "x": 90, "y": 20, "w": 40, "size": 12}])})
    with insured["app"].app_context():
        row = insured["db"].session.get(PayerForm, fid)
        assert [f["key"] for f in row.layout] == ["patient_name", "membership_number"]
        assert row.print_background
    printed = boss.get(f"/payer-forms/{fid}/print?visit={insured['ids']['visit']}"
                       ).get_data(as_text=True)
    assert "NL-7781" in printed and 'data-form-field="patient_name"' in printed
    assert "left:90.0mm" in printed and "size: 148mm 210mm" in printed
    # With no child, the designer's preview: the names of the facts.
    preview = boss.get(f"/payer-forms/{fid}/print").get_data(as_text=True)
    assert "رقم العضوية" in preview


def test_the_facts_come_from_the_card_the_visit_and_the_approval(insured):
    from app.models import InsuranceApproval, Patient, PayerEntity, Visit
    from app.utils import payer_forms as pf

    with insured["app"].test_request_context("/"):
        db = insured["db"]
        kid = db.session.get(Patient, insured["ids"]["child"])
        visit = db.session.get(Visit, insured["ids"]["visit"])
        payer = db.session.get(PayerEntity, insured["ids"]["payer"])
        values = pf.facts(kid, payer, visit=visit)
        assert values["membership_number"] == "NL-7781" and values["plan_name"] == "ذهبي"
        assert values["holder_name"] == "عمر حسن" and values["payer_name"] == "شركة النيل للتأمين"
        assert values["diagnosis_code"] == "I51.7" and "تضخم القلب" in values["diagnosis"]
        assert values["services"] == "إيكو على القلب"
        assert values["approval_number"] == "", "nothing guessed"
        approval = InsuranceApproval(patient_id=kid.id, payer_id=payer.id,
                                     service_id=insured["ids"]["echo"], status="approved",
                                     approval_number="AP-55", estimate=900)
        db.session.add(approval)
        db.session.flush()
        values = pf.facts(kid, approval=approval)
        assert (values["approval_number"], values["estimate"]) == ("AP-55", "900")


def test_the_visit_says_it_needs_an_approval_and_asks_once(insured):
    from app.models import InsuranceApproval

    _form(insured)
    doc = insured["sign_in"]("doc")
    url = f"/visits/{insured['ids']['visit']}/record"
    page = doc.get(url).get_data(as_text=True)
    assert "data-payer-asks" in page and f'data-ask-approval="{insured["ids"]["echo"]}"' in page
    assert "data-visit-payer-form" in page
    for _ in range(2):
        doc.post("/finance/approvals/ask", data={"visit_id": insured["ids"]["visit"],
                                                  "service_id": insured["ids"]["echo"]})
    with insured["app"].app_context():
        row = InsuranceApproval.query.one()
        assert (row.status, row.visit_id, row.service_id, row.estimate) == (
            "requested", insured["ids"]["visit"], insured["ids"]["echo"], 900)
        assert row.sent_at is None, "asking sends nothing"
    page = doc.get(url).get_data(as_text=True)
    assert f'data-asked="{insured["ids"]["echo"]}"' in page and "data-ask-approval" not in page


def test_an_approved_one_stops_the_question(insured):
    from app.models import InsuranceApproval

    with insured["app"].app_context():
        insured["db"].session.add(InsuranceApproval(
            patient_id=insured["ids"]["child"], payer_id=insured["ids"]["payer"],
            service_id=insured["ids"]["echo"], status="approved", approval_number="AP-1"))
        insured["db"].session.commit()
    page = insured["sign_in"]("doc").get(f"/visits/{insured['ids']['visit']}/record").get_data(as_text=True)
    assert "data-payer-asks" not in page


def test_no_card_no_question(clinic):
    page = clinic["sign_in"]("doc").get(f"/visits/{clinic['ids']['visit']}/record").get_data(as_text=True)
    assert "data-payer-asks" not in page and "data-visit-payer-form" not in page


def test_a_booking_opens_the_request_and_tells_the_desk(insured):
    from app.models import Appointment, InsuranceApproval
    from app.utils.clock import local_today

    with insured["app"].app_context():
        appt = Appointment(patient_id=insured["ids"]["child"], doctor_id=insured["ids"]["doctor"],
                           appt_date=local_today(), appt_time=__import__("datetime").time(11, 0),
                           extra_service_ids=str(insured["ids"]["echo"]))
        insured["db"].session.add(appt)
        insured["db"].session.commit()
        from app.utils import payer_forms as pf
        from app.models import Patient, User

        kid = insured["db"].session.get(Patient, insured["ids"]["child"])
        asks = pf.asks_for(kid, appointment=appt)
        assert [s.id for s, _ in asks] == [insured["ids"]["echo"]]
        pf.ask(kid, asks[0][0], User.query.filter_by(username="desk").one(), appointment=appt)
        insured["db"].session.commit()
        row = InsuranceApproval.query.one()
        assert row.appointment_id == appt.id and row.visit_id is None
    page = insured["sign_in"]("boss").get("/finance/approvals").get_data(as_text=True)
    assert 'data-approval-from="appointment"' in page


def test_sent_to_the_payers_approvals_desk(insured, monkeypatch):
    from app.models import InsuranceApproval, PayerEntity
    from app.utils import payer_forms as pf

    fid = _form(insured)
    doc = insured["sign_in"]("doc")
    doc.post("/finance/approvals/ask", data={"visit_id": insured["ids"]["visit"],
                                              "service_id": insured["ids"]["echo"]})
    boss = insured["sign_in"]("boss")
    with insured["app"].app_context():
        aid = InsuranceApproval.query.one().id
    page = boss.get("/finance/approvals").get_data(as_text=True)
    assert f'data-approval-form="{fid}"' in page and "data-approval-send" not in page, \
        "no address, no send button"
    boss.post(f"/finance/approvals/{aid}/send", data={"via": "email"})
    with insured["app"].app_context():
        assert insured["db"].session.get(InsuranceApproval, aid).sent_at is None

    boss.post(f"/finance/payers/{insured['ids']['payer']}/edit", data={
        "name": "شركة النيل للتأمين", "entity_type": "insurance", "is_active": "1",
        "approvals_email": "approvals@nile.example", "approvals_whatsapp": "01000000077"})
    with insured["app"].app_context():
        payer = insured["db"].session.get(PayerEntity, insured["ids"]["payer"])
        assert payer.approvals_email == "approvals@nile.example"
    sent = {}
    monkeypatch.setattr(pf, "_mail", lambda to, subject, body, attached: sent.update(
        to=to, subject=subject, body=body, attached=attached))
    page = boss.get("/finance/approvals").get_data(as_text=True)
    assert 'data-approval-send="email"' in page and 'data-approval-send="whatsapp"' in page
    boss.post(f"/finance/approvals/{aid}/send", data={"via": "email"})
    assert sent["to"] == "approvals@nile.example" and "NL-7781" in sent["body"]
    data, filename, mime = sent["attached"]
    assert data.startswith(b"%PDF") and (filename, mime) == ("approval-request.pdf",
                                                              "application/pdf")
    with insured["app"].app_context():
        row = insured["db"].session.get(InsuranceApproval, aid)
        assert (row.sent_via, row.sent_to, row.status) == ("email", "approvals@nile.example",
                                                             "requested"), "a person records the answer"
        assert row.sent_at is not None
    assert "data-approval-sent" in boss.get("/finance/approvals").get_data(as_text=True)


def test_who_may_print_and_who_may_design(insured):
    fid = _form(insured)
    assert insured["sign_in"]("doc").get(f"/finance/payer-forms/{fid}").status_code in (302, 403)
    assert insured["sign_in"]("doc").get(f"/payer-forms/{fid}/print?visit="
                                         f"{insured['ids']['visit']}").status_code == 200
