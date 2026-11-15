"""Kashier — a payment page through a payment session.

Written from Kashier's own developer documentation, read on 15 November 2026:

* create a session: ``POST {base}/v3/payment/sessions`` with the merchant's
  **Secret Key** in ``Authorization`` (the raw value, not ``Bearer``) and the
  **Payment API Key** in ``api-key``. ``amount`` is a string in pounds
  (``"100.00"``); ``order`` is our reference, and Kashier refuses one it has
  seen before. The answer carries ``_id`` and the ``sessionUrl`` the family
  opens. Test and live are separate hosts: ``test-api.kashier.io`` and
  ``api.kashier.io``.
* the webhook: a JSON ``{"event": …, "data": {…}}``. ``data.status`` —
  ``SUCCESS``, ``FAILURE`` or ``PENDING`` — is the outcome, **not**
  ``event``: a failed payment arrives as ``event: "pay"`` too. ``data.amount``
  is the plain order amount, and ``data.merchantOrderId`` is our ``order``.
* the proof: sort ``data.signatureKeys``, take those keys from ``data``,
  URL-encode **only the values**, join as ``key=value&…``, HMAC-SHA256 with the
  **Payment API Key** (not the Secret Key), and compare with the
  ``x-kashier-signature`` header. ``data.hash`` is Kashier's own and is not to
  be checked. The documentation's worked example (key ``11111``) is
  reproduced exactly in ``tests/test_the_gateways_from_their_documents.py``.

What is **not** known until the test account: whether a session with no
customer email is accepted, and the exact shape of a webhook for a payment
that started as a wallet. Hence locked (``sandbox_checked``).
"""
import hashlib
import hmac
import json
from datetime import datetime, timedelta
from urllib.parse import quote

from app.utils.gateways import (Checkout, Event, Gateway, GatewayError,
                                post_json, register, two_places)

HOSTS = {"test": "https://test-api.kashier.io", "live": "https://api.kashier.io"}

#: How long a link stays payable. The session needs a time; this one is a
#: clinic's two days, not a number from Kashier.
LINK_HOURS = 48

#: Kashier's statuses, in ours.
STATUS = {"SUCCESS": "paid", "FAILURE": "failed", "PENDING": "pending"}

#: Events that are about money coming in. A refund or a void is noted only.
PAYING = ("pay", "capture")


def _value(value):
    """A value as Kashier's own samples write it into the signed string
    (JavaScript ``String()``): ``true`` not ``True``, ``100`` not ``100.0``."""
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def signed_string(data):
    """The string Kashier signs a webhook's ``data`` with, or ``None`` if a key
    it names is missing (then nothing about the message is believed)."""
    keys = data.get("signatureKeys")
    if not isinstance(keys, list) or not keys:
        return None
    parts = []
    for key in sorted(keys):
        if key not in data or data[key] is None or isinstance(
                data[key], (dict, list)):
            return None
        parts.append(f"{key}={quote(_value(data[key]), safe='')}")
    return "&".join(parts)


@register
class Kashier(Gateway):
    name = "kashier"
    label_ar = "كاشير"
    label_en = "Kashier"
    fields = (("merchant_id", False), ("mode", False),
              ("secret_key", True), ("api_key", True))
    sources = (
        "https://developers.kashier.io/docs/accept-payments/payment-sessions",
        "https://developers.kashier.io/docs/webhooks",
        "https://developers.kashier.io/docs/webhooks/payloads",
        "https://developers.kashier.io/openapi.yaml",
    )
    sandbox_checked = None

    def _mode(self):
        mode = (self.settings.get("mode") or "").strip().lower()
        return mode if mode in HOSTS else None

    def configured(self):
        return super().configured() and self._mode() is not None

    def checkout(self, payment, return_url, notify_url):
        expires = datetime.utcnow() + timedelta(hours=LINK_HOURS)
        body = {
            "expireAt": expires.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            "maxFailureAttempts": 3,
            "paymentType": "credit",
            "amount": two_places(payment.amount),
            "currency": payment.currency,
            "order": payment.reference,
            "merchantId": self.settings["merchant_id"].strip(),
            "merchantRedirect": return_url,
            "serverWebhook": notify_url,
            "display": "ar",
            "type": "one-time",
            "mode": self._mode(),
            "allowedMethods": "card,wallet",
            # Kashier asks for a customer; the reference is ours, so no name
            # or phone leaves the clinic that Kashier did not need.
            "customer": {"reference": payment.reference},
        }
        data = post_json(HOSTS[self._mode()] + "/v3/payment/sessions", body, {
            "Authorization": self.settings["secret_key"].strip(),
            "api-key": self.settings["api_key"].strip(),
        })
        url = data.get("sessionUrl")
        if not url:
            raise GatewayError(str(data.get("messages") or data)[:200])
        return Checkout(provider_ref=data.get("_id"), url=url,
                        expires_at=expires)

    def prove(self, request):
        try:
            body = json.loads(request.get_data() or b"{}")
        except ValueError:
            return None
        data = body.get("data") if isinstance(body, dict) else None
        if not isinstance(data, dict):
            return None
        text = signed_string(data)
        given = (request.headers.get("x-kashier-signature") or "").strip()
        if text is None or not given:
            return None
        wanted = hmac.new(self.settings["api_key"].strip().encode(),
                          text.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(given.lower(), wanted):
            return None

        reference = str(data.get("merchantOrderId") or "")
        if not reference:
            return None
        status = STATUS.get(str(data.get("status") or "").upper(), "pending")
        if body.get("event") not in PAYING:
            status = "refunded" if status == "paid" else "pending"
        return Event(reference=reference, status=status,
                     amount=_number(data.get("amount")),
                     currency=data.get("currency"),
                     provider_ref=data.get("transactionId"), raw=body)


def _number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
