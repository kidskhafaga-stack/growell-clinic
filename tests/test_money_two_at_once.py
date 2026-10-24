"""Money written by two people at the same moment (the money review, ف-١).

Asked as a review of the books: *two deductions of 30 from 100 must leave 40;
two that do not both fit must not both pass; the same thing sent twice must
be recorded once.*

These run over a real SQLite file with a thread per cashier, and the moment
between «how much is owed / held?» and «write it» is held open on purpose —
the way ``test_one_slot_one_child`` holds the diary — so that a missing lock
shows up as money recorded twice instead of passing by luck.
"""
import os
import sys
import threading
import time as _time
from datetime import date

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

PAUSE = 0.4


@pytest.fixture()
def till(tmp_path, monkeypatch):
    """A clinic on a real file: two cashiers, a child, a bill of 100 and an
    account holding 100 for the family."""
    from app import create_app
    from app.extensions import db

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/till.db")
    app = create_app("testing")
    with app.app_context():
        db.create_all()
        from app.models import (Invoice, InvoiceItem, Patient, PatientCredit,
                                Service, User)
        from app.utils.accounting import ensure_seeded

        ensure_seeded()
        for n in range(2):
            user = User(username=f"cash{n}", full_name=f"خزنة {n}", role="admin",
                        is_active=True)
            user.set_password("secret")
            db.session.add(user)
        exam = Service(name="كشف", category="consultation", price=100,
                       is_active=True, commission_type="none", commission_value=0)
        child = Patient(patient_number="P1", full_name="طفل", gender="male",
                        date_of_birth=date(2024, 1, 1), is_active=True)
        db.session.add_all([exam, child])
        db.session.flush()
        bills = []
        for n in range(2):
            bill = Invoice(patient_id=child.id, invoice_number=f"INV-{n}",
                           invoice_date=date.today(), status="unpaid")
            db.session.add(bill)
            db.session.flush()
            db.session.add(InvoiceItem(invoice_id=bill.id, service_id=exam.id,
                                       description="كشف", quantity=1,
                                       unit_price=100, discount_value=0))
            bills.append(bill.id)
        db.session.add(PatientCredit(patient_id=child.id, kind="in", amount=100,
                                     method="instapay"))
        db.session.commit()
        for bill_id in bills:
            db.session.get(Invoice, bill_id).recalc_status()
        db.session.commit()
        ids = {"child": child.id, "bills": bills}

    def sign_in(username):
        client = app.test_client()
        client.post("/login", data={"username": username, "password": "secret"})
        return client

    return {"app": app, "db": db, "ids": ids, "sign_in": sign_in}


def _together(n, work):
    """Run ``work(i)`` for ``n`` cashiers, released at the same instant."""
    gate = threading.Barrier(n)
    replies, errors = [None] * n, []

    def one(i):
        try:
            gate.wait()
            replies[i] = work(i)
        except Exception as exc:  # noqa: BLE001 - reported below
            errors.append(exc)

    threads = [threading.Thread(target=one, args=(i,)) for i in range(n)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(60)
    return replies, errors


@pytest.fixture()
def slow_balance(monkeypatch):
    """Hold open «how much is held?» → «write it» on the family's account."""
    from app.utils import patient_credit

    real = patient_credit.balance

    def balance(patient_id):
        answer = real(patient_id)
        _time.sleep(PAUSE)
        return answer

    monkeypatch.setattr(patient_credit, "balance", balance)


@pytest.fixture()
def slow_collect(monkeypatch):
    """Hold open «how much is owed?» → «write the payment» at the till."""
    from app.blueprints.finance import routes

    real = routes._take_payment

    def take(*args, **kwargs):
        _time.sleep(PAUSE)
        return real(*args, **kwargs)

    monkeypatch.setattr(routes, "_take_payment", take)


def _held(till):
    from app.utils import patient_credit

    with till["app"].app_context():
        return patient_credit.balance(till["ids"]["child"])


def _paid(till, bill_id):
    from app.models import Invoice

    with till["app"].app_context():
        bill = till["db"].session.get(Invoice, bill_id)
        return round(bill.paid, 2), round(bill.balance, 2)


def _give_back(till, amount):
    def work(_i):
        from app.models import Patient
        from app.utils import patient_credit

        with till["app"].app_context():
            db = till["db"]
            try:
                patient_credit.give_back(db.session.get(Patient, till["ids"]["child"]),
                                         amount, method="instapay")
                db.session.commit()
                return "ok"
            except patient_credit.CreditError as exc:
                db.session.rollback()
                return str(exc)
    return work


# --------------------------------------------------- the family's account --
def test_two_give_backs_of_30_from_100_leave_40(till, slow_balance):
    replies, errors = _together(2, _give_back(till, 30))
    assert errors == []
    assert replies == ["ok", "ok"]
    assert _held(till) == 40


def test_two_give_backs_that_do_not_both_fit_never_overdraw(till, slow_balance):
    replies, errors = _together(2, _give_back(till, 70))
    assert errors == []
    assert sorted(replies) == ["ok", "over_held"]
    assert _held(till) == 30


def test_one_credit_paying_two_bills_at_once_is_spent_once(till, slow_balance):
    def work(i):
        from app.models import Invoice
        from app.utils import patient_credit

        with till["app"].app_context():
            db = till["db"]
            try:
                patient_credit.apply_to(db.session.get(Invoice, till["ids"]["bills"][i]))
                db.session.commit()
                return "ok"
            except patient_credit.CreditError as exc:
                db.session.rollback()
                return str(exc)

    replies, errors = _together(2, work)
    assert errors == []
    assert _held(till) >= 0
    spent = sum(_paid(till, b)[0] for b in till["ids"]["bills"])
    assert spent == 100


# ------------------------------------------------------------- the till ----
def test_two_cashiers_collecting_one_bill_at_once_never_pay_it_twice(till, slow_collect):
    bill = till["ids"]["bills"][0]
    desks = [till["sign_in"](f"cash{i}") for i in range(2)]

    def pay(i):
        return desks[i].post(f"/finance/invoices/{bill}/payment",
                             data={"amount": "100", "method": "instapay"})

    replies, errors = _together(2, pay)
    assert errors == []
    paid, owed = _paid(till, bill)
    assert (paid, owed) == (100, 0)


# ------------------------------------------------------------ the ledger ---
def test_one_document_posted_twice_at_once_is_one_entry(till, monkeypatch):
    from app.models import JournalEntry
    from app.utils import accounting

    def work(_i):
        with till["app"].app_context():
            return accounting.post_entry(
                "manual_test", 77, "مرة واحدة",
                [("1010", 50, 0, "x"), ("1030", 0, 50, "x")]) is not None

    # Hold the gap between «was it posted?» and the write.
    from sqlalchemy.orm import Query

    original = Query.first

    def first(self):
        answer = original(self)
        if self.column_descriptions and \
                self.column_descriptions[0].get("entity") is JournalEntry:
            _time.sleep(PAUSE)
        return answer

    monkeypatch.setattr(Query, "first", first)
    replies, errors = _together(2, work)
    assert errors == []
    with till["app"].app_context():
        assert JournalEntry.query.filter_by(source_type="manual_test",
                                            source_id=77).count() == 1


# ------------------------------------------------------------- refunds -----
def _settled(till, bill_id):
    """Bill ``bill_id`` paid in full (100) by InstaPay."""
    from app.models import Invoice, Payment

    with till["app"].app_context():
        db = till["db"]
        bill = db.session.get(Invoice, bill_id)
        bill.payments.append(Payment(amount=100, method="instapay", kind="payment"))
        bill.recalc_status()
        db.session.commit()


@pytest.fixture()
def slow_refund(monkeypatch):
    """Hold open «how much was paid?» → «write the refund»."""
    from app.utils import refunds

    real = refunds.scope_of

    def scope_of(*args, **kwargs):
        answer = real(*args, **kwargs)
        _time.sleep(PAUSE)
        return answer

    monkeypatch.setattr(refunds, "scope_of", scope_of)


def test_two_refunds_of_one_bill_at_once_give_back_what_was_paid_once(till, slow_refund):
    bill = till["ids"]["bills"][0]
    _settled(till, bill)
    desks = [till["sign_in"](f"cash{i}") for i in range(2)]

    def refund(i):
        return desks[i].post(f"/finance/invoices/{bill}/refund",
                             data={"amount": "100", "method": "instapay"})

    replies, errors = _together(2, refund)
    assert errors == []
    from app.models import Invoice

    with till["app"].app_context():
        row = till["db"].session.get(Invoice, bill)
        assert round(row.refunded, 2) == 100
        assert round(row.paid, 2) == 0


def test_one_refund_request_approved_twice_at_once_is_one_refund(till, slow_refund):
    from app.models import Invoice, RefundRequest

    bill = till["ids"]["bills"][0]
    _settled(till, bill)
    with till["app"].app_context():
        req = RefundRequest(invoice_id=bill, amount=60, method="instapay",
                            reason="اختبار")
        till["db"].session.add(req)
        till["db"].session.commit()
        req_id = req.id
    desks = [till["sign_in"](f"cash{i}") for i in range(2)]

    def approve(i):
        return desks[i].post(f"/finance/refund-requests/{req_id}/decide",
                             data={"decision": "approve"})

    replies, errors = _together(2, approve)
    assert errors == []
    with till["app"].app_context():
        row = till["db"].session.get(Invoice, bill)
        assert round(row.refunded, 2) == 60


# ------------------------------------------- ف-٢: the rest of «ask, then write» --
def test_one_supplier_instalment_paid_twice_at_once_is_paid_once(till, monkeypatch):
    from app.models import (StoreDocument, Supplier, SupplierInstallment,
                            SupplierPayment)
    from app.utils import payables

    with till["app"].app_context():
        db = till["db"]
        supplier = Supplier(name="مورد")
        db.session.add(supplier)
        db.session.flush()
        doc = StoreDocument(doc_number="GRN-1", kind="grn", supplier_id=supplier.id,
                            payment_terms="installments")
        db.session.add(doc)
        db.session.flush()
        inst = SupplierInstallment(document_id=doc.id, seq=1, due_date=date.today(),
                                   amount=500)
        db.session.add(inst)
        db.session.commit()
        inst_id = inst.id

    real = payables.record_payment

    def slow(*args, **kwargs):
        _time.sleep(PAUSE)
        return real(*args, **kwargs)

    monkeypatch.setattr(payables, "record_payment", slow)

    def work(_i):
        with till["app"].app_context():
            row = till["db"].session.get(SupplierInstallment, inst_id)
            return payables.pay_installment(row) is not None

    replies, errors = _together(2, work)
    assert errors == []
    with till["app"].app_context():
        assert SupplierPayment.query.count() == 1
        assert sorted(replies) == [False, True]


def test_a_bills_surplus_moved_to_the_account_twice_at_once_is_moved_once(till, monkeypatch):
    from app.models import Invoice, Payment
    from app.utils import approvals

    bill = till["ids"]["bills"][0]
    with till["app"].app_context():
        db = till["db"]
        row = db.session.get(Invoice, bill)
        row.payments.append(Payment(amount=160, method="instapay", kind="payment"))
        db.session.commit()

    from app.models import invoice as invoice_model

    original = invoice_model.Invoice.paid

    def slow_paid(self):
        answer = original.fget(self)
        _time.sleep(PAUSE)
        return answer

    monkeypatch.setattr(invoice_model.Invoice, "paid", property(slow_paid))

    def work(_i):
        with till["app"].app_context():
            db = till["db"]
            amount = approvals.credit_surplus(db.session.get(Invoice, bill), None, "اختبار")
            db.session.commit()
            return amount

    replies, errors = _together(2, work)
    assert errors == []
    assert sorted(replies) == [0, 60]
    assert _held(till) == 160


def test_one_vaccine_settlement_settled_twice_at_once_is_settled_once(till, monkeypatch):
    from app.blueprints.finance import routes
    from app.models import Invoice, Vaccine, VaccineBrand, VaccineSettlement

    bill = till["ids"]["bills"][0]
    with till["app"].app_context():
        db = till["db"]
        vac = Vaccine(code="X", name_ar="لقاح", is_mandatory=False)
        db.session.add(vac)
        db.session.flush()
        brand = VaccineBrand(vaccine_id=vac.id, name="ماركة", price=100)
        db.session.add(brand)
        db.session.flush()
        row = VaccineSettlement(patient_id=till["ids"]["child"], invoice_id=bill,
                                item_id=db.session.get(Invoice, bill).items[0].id,
                                billed_brand_id=brand.id, amount=100)
        db.session.add(row)
        db.session.commit()
        sid = row.id

    applied = []

    def apply_settlement(s, lang="ar", user_id=None):
        applied.append(s.id)
        _time.sleep(PAUSE)
        s.status = "done"
        return till["db"].session.get(Invoice, s.invoice_id)

    monkeypatch.setattr(routes, "apply_settlement", apply_settlement)
    desks = [till["sign_in"](f"cash{i}") for i in range(2)]

    def settle(i):
        return desks[i].post(f"/finance/vaccine-settlement/{sid}")

    replies, errors = _together(2, settle)
    assert errors == []
    assert applied == [sid]


# ------------------------------------------------ «back to» stays at home --
def test_a_back_address_from_a_form_never_leaves_the_program(till):
    from app.models import StoreDocument, Supplier, SupplierInstallment

    with till["app"].app_context():
        db = till["db"]
        supplier = Supplier(name="مورد")
        db.session.add(supplier)
        db.session.flush()
        doc = StoreDocument(doc_number="GRN-2", kind="grn", supplier_id=supplier.id)
        db.session.add(doc)
        db.session.flush()
        ids = []
        for n in range(3):
            inst = SupplierInstallment(document_id=doc.id, seq=n + 1,
                                       due_date=date.today(), amount=10)
            db.session.add(inst)
            db.session.flush()
            ids.append(inst.id)
        db.session.commit()
    desk = till["sign_in"]("cash0")
    for inst_id, where in zip(ids, ("https://elsewhere.example/x", "//elsewhere.example",
                                    "/\\elsewhere.example")):
        got = desk.post(f"/finance/installments/{inst_id}/pay", data={"next": where})
        assert "elsewhere" not in got.headers["Location"]
    got = desk.post(f"/finance/installments/{ids[0]}/pay", data={"next": "/finance/"})
    assert got.headers["Location"].endswith("/finance/")


def test_two_withdrawals_that_do_not_both_fit_never_overdraw_a_till(till, monkeypatch):
    from app.models import CashAccount, CashMovement
    from app.utils import treasury

    with till["app"].app_context():
        db = till["db"]
        drawer = CashAccount(name="خزنة تجربة", code="1099", kind="cash", opening_balance=100)
        db.session.add(drawer)
        db.session.commit()
        drawer_id = drawer.id
    real = treasury.account_balance

    def slow(account, upto=None):
        answer = real(account, upto)
        _time.sleep(PAUSE)
        return answer

    monkeypatch.setattr(treasury, "account_balance", slow)

    def work(_i):
        with till["app"].app_context():
            db = till["db"]
            try:
                treasury.record_movement("withdraw", db.session.get(CashAccount, drawer_id), 70)
                return "ok"
            except treasury.MovementError as exc:
                db.session.rollback()
                return str(exc)

    replies, errors = _together(2, work)
    assert errors == []
    assert sorted(replies) == ["insufficient", "ok"]
    with till["app"].app_context():
        assert CashMovement.query.count() == 1
        assert real(till["db"].session.get(CashAccount, drawer_id)) == 30


def test_two_dental_deposits_on_one_plan_at_once_never_overpay_it(till, monkeypatch):
    from types import SimpleNamespace

    from app.models import Invoice
    from app.utils import dental_money

    bill = till["ids"]["bills"][0]
    monkeypatch.setattr(dental_money, "_require_module", lambda: None)
    from app.models import invoice as invoice_model

    original = invoice_model.Invoice.balance

    def slow_balance(self):
        answer = original.fget(self)
        _time.sleep(PAUSE)
        return answer

    monkeypatch.setattr(invoice_model.Invoice, "balance", property(slow_balance))

    def work(_i):
        with till["app"].app_context():
            db = till["db"]
            plan = SimpleNamespace(invoice_id=bill, invoice=db.session.get(Invoice, bill))
            try:
                dental_money.take_deposit(plan, 100, method="instapay")
                db.session.commit()
                return "ok"
            except dental_money.DentalMoneyError as exc:
                db.session.rollback()
                return str(exc)

    replies, errors = _together(2, work)
    assert errors == []
    assert sorted(replies) == ["ok", "over_balance"]
    assert _paid(till, bill) == (100, 0)


# --------------------------------------- ف-٣: the same form, the same instant --
def test_one_payment_form_sent_twice_at_the_same_instant_is_taken_once(till, slow_collect):
    bill = till["ids"]["bills"][0]
    desks = [till["sign_in"](f"cash{i}") for i in range(2)]

    def pay(i):
        return desks[i].post(f"/finance/invoices/{bill}/payment",
                             data={"amount": "40", "method": "instapay",
                                   "form_key": "d" * 32})

    replies, errors = _together(2, pay)
    assert errors == []
    assert _paid(till, bill) == (40, 60)
