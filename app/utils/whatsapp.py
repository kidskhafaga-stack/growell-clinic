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
    # The global CRM switch: "manual" always produces a click-to-send wa.me
    # link; "automatic" defers to each notification type's own auto/manual
    # preference (resolved per message in ``resolve_provider``).
    mode = Setting.get("crm_mode", "manual")
    provider = Setting.get("wa_provider", "web")
    return {
        "mode": mode,
        "provider": provider,
        "country_code": Setting.get("wa_country_code", DEFAULT_COUNTRY_CODE),
        "cloud_token": Setting.get("wa_cloud_token", ""),
        "cloud_phone_id": Setting.get("wa_cloud_phone_id", ""),
        "wapilot_key": Setting.get("wa_wapilot_key", ""),
        "wapilot_endpoint": Setting.get("wa_wapilot_endpoint", ""),
        "public_base": (Setting.get("wa_public_base_url", "") or "").rstrip("/"),
    }


def resolve_provider(cfg, template_type=None):
    """Effective provider for one message.

    The clinic-wide switch is the master control: in ``manual`` mode every
    message becomes a click-to-send link. In ``automatic`` mode each managed
    notification type decides for itself — a type set to ``manual`` still
    produces a link, so e.g. birthdays can auto-send while another type stays
    manual.
    """
    if cfg.get("mode") != "automatic":
        return "web"
    if template_type:
        tpl = template_for(template_type)
        if tpl is not None and tpl.send_mode != "auto":
            return "web"
    return cfg.get("provider") or "web"


# --- Unified CRM template registry -------------------------------------
# Legacy settings keys, migrated into the registry by ``seed_system_templates``.
_SETTING_FALLBACK = {
    "appointment_confirm": "wa_tpl_appt_confirm",
    "doctor_schedule": "wa_tpl_doctor_schedule",
    "vaccine_given": "wa_tpl_vaccine_given",
}


def template_for(template_type):
    """The active template object for a type — prefer the canonical (system)
    row, else the first active custom one. Returns None if nothing active."""
    from app.models import MessageTemplate

    q = MessageTemplate.query.filter_by(occasion=template_type, is_active=True)
    return (q.filter_by(is_system=True).first()
            or q.order_by(MessageTemplate.id).first())


def template_image(template_type):
    """The image attached to a type's active template, or None."""
    tpl = template_for(template_type)
    return tpl.image_url if tpl else None


def template_body(template_type):
    """Resolve a message body for a type from the single template registry,
    falling back to the legacy setting and then a built-in default."""
    from app.models import TEMPLATE_DEFAULTS

    tpl = template_for(template_type)
    if tpl:
        return tpl.body
    key = _SETTING_FALLBACK.get(template_type)
    if key:
        val = Setting.get(key, "")
        if val:
            return val
    return TEMPLATE_DEFAULTS.get(template_type, "")


def seed_system_templates():
    """Ensure one canonical (system) template exists per managed notification
    type, migrating any legacy ``wa_tpl_*`` setting body into the registry.

    Idempotent: only creates rows that are missing, so it is safe to call on
    every ``upgrade-db``. This is what consolidates the old two-place template
    storage into the single CRM registry.
    """
    from app.models import AUTOMATION_TYPES, TEMPLATE_DEFAULTS, MessageTemplate

    changed = 0
    for ttype in AUTOMATION_TYPES:
        if MessageTemplate.query.filter_by(occasion=ttype, is_system=True).first():
            continue
        # Adopt an existing template for this type so we don't create a parallel
        # duplicate — this is what folds any legacy per-type rows into the one
        # canonical slot.
        adopt = (MessageTemplate.query.filter_by(occasion=ttype)
                 .order_by(MessageTemplate.id).first())
        if adopt is not None:
            adopt.is_system = True
            adopt.is_active = True
            changed += 1
            continue
        body = ""
        key = _SETTING_FALLBACK.get(ttype)
        if key:
            body = Setting.get(key, "") or ""
        if not body:
            body = TEMPLATE_DEFAULTS.get(ttype, "")
        db.session.add(MessageTemplate(
            name=ttype, occasion=ttype, body=body,
            is_system=True, send_mode="manual", is_active=True,
        ))
        changed += 1
    if changed:
        db.session.commit()
    return changed


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


def _public_image_url(cfg, image_url):
    """A provider-fetchable URL for a template image, or None.

    Absolute http(s) URLs pass through; a locally-uploaded path only becomes
    sendable when a public base URL (tunnel/domain) is configured.
    """
    if not image_url:
        return None
    if image_url.startswith(("http://", "https://")):
        return image_url
    base = cfg.get("public_base")
    if base:
        return base + "/" + image_url.lstrip("/")
    return None


def send(body, to_phone, patient_id=None, appointment_id=None, user_id=None,
         cfg=None, image_url=None, template_type=None):
    """Prepare/deliver a WhatsApp message and log it. Returns the MessageLog."""
    cfg = cfg or get_config()
    phone = normalize_phone(to_phone, cfg["country_code"])
    provider = resolve_provider(cfg, template_type)
    log = MessageLog(
        patient_id=patient_id, appointment_id=appointment_id, to_phone=phone,
        body=body, image_url=image_url, provider=provider,
        created_by=user_id, status="queued",
    )
    db.session.add(log)

    if not phone:
        log.status = "failed"
        log.error = "missing_phone"
        return log

    media = _public_image_url(cfg, image_url)
    if provider == "cloud_api":
        ok, err = _send_cloud(cfg, phone, body, media)
        log.status, log.error = ("sent", None) if ok else ("failed", err)
        if not ok:  # keep a usable fallback link
            log.link = wa_link(phone, body)
    elif provider == "wapilot":
        ok, err = _send_wapilot(cfg, phone, body, media)
        log.status, log.error = ("sent", None) if ok else ("failed", err)
        if not ok:
            log.link = wa_link(phone, body)
    else:  # web / default — wa.me carries text only; image is attached by hand
        log.status = "link"
        log.link = wa_link(phone, body)
    return log


def _post_json(url, payload, headers, timeout=12):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        return resp.status, resp.read().decode("utf-8", "replace")


def _send_cloud(cfg, phone, body, media=None):
    token, phone_id = cfg.get("cloud_token"), cfg.get("cloud_phone_id")
    if not token or not phone_id:
        return False, "cloud_not_configured"
    url = f"https://graph.facebook.com/{GRAPH_VERSION}/{phone_id}/messages"
    if media:  # image with the body as caption
        payload = {
            "messaging_product": "whatsapp", "to": phone,
            "type": "image", "image": {"link": media, "caption": body},
        }
    else:
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


def _send_wapilot(cfg, phone, body, media=None):
    key, endpoint = cfg.get("wapilot_key"), cfg.get("wapilot_endpoint")
    if not key or not endpoint:
        return False, "wapilot_not_configured"
    payload = {"phone": phone, "message": body}
    if media:
        payload["image"] = media  # provider-specific; harmless when unused
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    try:
        status, _ = _post_json(endpoint, payload, headers)
        return (200 <= status < 300), (None if 200 <= status < 300 else f"http_{status}")
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)[:180]
