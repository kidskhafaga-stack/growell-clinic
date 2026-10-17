"""The channels a family can reach the clinic on, and which ones this clinic
uses (``CONNECTHUB_PLAN.md``).

The program is sold to many clinics and hospitals, and no two have the same
accounts: one has WhatsApp and a Facebook page, another Instagram and a
switchboard, a third only a phone. So:

* **every channel is listed here once**, with what it can do;
* **each clinic ticks the ones it uses** (``channels_enabled``) — the rest
  stay out of its forms;
* **a channel with no direct connection still counts.** Its questions are
  written down by hand with that channel as their source, so "which channel
  brings us bookings" has an answer from the first day, before any
  connection exists;
* a direct connection is a separate fact (``connection``) and is honest about
  itself: WhatsApp is connected through the clinic's own settings; the rest
  say they are entered by hand until their adapter is built from the
  platform's official documentation.

**The public request page** is a channel too, but a door onto the open
internet, so it is off until somebody who may change the setup opens it
(``booking_page``).
"""
import re

from app.models import Setting

#: key → icon, the identity kind its people are reached by, and whether a
#: direct connection exists in this program yet. Order is the order shown.
CHANNELS = {
    "whatsapp": {"icon": "bi-whatsapp", "identity": "phone", "direct": True},
    "messenger": {"icon": "bi-messenger", "identity": "messenger",
                  "direct": False},
    "instagram": {"icon": "bi-instagram", "identity": "instagram",
                  "direct": False},
    "tiktok": {"icon": "bi-tiktok", "identity": "tiktok", "direct": False},
    "email": {"icon": "bi-envelope", "identity": "email", "direct": False},
    "phone": {"icon": "bi-telephone", "identity": "phone", "direct": False},
    "walk_in": {"icon": "bi-person-walking", "identity": "phone",
                "direct": False},
    "page": {"icon": "bi-globe2", "identity": "phone", "direct": True},
}

#: What a clinic that has said nothing uses: the phone, the desk, WhatsApp.
DEFAULT_ENABLED = ("whatsapp", "phone", "walk_in")

#: Setting keys.
ENABLED_KEY = "channels_enabled"
PAGE_KEY = "booking_page"

#: What a campaign tag may contain — it arrives in a public URL.
_TAG = re.compile(r"[^A-Za-z0-9_.:\-]+")
TAG_MAX = 80


def enabled():
    """The channels this clinic uses, in the registry's order. The request
    page is in the list exactly when it is open."""
    raw = Setting.get(ENABLED_KEY)
    chosen = (set(DEFAULT_ENABLED) if raw is None
              else {k.strip() for k in raw.split(",") if k.strip()})
    chosen.discard("page")
    if page_open():
        chosen.add("page")
    return [k for k in CHANNELS if k in chosen]


def set_enabled(keys):
    """Save the clinic's choice; unknown keys are dropped. The request page
    is opened and closed on its own (``set_page``)."""
    keep = [k for k in CHANNELS if k in set(keys or ()) and k != "page"]
    Setting.set(ENABLED_KEY, ",".join(keep))
    return keep


def page_open():
    return (Setting.get(PAGE_KEY) or "") == "on"


def set_page(on):
    Setting.set(PAGE_KEY, "on" if on else "off")


def connection(key):
    """How this channel reaches the program here: ``connected`` (with the
    provider), ``link`` (WhatsApp in click-to-send mode), ``open`` /
    ``closed`` (the request page), or ``manual`` — written down by hand."""
    if key == "whatsapp":
        provider = Setting.get("wa_provider", "web") or "web"
        if provider == "cloud" and Setting.get("wa_cloud_token") \
                and Setting.get("wa_cloud_phone_id"):
            return "connected"
        if provider == "wapilot" and Setting.get("wa_wapilot_key") \
                and Setting.get("wa_wapilot_instance"):
            return "connected"
        return "link"
    if key == "page":
        return "open" if page_open() else "closed"
    return "manual"


def clean_tag(raw):
    """A campaign tag as it may be stored: letters, digits and ``_.:-``."""
    return _TAG.sub("-", (raw or "").strip())[:TAG_MAX].strip("-") or None


def channel_of_tag(tag):
    """The channel a request page tag names — ``instagram-dr-ahmed`` came
    from Instagram — else the page itself."""
    head = re.split(r"[-:._]", tag or "", maxsplit=1)[0].lower()
    if head in ("facebook", "fb"):
        head = "messenger"
    if head in ("ig", "insta"):
        head = "instagram"
    return head if head in CHANNELS and head != "page" else "page"


def campaign_tag(channel, label):
    """The tag for a campaign link: the channel, then the clinic's label."""
    label = clean_tag(label) or ""
    channel = channel if channel in CHANNELS and channel != "page" else ""
    return clean_tag("-".join(p for p in (channel, label) if p))


def public_base():
    """Where the clinic is reached from outside — the same address the
    survey links use — or ``None`` when it has not said."""
    base = (Setting.get("wa_public_base_url", "") or "").strip().rstrip("/")
    return base or None


def identity_value(kind, raw):
    """An identity as it is stored and compared. ``None`` when there is
    nothing usable in it."""
    from app.utils.whatsapp import normalize_phone

    raw = (raw or "").strip()
    if not raw:
        return None
    if kind == "phone":
        digits = normalize_phone(raw)
        return digits if digits and len(digits) >= 8 else None
    if kind == "email":
        raw = raw.lower()
        return raw if re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", raw) else None
    value = raw.lstrip("@").strip().lower()
    return value[:160] or None


__all__ = ["CHANNELS", "DEFAULT_ENABLED", "campaign_tag", "channel_of_tag",
           "clean_tag", "connection", "enabled", "identity_value",
           "page_open", "public_base", "set_enabled", "set_page"]
