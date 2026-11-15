"""Paymob, Fawry and Kashier — written from their own documents, and locked.

``BOOKING_APPROVAL_PLAN.md`` م٤. Each gateway file was written from the
gateway's official developer pages (listed on the class as ``sources``), and
the checks here hold it to those pages, not to anybody's memory of them:

* **Kashier** publishes a worked signature: a ``data`` object, the key
  ``11111`` and the digest. The file reproduces that digest exactly.
* **Paymob** publishes a sample callback and the exact string its twenty keys
  join into. The file builds exactly that string from the sample.
* **Fawry** publishes its recipes but no key with a digest, so its checks are
  the recipe itself — and its lock says why.

And each is **locked until somebody has run a payment round on that
gateway's test account**: switched on and filled in, it is still not offered,
and no link can be made with it.
"""
import hashlib
import hmac
import json
import os
import sys
from datetime import date
from urllib.parse import urlparse

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402
from werkzeug.test import EnvironBuilder  # noqa: E402
from werkzeug.wrappers import Request  # noqa: E402

# ------------------------------------------------- from the documents ----
#: developers.kashier.io/docs/webhooks — «How the signature is computed,
#: step by step».
KASHIER_DATA = {
    "amount": 1,
    "channel": "online | e-commerce",
    "currency": "EGP",
    "kashierOrderId": "9ad06b17-755b-4e21-9774-aff3e2726ac9",
    "merchantOrderId": "1653481557813",
    "method": "card",
    "orderReference": "TEST-ORD-38855",
    "status": "SUCCESS",
    "transactionId": "TX-249893963",
    "transactionResponseCode": "00",
    "signatureKeys": [
        "amount", "channel", "currency", "kashierOrderId", "merchantOrderId",
        "method", "orderReference", "status", "transactionId",
        "transactionResponseCode",
    ],
}
KASHIER_STRING = (
    "amount=1&channel=online%20%7C%20e-commerce&currency=EGP"
    "&kashierOrderId=9ad06b17-755b-4e21-9774-aff3e2726ac9"
    "&merchantOrderId=1653481557813&method=card&orderReference=TEST-ORD-38855"
    "&status=SUCCESS&transactionId=TX-249893963&transactionResponseCode=00")
KASHIER_KEY = "11111"
KASHIER_DIGEST = ("9610477b2255b2a8ef84fd89adfaa5f1305ff9c20324205851890f1ea03"
                  "109f4")

#: developers.paymob.com — «HMAC Transaction Callback»: the sample processed
#: callback (the keys the HMAC reads), and the string it joins into.
PAYMOB_OBJ = {
    "id": 192036465, "pending": False, "amount_cents": 100000,
    "success": True, "is_auth": False, "is_capture": False,
    "is_standalone_payment": True, "is_voided": False, "is_refunded": False,
    "is_3d_secure": True, "integration_id": 4097558,
    "has_parent_transaction": False,
    "created_at": "2024-06-13T11:33:44.592345", "currency": "EGP",
    "error_occured": False, "owner": 302852,
    "order": {"id": 217503754, "merchant_order_id": None},
    "source_data": {"pan": "2346", "type": "card", "tenure": None,
                    "sub_type": "MasterCard"},
}
PAYMOB_STRING = ("1000002024-06-13T11:33:44.592345EGPfalsefalse192036465"
                 "4097558truefalsefalsefalsetruefalse217503754302852false"
                 "2346MasterCardcardtrue")


def _request(body, headers=None, query=""):
    raw = json.dumps(body).encode()
    return Request(EnvironBuilder(path="/x" + query, method="POST", data=raw,
                                  headers=dict({"Content-Type":
                                                "application/json"},
                                               **(headers or {}))
                                  ).get_environ())


# ---------------------------------------------------------- the lock ----
def test_every_gateway_has_a_file_and_says_where_it_came_from():
    from app.utils import gateways

    official = {"paymob": "developers.paymob.com",
                "fawry": "developers.fawrystaging.com",
                "kashier": "developers.kashier.io"}
    files = gateways.available()
    assert set(official) <= set(files)
    for name, host in official.items():
        cls = files[name]
        assert cls.sources, name
        assert {urlparse(u).hostname for u in cls.sources} == {host}, name


def test_every_gateway_is_locked_until_its_test_account(clinic):
    """Switched on and filled in, and still not offered: nobody has made a
    payment go round on any of the three test accounts yet."""
    from app.extensions import db
    from app.models import Setting
    from app.utils import gateways

    with clinic["app"].app_context():
        Setting.set("pay_gateways", "paymob,fawry,kashier")
        for name, cls in gateways.available().items():
            for key, _secret in cls.fields:
                Setting.set(f"pay_{name}_{key}",
                            {"mode": "test", "integration_id": "158"}.get(
                                key, "x"))
        db.session.commit()
        for name in ("paymob", "fawry", "kashier"):
            gateway = gateways.get(name)
            assert gateway.configured(), name
            assert gateways.locked(gateway), name
        assert gateways.enabled() == []


# ---------------------------------------------------------- Kashier ----
def test_kashier_reproduces_its_documented_signature():
    from app.utils.gateways import kashier

    assert kashier.signed_string(KASHIER_DATA) == KASHIER_STRING
    assert hmac.new(KASHIER_KEY.encode(), KASHIER_STRING.encode(),
                    hashlib.sha256).hexdigest() == KASHIER_DIGEST


def _kashier(**settings):
    from app.utils.gateways.kashier import Kashier

    return Kashier(dict({"merchant_id": "MID-1-1", "mode": "test",
                         "secret_key": "sk", "api_key": KASHIER_KEY},
                        **settings))


def test_kashier_believes_its_documented_webhook_and_nothing_else():
    gateway = _kashier()
    body = {"event": "pay", "data": dict(KASHIER_DATA)}
    event = gateway.prove(_request(body,
                                   {"x-kashier-signature": KASHIER_DIGEST}))
    assert (event.reference, event.status, event.amount, event.currency,
            event.provider_ref) == ("1653481557813", "paid", 1.0, "EGP",
                                    "TX-249893963")
    # Upper-case hex is the same digest.
    assert gateway.prove(_request(
        body, {"x-kashier-signature": KASHIER_DIGEST.upper()})) is not None
    # Not signed, signed with the other key, or one figure changed: refused.
    assert gateway.prove(_request(body)) is None
    assert _kashier(api_key="sk").prove(_request(
        body, {"x-kashier-signature": KASHIER_DIGEST})) is None
    forged = {"event": "pay", "data": dict(KASHIER_DATA, amount=1000)}
    assert gateway.prove(_request(
        forged, {"x-kashier-signature": KASHIER_DIGEST})) is None


def _kashier_signed(data, key=KASHIER_KEY):
    from app.utils.gateways import kashier

    return hmac.new(key.encode(), kashier.signed_string(data).encode(),
                    hashlib.sha256).hexdigest()


def test_kashier_reads_status_not_event():
    """A failed payment arrives as ``event: "pay"`` too — the documentation's
    warning. And a refund is noted, never a payment."""
    gateway = _kashier()
    for event, status, ours in (("pay", "FAILURE", "failed"),
                                ("pay", "PENDING", "pending"),
                                ("refund", "SUCCESS", "refunded")):
        data = dict(KASHIER_DATA, status=status)
        got = gateway.prove(_request({"event": event, "data": data},
                                     {"x-kashier-signature":
                                      _kashier_signed(data)}))
        assert got.status == ours, (event, status)


def test_kashier_asks_for_a_session_the_documented_way(monkeypatch):
    from app.utils.gateways import kashier

    sent = []

    def fake(url, body, headers=None):
        sent.append((url, body, headers))
        return {"_id": "67adc07584f10c00121f6739", "status": "CREATED",
                "sessionUrl": "https://payments.kashier.io/session/"
                              "67adc07584f10c00121f6739?mode=test"}

    monkeypatch.setattr(kashier, "post_json", fake)

    class Row:
        reference, amount, currency = "PP0A1B2C3D4E5F", 300.0, "EGP"

    got = _kashier().checkout(Row(), "https://c.example/back",
                              "https://c.example/notify")
    [(url, body, headers)] = sent
    assert url == "https://test-api.kashier.io/v3/payment/sessions"
    assert headers == {"Authorization": "sk", "api-key": KASHIER_KEY}
    assert (body["amount"], body["currency"], body["order"],
            body["merchantId"], body["merchantRedirect"],
            body["serverWebhook"]) == ("300.00", "EGP", "PP0A1B2C3D4E5F",
                                       "MID-1-1", "https://c.example/back",
                                       "https://c.example/notify")
    for required in ("expireAt", "maxFailureAttempts", "type", "display",
                     "customer"):
        assert required in body
    assert got.url.startswith("https://payments.kashier.io/session/")
    assert got.provider_ref == "67adc07584f10c00121f6739"
    # Live is its own host.
    _kashier(mode="live").checkout(Row(), "b", "n")
    assert sent[-1][0] == "https://api.kashier.io/v3/payment/sessions"


# ----------------------------------------------------------- Paymob ----
def test_paymob_builds_its_documented_string_from_its_sample():
    from app.utils.gateways import paymob

    assert paymob.signed_string(PAYMOB_OBJ) == PAYMOB_STRING


def _paymob():
    from app.utils.gateways.paymob import Paymob

    return Paymob({"public_key": "egy_pk_test_1", "integration_id": "158",
                   "secret_key": "sk_test_1", "hmac_secret": "HMAC-SECRET"})


def _paymob_body(**obj):
    o = json.loads(json.dumps(PAYMOB_OBJ))
    o["order"]["merchant_order_id"] = "PP0A1B2C3D4E5F"
    o.update(obj)
    return {"type": "TRANSACTION", "obj": o}


def _paymob_hmac(body, secret="HMAC-SECRET"):
    from app.utils.gateways import paymob

    return hmac.new(secret.encode(),
                    paymob.signed_string(body["obj"]).encode(),
                    hashlib.sha512).hexdigest()


def test_paymob_believes_a_signed_callback_and_nothing_else():
    gateway = _paymob()
    body = _paymob_body()
    event = gateway.prove(_request(body, query="?hmac=" + _paymob_hmac(body)))
    # Piastres in the callback; pounds on the bill.
    assert (event.reference, event.status, event.amount, event.currency,
            event.provider_ref) == ("PP0A1B2C3D4E5F", "paid", 1000.0, "EGP",
                                    "192036465")
    # The hmac is the query parameter; anywhere else, or missing: refused.
    assert gateway.prove(_request(body)) is None
    assert gateway.prove(_request(body, {"hmac": _paymob_hmac(body)})) is None
    assert gateway.prove(_request(
        body, query="?hmac=" + _paymob_hmac(body, "other"))) is None
    forged = _paymob_body(amount_cents=1)
    assert gateway.prove(_request(
        forged, query="?hmac=" + _paymob_hmac(body))) is None
    # A card-token callback is not a payment.
    token = dict(body, type="TOKEN")
    assert gateway.prove(_request(
        token, query="?hmac=" + _paymob_hmac(body))) is None


def test_paymob_reads_its_flags():
    gateway = _paymob()
    for obj, ours in (({"success": False}, "failed"),
                      ({"pending": True, "success": False}, "pending"),
                      ({"is_refunded": True}, "refunded"),
                      ({"is_voided": True}, "refunded")):
        body = _paymob_body(**obj)
        got = gateway.prove(_request(body,
                                     query="?hmac=" + _paymob_hmac(body)))
        assert got.status == ours, obj


# ------------------------------------------------------------ Fawry ----
def _fawry():
    from app.utils.gateways.fawry import Fawry

    return Fawry({"merchant_code": "1tSa6uxz2nTwlaAmt38enA==", "mode": "test",
                  "secure_key": "SECURE"})


def _fawry_notice(**extra):
    data = {"requestId": "c72827d084ea4b88949d91dd2db4996e",
            "fawryRefNumber": "/850090916",
            "merchantRefNumber": "PP0A1B2C3D4E5F",
            "paymentAmount": 302.00, "orderAmount": 300.00,
            "fawryFees": 2.00, "orderStatus": "PAID",
            "paymentMethod": "PAYATFAWRY",
            "paymentRefrenceNumber": "369552233"}
    data.update(extra)
    text = (f"{data['fawryRefNumber']}{data['merchantRefNumber']}"
            f"{data['paymentAmount']:.2f}{data['orderAmount']:.2f}"
            f"{data['orderStatus']}{data['paymentMethod']}"
            f"{data.get('paymentRefrenceNumber') or ''}SECURE")
    data["messageSignature"] = hashlib.sha256(text.encode()).hexdigest()
    return data


def test_fawry_signs_its_charge_the_documented_way():
    from app.utils.gateways import fawry

    text = "1tSa6uxz2nTwlaAmt38enA==2312465464PayAtFawry580.55SECURE"
    assert fawry.charge_signature("1tSa6uxz2nTwlaAmt38enA==", "2312465464",
                                  580.55, "SECURE") == \
        hashlib.sha256(text.encode()).hexdigest()
    # Two decimals, always: 150 is "150.00".
    assert "150.00" in fawry.notification_string(
        {"fawryRefNumber": "1", "merchantRefNumber": "2",
         "paymentAmount": 150, "orderAmount": 150, "orderStatus": "PAID",
         "paymentMethod": "PAYATFAWRY"}, "K")


def test_fawry_believes_a_signed_notice_and_compares_the_bill_not_the_fees():
    gateway = _fawry()
    event = gateway.prove(_request(_fawry_notice()))
    # paymentAmount carries Fawry's fees; the bill is orderAmount.
    assert (event.reference, event.status, event.amount,
            event.provider_ref) == ("PP0A1B2C3D4E5F", "paid", 300.0,
                                    "/850090916")
    forged = _fawry_notice()
    forged["orderAmount"] = 3.00
    assert gateway.prove(_request(forged)) is None
    unsigned = _fawry_notice()
    del unsigned["messageSignature"]
    assert gateway.prove(_request(unsigned)) is None
    # Created (no payment reference yet) is still provable, and only pending.
    created = _fawry_notice(orderStatus="NEW", paymentRefrenceNumber=None)
    assert gateway.prove(_request(created)).status == "pending"
    for status, ours in (("EXPIRED", "expired"), ("CANCELED", "failed"),
                         ("REFUNDED", "refunded")):
        assert gateway.prove(_request(
            _fawry_notice(orderStatus=status))).status == ours


# ------------------------------------------- through the whole program ----
@pytest.fixture()
def kashier_bill(clinic, monkeypatch):
    """A 300 bill, Kashier switched on and filled in — and, for this test
    only, its lock lifted, to show what unlocking will do."""
    from app.extensions import db
    from app.models import Invoice, InvoiceItem, Patient, Setting
    from app.utils.gateways import kashier
    from app.utils.treasury import seed_accounts

    sessions = []

    def fake(url, body, headers=None):
        sessions.append(body)
        return {"_id": "S-1", "sessionUrl": "https://payments.kashier.io/"
                                            "session/S-1?mode=test"}

    monkeypatch.setattr(kashier, "post_json", fake)
    with clinic["app"].app_context():
        kid = db.session.get(Patient, clinic["ids"]["child"])
        kid.own_phone = "01001234567"
        inv = Invoice(invoice_number="INV-K1", patient_id=kid.id,
                      doctor_id=clinic["ids"]["doctor"],
                      invoice_date=date.today())
        db.session.add(inv)
        db.session.flush()
        db.session.add(InvoiceItem(invoice_id=inv.id, description="كشف",
                                   unit_price=300, quantity=1))
        seed_accounts()
        Setting.set("pay_gateways", "kashier")
        for key, value in (("merchant_id", "MID-1-1"), ("mode", "test"),
                           ("secret_key", "sk"), ("api_key", KASHIER_KEY)):
            Setting.set(f"pay_kashier_{key}", value)
        Setting.set("wa_public_base_url", "https://clinic.example/")
        db.session.commit()
        clinic["invoice"] = inv.id
    clinic["sessions"] = sessions
    return clinic


def _link(bill):
    return bill["sign_in"]("boss").post(
        f"/finance/invoices/{bill['invoice']}/pay-link",
        data={"provider": "kashier"}, follow_redirects=True)


def _online_rows(bill):
    from app.models import OnlinePayment

    with bill["app"].app_context():
        return [(r.reference, r.status, r.payment_id)
                for r in OnlinePayment.query]


def test_locked_kashier_makes_no_link(kashier_bill):
    _link(kashier_bill)
    assert _online_rows(kashier_bill) == []
    assert kashier_bill["sessions"] == []
    # And its webhook address is not there at all.
    resp = kashier_bill["app"].test_client().post(
        "/wa/webhook/pay/kashier", data=b"{}",
        headers={"Content-Type": "application/json"})
    assert resp.status_code == 404


def test_unlocked_kashier_goes_all_the_way_round(kashier_bill, monkeypatch):
    from app.extensions import db
    from app.models import Invoice
    from app.utils.gateways.kashier import Kashier

    monkeypatch.setattr(Kashier, "sandbox_checked", "test only")
    _link(kashier_bill)
    [(reference, status, payment_id)] = _online_rows(kashier_bill)
    assert (status, payment_id) == ("pending", None)
    [asked] = kashier_bill["sessions"]
    assert (asked["order"], asked["amount"]) == (reference, "300.00")
    assert asked["serverWebhook"] == "https://clinic.example/wa/webhook/pay/kashier"

    data = dict(KASHIER_DATA, merchantOrderId=reference, amount=300)
    client = kashier_bill["app"].test_client()
    for _twice in range(2):
        resp = client.post("/wa/webhook/pay/kashier",
                           data=json.dumps({"event": "pay", "data": data}),
                           headers={"Content-Type": "application/json",
                                    "x-kashier-signature":
                                    _kashier_signed(data)})
        assert resp.status_code == 200
    # Forged: refused before a field is read.
    assert client.post("/wa/webhook/pay/kashier",
                       data=json.dumps({"event": "pay", "data": data}),
                       headers={"Content-Type": "application/json",
                                "x-kashier-signature": "0" * 64}
                       ).status_code == 403
    [(_ref, status, payment_id)] = _online_rows(kashier_bill)
    assert status == "paid" and payment_id
    with kashier_bill["app"].app_context():
        inv = db.session.get(Invoice, kashier_bill["invoice"])
        assert inv.paid == 300 and inv.status == "paid"
        assert len(inv.payments) == 1
