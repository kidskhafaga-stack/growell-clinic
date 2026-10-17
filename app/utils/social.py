"""Messenger, Instagram and Telegram — reading what they send, and replying.

``CONNECTHUB_PLAN.md`` stage two. Every rule below is taken from the
platform's own documentation, read in full for this module (October 2026):

**Meta** (Messenger, and Instagram accounts linked to a Facebook Page) —
``developers.facebook.com/documentation/business-messaging/…``:

* one webhook for both: ``object`` is ``page`` or ``instagram``; messages
  arrive in ``entry[].messaging[]`` (``sender.id`` is the Page- or
  Instagram-scoped id, ``message.mid``, ``text``, ``attachments``), and
  comments in ``entry[].changes[]`` (``feed`` on a Page — ``item`` comment,
  ``verb`` add; ``comments`` on Instagram);
* every POST is signed: ``X-Hub-Signature-256`` = ``sha256=`` + HMAC-SHA256
  of the raw body with the app secret (``webhook_auth.meta_signature_ok``,
  the WhatsApp check — the same rule);
* the endpoint answers ``200`` within five seconds, and must expect the
  same notification more than once — deduplicated on ``mid``;
* ``is_echo`` is a message the Page itself sent; ``read``/``delivery``
  events carry no message; an Instagram ``is_deleted`` means the person
  deleted it, and the platform's terms say it is deleted here too;
* a reply is ``POST /<PAGE_ID>/messages`` with ``recipient.id``,
  ``messaging_type`` ``RESPONSE`` and ``message.text`` — Messenger text
  under 2000 characters, Instagram at most 1000 bytes; within 24 hours of
  the person's last message. After that only the ``HUMAN_AGENT`` tag, by a
  person, within 7 days, and only once Meta has approved the app for it;
* a comment is answered with ``recipient.comment_id`` — **one** message,
  within 7 days of the comment;
* server calls may carry ``appsecret_proof`` = HMAC-SHA256 of
  ``token|time`` with the app secret, and ``appsecret_time``.

**Telegram** — ``core.telegram.org/bots/api``:

* updates are POSTed as JSON; ``setWebhook``'s ``secret_token`` comes back
  in ``X-Telegram-Bot-Api-Secret-Token`` on every request, and is the proof;
* ``update_id`` repeats on a retry — the dedupe key;
* a bot cannot write first; ``sendMessage`` takes ``chat_id`` and ``text``
  (1–4096 characters); a shared ``contact`` whose ``user_id`` is the
  sender's own id is the person's own number.

Nothing here decides who a person is or writes a row — that is
``social_inbound``. Nothing here sends on its own — a person presses send.
"""
import hashlib
import hmac
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from app.models import Setting

#: The Graph API version the documentation was read at. A clinic may move it
#: forward in its settings once Meta announces a newer one.
DEFAULT_GRAPH_VERSION = "v25.0"
GRAPH = "https://graph.facebook.com"
TELEGRAM = "https://api.telegram.org"

#: Hours the platform lets a business answer freely, and the days a person
#: may still answer under the human-agent tag.
STANDARD_WINDOW_HOURS = 24
HUMAN_AGENT_DAYS = 7
#: Days a comment may still be answered privately.
PRIVATE_REPLY_DAYS = 7

MESSENGER_MAX_CHARS = 2000      # "less than 2000 characters"
INSTAGRAM_MAX_BYTES = 1000      # "1,000 bytes or less"
TELEGRAM_MAX_CHARS = 4096

META_CHANNELS = ("messenger", "instagram")
SOCIAL_CHANNELS = ("messenger", "instagram", "telegram")

#: The identity each channel's sender id is filed under.
SENDER_KIND = {"messenger": "messenger_psid", "instagram": "instagram_igsid",
               "telegram": "telegram_id", "facebook_comment": "facebook_user"}


@dataclass
class Inbound:
    """One thing that arrived, the same shape whichever platform sent it."""
    channel: str                 # messenger | instagram | telegram
    kind: str                    # message | comment | echo | deleted
    sender_id: str               # the platform's id for the person
    msg_id: str = ""             # the platform's id for this message/comment
    text: str = ""
    name: str = ""               # the name the platform shows, if any
    username: str = ""           # @handle, if any
    media: list = field(default_factory=list)   # [(type, url-or-id)]
    at: datetime = None
    # Comments: what they were on. Ads: what brought them.
    post_ref: str = ""
    ad: dict = field(default_factory=dict)
    # Telegram: a number the person shared about themselves.
    own_phone: str = ""
    # The identity kind the sender id belongs to (facebook comments differ).
    sender_kind: str = ""

    def __post_init__(self):
        if not self.sender_kind:
            self.sender_kind = SENDER_KIND.get(self.channel, "")


# ------------------------------------------------------------- settings ---
def meta_config():
    return {
        "page_id": (Setting.get("meta_page_id") or "").strip(),
        "token": (Setting.get("meta_page_token") or "").strip(),
        "app_secret": (Setting.get("meta_app_secret") or "").strip(),
        "verify_token": (Setting.get("meta_verify_token") or "").strip(),
        "version": ((Setting.get("meta_graph_version") or "").strip()
                    or DEFAULT_GRAPH_VERSION),
        "human_agent": (Setting.get("meta_human_agent") or "") == "1",
    }


def meta_ready():
    cfg = meta_config()
    return bool(cfg["page_id"] and cfg["token"] and cfg["app_secret"]
                and cfg["verify_token"])


def telegram_config():
    return {"token": (Setting.get("tg_bot_token") or "").strip(),
            "secret": (Setting.get("tg_webhook_secret") or "").strip()}


def telegram_ready():
    cfg = telegram_config()
    return bool(cfg["token"] and cfg["secret"])


# -------------------------------------------------------------- parsing ---
def _ms(value):
    """Meta's millisecond timestamps → UTC datetime."""
    try:
        return datetime.utcfromtimestamp(int(value) / 1000.0)
    except (TypeError, ValueError, OverflowError):
        return datetime.utcnow()


def _attachments(message):
    out = []
    for att in message.get("attachments") or []:
        if not isinstance(att, dict):
            continue
        payload = att.get("payload") if isinstance(att.get("payload"), dict) else {}
        out.append((str(att.get("type") or "file")[:20],
                    str(payload.get("url") or "")[:300]))
    return out


def _referral(message, event):
    """What brought them, when an ad or an ig.me/m.me link did."""
    ref = message.get("referral") or event.get("referral") or {}
    if not isinstance(ref, dict) or not (ref.get("ad_id") or ref.get("ref")):
        return {}
    ctx = ref.get("ads_context_data") if isinstance(ref.get("ads_context_data"), dict) else {}
    return {"ad_id": str(ref.get("ad_id") or ""), "ref": str(ref.get("ref") or ""),
            "ad_title": str(ctx.get("ad_title") or ""),
            "post_id": str(ctx.get("post_id") or "")}


def parse_meta(payload):
    """A signed Meta notification → ``[Inbound]``. Anything not a person's
    message, comment, deletion or the Page's own reply is left out."""
    if not isinstance(payload, dict):
        return []
    obj = payload.get("object")
    if obj not in ("page", "instagram"):
        return []
    channel = "messenger" if obj == "page" else "instagram"
    out = []
    for entry in payload.get("entry") or []:
        if not isinstance(entry, dict):
            continue
        own_id = str(entry.get("id") or "")
        for event in entry.get("messaging") or []:
            item = _meta_event(channel, own_id, event)
            if item is not None:
                out.append(item)
        for change in entry.get("changes") or []:
            item = _meta_change(channel, change)
            if item is not None:
                out.append(item)
    return out


def _meta_event(channel, own_id, event):
    if not isinstance(event, dict):
        return None
    message = event.get("message")
    if not isinstance(message, dict):
        # A postback (a button or ice-breaker) is the person writing too.
        postback = event.get("postback")
        if isinstance(postback, dict) and (event.get("sender") or {}).get("id"):
            return Inbound(channel=channel, kind="message",
                           sender_id=str(event["sender"]["id"]),
                           msg_id=str(postback.get("mid") or ""),
                           text=str(postback.get("title") or postback.get("payload") or ""),
                           at=_ms(event.get("timestamp")),
                           ad=_referral(postback, event))
        return None          # read, delivery, reaction: no message in them
    sender = str((event.get("sender") or {}).get("id") or "")
    recipient = str((event.get("recipient") or {}).get("id") or "")
    mid = str(message.get("mid") or "")
    if message.get("is_echo"):
        # The Page wrote: the person is the recipient.
        return Inbound(channel=channel, kind="echo", sender_id=recipient,
                       msg_id=mid, text=str(message.get("text") or ""),
                       media=_attachments(message), at=_ms(event.get("timestamp")))
    if not sender or sender == own_id:
        return None
    if message.get("is_deleted"):
        return Inbound(channel=channel, kind="deleted", sender_id=sender,
                       msg_id=mid, at=_ms(event.get("timestamp")))
    return Inbound(channel=channel, kind="message", sender_id=sender, msg_id=mid,
                   text=str(message.get("text") or ""),
                   media=_attachments(message), at=_ms(event.get("timestamp")),
                   ad=_referral(message, event))


def _meta_change(channel, change):
    if not isinstance(change, dict):
        return None
    value = change.get("value") if isinstance(change.get("value"), dict) else {}
    who = value.get("from") if isinstance(value.get("from"), dict) else {}
    if channel == "messenger":
        # Page feed: only a person adding a comment is a question to answer.
        if (change.get("field") != "feed" or value.get("item") != "comment"
                or value.get("verb") != "add" or not who.get("id")):
            return None
        return Inbound(channel="messenger", kind="comment",
                       sender_id=str(who["id"]), sender_kind="facebook_user",
                       msg_id=str(value.get("comment_id") or ""),
                       text=str(value.get("message") or ""),
                       name=str(who.get("name") or ""),
                       post_ref=str(value.get("post_id") or ""),
                       at=(datetime.utcfromtimestamp(int(value["created_time"]))
                           if str(value.get("created_time") or "").isdigit()
                           else datetime.utcnow()))
    if change.get("field") not in ("comments", "live_comments") or not who.get("id"):
        return None
    media = value.get("media") if isinstance(value.get("media"), dict) else {}
    # The two examples Meta publishes name the comment's id differently
    # (``id`` in one, ``comment_id`` in the other); both are read.
    comment_id = str(value.get("id") or value.get("comment_id") or "")
    ad = ({"ad_id": str(media.get("ad_id")), "ad_title": str(media.get("ad_title") or ""),
           "post_id": str(media.get("id") or ""), "ref": ""}
          if media.get("ad_id") else {})
    return Inbound(channel="instagram", kind="comment", sender_id=str(who["id"]),
                   msg_id=comment_id, text=str(value.get("text") or ""),
                   username=str(who.get("username") or ""),
                   post_ref=str(media.get("id") or ""), ad=ad,
                   at=datetime.utcnow())


def parse_telegram(update):
    """A Telegram update → ``[Inbound]``. Private chats only: a clinic's bot
    answers families, not groups."""
    if not isinstance(update, dict):
        return []
    message = update.get("message")
    if not isinstance(message, dict):
        return []
    chat = message.get("chat") if isinstance(message.get("chat"), dict) else {}
    who = message.get("from") if isinstance(message.get("from"), dict) else {}
    if chat.get("type") != "private" or who.get("is_bot") or not chat.get("id"):
        return []
    name = " ".join(filter(None, [str(who.get("first_name") or ""),
                                  str(who.get("last_name") or "")])).strip()
    media = []
    for kind in ("photo", "document", "voice", "audio", "video"):
        if message.get(kind):
            item = message[kind]
            file_id = (item[-1].get("file_id") if isinstance(item, list) and item
                       else (item.get("file_id") if isinstance(item, dict) else ""))
            media.append((kind, str(file_id or "")))
    own_phone = ""
    contact = message.get("contact") if isinstance(message.get("contact"), dict) else {}
    if contact and contact.get("user_id") and contact.get("user_id") == who.get("id"):
        own_phone = str(contact.get("phone_number") or "")
    try:
        at = datetime.utcfromtimestamp(int(message.get("date")))
    except (TypeError, ValueError, OverflowError):
        at = datetime.utcnow()
    return [Inbound(channel="telegram", kind="message", sender_id=str(chat["id"]),
                    msg_id=f"tg:{update.get('update_id')}",
                    text=str(message.get("text") or message.get("caption") or ""),
                    name=name, username=str(who.get("username") or ""),
                    media=media, at=at, own_phone=own_phone)]


# -------------------------------------------------------------- sending ---
class SendRefused(Exception):
    """A reply the platform would refuse — said before it is tried. ``code``
    names why for the screen: ``not_ready``, ``too_long``, ``window``,
    ``comment_used``, ``comment_old``."""

    def __init__(self, code):
        super().__init__(code)
        self.code = code


def _post(url, payload, headers=None, timeout=10):
    """POST JSON; ``(status, body)``. Kept in one place so tests replace it."""
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={"Content-Type": "application/json",
                                          **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")


def appsecret_proof(token, app_secret, now=None):
    """``(proof, time)`` as Meta's security guide gives it: HMAC-SHA256 of
    ``token|time`` keyed with the app secret, hex."""
    stamp = int(now if now is not None else time.time())
    proof = hmac.new(app_secret.encode("utf-8"),
                     f"{token}|{stamp}".encode("utf-8"),
                     hashlib.sha256).hexdigest()
    return proof, stamp


def check_length(channel, text):
    if channel == "instagram" and len(text.encode("utf-8")) > INSTAGRAM_MAX_BYTES:
        raise SendRefused("too_long")
    if channel == "messenger" and len(text) >= MESSENGER_MAX_CHARS:
        raise SendRefused("too_long")
    if channel == "telegram" and len(text) > TELEGRAM_MAX_CHARS:
        raise SendRefused("too_long")


def meta_mode(last_inbound, now=None, human_agent=False):
    """``RESPONSE`` inside the standard window, ``HUMAN_AGENT`` after it for
    up to seven days when the clinic's app is approved for that tag; else
    the reply is refused (``window``)."""
    now = now or datetime.utcnow()
    if last_inbound is None:
        raise SendRefused("window")
    age = now - last_inbound
    if age <= timedelta(hours=STANDARD_WINDOW_HOURS):
        return "RESPONSE"
    if human_agent and age <= timedelta(days=HUMAN_AGENT_DAYS):
        return "HUMAN_AGENT"
    raise SendRefused("window")


def send_meta(channel, recipient, text, mode="RESPONSE"):
    """Reply on Messenger or Instagram. ``recipient`` is ``{"id": …}`` or
    ``{"comment_id": …}``. Returns ``(ok, message_id, error)``."""
    cfg = meta_config()
    if not meta_ready():
        raise SendRefused("not_ready")
    check_length(channel, text)
    body = {"recipient": recipient, "message": {"text": text}}
    if "id" in recipient:
        if mode == "HUMAN_AGENT":
            body["messaging_type"] = "MESSAGE_TAG"
            body["tag"] = "HUMAN_AGENT"
        else:
            body["messaging_type"] = "RESPONSE"
    proof, stamp = appsecret_proof(cfg["token"], cfg["app_secret"])
    query = urllib.parse.urlencode({"access_token": cfg["token"],
                                    "appsecret_proof": proof,
                                    "appsecret_time": stamp})
    url = f"{GRAPH}/{cfg['version']}/{cfg['page_id']}/messages?{query}"
    try:
        status, raw = _post(url, body)
    except Exception as exc:  # noqa: BLE001 — a network failure is a failed send
        return False, None, str(exc)[:200]
    try:
        data = json.loads(raw or "{}")
    except ValueError:
        data = {}
    if 200 <= status < 300 and data.get("message_id"):
        return True, str(data["message_id"]), None
    err = (data.get("error") or {}) if isinstance(data, dict) else {}
    return False, None, (f"{err.get('code', status)}: {err.get('message', '')}"[:200]
                         if err else f"HTTP {status}")


def send_telegram(chat_id, text):
    """Reply on Telegram. Returns ``(ok, message_id, error)``."""
    cfg = telegram_config()
    if not telegram_ready():
        raise SendRefused("not_ready")
    check_length("telegram", text)
    try:
        status, raw = _post(f"{TELEGRAM}/bot{cfg['token']}/sendMessage",
                            {"chat_id": chat_id, "text": text})
    except Exception as exc:  # noqa: BLE001
        return False, None, str(exc)[:200]
    try:
        data = json.loads(raw or "{}")
    except ValueError:
        data = {}
    if data.get("ok"):
        return True, str((data.get("result") or {}).get("message_id") or ""), None
    return False, None, str(data.get("description") or f"HTTP {status}")[:200]


def telegram_set_webhook(url):
    """Point the bot at the clinic's webhook with its secret token. Returns
    ``(ok, description)``."""
    cfg = telegram_config()
    if not telegram_ready():
        raise SendRefused("not_ready")
    try:
        status, raw = _post(f"{TELEGRAM}/bot{cfg['token']}/setWebhook",
                            {"url": url, "secret_token": cfg["secret"],
                             "allowed_updates": ["message"]})
        data = json.loads(raw or "{}")
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)[:200]
    return bool(data.get("ok")), str(data.get("description") or "")[:200]


__all__ = ["DEFAULT_GRAPH_VERSION", "HUMAN_AGENT_DAYS", "Inbound",
           "PRIVATE_REPLY_DAYS", "SOCIAL_CHANNELS", "STANDARD_WINDOW_HOURS",
           "SendRefused", "appsecret_proof", "check_length", "meta_config",
           "meta_mode", "meta_ready", "parse_meta", "parse_telegram",
           "send_meta", "send_telegram", "telegram_config", "telegram_ready",
           "telegram_set_webhook"]
