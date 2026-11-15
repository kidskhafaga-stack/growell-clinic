"""Paymob — the Unified Checkout page, from an intention.

Written from Paymob's own developer documentation, read on 15 November 2026:

* create an intention: ``POST https://accept.paymob.com/v1/intention/`` with
  ``Authorization: Token <secret key>``. ``amount`` is **in piastres**, and the
  items' amounts must add up to it. ``payment_methods`` holds the integration
  id(s) — test or live, matching the key. ``billing_data`` needs
  ``first_name``, ``last_name`` and ``email``; a missing ``phone_number`` is a
  documented refusal. ``special_reference`` is ours, and comes back in the
  callback as ``order.merchant_order_id``. ``notification_url`` gets the
  processed callback; ``redirection_url`` is where the family's browser lands.
  The answer's ``client_secret`` opens the page:
  ``https://eg.checkout.paymob.com/?publicKey=…&clientSecret=…``.
* the processed callback is a POST of JSON (``{"type": "TRANSACTION",
  "obj": {…}}``); the landing page's query string is never believed.
* the proof: the values of twenty keys, in Paymob's fixed order, joined with
  nothing between them, HMAC-SHA512 with the **HMAC secret**, compared with
  the ``hmac`` query parameter. ``obj.id`` and ``order.id`` for the POST.
  Booleans as ``true``/``false``. The documentation's sample callback gives
  exactly the documented string — checked in
  ``tests/test_the_gateways_from_their_documents.py``.

What is **not** known until the test account: the digest itself (the
documentation does not publish the secret its sample was signed with), and
whether ``merchant_order_id`` comes back on a wallet payment as on a card.
Hence locked (``sandbox_checked``).
"""
import hashlib
import hmac
import json

from app.utils.gateways import (Checkout, Event, Gateway, GatewayError,
                                payer, piastres, post_json, register)

API = "https://accept.paymob.com/v1/intention/"
CHECKOUT = "https://eg.checkout.paymob.com/"

#: The keys, in the order Paymob lists them — "HMAC String Keys" on the
#: «HMAC Transaction Callback» page. For the POST callback.
HMAC_KEYS = (
    "amount_cents", "created_at", "currency", "error_occured",
    "has_parent_transaction", "obj.id", "integration_id", "is_3d_secure",
    "is_auth", "is_capture", "is_refunded", "is_standalone_payment",
    "is_voided", "order.id", "owner", "pending", "source_data.pan",
    "source_data.sub_type", "source_data.type", "success",
)


def _value(value):
    if value is True:
        return "true"
    if value is False:
        return "false"
    if value is None:
        return ""
    return str(value)


def signed_string(obj):
    """The string Paymob signs a processed callback's ``obj`` with, or
    ``None`` if a key it needs is missing."""
    parts = []
    for key in HMAC_KEYS:
        if key == "obj.id":
            value = obj.get("id")
        elif key == "order.id":
            value = (obj.get("order") or {}).get("id")
        elif "." in key:
            outer, inner = key.split(".", 1)
            holder = obj.get(outer)
            if not isinstance(holder, dict) or inner not in holder:
                return None
            value = holder[inner]
        else:
            if key not in obj:
                return None
            value = obj[key]
        if isinstance(value, (dict, list)):
            return None
        parts.append(_value(value))
    return "".join(parts)


@register
class Paymob(Gateway):
    name = "paymob"
    label_ar = "باي موب"
    label_en = "Paymob"
    fields = (("public_key", False), ("integration_id", False),
              ("secret_key", True), ("hmac_secret", True))
    sources = (
        "https://developers.paymob.com/paymob-docs/developers/intention-apis/create-intention",
        "https://developers.paymob.com/paymob-docs/developers/checkout/unified-checkout-redirection",
        "https://developers.paymob.com/paymob-docs/manage-callback/transaction-callbacks",
        "https://developers.paymob.com/paymob-docs/developers/webhook-callbacks-and-hmac/hmac/hmac-transaction-callback",
    )
    sandbox_checked = None

    def configured(self):
        return (super().configured()
                and self.settings["integration_id"].strip().isdigit())

    def checkout(self, payment, return_url, notify_url):
        who = payer(payment)
        if not who["email"]:
            # Paymob marks billing_data.email required. Sending a made-up
            # address would put a stranger's inbox on the family's receipt.
            raise GatewayError("Paymob needs the family's email "
                               "(ولي الأمر من غير إيميل)")
        if not who["phone"]:
            raise GatewayError("Paymob needs the family's phone")
        cents = piastres(payment.amount)
        body = {
            "amount": cents,
            "currency": payment.currency,
            "payment_methods": [int(self.settings["integration_id"].strip())],
            "items": [{"name": who["description"][:50], "amount": cents,
                       "quantity": 1}],
            "billing_data": {
                # A one-word name is both: Paymob requires the two.
                "first_name": who["first_name"][:50],
                "last_name": who["last_name"][:50] or who["first_name"][:50],
                "email": who["email"],
                "phone_number": who["phone"],
            },
            "special_reference": payment.reference,
            "notification_url": notify_url,
            "redirection_url": return_url,
        }
        data = post_json(API, body, {
            "Authorization": "Token " + self.settings["secret_key"].strip()})
        secret = data.get("client_secret")
        if not secret:
            raise GatewayError(str(data)[:200])
        from urllib.parse import urlencode

        url = CHECKOUT + "?" + urlencode({
            "publicKey": self.settings["public_key"].strip(),
            "clientSecret": secret})
        return Checkout(provider_ref=str(data.get("intention_order_id")
                                         or data.get("id") or ""),
                        url=url)

    def prove(self, request):
        given = (request.args.get("hmac") or "").strip().lower()
        if not given:
            return None
        try:
            body = json.loads(request.get_data() or b"{}")
        except ValueError:
            return None
        obj = body.get("obj") if isinstance(body, dict) else None
        if body.get("type") != "TRANSACTION" or not isinstance(obj, dict):
            return None
        text = signed_string(obj)
        if text is None:
            return None
        wanted = hmac.new(self.settings["hmac_secret"].strip().encode(),
                          text.encode(), hashlib.sha512).hexdigest()
        if not hmac.compare_digest(given, wanted):
            return None

        order = obj.get("order") or {}
        reference = str(order.get("merchant_order_id") or "")
        if not reference:
            return None
        if obj.get("is_refunded") or obj.get("is_voided"):
            status = "refunded"
        elif obj.get("pending"):
            status = "pending"
        elif obj.get("success") is True:
            status = "paid"
        else:
            status = "failed"
        cents = obj.get("amount_cents")
        amount = None if cents is None else float(cents) / 100
        return Event(reference=reference, status=status, amount=amount,
                     currency=obj.get("currency"),
                     provider_ref=str(obj.get("id") or ""), raw=body)
