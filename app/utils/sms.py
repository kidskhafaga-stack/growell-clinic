"""SMS — one more channel for the messages the clinic already sends.

Off until a clinic switches it on. It is meant for an SMS company (the
message arrives under the clinic's sender name, and the company reports back
whether it was delivered), and it also works with a phone acting as a
gateway (OpenSMS) for a clinic whose program runs on its own network.

**No company is assumed.** Every SMS company has its own address and its own
field names, and guessing one wrong sends nothing. So the clinic writes what
its company's documentation says — the address, how the request is sent, and
a request body with blanks the program fills in:

``{to}`` the number · ``{text}`` the message · ``{sender}`` the sender name ·
``{key}`` the account key or password (for a company that wants it in the
request rather than in a header) · ``{user}`` the account's user name ·
``{lang}`` the language code the company wants, picked per message (Arabic
or not) · ``{id}`` a reference the program makes for this message, for a
company that takes the sender's own id and reports delivery against it.

**«الاعدادات بتاعت SMS متوافقة مع الشركات فى مصر؟»** — checked against how
the Egyptian companies are actually called (20 October 2026), which is what
the presets are:

* **OpenSMS** — its README: JSON with a Bearer key.
* **SMS Misr** — POST with every field *in the address*, not the body
  (``post_query``), and an answer of 200 whatever happened: success is the
  JSON field ``code`` being ``1901``. Read from an open-source client of
  theirs (gaitco/laravel-smsmisr), not from a published reference.
* **Victory Link** — a form POST of ``UserName``, ``Password``, ``SMSText``,
  ``SMSLang``, ``SMSSender``, ``SMSReceiver`` and the sender's own
  ``SMSID``; the answer is a bare number, ``0`` for sent, ``-5`` out of
  credit, ``-10`` already queued… — so ``0`` must match as a number, not as
  a letter inside ``-10``. From an open-source client
  (bellalMohamed/victory-link-sms-api).
* **CEQUENS** — JSON with a Bearer token: ``senderName``, ``messageType``,
  ``messageText``, ``recipients`` in international form; from their own
  sample code.

The language codes and the phone shape are the places a company's own sheet
wins; the screen says so.

Which messages go by SMS is the clinic's choice per type (``sms_types``), and
a WhatsApp message that fails can be sent again by SMS (``sms_fallback``).
Either way it is a new row in the same message log, marked ``channel="sms"``,
so every screen that counts messages counts these too.

Only automatic sending uses SMS. In manual mode a person presses a WhatsApp
link; there is no SMS link to press on a clinic computer.
"""
import json
import re
import urllib.error
import uuid
import urllib.parse
import urllib.request
from datetime import datetime

from app.extensions import db
from app.models import MessageLog, Setting

CHANNEL = PROVIDER = "sms"
METHODS = ("json", "form", "get", "post_query")
PHONE_FORMATS = ("intl", "plus", "local")
TIMEOUT = 15

#: What the OpenSMS README shows: ``POST /sms/`` with a Bearer key and a JSON
#: body of ``number`` and ``text``, on port 9292 of the phone.
PRESETS = {
    "opensms": {
        "sms_endpoint": "http://PHONE-IP:9292/sms/",
        "sms_method": "json",
        "sms_auth_header": "Authorization",
        "sms_payload": '{"number": "{to}", "text": "{text}"}',
        "sms_phone_format": "plus",
        "sms_id_field": "", "sms_ok_field": "", "sms_ok_text": "",
        "sms_lang_plain": "", "sms_lang_unicode": "",
    },
    "smsmisr": {
        "sms_endpoint": "https://smsmisr.com/api/SMS/",
        "sms_method": "post_query",
        "sms_auth_header": "",
        "sms_payload": ("environment=1&username={user}&password={key}&sender={sender}"
                        "&mobile={to}&language={lang}&message={text}"),
        "sms_phone_format": "intl",
        "sms_id_field": "", "sms_ok_field": "code", "sms_ok_text": "1901",
        "sms_lang_plain": "1", "sms_lang_unicode": "2",
    },
    "victorylink": {
        "sms_endpoint": ("https://smsvas.vlserv.com/VLSMSPlatformResellerAPI/"
                         "NewSendingAPI/api/SMSSender/SendSMS"),
        "sms_method": "form",
        "sms_auth_header": "",
        "sms_payload": ("UserName={user}&Password={key}&SMSText={text}&SMSLang={lang}"
                        "&SMSSender={sender}&SMSReceiver={to}&SMSID={id}"),
        "sms_phone_format": "intl",
        "sms_id_field": "", "sms_ok_field": "", "sms_ok_text": "0",
        "sms_lang_plain": "e", "sms_lang_unicode": "a",
    },
    "cequens": {
        "sms_endpoint": "https://apis.cequens.com/sms/v1/messages",
        "sms_method": "json",
        "sms_auth_header": "Authorization",
        "sms_payload": ('{"senderName": "{sender}", "messageType": "text", "shortURL": false, '
                        '"messageText": "{text}", "recipients": "{to}"}'),
        "sms_phone_format": "intl",
        "sms_id_field": "", "sms_ok_field": "", "sms_ok_text": "",
        "sms_lang_plain": "", "sms_lang_unicode": "",
    },
}

KEYS = ("sms_enabled", "sms_endpoint", "sms_method", "sms_auth_header",
        "sms_auth_value", "sms_sender", "sms_payload", "sms_phone_format",
        "sms_id_field", "sms_ok_text", "sms_ok_field", "sms_username",
        "sms_lang_plain", "sms_lang_unicode", "sms_types", "sms_fallback",
        "sms_dlr_id_field", "sms_dlr_status_field", "sms_dlr_delivered",
        "sms_dlr_failed")


def config():
    get = Setting.get
    return {
        "enabled": get("sms_enabled", "0") == "1",
        "endpoint": (get("sms_endpoint", "") or "").strip(),
        "method": get("sms_method", "json") if get("sms_method", "json") in METHODS else "json",
        "auth_header": (get("sms_auth_header", "") or "").strip(),
        "auth_value": (get("sms_auth_value", "") or "").strip(),
        "sender": (get("sms_sender", "") or "").strip(),
        "payload": (get("sms_payload", "") or "").strip(),
        "phone_format": get("sms_phone_format", "intl") if get("sms_phone_format", "intl") in PHONE_FORMATS else "intl",
        "id_field": (get("sms_id_field", "") or "").strip(),
        "ok_text": (get("sms_ok_text", "") or "").strip(),
        "ok_field": (get("sms_ok_field", "") or "").strip(),
        "username": (get("sms_username", "") or "").strip(),
        "lang_plain": (get("sms_lang_plain", "") or "").strip(),
        "lang_unicode": (get("sms_lang_unicode", "") or "").strip(),
        "types": {t.strip() for t in (get("sms_types", "") or "").split(",") if t.strip()},
        "fallback": get("sms_fallback", "0") == "1",
        "dlr_id": (get("sms_dlr_id_field", "") or "").strip(),
        "dlr_status": (get("sms_dlr_status_field", "") or "").strip(),
        "dlr_delivered": _words(get("sms_dlr_delivered", "")),
        "dlr_failed": _words(get("sms_dlr_failed", "")),
        "country_code": get("wa_country_code", "20") or "20",
    }


def _words(raw):
    return {w.strip().lower() for w in (raw or "").split(",") if w.strip()}


def ready(cfg=None):
    """Switched on and filled in enough to send."""
    cfg = cfg or config()
    return bool(cfg["enabled"] and cfg["endpoint"] and cfg["payload"])


def wanted_for(template_type, cfg=None):
    """Whether this message type goes by SMS instead of WhatsApp."""
    cfg = cfg or config()
    return bool(template_type) and template_type in cfg["types"] and ready(cfg)


# ---- the message itself -------------------------------------------------
GSM7 = set("@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞÆæßÉ !\"#¤%&'()*+,-./0123456789:;<=>?"
           "¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§¿abcdefghijklmnopqrstuvwxyzäöñüà")


def segments(text):
    """``(parts, per_part, unicode)`` — how many SMS this text costs.

    Arabic is sent as Unicode: 70 characters in one message, 67 a part once
    it is split. Plain Latin text: 160, then 153. Companies charge per part,
    so the screen says it before anything is sent.
    """
    text = text or ""
    uni = any(ch not in GSM7 for ch in text)
    single, multi = (70, 67) if uni else (160, 153)
    n = len(text)
    if n <= single:
        return 1, single, uni
    return -(-n // multi), multi, uni


def format_phone(phone, fmt, country_code="20"):
    """The number as this company wants it, from the program's
    international digits (``2010…``)."""
    digits = "".join(ch for ch in (phone or "") if ch.isdigit())
    if not digits:
        return ""
    if fmt == "plus":
        return "+" + digits
    if fmt == "local" and digits.startswith(country_code):
        return "0" + digits[len(country_code):]
    return digits


def _fill(template, values, method):
    out = template
    for name, value in values.items():
        value = "" if value is None else str(value)
        if method == "json":
            value = json.dumps(value, ensure_ascii=False)[1:-1]
        else:
            value = urllib.parse.quote(value, safe="")
        out = out.replace("{" + name + "}", value)
    return out


def build_request(cfg, phone, text, ref=None):
    """``(url, data, headers, http_method)`` — nothing sent yet. ``ref`` is
    the program's own reference for this message, put where ``{id}`` is."""
    _parts, _per, uni = segments(text)
    values = {"to": format_phone(phone, cfg["phone_format"], cfg["country_code"]),
              "text": text, "sender": cfg["sender"], "key": cfg["auth_value"],
              "user": cfg.get("username", ""), "id": ref or "",
              "lang": cfg.get("lang_unicode" if uni else "lang_plain", "")}
    headers = {}
    if cfg["auth_header"] and cfg["auth_value"]:
        headers[cfg["auth_header"]] = cfg["auth_value"]
    body = _fill(cfg["payload"], values, cfg["method"])
    if cfg["method"] == "json":
        json.loads(body)                    # a broken template fails here, said plainly
        headers["Content-Type"] = "application/json"
        return cfg["endpoint"], body.encode("utf-8"), headers, "POST"
    if cfg["method"] == "form":
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        return cfg["endpoint"], body.encode("utf-8"), headers, "POST"
    sep = "&" if "?" in cfg["endpoint"] else "?"
    if cfg["method"] == "post_query":
        # SMS Misr: a POST whose fields all ride in the address.
        return cfg["endpoint"] + sep + body, b"", headers, "POST"
    return cfg["endpoint"] + sep + body, None, headers, "GET"


def _dig(data, path):
    for part in (path or "").split("."):
        if not part:
            continue
        if isinstance(data, list):
            data = data[int(part)] if part.isdigit() and int(part) < len(data) else None
        elif isinstance(data, dict):
            data = data.get(part)
        else:
            return None
    return data


def _accepted(cfg, raw):
    """Whether the company's answer says it took the message.

    Nothing written: any 2xx is enough. With a field (``code``): that field
    of the JSON answer is one of the words. Without one: the words are looked
    for in the answer — a number as a whole number, so Victory Link's ``0``
    is not found inside its ``-10``.
    """
    wanted = [w.strip() for w in (cfg.get("ok_text") or "").split(",") if w.strip()]
    if not wanted:
        return True
    if cfg.get("ok_field"):
        try:
            got = _dig(json.loads(raw), cfg["ok_field"])
        except (ValueError, TypeError):
            return False
        return got is not None and str(got).strip().lower() in {w.lower() for w in wanted}
    for word in wanted:
        if re.fullmatch(r"-?\d+", word):
            if re.search(r"(?<![\d-])" + re.escape(word) + r"(?!\d)", raw):
                return True
        elif word.lower() in raw.lower():
            return True
    return False


def deliver(cfg, phone, text):
    """Hand one message to the company. ``(ok, error, msg_id)``."""
    ref = uuid.uuid4().hex if "{id}" in (cfg.get("payload") or "") else None
    try:
        url, data, headers, method = build_request(cfg, phone, text, ref=ref)
    except ValueError:
        return False, "sms_payload_invalid", None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:  # noqa: S310 — the clinic's own gateway
            status, raw = resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return False, f"http_{exc.code}", None
    except Exception as exc:  # noqa: BLE001 — network, refused, timeout
        return False, str(exc)[:180] or "sms_unreachable", None
    if not 200 <= status < 300:
        return False, f"http_{status}", None
    # Some companies answer 200 to a refusal and say so in the body. When the
    # clinic has written the word its company uses for success, it must be
    # there.
    if not _accepted(cfg, raw):
        return False, ("sms_rejected: " + raw.strip())[:180], None
    # A company that takes the sender's own id reports delivery against it.
    msg_id = ref
    if cfg["id_field"]:
        try:
            found = _dig(json.loads(raw), cfg["id_field"])
            msg_id = str(found)[:120] if found not in (None, "") else ref
        except (ValueError, TypeError):
            msg_id = ref
    return True, None, msg_id


def dispatch(log, cfg=None):
    """Send a logged SMS row now and stamp it, like WhatsApp's own."""
    cfg = cfg or config()
    if not ready(cfg):
        log.status, log.error = "failed", "sms_not_configured"
    else:
        ok, err, msg_id = deliver(cfg, log.to_phone, log.body)
        log.status, log.error = ("sent", None) if ok else ("failed", err)
        log.provider_msg_id = msg_id
    log.sent_at = datetime.utcnow()
    return log


def send(body, to_phone, patient_id=None, appointment_id=None, user_id=None,
         template_type=None, scheduled_at=None, retry_of=None, cfg=None,
         wa_cfg=None, ignore_window=False):
    """Log and send one SMS. Same rules as WhatsApp's ``send``: the family's
    opt-out, a future time, the clinic's sending hours and daily cap."""
    from app.utils import whatsapp as wa

    cfg = cfg or config()
    wa_cfg = wa_cfg or wa.get_config()
    phone = wa.normalize_phone(to_phone, wa_cfg["country_code"])
    log = MessageLog(patient_id=patient_id, appointment_id=appointment_id,
                     to_phone=phone, body=body, provider=PROVIDER, channel=CHANNEL,
                     template_type=template_type, scheduled_at=scheduled_at,
                     created_by=user_id, status="queued", retry_of=retry_of)
    db.session.add(log)
    if wa._opted_out(patient_id):
        log.status, log.error = "skipped", "opted_out"
        return log
    if not phone:
        log.status, log.error = "failed", "missing_phone"
        return log
    now = datetime.utcnow()
    if scheduled_at and scheduled_at > now:
        log.status = "scheduled"
        return log
    if not ignore_window and (not wa._in_window(wa_cfg, now) or wa._cap_reached(wa_cfg, now)):
        log.status = "scheduled"
        log.scheduled_at = wa._next_slot(wa_cfg, now)
        return log
    return dispatch(log, cfg)


def fallback(failed_log, cfg=None):
    """A WhatsApp message that failed, sent again by SMS — when the clinic
    asked for that. A new row (``retry_of``), so the failure stays on record.
    Returns the new row or ``None``."""
    cfg = cfg or config()
    if (not cfg["fallback"] or not ready(cfg) or failed_log is None
            or failed_log.channel_key != "whatsapp" or failed_log.status != "failed"
            or failed_log.error in ("opted_out", "missing_phone")
            or failed_log.template_type == "test"):
        return None
    if MessageLog.query.filter_by(retry_of=failed_log.id, channel=CHANNEL).first():
        return None
    db.session.flush()
    return send(failed_log.body, failed_log.to_phone, patient_id=failed_log.patient_id,
                appointment_id=failed_log.appointment_id, user_id=failed_log.created_by,
                template_type=failed_log.template_type, retry_of=failed_log.id, cfg=cfg,
                ignore_window=True)


# ---- delivery reports ---------------------------------------------------
def normalize_dlr(payload, cfg=None):
    """A company's delivery report → ``[{msg_id, status, error}]`` in the
    program's words (``delivered`` / ``failed``), by the field names and
    values the clinic wrote from its company's documentation. A report the
    clinic has not described is ignored rather than guessed at."""
    cfg = cfg or config()
    if not (cfg["dlr_id"] and cfg["dlr_status"]):
        return []
    rows = payload if isinstance(payload, list) else [payload]
    out = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        msg_id, raw = _dig(row, cfg["dlr_id"]), _dig(row, cfg["dlr_status"])
        if msg_id in (None, "") or raw in (None, ""):
            continue
        word = str(raw).strip().lower()
        if word in cfg["dlr_delivered"]:
            status = "delivered"
        elif word in cfg["dlr_failed"]:
            status = "failed"
        else:
            continue
        out.append({"msg_id": str(msg_id), "status": status,
                    "error": ("sms: " + str(raw))[:200] if status == "failed" else None})
    return out


__all__ = ["CHANNEL", "KEYS", "METHODS", "PHONE_FORMATS", "PRESETS", "build_request",
           "config", "deliver", "dispatch", "fallback", "format_phone",
           "normalize_dlr", "ready", "segments", "send", "wanted_for"]
