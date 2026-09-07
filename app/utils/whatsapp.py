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
import mimetypes
import os
import re
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timedelta

from app.extensions import db
from app.models import MessageLog, Setting

DEFAULT_COUNTRY_CODE = "20"  # Egypt
GRAPH_VERSION = "v21.0"
WAPILOT_BASE = "https://api.wapilot.net/api/v2"


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
        "wapilot_instance": Setting.get("wa_wapilot_instance", ""),
        "wapilot_endpoint": (Setting.get("wa_wapilot_endpoint", "")
                             or WAPILOT_BASE).rstrip("/"),
        "public_base": (Setting.get("wa_public_base_url", "") or "").rstrip("/"),
        "send_from": _int(Setting.get("wa_send_from", ""), 0),   # window start hour
        "send_to": _int(Setting.get("wa_send_to", ""), 24),      # window end hour
        "daily_cap": _int(Setting.get("wa_daily_cap", ""), 0),   # 0 = unlimited
    }


def _int(val, default):
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


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


def sends_itself(template_type):
    """True when a message of this type would actually leave on its own.

    In manual mode — and for a type set to manual inside automatic mode —
    ``resolve_provider`` returns ``web``: a click-to-send link for a person to
    press. That is fine for a message somebody is composing right now, and
    wrong for anything **scheduled**: a link queued for tomorrow morning is a
    link nobody is standing in front of, and it sits in the log looking like a
    message that went out.

    So the scheduled types ask this first and queue nothing rather than queue
    something that cannot deliver itself.
    """
    return resolve_provider(get_config(), template_type) != "web"


def type_is_off(template_type):
    """True when this notification exists and every copy of it is switched off.

    :func:`template_for` returns None for two different situations — "somebody
    switched this off" and "nobody has ever set it up" — and callers that
    treated the two as one silently stopped messaging anybody. A clinic that
    has never opened the templates screen should still get its messages, from
    the built-in wording; a clinic that deliberately turned one off should get
    silence, and be told that silence is what it asked for.
    """
    from app.models import MessageTemplate

    if template_for(template_type) is not None:
        return False
    return (MessageTemplate.query
            .filter_by(occasion=template_type).first() is not None)


def feedback_link(token, cfg=None):
    """Public survey URL for a feedback token — uses the configured public base
    (tunnel/domain) so it opens on the patient's phone; falls back to the
    request host."""
    cfg = cfg or get_config()
    base = cfg.get("public_base")
    if base:
        return f"{base}/f/{token}"
    from flask import url_for
    try:
        return url_for("feedback.rate", token=token, _external=True)
    except Exception:  # noqa: BLE001 - no request/app context
        return f"/f/{token}"


def template_image(template_type):
    """The image attached to a type's active template, or None."""
    tpl = template_for(template_type)
    return tpl.image_url if tpl else None


def template_body(template_type, gender=None):
    """Resolve a message body for a type from the single template registry,
    falling back to the legacy setting and then a built-in default.

    ``gender`` picks the feminine wording when the clinic wrote one. Arabic
    has no gender-neutral second person: "كل سنة وانت طيب" is wrong for half
    the children in the register, and "طيب/طيبة" in the middle of a greeting
    reads like a form.
    """
    from app.models import TEMPLATE_DEFAULTS

    tpl = template_for(template_type)
    if tpl:
        return tpl.body_for(gender)
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


def first_name_of(full):
    """The name a greeting should use. ``"عمر محمد السيد خفاجة"`` → ``"عمر"``.

    A birthday card addressed to a child by all four of their names reads like
    a summons. The full name is still available as ``{patient}`` — a
    prescription heading wants it — so this is an extra token and never a
    replacement.
    """
    return (full or "").strip().split(" ")[0] if (full or "").strip() else ""


def render(template, mapping):
    """Substitute ``{placeholder}`` tokens in a template string.

    ``{first_name}`` is derived here rather than at each of the twelve places
    that build one of these mappings. Adding it to twelve call sites is adding
    it to eleven and forgetting one, and the one forgotten is the message that
    goes out with an empty gap where a child's name should be.
    """
    mapping = dict(mapping)
    if "patient" in mapping and "first_name" not in mapping:
        mapping["first_name"] = first_name_of(mapping.get("patient"))
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


def _opted_out(patient_id):
    if not patient_id:
        return False
    from app.models import Patient
    p = db.session.get(Patient, patient_id)
    return bool(p and p.wa_opt_out)


def _in_window(cfg, when):
    """Is ``when`` inside the configured daily send window?"""
    lo, hi = cfg.get("send_from", 0), cfg.get("send_to", 24)
    if lo <= 0 and hi >= 24:
        return True
    if lo >= hi:  # misconfigured — treat as always allowed
        return True
    return lo <= when.hour < hi


def _cap_reached(cfg, when):
    cap = cfg.get("daily_cap", 0)
    if not cap or cap <= 0:
        return False
    start = when.replace(hour=0, minute=0, second=0, microsecond=0)
    sent_today = (MessageLog.query
                  .filter(MessageLog.status == "sent",
                          MessageLog.sent_at >= start)
                  .count())
    return sent_today >= cap


def _next_slot(cfg, now):
    """Next moment inside the send window (today or tomorrow)."""
    lo = cfg.get("send_from", 0)
    if _in_window(cfg, now) and not _cap_reached(cfg, now):
        return now
    slot = now.replace(hour=max(lo, 0), minute=0, second=0, microsecond=0)
    if slot <= now:
        slot += timedelta(days=1)
    return slot


def _dispatch(log, cfg):
    """Actually hand ``log`` to its provider (or build a link) and stamp it."""
    phone, body, image_url = log.to_phone, log.body, log.image_url
    if log.provider == "cloud_api":
        ok, err, msg_id = _send_cloud(cfg, phone, body, image_url)
        log.status, log.error = ("sent", None) if ok else ("failed", err)
        # "sent" is the weakest of the three words this row can carry: it means
        # the provider took it, nothing more. The id is what lets a delivery
        # receipt come back later and say whether it actually arrived.
        log.provider_msg_id = msg_id
        if not ok:
            log.link = wa_link(phone, body)
    elif log.provider == "wapilot":
        ok, err = _send_wapilot(cfg, phone, body, image_url)
        log.status, log.error = ("sent", None) if ok else ("failed", err)
        if not ok:
            log.link = wa_link(phone, body)
    else:  # web / default — wa.me carries text only; image is attached by hand
        log.status = "link"
        log.link = wa_link(phone, body)
    log.sent_at = datetime.utcnow()
    return log


def send(body, to_phone, patient_id=None, appointment_id=None, user_id=None,
         cfg=None, image_url=None, template_type=None, scheduled_at=None,
         ignore_window=False):
    """Prepare/deliver a WhatsApp message and log it. Returns the MessageLog.

    Honours the patient opt-out, an explicit future ``scheduled_at``, and — for
    API auto-sends — the daily send window and cap (deferring to the next slot
    when outside them). ``web`` links are always produced immediately.

    ``ignore_window`` is for the messages a person is standing there waiting
    for — a test send, a reply to somebody specific. The window and the cap
    exist to stop the clinic messaging families at 2 a.m. in bulk; holding back
    a test the receptionist just asked for would only look broken.
    """
    cfg = cfg or get_config()
    phone = normalize_phone(to_phone, cfg["country_code"])
    provider = resolve_provider(cfg, template_type)
    log = MessageLog(
        patient_id=patient_id, appointment_id=appointment_id, to_phone=phone,
        body=body, image_url=image_url, provider=provider,
        template_type=template_type, scheduled_at=scheduled_at,
        created_by=user_id, status="queued",
    )
    db.session.add(log)

    if _opted_out(patient_id):
        log.status, log.error = "skipped", "opted_out"
        return log
    if not phone:
        log.status, log.error = "failed", "missing_phone"
        return log

    now = datetime.utcnow()
    if scheduled_at and scheduled_at > now:
        log.status = "scheduled"
        return log

    # API auto-sends respect the window + daily cap; links go out anytime.
    if not ignore_window and provider in ("cloud_api", "wapilot") and (
            not _in_window(cfg, now) or _cap_reached(cfg, now)):
        log.status = "scheduled"
        log.scheduled_at = _next_slot(cfg, now)
        return log

    return _dispatch(log, cfg)


def send_approved(tpl, values, to_phone, patient_id=None, user_id=None,
                  cfg=None):
    """Send a Meta-approved template — what goes out once the window shuts.

    Logged with the *filled* body so the conversation shows the family the
    same sentence they read, even though the wire format carries a name and a
    list of parameters. Sent immediately: this is somebody answering a specific
    person who is waiting, not a campaign, so the daily cap and the send window
    do not hold it back.
    """
    from app.utils.wa_templates import fill

    cfg = cfg or get_config()
    phone = normalize_phone(to_phone, cfg["country_code"])
    body = fill(tpl.get("body"), values) or tpl.get("name")
    log = MessageLog(patient_id=patient_id, to_phone=phone, body=body,
                     provider=resolve_provider(cfg),
                     template_type="approved", created_by=user_id,
                     status="queued")
    db.session.add(log)
    if _opted_out(patient_id):
        log.status, log.error = "skipped", "opted_out"
        return log
    if not phone:
        log.status, log.error = "failed", "missing_phone"
        return log
    if log.provider != "cloud_api":
        log.status, log.error = "failed", "templates_need_cloud_api"
        return log
    ok, err, msg_id = _send_cloud_template(cfg, phone, tpl, values)
    log.status, log.error = ("sent", None) if ok else ("failed", err)
    log.provider_msg_id = msg_id
    log.sent_at = datetime.utcnow()
    return log


def _send_cloud_template(cfg, phone, tpl, values):
    token, phone_id = cfg.get("cloud_token"), cfg.get("cloud_phone_id")
    if not token or not phone_id:
        # Three values, like every other exit from here. This returned two and
        # the caller unpacks three, so a clinic that picked Cloud API and had
        # not yet pasted its credentials met a ValueError instead of the
        # message "cloud_not_configured" — a crash in place of the sentence
        # that would have told them what to fix.
        return False, "cloud_not_configured", None
    url = f"https://graph.facebook.com/{GRAPH_VERSION}/{phone_id}/messages"
    template = {"name": tpl.get("name"),
                "language": {"code": tpl.get("lang") or "ar"}}
    if values:
        template["components"] = [{
            "type": "body",
            "parameters": [{"type": "text", "text": str(v)} for v in values],
        }]
    payload = {"messaging_product": "whatsapp", "to": phone,
               "type": "template", "template": template}
    headers = {"Authorization": f"Bearer {token}",
               "Content-Type": "application/json"}
    try:
        status, raw = _post_json(url, payload, headers)
        ok = 200 <= status < 300
        return ok, (None if ok else f"http_{status}"), (_cloud_msg_id(raw) if ok else None)
    except Exception as exc:  # noqa: BLE001 - network/credential failure
        return False, str(exc)[:180], None


def dispatch_due(cfg=None, limit=500):
    """Send every scheduled message whose time has come. Returns a summary.

    Skips (re-schedules) while outside the window or over the cap so a manual
    "send due now" and the ``send-due`` CLI behave identically.
    """
    cfg = cfg or get_config()
    now = datetime.utcnow()
    try:  # arm any occasion campaign whose date has arrived (idempotent)
        from app.utils.occasions import enqueue_due_occasions
        enqueue_due_occasions()
    except Exception:  # noqa: BLE001 - campaigns must never block sending
        pass
    # Operational messages (confirmations, surveys, reminders) always beat
    # bulk campaign messages, so a big occasion blast can't starve them.
    due = (MessageLog.query
           .filter(MessageLog.status == "scheduled",
                   MessageLog.scheduled_at <= now)
           .order_by(MessageLog.template_id.isnot(None),
                     MessageLog.scheduled_at)
           .limit(limit).all())
    sent = skipped = 0
    for log in due:
        if _opted_out(log.patient_id):
            log.status, log.error = "skipped", "opted_out"
            skipped += 1
            continue
        if log.provider in ("cloud_api", "wapilot") and (
                not _in_window(cfg, now) or _cap_reached(cfg, now)):
            log.scheduled_at = _next_slot(cfg, now)
            continue  # still scheduled — try again next run
        _dispatch(log, cfg)
        sent += 1
    db.session.commit()
    return {"sent": sent, "skipped": skipped, "considered": len(due)}


def maybe_dispatch(min_gap_minutes=10):
    """Opportunistic queue drain: piggybacks on the screens' live-refresh
    polling so scheduled messages/campaigns go out during the day without a
    separate scheduler. Throttled by a settings timestamp; silent on failure —
    a UI poll must never break because sending hiccuped."""
    try:
        from datetime import timedelta
        now = datetime.utcnow()
        last = Setting.get("wa_last_auto_dispatch", "")
        if last:
            try:
                if now - datetime.fromisoformat(last) < timedelta(minutes=min_gap_minutes):
                    return None
            except ValueError:
                pass
        Setting.set("wa_last_auto_dispatch", now.isoformat())
        db.session.commit()
        return dispatch_due()
    except Exception:  # noqa: BLE001
        db.session.rollback()
        return None


def _post_json(url, payload, headers, timeout=12):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        return resp.status, resp.read().decode("utf-8", "replace")


def _local_image_path(image_url):
    """Filesystem path for a locally-uploaded template image, or None."""
    if not image_url or image_url.startswith(("http://", "https://")):
        return None
    try:
        from flask import current_app
        rel = image_url.split("static/", 1)[1] if "static/" in image_url else image_url
        path = os.path.join(current_app.static_folder, rel)
        return path if os.path.isfile(path) else None
    except Exception:  # noqa: BLE001 - no app context / bad path
        return None


def _post_multipart(url, fields, file_field, file_path, headers, timeout=20):
    """POST a multipart/form-data request with one file upload (stdlib only)."""
    boundary = "----pediapro" + uuid.uuid4().hex
    with open(file_path, "rb") as fh:
        file_data = fh.read()
    fname = os.path.basename(file_path)
    ctype = mimetypes.guess_type(fname)[0] or "application/octet-stream"
    parts = []
    for name, value in fields.items():
        parts.append(f"--{boundary}\r\nContent-Disposition: form-data; "
                     f"name=\"{name}\"\r\n\r\n{value}\r\n".encode("utf-8"))
    head = (f"--{boundary}\r\nContent-Disposition: form-data; "
            f"name=\"{file_field}\"; filename=\"{fname}\"\r\n"
            f"Content-Type: {ctype}\r\n\r\n").encode("utf-8")
    body = b"".join(parts) + head + file_data + f"\r\n--{boundary}--\r\n".encode()
    h = dict(headers)
    h["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    req = urllib.request.Request(url, data=body, headers=h, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        return resp.status, resp.read().decode("utf-8", "replace")


def _send_cloud(cfg, phone, body, image_url=None):
    token, phone_id = cfg.get("cloud_token"), cfg.get("cloud_phone_id")
    if not token or not phone_id:
        return False, "cloud_not_configured", None
    url = f"https://graph.facebook.com/{GRAPH_VERSION}/{phone_id}/messages"
    media = _public_image_url(cfg, image_url)  # Cloud API fetches by link
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
        status, raw = _post_json(url, payload, headers)
        ok = 200 <= status < 300
        return ok, (None if ok else f"http_{status}"), (_cloud_msg_id(raw) if ok else None)
    except Exception as exc:  # noqa: BLE001 - network/credential failure
        return False, str(exc)[:180], None


def _cloud_msg_id(raw):
    """The ``wamid.…`` Meta hands back for a message it accepted.

    This was being thrown away — ``status, _ = _post_json(...)`` — and it is
    the only thing a delivery receipt can be matched against. Without it every
    message in this program was stuck at "the provider accepted it": a number
    that has been dead for a year and a message somebody read look identical.

    Never raises: a body that does not parse means no id, which costs a receipt
    and must not cost the send.
    """
    try:
        data = json.loads(raw or "{}")
        return ((data.get("messages") or [{}])[0].get("id")) or None
    except Exception:  # noqa: BLE001 - malformed body is not a send failure
        return None


def _send_wapilot(cfg, phone, body, image_url=None):
    """WaPilot API v2: token-header auth, per-instance send-message / send-image.

    Text  -> POST {base}/{instance}/send-message  (JSON chat_id + text)
    Image -> POST {base}/{instance}/send-image    (multipart file upload)
    A local template image is uploaded directly; an external image URL or a
    missing file falls back to a text message.
    """
    token = cfg.get("wapilot_key")
    instance = cfg.get("wapilot_instance")
    base = cfg.get("wapilot_endpoint") or WAPILOT_BASE
    if not token or not instance:
        return False, "wapilot_not_configured"

    local_img = _local_image_path(image_url)
    try:
        if local_img:  # image message with the body as caption
            url = f"{base}/{instance}/send-image"
            # The upload field is ``media``. It was ``image`` here, which is
            # the one name WaPilot rejects: its own validation error for this
            # endpoint reads *"The media field is required."* — so every
            # picture the clinic ever sent through WaPilot came back 422.
            status, _ = _post_multipart(
                url, {"chat_id": phone, "caption": body or ""},
                "media", local_img, {"token": token})
        else:
            url = f"{base}/{instance}/send-message"
            status, _ = _post_json(
                url, {"chat_id": phone, "text": body},
                {"token": token, "Content-Type": "application/json"})
        return (200 <= status < 300), (None if 200 <= status < 300 else f"http_{status}")
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)[:180]
