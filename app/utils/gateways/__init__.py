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
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

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
    ``paid``, ``failed``, ``expired`` or ``pending``."""
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
        if gateway is not None and gateway.configured():
            out.append(gateway)
    return out
