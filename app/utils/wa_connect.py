"""Proving the clinic can actually be reached — before a parent finds out.

Everything about inbound WhatsApp is set up blind. The clinic types a public
address, opens a tunnel, pastes a URL into two provider dashboards, and then
**waits**. If nothing arrives there is no way to tell which link in the chain
is broken: the tunnel, the address, the path, the secret, the switch, or the
provider's own subscription. So the setup gets abandoned, or worse, believed.

This asks the question directly: it calls the clinic's own public webhook
from outside and reports what came back. The round trip is the point — a
request that leaves the building and returns has proved the tunnel, DNS, TLS,
the path and the guard in one go, which no amount of reading settings can.

**It never fabricates a message.** The WaPilot probe posts an empty body,
which the receiver already answers with "nothing here for me" and writes
nothing; the Meta probe is the verification handshake Meta itself performs.
Neither leaves a row behind.

The wrong-secret probe is the one people skip and the one that matters most:
a 200 for a token that should be refused does not mean "reachable", it means
**something that is not this program is answering on the clinic's address**,
and every message a parent sends is going there instead. Reporting that as
success would be worse than reporting nothing.
"""
import json
import urllib.error
import urllib.parse
import urllib.request
import uuid

#: How long to wait on the round trip. Long enough for a tunnel on a slow
#: line, short enough that a dead address answers the admin, not the clock.
TIMEOUT_SECONDS = 12

#: What a probe concluded. The screen decides its own wording; these are the
#: facts, and they are deliberately more than pass/fail — "reachable but
#: switched off" and "reachable but somebody else is answering" are different
#: problems with different fixes, and both used to look like silence.
VERDICTS = (
    "ok",            # answered exactly as this program answers
    "off",           # this program answered, with receiving switched off
    "refused",       # the right secret was refused — settings and live differ
    "impostor",      # a wrong secret was accepted: not this program
    "wrong_place",   # something answered, but not this endpoint
    "unreachable",   # nothing answered at all
    "not_set",       # nothing to test yet
)


def _call(url, data=None, timeout=TIMEOUT_SECONDS):
    """One probe. Returns ``(status, body)``, or ``(None, reason)``.

    An HTTP error is an answer, not a failure — a 403 is the single most
    informative thing this module can receive — so it is unwrapped and
    returned like any other status.
    """
    req = urllib.request.Request(
        url, data=data, method=("POST" if data is not None else "GET"),
        headers=({"Content-Type": "application/json"} if data else {}))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")
    except Exception as exc:                    # noqa: BLE001 — never raise
        return None, type(exc).__name__


def _answered_ok(body):
    """Is this the body the receiving endpoint returns when it accepted?"""
    try:
        return bool(json.loads(body or "").get("ok"))
    except (ValueError, AttributeError):
        return False


def base_url():
    """The clinic's public address, or ``None``."""
    from app.models import Setting

    return (Setting.get("wa_public_base_url", "") or "").strip().rstrip("/") or None


def wapilot_url(base=None, secret=None):
    """The address WaPilot is meant to be given, secret and all."""
    from app.models import Setting

    base = base or base_url()
    secret = secret if secret is not None else Setting.get("wa_webhook_secret", "")
    if not base or not secret:
        return None
    return f"{base}/wa/webhook/wapilot/{secret}"


def meta_url(base=None):
    """The address Meta is meant to be given."""
    base = base or base_url()
    return f"{base}/wa/webhook/meta" if base else None


def check_wapilot():
    """Two probes: one that must be refused, then one that must be accepted.

    Order matters. Until a wrong secret is proved to be refused, a success
    from the right one means nothing — anything at all could be answering
    with a 200.
    """
    url = wapilot_url()
    if not url:
        return {"verdict": "not_set", "detail": None}

    base = base_url()
    decoy = f"{base}/wa/webhook/wapilot/{uuid.uuid4().hex}"
    status, body = _call(decoy, data=b"{}")
    if status is None:
        return {"verdict": "unreachable", "detail": body}
    if status == 404:
        return {"verdict": "wrong_place", "detail": "404"}
    if status != 403:
        # Anything but a refusal here is somebody else's server, or a guard
        # that has stopped guarding. Either way the clinic's address is not
        # doing what the clinic thinks.
        return {"verdict": "impostor", "detail": str(status)}

    status, body = _call(url, data=b"{}")
    if status is None:
        return {"verdict": "unreachable", "detail": body}
    if status == 403:
        return {"verdict": "refused", "detail": "403"}
    if status != 200:
        return {"verdict": "wrong_place", "detail": str(status)}
    # Receiving switched off answers 200 with an empty body on purpose, so
    # providers stop retrying. From outside that is indistinguishable from
    # working — which is exactly the confusion this separates.
    return {"verdict": "ok" if _answered_ok(body) else "off", "detail": None}


def check_meta():
    """Meta's own handshake, performed by the clinic against itself.

    Meta subscribes by asking for a challenge back. Doing the same thing here
    tests precisely what Meta will test, so a pass means Meta's dashboard
    will accept the URL rather than merely that the port is open.
    """
    from app.models import Setting

    url = meta_url()
    token = (Setting.get("wa_meta_verify_token", "") or "").strip()
    if not url or not token:
        return {"verdict": "not_set", "detail": None}

    nonce = uuid.uuid4().hex[:12]
    query = urllib.parse.urlencode({"hub.mode": "subscribe",
                                    "hub.verify_token": token,
                                    "hub.challenge": nonce})
    status, body = _call(f"{url}?{query}")
    if status is None:
        return {"verdict": "unreachable", "detail": body}
    if status == 404:
        return {"verdict": "wrong_place", "detail": "404"}
    if status == 403:
        return {"verdict": "refused", "detail": "403"}
    if status != 200:
        return {"verdict": "wrong_place", "detail": str(status)}
    # The challenge has to come back *unchanged*. A 200 carrying anything
    # else is a different server being agreeable, and Meta would reject it.
    if (body or "").strip() != nonce:
        return {"verdict": "impostor", "detail": "challenge"}
    return {"verdict": "ok", "detail": None}


def check():
    """Both providers, plus whether there is an address to test at all."""
    from app.models import Setting

    return {
        "base": base_url(),
        "inbound_on": Setting.get("wa_inbound_enabled", "0") == "1",
        "wapilot": check_wapilot(),
        "meta": check_meta(),
    }
