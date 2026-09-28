"""Cost centres: which part of the clinic earned the money, and which spent it.

``IMPROVEMENTS_BACKLOG.md`` and the About screen's «لسه» list carried it for a
year: *revenue and expense split across the clinic's departments* — and the
journal line had nowhere to write a department. What is held here:

* **revenue is placed, never chosen** — a bed night is its unit's, a dose on
  the ward and a box over the counter the pharmacy's, an operation the
  theatre's, a vaccine the vaccination service's, a test the laboratory's,
  a dental plan the dentist's, an emergency attendance the emergency
  department's, the rest the outpatient clinics'; a service the clinic
  pointed at a centre of its own goes there;
* **the answer is written once** — on the invoice line and the journal line —
  and does not move when the rule does afterwards;
* **the accounts do not change** — the services and vaccination revenue
  accounts carry exactly what they carried before, only in more lines; a bill
  that will not split cleanly is posted exactly as it always was;
* **costs are placed only when somebody says so** — an expense against a
  centre, or none (shared); what left the shelf goes where it was used;
* **the report adds up to the income statement**, with the shared costs and
  the revenue nobody placed on lines of their own — never spread by a rule.
"""
import os
import sys
from datetime import datetime, time, timedelta
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

from tests.test_a_dose_that_never_left_the_shelf import (  # noqa: E402,F401
    _admit as _ward_admit, _charge as _ward_charge, _child as _ward_child,
    _give, _order, ward)
from tests.test_the_box_that_left_the_shelf import (  # noqa: E402,F401
    _collect as _counter_collect, _put_on_shelf, counter)
from tests.test_two_people_in_the_theatre import (  # noqa: E402,F401
    _admit as _theatre_admit, _bill_day_case, _case, child, theatre)
from tests.test_what_a_family_agreed_to import (  # noqa: E402,F401
    _plan as _dental_plan, boss, dental)


@pytest.fixture()
def books(clinic):
    from app.models import Service
    from app.utils import accounting as acct

    with clinic["app"].app_context():
        acct.ensure_seeded()
        db = clinic["db"]
        lab = Service(name="صورة دم", category="lab", price=100, is_active=True)
        xray = Service(name="أشعة صدر", category="radiology", price=300,
                       is_active=True)
        jab = Service(name="تطعيم", category="vaccination_fee", price=50,
                      service_type="vaccination", is_active=True)
        db.session.add_all([lab, xray, jab])
        db.session.commit()
        clinic["ids"].update(lab=lab.id, xray=xray.id, jab=jab.id)
    return clinic


def _invoice(clinic, lines, number="INV-1", on=None, **fields):
    """A bill with ``lines`` of ``(service key or None, price, extras)``,
    posted to the books the way every screen posts one."""
    from app.models import Invoice, InvoiceItem
    from app.utils import billing
    from app.utils.clock import local_today

    with clinic["app"].app_context():
        db = clinic["db"]
        inv = Invoice(invoice_number=number, patient_id=clinic["ids"]["child"],
                      doctor_id=clinic["ids"]["doctor"],
                      invoice_date=on or local_today(), **fields)
        db.session.add(inv)
        db.session.flush()
        for key, price, extra in lines:
            item = InvoiceItem(invoice_id=inv.id,
                               service_id=clinic["ids"][key] if key else None,
                               description=key or "سطر", unit_price=price,
                               quantity=1, **extra)
            db.session.add(item)
        db.session.commit()
        billing.post_to_ledger("invoice", inv)
        return inv.id


def _journal(clinic, source_type, source_id):
    """``{(code, debit, credit, centre key)}`` of one posted document."""
    from app.models import JournalEntry

    with clinic["app"].app_context():
        entry = JournalEntry.query.filter_by(source_type=source_type,
                                             source_id=source_id).one()
        return sorted(((ln.account.code, ln.debit, ln.credit,
                        ln.cost_centre.key if ln.cost_centre else None)
                       for ln in entry.lines), key=str)


def _item_centres(clinic, invoice_id):
    from app.models import Invoice

    with clinic["app"].app_context():
        inv = clinic["db"].session.get(Invoice, invoice_id)
        return sorted(((i.description, i.cost_centre.key if i.cost_centre
                        else None) for i in inv.items), key=str)


def _key(clinic, centre_id):
    from app.models import CostCentre

    with clinic["app"].app_context():
        row = clinic["db"].session.get(CostCentre, centre_id)
        return row.key if row else None


# ------------------------------------------------------- revenue, placed ----
def test_an_outpatient_bill_is_the_clinics(books):
    invoice = _invoice(books, [("exam", 200, {})])
    assert _journal(books, "invoice", invoice) == [
        ("1030", 200.0, 0.0, None), ("4010", 0.0, 200.0, "outpatient")]
    assert _item_centres(books, invoice) == [("exam", "outpatient")]


def test_each_line_goes_where_it_came_from(books):
    invoice = _invoice(books, [
        ("exam", 200, {}),
        ("lab", 100, {}),
        ("xray", 300, {}),
        ("jab", 50, {}),
        # A vaccine product line: no service, the brand on it.
        (None, 900, {"vaccine_brand_id": books["ids"]["brand"]}),
    ])
    lines = _journal(books, "invoice", invoice)
    assert ("4010", 0.0, 200.0, "outpatient") in lines
    assert ("4010", 0.0, 100.0, "lab") in lines
    assert ("4010", 0.0, 300.0, "imaging") in lines
    # The vaccination *account* is still decided by the service type, as it
    # always was; the *centre* of both vaccine lines is the vaccinations'.
    assert ("4020", 0.0, 50.0, "vaccinations") in lines
    assert ("4010", 0.0, 900.0, "vaccinations") in lines


def test_the_accounts_carry_exactly_what_they_did_before(books):
    """More lines, the same two numbers: whatever reads the services and the
    vaccination revenue accounts sees no change."""
    from app.models import Invoice
    from app.utils.accounting import _vaccine_split

    invoice = _invoice(books, [("exam", 200, {}), ("lab", 100, {}),
                               ("jab", 50, {}), ("nebul", 150, {})])
    lines = _journal(books, "invoice", invoice)
    with books["app"].app_context():
        vac, svc = _vaccine_split(books["db"].session.get(Invoice, invoice))
    assert sum(c for code, _d, c, _k in lines if code == "4010") == svc == 450
    assert sum(c for code, _d, c, _k in lines if code == "4020") == vac == 50
    assert sum(d for _c, d, _cr, _k in lines) == sum(c for _c, _d, c, _k in lines)


def test_a_bill_that_will_not_split_cleanly_is_posted_as_it_always_was(books):
    """A negative line in one centre would be a debit to revenue there — the
    entry is posted as before, one line, no centre, rather than bent. (A
    discount over 100% is the one way a line nets below zero.)"""
    invoice = _invoice(books, [("exam", 200, {}),
                               ("lab", 100, {"discount_value": 150,
                                             "discount_is_percent": True})])
    assert _journal(books, "invoice", invoice) == [
        ("1030", 150.0, 0.0, None), ("4010", 0.0, 150.0, None)]


def test_an_emergency_attendance_is_the_emergency_departments(books):
    from app.models import EmergencyVisit

    with books["app"].app_context():
        books["db"].session.add(EmergencyVisit(
            patient_id=books["ids"]["child"], visit_id=books["ids"]["visit"]))
        books["db"].session.commit()
    invoice = _invoice(books, [("exam", 200, {})],
                       visit_id=books["ids"]["visit"])
    assert ("4010", 0.0, 200.0, "emergency") in _journal(books, "invoice", invoice)


def test_a_service_the_clinic_pointed_at_a_centre_goes_there(books):
    from app.models import Service
    from app.utils import cost_centres

    with books["app"].app_context():
        physio = cost_centres.add_own("علاج طبيعي", "Physiotherapy")
        books["db"].session.get(Service, books["ids"]["nebul"]).cost_centre_id = physio.id
        books["db"].session.commit()
        key = physio.key
    invoice = _invoice(books, [("nebul", 150, {}), ("exam", 200, {})])
    lines = _journal(books, "invoice", invoice)
    assert ("4010", 0.0, 150.0, key) in lines
    assert ("4010", 0.0, 200.0, "outpatient") in lines


def test_the_answer_does_not_move_when_the_rule_does(books):
    """Posted, then the service is pointed elsewhere, then the bill grows and
    is posted again: the first line stays where it was placed."""
    from app.models import Invoice, InvoiceItem, Service
    from app.utils import billing, cost_centres

    invoice = _invoice(books, [("exam", 200, {})])
    with books["app"].app_context():
        db = books["db"]
        own = cost_centres.add_own("عيادة المساء")
        db.session.get(Service, books["ids"]["exam"]).cost_centre_id = own.id
        inv = db.session.get(Invoice, invoice)
        db.session.add(InvoiceItem(invoice_id=inv.id,
                                   service_id=books["ids"]["exam"],
                                   description="exam", unit_price=200, quantity=1))
        db.session.commit()
        billing.post_to_ledger("invoice", db.session.get(Invoice, invoice))
        key = own.key
    lines = _journal(books, "invoice", invoice)
    assert ("4010", 0.0, 200.0, "outpatient") in lines
    assert ("4010", 0.0, 200.0, key) in lines


def test_a_line_already_placed_is_never_placed_again(books):
    from app.models import InvoiceItem
    from app.utils import cost_centres

    with books["app"].app_context():
        item = InvoiceItem(description="x", unit_price=1, quantity=1)
        cost_centres.stamp(item, "theatres")
        theatres = item.cost_centre_id
        cost_centres.stamp(item, "pharmacy")
        assert item.cost_centre_id == theatres
        assert cost_centres.for_item(item) == theatres
        # A key that is nobody's is not made up into a centre.
        assert cost_centres.centre("nonsense") is None
        assert cost_centres.centre("unit:99999") is None


# --------------------------------------------------------------- the ward ----
def test_a_stay_its_nights_to_the_unit_and_its_doses_to_the_pharmacy(ward):
    from app.models import Invoice, StockMovement, StoreDocument
    from app.models.place import Unit

    with ward["app"].app_context():
        ward["db"].session.add(StockMovement(
            item_id=ward["drug_item"], kind="in", qty=20, unit_cost=10))
        ward["db"].session.commit()
        unit_key = f"unit:{Unit.query.one().id}"
    child_id = _ward_child(ward, "مراكز")
    admission = _ward_admit(ward, child_id)
    order = _order(ward, admission, store_item_id=ward["drug_item"])
    _give(ward, order, hours_ago=10)
    _ward_charge(ward, admission)

    with ward["app"].app_context():
        inv = Invoice.query.filter_by(admission_id=admission).one()
        by_centre = {}
        for item in inv.items:
            by_centre.setdefault(item.cost_centre.key, []).append(item.net)
        document = StoreDocument.query.filter_by(kind="issue").one()
        invoice_id, document_id = inv.id, document.id
    assert set(by_centre) == {unit_key, "pharmacy"}
    assert by_centre["pharmacy"] == [25.0]
    lines = _journal(ward, "invoice", invoice_id)
    assert ("4010", 0.0, 25.0, "pharmacy") in lines
    assert ("4010", 0.0, sum(by_centre[unit_key]), unit_key) in lines
    # And what the dose cost is the pharmacy's too.
    assert ("5020", 10.0, 0.0, "pharmacy") in _journal(ward, "store_doc",
                                                       document_id)


def test_a_child_moved_between_units_is_each_units_on_its_days(ward):
    """A line with no maker's mark on a stay's bill — a bed night, a care
    charge, a round — is the unit the child was in that day: the ward on
    Monday, the NICU after the move."""
    from app.models import Admission, Invoice, InvoiceItem, Service
    from app.models.admission import BedStay
    from app.models.place import Bed, Space, Unit
    from app.utils import billing
    from app.utils.clock import local_today

    child_id = _ward_child(ward, "نقل")
    with ward["app"].app_context():
        db = ward["db"]
        nicu = Unit(name="الحضّانات", kind="nicu")
        db.session.add(nicu)
        db.session.flush()
        space = Space(unit_id=nicu.id, name="حضّانات", kind="bay")
        db.session.add(space)
        db.session.flush()
        cot = Bed(space_id=space.id, name="ح١", kind="incubator")
        db.session.add(cot)
        db.session.flush()
        today = local_today()
        start = datetime.combine(today - timedelta(days=6), time(12))
        left = datetime.combine(today - timedelta(days=5), time(12))
        moved = datetime.combine(today - timedelta(days=2), time(12))
        stay = Admission(patient_id=child_id, doctor_id=ward["ids"]["doctor"],
                         admitted_at=start)
        db.session.add(stay)
        db.session.flush()
        db.session.add_all([
            # On the ward, then two days with no bed recorded (in theatre,
            # say), then the incubators.
            BedStay(admission_id=stay.id, bed_id=ward["bed"], since=start,
                    until=left),
            BedStay(admission_id=stay.id, bed_id=cot.id, since=moved)])
        care = Service(name="رعاية", category="other", price=100)
        db.session.add(care)
        db.session.flush()
        inv = Invoice(invoice_number="INV-MOVE", patient_id=child_id,
                      admission_id=stay.id, invoice_date=today)
        db.session.add(inv)
        db.session.flush()
        for days_ago, price in ((8, 90), (4, 100), (2, 50), (1, 110)):
            db.session.add(InvoiceItem(
                invoice_id=inv.id, service_id=care.id, description="رعاية",
                unit_price=price, quantity=1,
                service_date=today - timedelta(days=days_ago)))
        db.session.commit()
        billing.post_to_ledger("invoice", inv)
        ward_key = f"unit:{Unit.query.filter_by(kind='ward').one().id}"
        nicu_key = f"unit:{nicu.id}"
        invoice_id = inv.id
    lines = _journal(ward, "invoice", invoice_id)
    # Charged before the first bed: the first unit. Between the two stays:
    # the unit the child had been in, not the one not reached yet. The day of
    # the move is the new unit's — the night is spent there.
    assert ("4010", 0.0, 190.0, ward_key) in lines
    assert ("4010", 0.0, 160.0, nicu_key) in lines


# ------------------------------------------------------------ the theatre ----
def test_a_day_case_at_the_desk_is_the_theatres(theatre, child):
    operation = _case(theatre, case_type="private")
    invoice = _bill_day_case(theatre, child, operation)
    centres = {key for _d, key in _item_centres(theatre, invoice)}
    assert centres == {"theatres"}


def test_a_case_on_a_stays_bill_is_the_theatres_not_the_units(theatre, child):
    from app.models import Invoice, Operation
    from app.models.admission import Admission
    from app.utils import theatres as theatre_util

    operation = _case(theatre, case_type="private")
    stay = _theatre_admit(theatre, child)
    with theatre["app"].app_context():
        op = theatre["db"].session.get(Operation, operation)
        op.admission_id = stay
        invoice = Invoice(invoice_number="INV-WARD-CC", patient_id=child,
                          admission_id=stay)
        theatre["db"].session.add(invoice)
        theatre["db"].session.flush()
        theatre_util.charge(theatre["db"].session.get(Admission, stay),
                            invoice, lang="ar")
        theatre["db"].session.commit()
        invoice_id = invoice.id
    centres = [key for _d, key in _item_centres(theatre, invoice_id)]
    assert centres == ["theatres", "theatres"]


# -------------------------------------------------- the pharmacy counter ----
def test_a_box_over_the_counter_is_the_pharmacys_and_so_is_its_cost(counter):
    from app.models import Invoice, StockMovement, StoreDocument

    with counter["app"].app_context():
        counter["db"].session.add(StockMovement(
            item_id=counter["box"], kind="in", qty=10, unit_cost=25))
        counter["db"].session.commit()
    client = _put_on_shelf(counter, quantity=2)
    client.post(f"/pharmacy/line/{counter['line']}/dispense",
                follow_redirects=True)
    _counter_collect(counter, counter["line"])
    with counter["app"].app_context():
        inv = Invoice.query.one()
        document = StoreDocument.query.filter_by(kind="issue").one()
        invoice_id, document_id = inv.id, document.id
    assert [key for _d, key in _item_centres(counter, invoice_id)] == ["pharmacy"]
    assert ("5020", 50.0, 0.0, "pharmacy") in _journal(counter, "store_doc",
                                                       document_id)


def test_a_services_consumables_cost_the_centre_of_the_service(books):
    """The gauze a nebuliser session burns is the outpatient clinics' cost,
    because the session is their revenue."""
    from app.models import ServiceConsumable, StockMovement, StoreDocument, StoreItem

    with books["app"].app_context():
        db = books["db"]
        gauze = StoreItem(name="شاش", unit="قطعة", item_type="consumable",
                          sell_price=5, purchase_price=2, is_active=True)
        db.session.add(gauze)
        db.session.flush()
        db.session.add(StockMovement(item_id=gauze.id, kind="in", qty=50,
                                     unit_cost=2))
        db.session.add(ServiceConsumable(service_id=books["ids"]["nebul"],
                                         store_item_id=gauze.id, quantity=3))
        db.session.commit()
    books["sign_in"]("boss").post(
        f"/finance/collect/{books['ids']['child']}", data={
            "doctor_id": books["ids"]["doctor"], "discount_id": "none",
            "line_service_id": [str(books["ids"]["nebul"])],
            "line_desc": ["جلسة تنفس"], "line_price": ["150"], "line_qty": ["1"],
            "line_no_commission": ["0"], "line_brand_id": [""],
            "line_dose_id": [""], "line_dose_number": [""], "line_vs_id": [""],
            "line_op_id": [""], "line_test_id": [""], "line_rx_line_id": [""],
        }, follow_redirects=True)
    with books["app"].app_context():
        document_id = StoreDocument.query.filter_by(kind="issue").one().id
    assert ("5020", 6.0, 0.0, "outpatient") in _journal(books, "store_doc",
                                                        document_id)


def test_a_documents_cost_split_over_centres_adds_up_to_the_penny(books):
    from app.models import StockMovement, StoreDocument, StoreItem
    from app.utils import accounting, cost_centres

    with books["app"].app_context():
        db = books["db"]
        thing = StoreItem(name="س", unit="ق", item_type="consumable",
                          is_active=True)
        db.session.add(thing)
        db.session.flush()
        doc = StoreDocument(doc_number="ISS-X", kind="issue")
        db.session.add(doc)
        db.session.flush()
        for centre, cost in (("pharmacy", 1.005), ("lab", 1.005), (None, 1.005)):
            db.session.add(StockMovement(
                item_id=thing.id, kind="out", qty=-1, unit_cost=cost,
                document_id=doc.id,
                cost_centre_id=cost_centres.centre_id(centre)))
        db.session.commit()
        accounting.post_store_doc(doc)
        doc_id, doc_value = doc.id, accounting._doc_value(doc)
    lines = _journal(books, "store_doc", doc_id)
    debit = round(sum(d for _c, d, _cr, _k in lines), 2)
    credit = round(sum(c for _c, _d, c, _k in lines), 2)
    # Three thirds of a penny each way: the entry balances, and the rounding
    # sits on one line rather than unbalancing it.
    assert debit == credit == doc_value
    assert {k for code, _d, _c, k in lines if code == "5020"} == {
        "pharmacy", "lab", None}


# ---------------------------------------------------------------- dental ----
def test_an_accepted_dental_plan_is_the_dentists(dental, boss):
    from app.models import TreatmentPlan

    plan_id = _dental_plan(dental)
    boss.post(f"/dentistry/plan/{plan_id}/accept", follow_redirects=True)
    with dental["app"].app_context():
        invoice_id = dental["db"].session.get(TreatmentPlan, plan_id).invoice_id
    assert {key for _d, key in _item_centres(dental, invoice_id)} == {"dentistry"}


# --------------------------------------------------------------- costs ----
def test_a_dose_given_costs_the_vaccination_service(books):
    from app.utils import accounting

    with books["app"].app_context():
        dose = SimpleNamespace(id=4242, given_outside=False, dose_number=1,
                               batch=SimpleNamespace(unit_cost=320),
                               brand=SimpleNamespace(name="Prevenar",
                                                     purchase_price=300))
        accounting.post_dose_cogs(dose)
    assert _journal(books, "vaccine_dose", 4242) == [
        ("1040", 0.0, 320.0, None), ("5020", 320.0, 0.0, "vaccinations")]


def _expense(clinic, centre_id=None, amount="300"):
    from app.models import Expense

    clinic["sign_in"]("boss").post("/finance/expenses/new", data={
        "category": "supplies", "amount": amount, "description": "م",
        "payment_method": "bank", "cost_centre_id": centre_id or ""})
    with clinic["app"].app_context():
        return Expense.query.order_by(Expense.id.desc()).first().id


def test_an_expense_is_its_centres_or_shared(books):
    from app.utils import cost_centres

    with books["app"].app_context():
        lab = cost_centres.centre("lab")
        off = cost_centres.add_own("قسم مقفول")
        off.is_active = False
        books["db"].session.commit()
        lab_id, off_id = lab.id, off.id
    placed = _expense(books, lab_id)
    shared = _expense(books)
    switched_off = _expense(books, off_id)
    assert ("5010", 300.0, 0.0, "lab") in _journal(books, "expense", placed)
    assert ("5010", 300.0, 0.0, None) in _journal(books, "expense", shared)
    # A centre that is switched off is not one to put new money on.
    assert ("5010", 300.0, 0.0, None) in _journal(books, "expense", switched_off)


def test_the_expense_form_offers_the_centres_that_are_on(books):
    from app.utils import cost_centres

    with books["app"].app_context():
        cost_centres.add_own("علاج طبيعي")
        cost_centres.add_own("قسم مقفول").is_active = False
        books["db"].session.commit()
    page = books["sign_in"]("boss").get("/finance/expenses").get_data(as_text=True)
    box = page[page.index("data-expense-centre"):]
    box = box[:box.index("</select>")]
    assert "علاج طبيعي" in box and "قسم مقفول" not in box
    assert 'value=""' in box                     # shared is the first answer


# ------------------------------------------------------------ the report ----
def _month_of_books(books):
    """An outpatient bill, a lab bill with a cost of its own, the rent, and
    the two kinds of revenue nobody placed: a bill from before centres, and
    an insurer's claim payment."""
    from app.utils import accounting, cost_centres

    _invoice(books, [("exam", 200, {}), ("lab", 100, {})])
    with books["app"].app_context():
        lab_id = cost_centres.centre_id("lab")
        books["db"].session.commit()
    _expense(books, lab_id, amount="30")
    _expense(books, amount="500")
    with books["app"].app_context():
        accounting.post_entry("invoice", 9001, "old", [
            ("1030", 80, 0, "old"), ("4010", 0, 80, "old")])
        accounting.post_entry("claim", 9002, "claim", [
            ("1010", 70, 0, "c"), ("4010", 0, 70, "c")])


def _income_net(books, date_from, date_to):
    """The income statement's own sum, worked out independently here."""
    from app.models import Account, JournalEntry, JournalLine

    with books["app"].app_context():
        net = 0.0
        for line in (JournalLine.query.join(JournalEntry).join(Account)
                     .filter(JournalEntry.entry_date >= date_from,
                             JournalEntry.entry_date <= date_to).all()):
            if line.account.type == "revenue":
                net += line.credit - line.debit
            elif line.account.type == "expense":
                net -= line.debit - line.credit
        return round(net, 2)


def test_the_report_adds_up_to_the_income_statement(books):
    from app.utils import cost_centre_report
    from app.utils.clock import local_today

    _month_of_books(books)
    today = local_today()
    with books["app"].app_context():
        report = cost_centre_report.report(today.replace(day=1), today)
        lines = {line["centre"].key: line for line in report["lines"]}
        shared = {acc.code: amount for acc, amount in report["shared"]}
    assert set(lines) == {"outpatient", "lab"}
    assert (lines["lab"]["revenue"], lines["lab"]["direct"],
            lines["lab"]["contribution"], lines["lab"]["margin"]) == (100, 30, 70, 70.0)
    assert lines["outpatient"]["margin"] == 100.0
    assert shared == {"5010": 500}
    assert report["unplaced"] == {"invoice": 80, "claim": 70}
    assert (report["revenue"], report["expenses"]) == (450, 530)
    # Left from the centres, plus what nobody placed, less what is shared:
    assert report["contribution"] + report["unplaced_total"] \
        - report["shared_total"] == report["net"] == -80
    assert report["net"] == _income_net(books, today.replace(day=1), today)
    assert report["placed_pct"] == 67             # 300 of 450


def test_the_doctors_share_is_read_from_the_bills_of_that_centre(books):
    from app.utils import cost_centre_report
    from app.utils.clock import local_today

    _invoice(books, [("exam", 200, {"commission_amount": 80})])
    today = local_today()
    with books["app"].app_context():
        line = cost_centre_report.report(today, today)["lines"][0]
    assert (line["doctors"], line["revenue"], line["contribution"]) == (80, 200, 200)


def test_the_period_counts_only_its_days(books):
    from app.utils import cost_centre_report
    from app.utils.clock import local_today

    today = local_today()
    _invoice(books, [("exam", 200, {})], number="INV-OLD",
             on=today - timedelta(days=40))
    _invoice(books, [("lab", 100, {})], number="INV-NOW")
    with books["app"].app_context():
        report = cost_centre_report.report(today - timedelta(days=5), today)
    assert [line["centre"].key for line in report["lines"]] == ["lab"]
    assert report["revenue"] == 100


def test_the_screen_draws_it(books):
    from app.utils.clock import local_today

    _month_of_books(books)
    today = local_today()
    page = books["sign_in"]("boss").get(
        f"/reports/cost-centres?date_from={today.replace(day=1)}&date_to={today}"
    ).get_data(as_text=True)
    assert 'data-centre="outpatient"' in page and 'data-centre="lab"' in page
    assert 'data-margin="70.0"' in page
    assert 'data-net="-80.0"' in page
    assert 'data-unplaced-why="claim"' in page and 'data-unplaced-why="invoice"' in page
    assert 'data-shared="500.0"' in page
    assert "data-manage-centres" in page
    assert "/reports/cost-centres" in books["sign_in"]("boss").get(
        "/reports/").get_data(as_text=True)


def test_the_screen_before_anything_is_posted(books):
    page = books["sign_in"]("boss").get("/reports/cost-centres") \
        .get_data(as_text=True)
    assert "data-centres-empty" in page and "data-periods" in page


# ---------------------------------------------------------------- the list --
def test_the_list_is_made_from_what_the_clinic_runs(books):
    from app.models import CostCentre, Setting
    from app.models.place import Unit
    from app.utils import cost_centres

    with books["app"].app_context():
        db = books["db"]
        unit = Unit(name="الرعاية", kind="icu")
        db.session.add(unit)
        db.session.commit()
        cost_centres.ensure_all()
        db.session.commit()
        before = {c.key for c in CostCentre.query.all()}
        Setting.set("mod_enabled:theatres", "1")
        Setting.set("mod_enabled:beds", "1")
        cost_centres.ensure_all()
        db.session.commit()
        after = {c.key for c in CostCentre.query.all()}
        unit_key = f"unit:{unit.id}"
    assert "outpatient" in before and "vaccinations" in before
    assert "theatres" not in before and unit_key not in before
    assert {"theatres", unit_key} <= after


def test_the_owner_renames_adds_and_switches_off(books):
    from app.models import CostCentre

    boss = books["sign_in"]("boss")
    assert boss.get("/finance/cost-centres").status_code == 200
    boss.post("/finance/cost-centres/new",
              data={"name_ar": "علاج طبيعي", "name_en": "Physio"})
    with books["app"].app_context():
        own = CostCentre.query.filter(CostCentre.key.like("own:%")).one()
        outpatient = CostCentre.query.filter_by(key="outpatient").one()
        own_id, out_id = own.id, outpatient.id
    boss.post(f"/finance/cost-centres/{out_id}",
              data={"name_ar": "العيادات", "name_en": "", "is_active": "1"})
    boss.post(f"/finance/cost-centres/{own_id}",
              data={"name_ar": "علاج طبيعي", "name_en": "Physio"})
    with books["app"].app_context():
        db = books["db"]
        assert db.session.get(CostCentre, out_id).name_ar == "العيادات"
        assert db.session.get(CostCentre, own_id).is_active is False
    page = boss.get("/finance/cost-centres").get_data(as_text=True)
    assert 'data-centre-row="outpatient"' in page


def test_only_the_owner_manages_the_list(books):
    reply = books["sign_in"]("acct").get("/finance/cost-centres")
    assert reply.status_code in (302, 403)
    reply = books["sign_in"]("acct").post("/finance/cost-centres/new",
                                          data={"name_ar": "x"})
    assert reply.status_code in (302, 403)
    from app.models import CostCentre

    with books["app"].app_context():
        assert CostCentre.query.filter(CostCentre.key.like("own:%")).count() == 0


def test_a_service_is_pointed_at_a_centre_and_a_price_edit_keeps_it(books):
    from app.models import Service
    from app.utils import cost_centres

    with books["app"].app_context():
        physio = cost_centres.add_own("علاج طبيعي")
        books["db"].session.commit()
        physio_id = physio.id
    boss = books["sign_in"]("boss")
    nebul = books["ids"]["nebul"]
    boss.post(f"/finance/services/{nebul}/edit", data={
        "name": "جلسة تنفس", "category": "procedure", "price": "150",
        "cost_centre_id": str(physio_id)})
    with books["app"].app_context():
        assert books["db"].session.get(Service, nebul).cost_centre_id == physio_id
    boss.post(f"/finance/services/{nebul}/edit", data={
        "name": "جلسة تنفس", "category": "procedure", "price": "175"})
    with books["app"].app_context():
        svc = books["db"].session.get(Service, nebul)
        assert (svc.price, svc.cost_centre_id) == (175, physio_id)
    page = boss.get("/finance/services").get_data(as_text=True)
    assert "data-service-centre" in page
