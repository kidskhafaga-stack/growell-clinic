"""Paid through a gateway — believed only when the gateway proves it.

``BOOKING_APPROVAL_PLAN.md`` §3🅐, chosen for the clinic: Paymob, Fawry and
Kashier, beside reception recording money by hand, which stays the default.

The gateways themselves arrive one file at a time, each written from its own
documentation and checked against its own test environment. What is held
here is everything that is the same for all of them, and decides whether
money is counted — with a stand-in gateway whose callbacks are signed the
way a real one's are:

* with no gateway switched on, nothing on any screen changes;
* a link is a way to pay, not a payment — the bill is untouched until the
  gateway confirms;
* a confirmation that cannot be proved is refused before anything is read,
  and the page the family lands on afterwards decides nothing;
* a proved payment is written once, however many times it arrives, as an
  ordinary payment on the bill, in the gateway's own "under collection"
  account, posted to the ledger and written in the audit log;
* a proved payment of a different amount is not written on the bill — it is
  put in front of a person;
* a payment that arrives after a first attempt failed is still counted.
"""
import hashlib
import hmac
import json
import os
import sys
from datetime import date

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

SECRET = "test-signing-secret"


@pytest.fixture()
def stand_in(monkeypatch):
    """A gateway that behaves like a real one: it hands out a page to pay on
    and signs its callbacks with the merchant's secret."""
    from app.utils import gateways

    asked = []

    class StandIn(gateways.Gateway):
        name = "standin"
        label_ar = "بوابة تجريبية"
        label_en = "Stand-in gateway"
        fields = (("merchant", False), ("secret", True))
        refuse = None

        def checkout(self, payment, return_url, notify_url):
            if StandIn.refuse:
                raise gateways.GatewayError(StandIn.refuse)
            asked.append((payment.reference, payment.amount, return_url,
                          notify_url))
            return gateways.Checkout(
                provider_ref=f"T-{payment.reference}",
                url=f"https://pay.example/{payment.reference}")

        def prove(self, request):
            body = request.get_data()
            given = request.headers.get("X-Signature", "")
            wanted = hmac.new(self.settings["secret"].encode(), body,
                              hashlib.sha256).hexdigest()
            if not hmac.compare_digest(given, wanted):
                return None
            data = json.loads(body)
            return gateways.Event(reference=data["ref"], status=data["status"],
                                  amount=data.get("amount"),
                                  currency=data.get("currency"),
                                  provider_ref=data.get("txn"), raw=data)

    monkeypatch.setitem(gateways._REGISTRY, "standin", StandIn)
    return {"cls": StandIn, "asked": asked}


@pytest.fixture()
def bill(clinic, stand_in):
    """A 300 bill for a child with a phone, and the stand-in switched on."""
    from app.models import Invoice, InvoiceItem, Patient, Setting

    db = clinic["db"]
    with clinic["app"].app_context():
        kid = db.session.get(Patient, clinic["ids"]["child"])
        kid.own_phone = "01001234567"
        inv = Invoice(invoice_number="INV-G1", patient_id=kid.id,
                      doctor_id=clinic["ids"]["doctor"],
                      invoice_date=date.today())
        db.session.add(inv)
        db.session.flush()
        db.session.add(InvoiceItem(invoice_id=inv.id, description="كشف",
                                   unit_price=300, quantity=1))
        # The tills every clinic starts with — the bank among them.
        from app.utils.treasury import seed_accounts
        seed_accounts()
        Setting.set("pay_gateways", "standin")
        Setting.set("pay_standin_merchant", "M-1")
        Setting.set("pay_standin_secret", SECRET)
        Setting.set("wa_public_base_url", "https://clinic.example/")
        db.session.commit()
        clinic["invoice"] = inv.id
    clinic.update(stand_in)
    return clinic


def _make_link(bill, provider="standin"):
    return bill["sign_in"]("boss").post(
        f"/finance/invoices/{bill['invoice']}/pay-link",
        data={"provider": provider}, follow_redirects=True)


def _rows(bill):
    from app.models import OnlinePayment

    with bill["app"].app_context():
        return [(r.reference, r.status, r.amount, r.payment_id)
                for r in OnlinePayment.query.order_by(OnlinePayment.id)]


def _invoice(bill):
    from app.extensions import db
    from app.models import Invoice

    with bill["app"].app_context():
        inv = db.session.get(Invoice, bill["invoice"])
        return {"status": inv.status, "paid": inv.paid,
                "payments": [(p.amount, p.method, p.account.kind
                              if p.account else None,
                              p.account.settles_into.code
                              if p.account and p.account.settles_into else None)
                             for p in inv.payments]}


def _notify(bill, payload, secret=SECRET, name="standin"):
    body = json.dumps(payload).encode()
    signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return bill["app"].test_client().post(
        f"/wa/webhook/pay/{name}", data=body,
        headers={"X-Signature": signature,
                 "Content-Type": "application/json"})


def _paid(reference, amount=300.0, **extra):
    return dict({"ref": reference, "status": "paid", "amount": amount,
                 "currency": "EGP", "txn": "TX-9"}, **extra)


# ------------------------------------------------------------ switched off ----
def test_with_no_gateway_nothing_changes(clinic, stand_in):
    """The usual clinic: no gateway on, the bill looks as it always did, and
    no link can be made."""
    from app.models import Invoice, InvoiceItem

    db = clinic["db"]
    with clinic["app"].app_context():
        inv = Invoice(invoice_number="INV-0", patient_id=clinic["ids"]["child"],
                      invoice_date=date.today())
        db.session.add(inv)
        db.session.flush()
        db.session.add(InvoiceItem(invoice_id=inv.id, description="كشف",
                                   unit_price=100, quantity=1))
        db.session.commit()
        invoice_id = inv.id
    client = clinic["sign_in"]("boss")
    page = client.get(f"/finance/invoices/{invoice_id}").get_data(as_text=True)
    assert "data-online-pay" not in page
    client.post(f"/finance/invoices/{invoice_id}/pay-link",
                data={"provider": "standin"})
    from app.models import OnlinePayment

    with clinic["app"].app_context():
        assert OnlinePayment.query.count() == 0


def test_the_desk_cannot_choose_online_by_hand():
    """Only a gateway's proved confirmation writes an online payment."""
    from app.models import PAYMENT_METHODS
    from app.models.online_payment import ONLINE_METHOD

    assert ONLINE_METHOD not in PAYMENT_METHODS


# ------------------------------------------------------------ the link ----
def test_a_link_is_a_way_to_pay_not_a_payment(bill):
    page = _make_link(bill).get_data(as_text=True)
    [(reference, status, amount, payment_id)] = _rows(bill)
    assert (status, amount, payment_id) == ("pending", 300.0, None)
    assert _invoice(bill)["status"] == "unpaid"
    # The gateway was told where to confirm and where to send the family —
    # at the clinic's public address, never its office network.
    [(ref, asked_amount, back, notify)] = bill["asked"]
    assert (ref, asked_amount) == (reference, 300.0)
    assert back == f"https://clinic.example/wa/webhook/pay/standin/back/{reference}"
    assert notify == "https://clinic.example/wa/webhook/pay/standin"
    # The desk sees the link, and can send it to the family.
    assert f"https://pay.example/{reference}" in page
    assert "wa.me/201001234567" in page


def test_no_public_address_no_link(bill):
    from app.extensions import db
    from app.models import Setting

    with bill["app"].app_context():
        Setting.set("wa_public_base_url", "")
        db.session.commit()
    _make_link(bill)
    assert _rows(bill) == []


def test_a_gateway_that_refuses_is_kept_with_its_words(bill):
    bill["cls"].refuse = "merchant not active"
    try:
        page = _make_link(bill).get_data(as_text=True)
    finally:
        bill["cls"].refuse = None
    [(_ref, status, _amount, _pid)] = _rows(bill)
    assert status == "failed"
    assert "merchant not active" in page
    assert _invoice(bill)["status"] == "unpaid"


def test_a_settled_bill_gets_no_link(bill):
    first = _make_link(bill)
    reference = _rows(bill)[0][0]
    _notify(bill, _paid(reference))
    _make_link(bill)
    assert len(_rows(bill)) == 1
    assert first.status_code == 200


# ------------------------------------------------------------ proof ----
def test_an_unproved_confirmation_changes_nothing(bill):
    _make_link(bill)
    reference = _rows(bill)[0][0]
    reply = _notify(bill, _paid(reference), secret="somebody-else")
    assert reply.status_code == 403
    assert _rows(bill)[0][1] == "pending"
    assert _invoice(bill)["payments"] == []


def test_the_page_the_family_lands_on_decides_nothing(bill):
    """Anybody can open this address, with anything after it."""
    _make_link(bill)
    reference = _rows(bill)[0][0]
    page = bill["app"].test_client().get(
        f"/wa/webhook/pay/standin/back/{reference}?status=paid&success=true"
        f"&amount=300").get_data(as_text=True)
    assert 'data-pay-state="pending"' in page
    assert _invoice(bill)["payments"] == []


def test_a_gateway_that_is_not_switched_on_is_not_there(bill):
    from app.extensions import db
    from app.models import Setting

    _make_link(bill)
    reference = _rows(bill)[0][0]
    with bill["app"].app_context():
        Setting.set("pay_gateways", "")
        db.session.commit()
    assert _notify(bill, _paid(reference)).status_code == 404
    assert _invoice(bill)["payments"] == []


# ------------------------------------------------------------ paid ----
def test_a_proved_payment_is_on_the_bill_the_books_and_the_log(bill):
    from app.models import ActivityLog, JournalEntry

    _make_link(bill)
    reference = _rows(bill)[0][0]
    reply = _notify(bill, _paid(reference))
    assert reply.get_json()["outcome"] == "paid"
    state = _invoice(bill)
    assert state["status"] == "paid" and state["paid"] == 300.0
    # In the gateway's own account, under collection until it settles into
    # the bank — as card takings are.
    assert state["payments"] == [(300.0, "online", "clearing", "1020")]
    with bill["app"].app_context():
        [(ref, status, _amount, payment_id)] = _rows(bill)
        assert status == "paid" and payment_id is not None
        assert JournalEntry.query.filter_by(source_type="payment",
                                            source_id=payment_id).count() == 1
        assert ActivityLog.query.filter_by(
            action="online_payment.paid").count() == 1
    # And the family's page now says so.
    page = bill["app"].test_client().get(
        f"/wa/webhook/pay/standin/back/{reference}").get_data(as_text=True)
    assert 'data-pay-state="paid"' in page


def test_the_same_confirmation_twice_is_one_payment(bill):
    _make_link(bill)
    reference = _rows(bill)[0][0]
    assert _notify(bill, _paid(reference)).get_json()["outcome"] == "paid"
    assert _notify(bill, _paid(reference)).get_json()["outcome"] == "again"
    assert len(_invoice(bill)["payments"]) == 1


def test_two_gateways_settle_into_two_accounts_made_once(bill):
    """The account is made the first time money comes through it — and not
    again the second time."""
    from app.models import CashAccount

    _make_link(bill)
    with bill["app"].app_context():
        before = CashAccount.query.count()
    _notify(bill, _paid(_rows(bill)[0][0]))
    with bill["app"].app_context():
        assert CashAccount.query.count() == before + 1
        till = CashAccount.query.order_by(CashAccount.id.desc()).first()
        assert till.kind == "clearing" and "بوابة تجريبية" in till.name


def test_a_different_amount_is_put_in_front_of_a_person(bill):
    from app.models import ActivityLog

    _make_link(bill)
    reference = _rows(bill)[0][0]
    assert _notify(bill, _paid(reference, amount=30.0)) \
        .get_json()["outcome"] == "mismatch"
    assert _rows(bill)[0][1] == "mismatch"
    assert _invoice(bill)["payments"] == []
    with bill["app"].app_context():
        assert ActivityLog.query.filter_by(
            action="online_payment.mismatch").count() == 1
    page = bill["sign_in"]("boss").get(
        f"/finance/invoices/{bill['invoice']}").get_data(as_text=True)
    assert 'data-online-status="mismatch"' in page


def test_a_different_currency_is_a_different_amount(bill):
    _make_link(bill)
    reference = _rows(bill)[0][0]
    _notify(bill, _paid(reference, currency="USD"))
    assert _rows(bill)[0][1] == "mismatch"
    assert _invoice(bill)["payments"] == []


def test_paid_after_a_first_attempt_failed_is_still_counted(bill):
    """A card refused, then a second card on the same link: the money
    arrived, and a bill still owing it would be the worse mistake."""
    _make_link(bill)
    reference = _rows(bill)[0][0]
    failed = dict(_paid(reference), status="failed")
    assert _notify(bill, failed).get_json()["outcome"] == "closed"
    assert _rows(bill)[0][1] == "failed"
    assert _notify(bill, _paid(reference)).get_json()["outcome"] == "paid"
    assert _invoice(bill)["status"] == "paid"


def test_a_reference_the_gateway_never_had_is_nobodys(bill):
    assert _notify(bill, _paid("PPNOTOURS")).get_json()["outcome"] == "unknown"
    assert _invoice(bill)["payments"] == []


def test_a_reference_from_another_gateway_is_not_this_ones(bill, monkeypatch):
    """A proved message settles only what was opened with the same
    gateway."""
    from app.extensions import db
    from app.models import OnlinePayment

    _make_link(bill)
    with bill["app"].app_context():
        row = OnlinePayment.query.one()
        row.provider = "another"
        db.session.commit()
        reference = row.reference
    assert _notify(bill, _paid(reference)).get_json()["outcome"] == "unknown"
    assert _invoice(bill)["payments"] == []


def test_two_copies_arriving_together_are_one_payment(tmp_path, monkeypatch,
                                                       stand_in):
    """Gateways retry, and a retry can land while the first is still being
    written. The moment between "is it paid yet?" and writing it is held
    open here, so both copies are inside it together."""
    import threading
    import time as _time

    from app import create_app
    from app.extensions import db
    from app.models import Invoice, InvoiceItem, OnlinePayment, Patient, Setting
    from app.utils import gateways, online_pay

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/together.db")
    app = create_app("testing")
    with app.app_context():
        db.create_all()
        from app.utils.treasury import seed_accounts
        seed_accounts()
        kid = Patient(patient_number="T1", full_name="طفل", gender="male",
                      date_of_birth=date(2024, 1, 1), is_active=True)
        db.session.add(kid)
        db.session.flush()
        inv = Invoice(invoice_number="INV-T", patient_id=kid.id,
                      invoice_date=date.today())
        db.session.add(inv)
        db.session.flush()
        db.session.add(InvoiceItem(invoice_id=inv.id, description="كشف",
                                   unit_price=300, quantity=1))
        db.session.add(OnlinePayment(invoice_id=inv.id, provider="standin",
                                     reference="PPTOGETHER", amount=300.0,
                                     currency="EGP", status="pending"))
        Setting.set("pay_standin_secret", SECRET)
        db.session.commit()
        invoice_id = inv.id

    real = online_pay._same_money

    def slow(row, event):
        answer = real(row, event)
        _time.sleep(0.3)
        return answer

    monkeypatch.setattr(online_pay, "_same_money", slow)
    gate = threading.Barrier(2)
    outcomes = []

    def arrive():
        with app.app_context():
            gate.wait()
            event = gateways.Event(reference="PPTOGETHER", status="paid",
                                   amount=300.0, currency="EGP")
            try:
                outcomes.append(online_pay.receive(gateways.get("standin"),
                                                   event))
            except Exception as exc:                 # noqa: BLE001
                db.session.rollback()
                outcomes.append(type(exc).__name__)

    threads = [threading.Thread(target=arrive) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)
    with app.app_context():
        inv = db.session.get(Invoice, invoice_id)
        assert len(inv.payments) == 1, outcomes
        assert inv.paid == 300.0
    assert outcomes.count("paid") == 1


def test_one_account_per_gateway_however_many_payments(bill):
    from app.extensions import db
    from app.models import CashAccount, Invoice, InvoiceItem

    _make_link(bill)
    _notify(bill, _paid(_rows(bill)[0][0]))
    with bill["app"].app_context():
        after_first = CashAccount.query.count()
        inv = Invoice(invoice_number="INV-G2",
                      patient_id=bill["ids"]["child"],
                      invoice_date=date.today())
        db.session.add(inv)
        db.session.flush()
        db.session.add(InvoiceItem(invoice_id=inv.id, description="متابعة",
                                   unit_price=150, quantity=1))
        db.session.commit()
        second = inv.id
    bill["sign_in"]("boss").post(f"/finance/invoices/{second}/pay-link",
                                 data={"provider": "standin"})
    reference = _rows(bill)[-1][0]
    assert _notify(bill, _paid(reference, amount=150.0)) \
        .get_json()["outcome"] == "paid"
    with bill["app"].app_context():
        assert CashAccount.query.count() == after_first


def test_a_gateway_not_filled_in_is_not_on(bill):
    """Switched on but missing its secret: not offered, and its address is
    not there — a gateway that cannot prove its callbacks must not take any."""
    from app.extensions import db
    from app.models import Setting

    _make_link(bill)
    reference = _rows(bill)[0][0]
    with bill["app"].app_context():
        Setting.set("pay_standin_secret", "")
        db.session.commit()
    page = bill["sign_in"]("boss").get(
        f"/finance/invoices/{bill['invoice']}").get_data(as_text=True)
    assert "pay-link" not in page
    assert bill["app"].test_client().post(
        "/wa/webhook/pay/standin", data=b"{}").status_code == 404
    assert bill["app"].test_client().get(
        f"/wa/webhook/pay/standin/back/{reference}").status_code == 404
