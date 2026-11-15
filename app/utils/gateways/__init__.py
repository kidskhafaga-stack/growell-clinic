"""Payment gateways — one file each, and one shape for all of them.

Chosen for the clinic: Paymob, Fawry and Kashier, **beside** reception
recording money by hand, which stays exactly as it is and stays the default.
A clinic that switches nothing on has no gateway at all.

A gateway is two jobs and nothing else:

* **ask** — given a bill's amount and our reference, get the family something
  to pay with: a page to open, a code for a kiosk, or both;
* **prove** — given what arrived at our webhook, say whether this gateway
  really sent it, and if so what it says happened.

Everything after that — matching the reference, checking the amount, writing
the money on the invoice, the ledger, the audit — is the same for every
gateway and lives in :mod:`app.utils.online_pay`, written once. A gateway that
got the amount check or the "only once" rule slightly wrong would be a
gateway that could pay a bill twice; those rules are not a gateway's to keep.

**What a gateway file must not do** is invent its API. Endpoints, field
names and above all the signature a callback is proved with come from the
gateway's own documentation, checked against its test environment — never
from memory. A signature check that is almost right accepts forgeries.

**Each gateway stays locked until it has been run against that gateway's own
test account.** A file written from the documentation is not yet a file that
has taken a test payment: until somebody with a sandbox account has made one
go round — link, payment, signed callback, money on the bill — the gateway
carries ``sandbox_checked = None``, and :func:`enabled` does not offer it,
whatever the clinic switched on. Filling in the date is a code change, made
by the person who did the round trip, with what they saw.
"""
from dataclasses import dataclass, field
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

#: How long one call to a gateway may take before the desk is told it did
#: not answer.
TIMEOUT = 20

#: name -> gateway class. Filled by each gateway file as it is imported.
_REGISTRY = {}

#: Setting holding the gateways a clinic has switched on, comma-separated.
ENABLED_SETTING = "pay_gateways"


@dataclass
class Checkout:
    """What the gateway gave back when asked for a payment."""
    provider_ref: Optional[str] = None
    url: Optional[str] = None           # a page the family opens
    code: Optional[str] = None          # a code they pay at a kiosk
    expires_at: Optional[datetime] = None


@dataclass
class Event:
    """What a proved callback says. ``status`` is ours, not the gateway's:
    ``paid``, ``failed``, ``expired`` or ``pending`` — and ``refunded`` for a
    refund or a void, which :func:`app.utils.online_pay.receive` notes and
    does not act on (a refund is the desk's, as it always was)."""
    reference: str
    status: str
    amount: Optional[float] = None
    currency: Optional[str] = None
    provider_ref: Optional[str] = None
    raw: dict = field(default_factory=dict)


class GatewayError(Exception):
    """The gateway refused, or could not be reached. Said to the desk as it
    is; nothing is recorded as paid because of it."""


class Gateway:
    """The shape every gateway file fills in."""

    #: Short and permanent: stored on every row this gateway touches.
    name = ""
    label_ar = ""
    label_en = ""
    #: Settings this gateway needs: (key, is_secret). A secret is never
    #: shown back on a screen once saved.
    fields = ()
    #: The official pages this file was written from — kept with the code so
    #: whoever unlocks it checks the same pages, not their memory of them.
    sources = ()
    #: When, and by whom, a payment went all the way round on the gateway's
    #: own test account. ``None`` — the gateway is locked (see the module).
    sandbox_checked = None

    def __init__(self, settings):
        self.settings = settings

    def configured(self):
        """Every field it needs has a value."""
        return all((self.settings.get(key) or "").strip()
                   for key, _secret in self.fields)

    def checkout(self, payment, return_url, notify_url):
        """Ask the gateway for a way to pay ``payment``. Returns a
        :class:`Checkout`; raises :class:`GatewayError`."""
        raise NotImplementedError

    def prove(self, request):
        """The :class:`Event` a callback carries if this gateway really sent
        it, else ``None``. Nothing about an unproved request is believed."""
        raise NotImplementedError


def register(cls):
    """Make a gateway available. Used as a decorator by each gateway file."""
    if not cls.name:
        raise ValueError("a gateway needs a name")
    _REGISTRY[cls.name] = cls
    return cls


def available():
    """Every gateway this copy of the program has a file for."""
    return dict(_REGISTRY)


def _settings_for(cls):
    from app.models import Setting

    return {key: Setting.get(f"pay_{cls.name}_{key}", "") or ""
            for key, _secret in cls.fields}


def get(name):
    """The gateway called ``name`` with its settings, or ``None`` if there is
    no such file."""
    cls = _REGISTRY.get(name)
    return cls(_settings_for(cls)) if cls else None


def enabled():
    """The gateways this clinic switched on **and** filled in, in the order
    it listed them. Empty — the usual case — means reception records every
    payment by hand, exactly as it always has."""
    from app.models import Setting

    wanted = [n.strip() for n in
              (Setting.get(ENABLED_SETTING, "") or "").split(",") if n.strip()]
    out = []
    for name in wanted:
        gateway = get(name)
        if (gateway is not None and not locked(gateway)
                and gateway.configured()):
            out.append(gateway)
    return out


def locked(gateway):
    """True while the gateway has not been run against its own test account
    (``sandbox_checked``). A locked gateway is never offered, switched on or
    not."""
    return not getattr(gateway, "sandbox_checked", None)


# ------------------------------------------- shared by the gateway files ---
def two_places(value):
    """``value`` written with two decimals, the way the gateways sign money:
    ``580.55``, ``150.00``. Half-up, from the decimal digits as written — a
    float's binary noise must not move a signature by a piastre."""
    return str(Decimal(str(value)).quantize(Decimal("0.01"),
                                            rounding=ROUND_HALF_UP))


def piastres(value):
    """``value`` in the smallest unit (piastres, cents), as an integer."""
    return int(Decimal(str(value)).scaleb(2).quantize(Decimal("1"),
                                                      rounding=ROUND_HALF_UP))


def payer(payment):
    """Who is paying, as the gateways ask for it: a name, a phone, an email.

    The bill's child, and the family's primary guardian when there is one —
    the person the link is sent to. Nothing is made up: a field the clinic
    does not have stays empty, and a gateway that needs it says so to the
    desk (:class:`GatewayError`) rather than being sent a placeholder.
    """
    invoice = getattr(payment, "invoice", None)
    patient = getattr(invoice, "patient", None)
    guardian = getattr(patient, "primary_guardian", None) if patient else None
    who = guardian or patient
    name = ((getattr(who, "full_name_en", None) or getattr(who, "full_name", "")
             or "") if who else "").strip()
    phone = ((getattr(patient, "contact_phone", None) or "") if patient
             else "").strip()
    email = ((getattr(guardian, "email", None) or "") if guardian
             else "").strip()
    first, _, last = name.partition(" ")
    return {"name": name, "first_name": first, "last_name": last.strip(),
            "phone": phone, "email": email,
            "description": (f"{invoice.invoice_number}" if invoice is not None
                            else payment.reference)}


def post_json(url, body, headers=None):
    """POST ``body`` as JSON and return the decoded answer.

    One place for the network, so a test can stand in for every gateway's
    server at once. TLS is verified, always. A refusal, a timeout or an answer
    that is not JSON is a :class:`GatewayError` with the gateway's own words.
    """
    import requests

    try:
        resp = requests.post(url, json=body, headers=headers or {},
                             timeout=TIMEOUT)
    except requests.RequestException as exc:
        raise GatewayError(f"no answer: {exc.__class__.__name__}") from exc
    try:
        data = resp.json()
    except ValueError as exc:
        raise GatewayError(f"HTTP {resp.status_code}") from exc
    if resp.status_code >= 400:
        raise GatewayError(f"HTTP {resp.status_code}: {str(data)[:200]}")
    return data


# Each gateway file registers itself on import. Imported here, at the end,
# so that ``available()`` lists them wherever this package is used.
from app.utils.gateways import fawry, kashier, paymob  # noqa: E402,F401
