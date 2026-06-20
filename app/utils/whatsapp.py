"""WhatsApp messaging layer.

Supports three delivery modes, selectable in settings:

* ``web``       – produce a ``wa.me`` click-to-send link (no credentials,
                  always available; the staff member clicks to send).
* ``cloud_api`` – Meta WhatsApp Cloud API (Graph) with a token + phone id.
* ``wapilot``   – a generic HTTP provider (WaPilot) with an API key + endpoint.

Every attempt is recorded in ``MessageLog``. API sends are best-effort: if the
network or credentials are unavailable the message is logged as ``failed`` and
the caller can still fall back to the wa.me link.
"""
import json
import re
import urllib.parse
import urllib.request

from app.extensions import db
from app.models import MessageLog, Setting

DEFAULT_COUNTRY_CODE = "20"  # Egypt
GRAPH_VERSION = "v21.0"


def get_config():
    return {
        "provider": Setting.get("wa_provider", "web"),
        "country_code": Setting.get("wa_country_code", DEFAULT_COUNTRY_CODE),
        "cloud_token": Setting.get("wa_cloud_token", ""),
        "cloud_phone_id": Setting.get("wa_cloud_phone_id", ""),
        "wapilot_key": Setting.get("wa_wapilot_key", ""),
        "wapilot_endpoint": Setting.get("wa_wapilot_endpoint", ""),
    }


def normalize_phone(raw, country_code=DEFAULT_COUNTRY_CODE):
    """Best-effort conversion to international digits (no ``+``)."""
    if not raw:
        return None
    had_plus = raw.strip().startswith("+")
    digits = re.sub(r"\D", "", raw)
    if not digits:
        return None
    if digits.startswith("00"):
        digits = digits[2:]
    elif had_plus:
        pass  # already international
    elif digits.startswith("0"):
        digits = country_code + digits[1:]
    elif not digits.startswith(country_code) and len(digits) <= 10:
        digits = country_code + digits
    return digits


def render(template, mapping):
    """Substitute ``{placeholder}`` tokens in a template string."""
    out = template or ""
    for key, value in mapping.items():
        out = out.replace("{" + key + "}", "" if value is None else str(value))
    return out


def wa_link(phone, text):
    return f"https://wa.me/{phone}?text=" + urllib.parse.quote(text or "")


def send(body, to_phone, patient_id=None, appointment_id=None, user_id=None,
         cfg=None):
    """Prepare/deliver a WhatsApp message and log it. Returns the MessageLog."""
    cfg = cfg or get_config()
    phone = normalize_phone(to_phone, cfg["country_code"])
    log = MessageLog(
        patient_id=patient_id, appointment_id=appointment_id, to_phone=phone,
        body=body, provider=cfg["provider"], created_by=user_id, status="queued",
    )
    db.session.add(log)

    if not phone:
        log.status = "failed"
        log.error = "missing_phone"
        return log

    provider = cfg["provider"]
    if provider == "cloud_api":
        ok, err = _send_cloud(cfg, phone, body)
        log.status, log.error = ("sent", None) if ok else ("failed", err)
        if not ok:  # keep a usable fallback link
            log.link = wa_link(phone, body)
    elif provider == "wapilot":
        ok, err = _send_wapilot(cfg, phone, body)
        log.status, log.error = ("sent", None) if ok else ("failed", err)
        if not ok:
            log.link = wa_link(phone, body)
    else:  # web / default
        log.status = "link"
        log.link = wa_link(phone, body)
    return log


def _post_json(url, payload, headers, timeout=12):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        return resp.status, resp.read().decode("utf-8", "replace")


def _send_cloud(cfg, phone, body):
    token, phone_id = cfg.get("cloud_token"), cfg.get("cloud_phone_id")
    if not token or not phone_id:
        return False, "cloud_not_configured"
    url = f"https://graph.facebook.com/{GRAPH_VERSION}/{phone_id}/messages"
    payload = {
        "messaging_product": "whatsapp", "to": phone,
        "type": "text", "text": {"body": body},
    }
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    try:
        status, _ = _post_json(url, payload, headers)
        return (200 <= status < 300), (None if 200 <= status < 300 else f"http_{status}")
    except Exception as exc:  # noqa: BLE001 - network/credential failure
        return False, str(exc)[:180]


def _send_wapilot(cfg, phone, body):
    key, endpoint = cfg.get("wapilot_key"), cfg.get("wapilot_endpoint")
    if not key or not endpoint:
        return False, "wapilot_not_configured"
    payload = {"phone": phone, "message": body}
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    try:
        status, _ = _post_json(endpoint, payload, headers)
        return (200 <= status < 300), (None if 200 <= status < 300 else f"http_{status}")
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)[:180]
