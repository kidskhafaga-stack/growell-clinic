"""Selling a vaccine forward, and which dose it is.

The clinic's description of what was missing:

> *"There should be a vaccination service and a service added with it called
> the vaccination fee. The vaccination service brings up the available
> vaccines, and you pick the trade name, and pick which dose — and if they have
> had a dose with me before, it tells you the doses **after** that, once you
> pick the patient. Even if they are coming for two vaccines."*

The billing already ran the other way round: a doctor gave a dose and the
cashier swept it up afterwards. There was no way to sell one **forward** — the
family paying at reception before the nurse gives it — which is how a
vaccination visit actually runs. The only route to money was "give it first,
find it on the bill later", so anything a family declined after paying became a
correction rather than a choice.

Three things this has to get right, and each is a way of being quietly wrong:

**"The doses after that."** Offering dose 1 of a course the child is three
doses into is the mistake being reported, and it is not a display problem:
whichever dose is billed is the one the record will be settled against. The
next undone dose is preselected, and the ones already had stay on the list
*marked* rather than hidden — "the first was at a government unit" is a real
thing somebody needs to be able to say.

**Stock is the difference between selling and promising.** A vaccine with an
empty fridge shelf is not offered, because taking money for it is taking money
for a phone call tomorrow.

**The fee comes once.** Two vaccines in one visit is ordinary practice, and
charging the administration fee twice for one administration is the kind of
overcharge nobody spots until a parent counts it.

And the fee line is added **even when it is zero**, which is the clinic's own
distinction: a clinic that gives the vaccine at cost still wants the line
visible at nothing, because "not charged" and "not written down" read the same
on a piece of paper.
"""
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def shelf(clinic):
    """The PCV course from the shared fixture, plus a fee service and a second
    optional vaccine so "two vaccines in one visit" is testable."""
    from app.models import (Service, Vaccine, VaccineBrand, VaccineBrandDose,
                            VaccineInventory)

    with clinic["app"].app_context():
        db = clinic["db"]
        db.session.add(Service(code="SVC-VACFEE", name="رسم تطعيم",
                               name_en="Vaccination fee", price=100,
                               category="vaccination_fee",
                               commission_type="none", is_active=True))

        rota = Vaccine(code="ROTA", name_ar="الروتا", is_mandatory=False)
        db.session.add(rota)
        db.session.flush()
        brand = VaccineBrand(vaccine_id=rota.id, name="Rotarix", price=600,
                             doses_per_vial=1)
        db.session.add(brand)
        db.session.flush()
        for number, months in ((1, 2), (2, 4)):
            db.session.add(VaccineBrandDose(brand_id=brand.id,
                                            dose_number=number,
                                            age_months=months))
        db.session.add(VaccineInventory(brand_id=brand.id, lot_number="R1",
                                        qty_received=5, qty_used=0,
                                        expiry_date=date(2030, 1, 1)))
        db.session.commit()
        ids = {"rota": rota.id, "rota_brand": brand.id}
    return {**clinic, "extra": ids}


@pytest.fixture()
def desk(clinic):
    return clinic["sign_in"]("desk")


def _offers(env):
    from app.models import Patient
    from app.utils.vaccine_sale import sellable

    with env["app"].test_request_context("/"):
        patient = env["db"].session.get(Patient, env["ids"]["child"])
        return sellable(patient)


def _by_name(offers, needle):
    return next(o for o in offers if needle in o["name"])


# ============================================== what is on the list ========
def test_a_vaccine_in_stock_is_offered(shelf):
    offers = _offers(shelf)
    assert _by_name(offers, "المكورات")


def test_a_vaccine_with_an_empty_shelf_is_not(shelf):
    """Taking money for a vaccine that is not there is taking money for a
    phone call tomorrow."""
    from app.models import VaccineInventory

    with shelf["app"].app_context():
        for batch in VaccineInventory.query.filter_by(
                brand_id=shelf["ids"]["brand"]).all():
            batch.qty_used = batch.qty_received
        shelf["db"].session.commit()

    assert not [o for o in _offers(shelf) if "المكورات" in o["name"]]


def test_a_government_vaccine_is_never_on_the_till(shelf):
    """It is free and never comes off the clinic's fridge. Putting it on a
    till screen invites somebody to charge for one."""
    offers = _offers(shelf)
    assert not [o for o in offers if "شلل" in o["name"]]


def test_a_finished_course_drops_off_the_list(shelf):
    from app.models import PatientVaccine

    ids = shelf["ids"]
    with shelf["app"].app_context():
        for number in (1, 2, 3):
            shelf["db"].session.add(PatientVaccine(
                patient_id=ids["child"], vaccine_id=ids["pcv"],
                brand_id=ids["brand"], dose_number=number,
                given_date=date.today() - timedelta(days=90 * number),
                event_type="given"))
        shelf["db"].session.commit()

    assert not [o for o in _offers(shelf) if "المكورات" in o["name"]]


# ================================== the doses after the ones already had ===
def test_a_child_with_no_doses_starts_at_the_first(shelf):
    brand = _by_name(_offers(shelf), "المكورات")["brands"][0]
    assert brand["next"] == 1


def test_the_next_dose_is_the_one_after_what_they_have_had(shelf):
    """The request, stated directly. Offering dose 1 to a child two doses in
    is not a display problem — whichever dose is billed is the one the record
    is settled against."""
    from app.models import PatientVaccine

    ids = shelf["ids"]
    with shelf["app"].app_context():
        for number in (1, 2):
            shelf["db"].session.add(PatientVaccine(
                patient_id=ids["child"], vaccine_id=ids["pcv"],
                brand_id=ids["brand"], dose_number=number,
                given_date=date.today() - timedelta(days=120 * number),
                event_type="given"))
        shelf["db"].session.commit()

    brand = _by_name(_offers(shelf), "المكورات")["brands"][0]
    assert brand["next"] == 3
    assert [d["number"] for d in brand["remaining"]] == [3]


def test_the_doses_already_had_stay_on_the_list_marked(shelf):
    """Hidden, "the first was at a government unit" becomes unsayable. Marked,
    it is one click."""
    from app.models import PatientVaccine

    ids = shelf["ids"]
    with shelf["app"].app_context():
        shelf["db"].session.add(PatientVaccine(
            patient_id=ids["child"], vaccine_id=ids["pcv"],
            brand_id=ids["brand"], dose_number=1,
            given_date=date.today() - timedelta(days=60), event_type="given"))
        shelf["db"].session.commit()

    brand = _by_name(_offers(shelf), "المكورات")["brands"][0]
    numbers = [d["number"] for d in brand["doses"]]
    assert numbers == [1, 2, 3]
    assert brand["doses"][0]["given"] is True
    assert brand["doses"][1]["given"] is False


def test_every_dose_carries_a_label_somebody_can_read(shelf):
    brand = _by_name(_offers(shelf), "المكورات")["brands"][0]
    assert all(d["label"] for d in brand["doses"])
    assert brand["next_label"]


# ================================================= what goes on the bill ===
def _picks(env, *specs):
    from app.models import VaccineBrand

    return [{"brand": env["db"].session.get(VaccineBrand, bid),
             "dose_number": dose} for bid, dose in specs]


def _fee(env):
    from app.models import Service

    return Service.query.filter_by(code="SVC-VACFEE").first()


def test_a_sale_bills_the_vial_and_the_fee(shelf):
    from app.models import Patient
    from app.utils.vaccine_sale import sale_lines

    ids = shelf["ids"]
    with shelf["app"].test_request_context("/"):
        patient = shelf["db"].session.get(Patient, ids["child"])
        lines = sale_lines(patient, _picks(shelf, (ids["brand"], 1)),
                           fee_service=_fee(shelf))
    assert len(lines) == 2
    assert lines[0]["unit_price"] == 900
    assert lines[1]["unit_price"] == 100


def test_the_vial_is_not_the_fees_service(shelf):
    """They shared one service id once, so a discount aimed at "رسم تطعيم"
    came off the vaccine's price with it."""
    from app.models import Patient
    from app.utils.vaccine_sale import sale_lines

    ids = shelf["ids"]
    with shelf["app"].test_request_context("/"):
        patient = shelf["db"].session.get(Patient, ids["child"])
        lines = sale_lines(patient, _picks(shelf, (ids["brand"], 1)),
                           fee_service=_fee(shelf))
    vial, fee = lines[0], lines[1]
    assert vial["service_id"] == ""
    assert vial["brand_id"] == ids["brand"]
    assert fee["service_id"] and fee["service_id"] != vial["service_id"]


def test_the_vial_carries_no_invoice_commission(shelf):
    """The doctor's share of a vial is the brand's doctor_fee, credited on the
    dose. Paying it again here would pay it twice."""
    from app.models import Patient
    from app.utils.vaccine_sale import sale_lines

    ids = shelf["ids"]
    with shelf["app"].test_request_context("/"):
        patient = shelf["db"].session.get(Patient, ids["child"])
        lines = sale_lines(patient, _picks(shelf, (ids["brand"], 1)),
                           fee_service=_fee(shelf))
    assert lines[0]["no_commission"] == "1"


def test_the_chosen_dose_travels_onto_the_line(shelf):
    """Asking "which dose" and then dropping the answer would make the
    question theatre."""
    from app.models import Patient
    from app.utils.vaccine_sale import sale_lines

    ids = shelf["ids"]
    with shelf["app"].test_request_context("/"):
        patient = shelf["db"].session.get(Patient, ids["child"])
        lines = sale_lines(patient, _picks(shelf, (ids["brand"], 2)),
                           fee_service=_fee(shelf))
    assert lines[0]["dose_number"] == 2


def test_two_vaccines_in_one_visit_pay_one_fee(shelf):
    """Ordinary practice, and it is one administration. Charging the fee twice
    is the kind of overcharge nobody spots until a parent counts it."""
    from app.models import Patient
    from app.utils.vaccine_sale import sale_lines

    ids, extra = shelf["ids"], shelf["extra"]
    with shelf["app"].test_request_context("/"):
        patient = shelf["db"].session.get(Patient, ids["child"])
        lines = sale_lines(
            patient,
            _picks(shelf, (ids["brand"], 1), (extra["rota_brand"], 1)),
            fee_service=_fee(shelf))
    fees = [line for line in lines if line["service_id"]]
    assert len(lines) == 3
    assert len(fees) == 1


def test_the_fee_is_not_added_twice_across_one_days_bill(shelf):
    """The exam was collected first and a dose is being added afterwards. The
    fee is already on today's invoice."""
    from app.models import Invoice, InvoiceItem, Patient, Service
    from app.utils.vaccine_sale import sale_lines

    ids = shelf["ids"]
    with shelf["app"].test_request_context("/"):
        fee = _fee(shelf)
        invoice = Invoice(invoice_number="INV-V1", patient_id=ids["child"])
        shelf["db"].session.add(invoice)
        shelf["db"].session.flush()
        shelf["db"].session.add(InvoiceItem(
            invoice_id=invoice.id, service_id=fee.id,
            description="رسم تطعيم", unit_price=100, quantity=1))
        shelf["db"].session.commit()

        patient = shelf["db"].session.get(Patient, ids["child"])
        lines = sale_lines(patient, _picks(shelf, (ids["brand"], 1)),
                           invoice=invoice, fee_service=fee)
    assert len(lines) == 1
    assert Service  # imported for clarity of the fixture above


def test_a_zero_fee_still_appears_on_the_bill(shelf):
    """The clinic's own point: a clinic that gives the vaccine at cost still
    wants the line visible at nothing, because "not charged" and "not written
    down" read the same on a piece of paper."""
    from app.models import Patient
    from app.utils.vaccine_sale import sale_lines

    ids = shelf["ids"]
    with shelf["app"].test_request_context("/"):
        fee = _fee(shelf)
        fee.price = 0
        shelf["db"].session.commit()
        patient = shelf["db"].session.get(Patient, ids["child"])
        lines = sale_lines(patient, _picks(shelf, (ids["brand"], 1)),
                           fee_service=fee)
    assert len(lines) == 2
    assert lines[1]["unit_price"] == 0


# ==================================================== the till screen ======
def test_the_picker_is_on_the_invoice_screen(shelf, desk):
    body = desk.get("/finance/invoices/new",
                    query_string={"patient_id": shelf["ids"]["child"]}
                    ).get_data(as_text=True)
    with shelf["app"].test_request_context("/"):
        from app.i18n import t
        assert t("invoices.add_vaccine") in body
    assert "addVaccine()" in body


def test_the_screen_is_given_the_doses_not_just_the_vaccines(shelf, desk):
    """The dose list has to arrive with the page: fetching it after the
    patient is picked would leave the desk waiting with a family in front of
    them."""
    body = desk.get("/finance/invoices/new",
                    query_string={"patient_id": shelf["ids"]["child"]}
                    ).get_data(as_text=True)
    assert '"doses"' in body and '"next"' in body


def test_the_offers_carry_no_model_objects(shelf):
    """They are serialised into the page, so anything not JSON-safe would be
    a 500 on the busiest screen in the clinic."""
    import json

    from app.models import Patient
    from app.utils.vaccine_sale import as_json, sellable

    with shelf["app"].test_request_context("/"):
        patient = shelf["db"].session.get(Patient, shelf["ids"]["child"])
        json.dumps(as_json(sellable(patient)))


def test_a_patient_with_nothing_to_sell_gets_no_panel(clinic, desk):
    """An empty picker is a control that does nothing, next to a family
    waiting."""
    body = desk.get("/finance/invoices/new").get_data(as_text=True)
    with clinic["app"].test_request_context("/"):
        from app.i18n import t
        assert t("invoices.add_vaccine") not in body


def test_the_dose_number_is_stored_on_the_invoice_line(shelf, desk):
    """End to end: the choice made at the desk survives into the record."""
    from app.models import Invoice, InvoiceItem

    ids = shelf["ids"]
    desk.post("/finance/invoices/new", data={
        "patient_id": ids["child"],
        "line_service_id": "", "line_description": "المكورات — Prevenar",
        "line_unit_price": "900", "line_quantity": "1",
        "line_discount_value": "0", "line_discount_is_percent": "0",
        "line_no_commission": "1", "line_brand_id": str(ids["brand"]),
        "line_dose_id": "", "line_vs_id": "", "line_dose_number": "2",
    }, follow_redirects=True)

    with shelf["app"].app_context():
        item = (InvoiceItem.query
                .filter(InvoiceItem.vaccine_brand_id == ids["brand"])
                .order_by(InvoiceItem.id.desc()).first())
        assert item is not None, "the vaccine line was not saved"
        assert item.vaccine_dose_number == 2
        assert Invoice.query.count() >= 1


def test_the_screen_still_opens_without_a_patient(clinic, desk):
    assert desk.get("/finance/invoices/new").status_code == 200


# ================================ paid once, given once =====================
def test_a_dose_paid_for_at_the_desk_is_not_billed_again(shelf, desk):
    """The half that makes selling forward safe. Reception sells dose 2, the
    nurse records it — and the biller, which looks for doses with no invoice,
    finds it and puts it on the next bill. The family pays twice for one
    vaccine, and the second charge looks exactly like a normal one."""
    from app.models import Invoice, InvoiceItem, Patient, Vaccine
    from app.utils.vaccines import administer_dose

    ids = shelf["ids"]
    with shelf["app"].test_request_context("/"):
        invoice = Invoice(invoice_number="INV-PRE", patient_id=ids["child"])
        shelf["db"].session.add(invoice)
        shelf["db"].session.flush()
        shelf["db"].session.add(InvoiceItem(
            invoice_id=invoice.id, description="المكورات — Prevenar",
            unit_price=900, quantity=1, vaccine_brand_id=ids["brand"],
            vaccine_dose_number=1))
        shelf["db"].session.commit()

        patient = shelf["db"].session.get(Patient, ids["child"])
        vaccine = shelf["db"].session.get(Vaccine, ids["pcv"])
        pv, _ = administer_dose(patient, vaccine, dose_number=1)
        shelf["db"].session.commit()
        assert pv is not None
        assert pv.invoice_id == invoice.id, "the dose was not linked to its payment"


def test_the_biller_leaves_a_prepaid_dose_alone(shelf, desk):
    from app.models import Invoice, InvoiceItem, Patient, Vaccine
    from app.utils.vaccines import administer_dose

    ids = shelf["ids"]
    with shelf["app"].test_request_context("/"):
        invoice = Invoice(invoice_number="INV-PRE2", patient_id=ids["child"])
        shelf["db"].session.add(invoice)
        shelf["db"].session.flush()
        shelf["db"].session.add(InvoiceItem(
            invoice_id=invoice.id, description="المكورات — Prevenar",
            unit_price=900, quantity=1, vaccine_brand_id=ids["brand"],
            vaccine_dose_number=1))
        shelf["db"].session.commit()

        patient = shelf["db"].session.get(Patient, ids["child"])
        vaccine = shelf["db"].session.get(Vaccine, ids["pcv"])
        administer_dose(patient, vaccine, dose_number=1)
        shelf["db"].session.commit()

    from app.blueprints.finance.routes import _uncharged_vaccines

    with shelf["app"].app_context():
        assert _uncharged_vaccines(ids["child"]) == []


def test_a_dose_given_without_being_paid_for_is_still_billed(shelf):
    """The guard must not swallow the ordinary case: the doctor gave a dose,
    nobody paid, and the cashier has to see it."""
    from app.blueprints.finance.routes import _uncharged_vaccines
    from app.models import Patient, Vaccine
    from app.utils.vaccines import administer_dose

    ids = shelf["ids"]
    with shelf["app"].test_request_context("/"):
        patient = shelf["db"].session.get(Patient, ids["child"])
        vaccine = shelf["db"].session.get(Vaccine, ids["pcv"])
        pv, _ = administer_dose(patient, vaccine, dose_number=1)
        shelf["db"].session.commit()
        assert pv.invoice_id is None

    with shelf["app"].app_context():
        assert len(_uncharged_vaccines(ids["child"])) == 1


def test_one_payment_cannot_cover_two_doses(shelf):
    """Sell one, give two, and the second must still reach the till."""
    from app.models import Invoice, InvoiceItem, Patient, Vaccine
    from app.utils.vaccines import administer_dose

    ids = shelf["ids"]
    with shelf["app"].test_request_context("/"):
        invoice = Invoice(invoice_number="INV-ONE", patient_id=ids["child"])
        shelf["db"].session.add(invoice)
        shelf["db"].session.flush()
        shelf["db"].session.add(InvoiceItem(
            invoice_id=invoice.id, description="المكورات — Prevenar",
            unit_price=900, quantity=1, vaccine_brand_id=ids["brand"],
            vaccine_dose_number=1))
        shelf["db"].session.commit()

        patient = shelf["db"].session.get(Patient, ids["child"])
        vaccine = shelf["db"].session.get(Vaccine, ids["pcv"])
        first, _ = administer_dose(patient, vaccine, dose_number=1)
        shelf["db"].session.commit()
        second, _ = administer_dose(patient, vaccine, dose_number=2)
        shelf["db"].session.commit()

        assert first.invoice_id == invoice.id
        assert second.invoice_id is None, "one payment covered two doses"


def test_a_line_billed_the_old_way_still_matches_on_the_brand(shelf):
    """Clinics upgrading mid-course have paid lines with no dose number on
    them. Refusing to match there would reintroduce the double charge for
    exactly the people who upgraded."""
    from app.models import Invoice, InvoiceItem, Patient, Vaccine
    from app.utils.vaccines import administer_dose

    ids = shelf["ids"]
    with shelf["app"].test_request_context("/"):
        invoice = Invoice(invoice_number="INV-OLD", patient_id=ids["child"])
        shelf["db"].session.add(invoice)
        shelf["db"].session.flush()
        shelf["db"].session.add(InvoiceItem(
            invoice_id=invoice.id, description="المكورات — Prevenar",
            unit_price=900, quantity=1, vaccine_brand_id=ids["brand"]))
        shelf["db"].session.commit()

        patient = shelf["db"].session.get(Patient, ids["child"])
        vaccine = shelf["db"].session.get(Vaccine, ids["pcv"])
        pv, _ = administer_dose(patient, vaccine, dose_number=1)
        shelf["db"].session.commit()
        assert pv.invoice_id == invoice.id


def test_another_patients_payment_is_never_borrowed(shelf):
    """Matching on brand alone across patients would let one family's payment
    cover another's dose — an error that balances the books and loses money."""
    from datetime import date as _date

    from app.models import Invoice, InvoiceItem, Patient, Vaccine
    from app.utils.vaccines import administer_dose

    ids = shelf["ids"]
    with shelf["app"].test_request_context("/"):
        other = Patient(patient_number="P-OTHER", full_name="طفل تاني",
                        gender="male", date_of_birth=_date(2024, 1, 1),
                        is_active=True)
        shelf["db"].session.add(other)
        shelf["db"].session.flush()
        invoice = Invoice(invoice_number="INV-OTHER", patient_id=other.id)
        shelf["db"].session.add(invoice)
        shelf["db"].session.flush()
        shelf["db"].session.add(InvoiceItem(
            invoice_id=invoice.id, description="المكورات — Prevenar",
            unit_price=900, quantity=1, vaccine_brand_id=ids["brand"],
            vaccine_dose_number=1))
        shelf["db"].session.commit()

        patient = shelf["db"].session.get(Patient, ids["child"])
        vaccine = shelf["db"].session.get(Vaccine, ids["pcv"])
        pv, _ = administer_dose(patient, vaccine, dose_number=1)
        shelf["db"].session.commit()
        assert pv.invoice_id is None


def test_a_billing_failure_never_blocks_a_dose(shelf):
    """A child in front of a nurse does not wait on the accounts."""
    import inspect

    from app.utils import vaccines

    source = inspect.getsource(vaccines.administer_dose)
    assert "claim_prepaid" in source
    block = source[source.index("claim_prepaid") - 200:]
    assert "except Exception" in block
