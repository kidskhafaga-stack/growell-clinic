"""Fawry — a reference number the family pays at any Fawry outlet.

Written from FawryPay's own developer guide, read on 15 November 2026
(``developers.fawrystaging.com/fawrypay``):

* the charge: ``POST {base}/ECommerceWeb/Fawry/payments/charge`` — staging
  ``https://atfawry.fawrystaging.com``, production ``https://www.atfawry.com``
  — with ``paymentMethod`` «PayAtFawry», ``amount`` with two decimals,
  ``merchantRefNum`` ours, and ``customerMobile``, ``customerEmail``,
  ``description``, ``language`` and ``chargeItems`` all marked required. The
  ``signature`` is SHA-256 of ``merchantCode + merchantRefNum +
  customerProfileId (if any) + paymentMethod + amount (two decimals) +
  secureKey``. The answer's ``referenceNumber`` is what the family pays with;
  ``statusCode`` 200 is success, anything else carries
  ``statusDescription``.
* the server notification V2: JSON POSTed to the merchant's callback URL —
  which Fawry says is set **with Fawry's operations team when the account is
  opened**, and can also be given per order as ``orderWebHookUrl``.
  ``orderStatus`` is NEW, PAID, CANCELED, REFUNDED, EXPIRED,
  PARTIAL_REFUNDED or FAILED. ``paymentAmount`` includes Fawry's fees;
  ``orderAmount`` is the bill without them — so ``orderAmount`` is what is
  compared with what we asked.
* the proof: ``messageSignature`` = SHA-256 of ``fawryRefNumber +
  merchantRefNumber + paymentAmount (two decimals) + orderAmount (two
  decimals) + orderStatus + paymentMethod + paymentRefrenceNumber (if any) +
  secureKey``. (``paymentRefrenceNumber`` is spelt that way in Fawry's own
  table.)

What is **not** known until the test account: Fawry's guide publishes no
key with its signatures, so neither recipe has been reproduced against a
digest of theirs; whether our ``PP…`` reference is accepted where the table
says «Integer»; and whether ``customerEmail`` is truly refused when empty.
Hence locked (``sandbox_checked``).
"""
import hashlib
import hmac
import json

from app.utils.gateways import (Checkout, Event, Gateway, GatewayError,
                                payer, post_json, register, two_places)

HOSTS = {"test": "https://atfawry.fawrystaging.com",
         "live": "https://www.atfawry.com"}
CHARGE = "/ECommerceWeb/Fawry/payments/charge"
METHOD = "PayAtFawry"

STATUS = {"PAID": "paid", "EXPIRED": "expired", "CANCELED": "failed",
          "FAILED": "failed", "NEW": "pending", "UNPAID": "pending",
          "REFUNDED": "refunded", "PARTIAL_REFUNDED": "refunded"}


def charge_signature(merchant_code, reference, amount, secure_key,
                     method=METHOD, profile_id=""):
    text = (f"{merchant_code}{reference}{profile_id or ''}{method}"
            f"{two_places(amount)}{secure_key}")
    return hashlib.sha256(text.encode()).hexdigest()


def notification_string(data, secure_key):
    """The string Fawry signs a V2 notification with, or ``None`` if a field
    it needs is missing."""
    try:
        return (f"{data['fawryRefNumber']}{data['merchantRefNumber']}"
                f"{two_places(data['paymentAmount'])}"
                f"{two_places(data['orderAmount'])}"
                f"{data['orderStatus']}{data['paymentMethod']}"
                f"{data.get('paymentRefrenceNumber') or ''}{secure_key}")
    except (KeyError, TypeError, ArithmeticError, ValueError):
        return None


@register
class Fawry(Gateway):
    name = "fawry"
    label_ar = "فوري"
    label_en = "Fawry"
    fields = (("merchant_code", False), ("mode", False),
              ("secure_key", True))
    sources = (
        "https://developers.fawrystaging.com/fawrypay/serverSideApis/paymentRequestUsingReferenceNumber",
        "https://developers.fawrystaging.com/fawrypay/checkingPaymentStatus/serverNotificationV2",
    )
    sandbox_checked = None

    def _mode(self):
        mode = (self.settings.get("mode") or "").strip().lower()
        return mode if mode in HOSTS else None

    def configured(self):
        return super().configured() and self._mode() is not None

    def checkout(self, payment, return_url, notify_url):
        who = payer(payment)
        if not who["phone"]:
            raise GatewayError("Fawry needs the family's mobile")
        if not who["email"]:
            raise GatewayError("Fawry needs the family's email "
                               "(ولي الأمر من غير إيميل)")
        code = self.settings["merchant_code"].strip()
        key = self.settings["secure_key"].strip()
        amount = two_places(payment.amount)
        body = {
            "merchantCode": code,
            "merchantRefNum": payment.reference,
            "customerName": who["name"],
            "customerMobile": who["phone"],
            "customerEmail": who["email"],
            "paymentMethod": METHOD,
            "amount": amount,
            "currencyCode": payment.currency,
            "language": "ar-eg",
            "description": who["description"],
            "chargeItems": [{"itemId": payment.reference,
                             "description": who["description"],
                             "price": amount, "quantity": "1"}],
            "orderWebHookUrl": notify_url,
            "signature": charge_signature(code, payment.reference, amount,
                                          key),
        }
        data = post_json(HOSTS[self._mode()] + CHARGE, body,
                         {"Accept": "application/json"})
        if str(data.get("statusCode")) != "200" or not data.get(
                "referenceNumber"):
            raise GatewayError(f"{data.get('statusCode')}: "
                               f"{data.get('statusDescription') or ''}"[:200])
        ref = str(data["referenceNumber"])
        return Checkout(provider_ref=ref, code=ref)

    def prove(self, request):
        try:
            data = json.loads(request.get_data() or b"{}")
        except ValueError:
            return None
        if not isinstance(data, dict):
            return None
        given = str(data.get("messageSignature") or "").strip().lower()
        text = notification_string(data,
                                   self.settings["secure_key"].strip())
        if not given or text is None:
            return None
        wanted = hashlib.sha256(text.encode()).hexdigest()
        if not hmac.compare_digest(given, wanted):
            return None

        reference = str(data.get("merchantRefNumber") or "")
        if not reference:
            return None
        status = STATUS.get(str(data.get("orderStatus") or "").upper(),
                            "pending")
        try:
            amount = float(data.get("orderAmount"))
        except (TypeError, ValueError):
            amount = None
        return Event(reference=reference, status=status, amount=amount,
                     currency=data.get("currency"),
                     provider_ref=str(data.get("fawryRefNumber") or ""),
                     raw=data)
