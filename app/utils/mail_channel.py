"""The clinic's mailbox as a channel — IMAP in, SMTP out (``CONNECTHUB_PLAN.md``).

E-mail is standard protocol, not a vendor API, so this follows the RFCs and
Python's own ``imaplib``/``smtplib``/``email``:

* **reading** — new mail is found by UID (RFC 3501): the mailbox's
  ``UIDVALIDITY`` and the last UID read are kept, so nothing is read twice
  and nothing is skipped; messages are fetched with ``BODY.PEEK[]`` so the
  clinic's own mail client still sees them as unread;
* **one message once** — its ``Message-ID`` is the dedupe key;
* **never a loop** — mail marked ``Auto-Submitted`` (RFC 3834), bulk or list
  mail (``Precedence``, ``List-Id``) and mail from the clinic's own address
  is not filed; an out-of-hours note this sends says ``Auto-Submitted:
  auto-replied``, so a well-behaved mailbox never answers it back;
* **who wrote** is the From address — an identity, never the name;
* **a reply** goes in the same thread: ``Re:`` the subject, with
  ``In-Reply-To`` and ``References`` (RFC 5322);
* TLS is verified on both sides, with the system's trust store.

**Signing in.** A mailbox that takes a password (or an app password) signs
in with it. One that only allows OAuth — Microsoft 365, Outlook.com, and
Gmail without an app password — signs in with **SASL XOAUTH2**, the format
both providers document for IMAP ``AUTHENTICATE`` and SMTP ``AUTH``:
``base64("user=" user "^Aauth=Bearer " token "^A^A")`` (``^A`` is
``\\x01``); on a
failure the server sends an error challenge, answered with an empty line.
The token comes from the organisation's **own** OAuth app (its Google Cloud
client, its Microsoft Entra app registration — as with TikTok, the buyer
owns the app), by the authorization-code flow with ``state`` and PKCE
(S256):

* **Google** — ``accounts.google.com/o/oauth2/v2/auth`` with the scope
  ``https://mail.google.com/``, ``access_type=offline`` (or no refresh
  token comes back) and ``prompt=consent``; the code is exchanged at
  ``oauth2.googleapis.com/token``. Google lets a person untick a scope, so
  the scope granted is checked, not assumed;
* **Microsoft** — ``login.microsoftonline.com/{tenant}/oauth2/v2.0/
  authorize`` with ``https://outlook.office.com/IMAP.AccessAsUser.All``,
  ``https://outlook.office.com/SMTP.Send`` and ``offline_access``; a
  refresh may hand back a **new** refresh token, which replaces the old.

The access token lives about an hour and is renewed from the refresh token
when it has under five minutes left. A refresh token that stops working
(revoked, a password changed) is said on the channels screen — the box is
connected again, never silently skipped.

There is no webhook for mail: the box is read on a ``check now`` button and
on the same heartbeat that drains the WhatsApp queue (``maybe_poll``).
"""
import base64
import email
import email.policy
import email.utils
import imaplib
import json
import re
import smtplib
import ssl
import urllib.parse
from datetime import datetime, timedelta
from email.message import EmailMessage

from app.extensions import db
from app.models import MessageLog, Setting

POLL_MINUTES = 5
#: The most messages one pass reads — a first connection to a full box
#: starts from now, not from its first mail ten years ago.
BATCH = 25
TIMEOUT = 20
BODY_MAX = 4000


#: How the box signs in.
AUTH_MODES = ("password", "google", "microsoft")

#: Each provider's documented endpoints, scopes and mail servers.
PROVIDERS = {
    "google": {
        "authorize": "https://accounts.google.com/o/oauth2/v2/auth",
        "token": "https://oauth2.googleapis.com/token",
        "scope": "https://mail.google.com/",
        "imap": ("imap.gmail.com", 993), "smtp": ("smtp.gmail.com", 587),
    },
    "microsoft": {
        "authorize": "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize",
        "token": "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
        "scope": ("https://outlook.office.com/IMAP.AccessAsUser.All "
                  "https://outlook.office.com/SMTP.Send offline_access"),
        "imap": ("outlook.office365.com", 993), "smtp": ("smtp.office365.com", 587),
    },
}
#: Renew the access token when fewer than this many seconds are left.
RENEW_BEFORE = 300


class MailRefused(Exception):
    """The box cannot sign in — the reason is a short code."""

    def __init__(self, code):
        super().__init__(code)
        self.code = code


def auth_mode():
    mode = (Setting.get("mail_auth") or "password").strip()
    return mode if mode in AUTH_MODES else "password"


def oauth_config():
    tenant = (Setting.get("mail_oauth_tenant") or "").strip() or "common"
    return {
        "client_id": (Setting.get("mail_oauth_client_id") or "").strip(),
        "client_secret": Setting.get("mail_oauth_client_secret") or "",
        "tenant": re.sub(r"[^A-Za-z0-9.\-]", "", tenant)[:80] or "common",
        "refresh": Setting.get("mail_oauth_refresh") or "",
        "access": Setting.get("mail_oauth_access") or "",
        "until": Setting.get("mail_oauth_until") or "",
        "error": Setting.get("mail_oauth_error") or "",
    }


def config():
    return {
        "imap_host": (Setting.get("mail_imap_host") or "").strip(),
        "imap_port": int((Setting.get("mail_imap_port") or "993").strip() or 993),
        "smtp_host": (Setting.get("mail_smtp_host") or "").strip(),
        "smtp_port": int((Setting.get("mail_smtp_port") or "587").strip() or 587),
        "user": (Setting.get("mail_user") or "").strip(),
        "password": Setting.get("mail_password") or "",
        "address": (Setting.get("mail_address") or "").strip().lower(),
    }


def ready():
    cfg = config()
    base = bool(cfg["imap_host"] and cfg["smtp_host"] and cfg["user"]
                and cfg["address"])
    if auth_mode() == "password":
        return base and bool(cfg["password"])
    oc = oauth_config()
    return base and bool(oc["client_id"] and oc["refresh"])


# ---------------------------------------------------------------- OAuth ---
def _endpoint(mode, which):
    return PROVIDERS[mode][which].replace("{tenant}", oauth_config()["tenant"])


def pkce_pair():
    """A PKCE verifier and its S256 challenge (RFC 7636)."""
    import hashlib
    import secrets

    verifier = secrets.token_urlsafe(48)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return verifier, base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def authorize_url(redirect_uri, state, challenge):
    mode = auth_mode()
    if mode == "password":
        raise MailRefused("not_oauth")
    oc = oauth_config()
    if not oc["client_id"]:
        raise MailRefused("not_ready")
    params = {"client_id": oc["client_id"], "redirect_uri": redirect_uri,
              "response_type": "code", "scope": PROVIDERS[mode]["scope"],
              "state": state, "code_challenge": challenge,
              "code_challenge_method": "S256"}
    hint = (Setting.get("mail_user") or "").strip()
    if hint:
        params["login_hint"] = hint
    if mode == "google":
        params.update(access_type="offline", prompt="consent")
    else:
        params["response_mode"] = "query"
    return _endpoint(mode, "authorize") + "?" + urllib.parse.urlencode(params)


def _token_call(fields):
    from app.utils import social

    mode = auth_mode()
    oc = oauth_config()
    fields = {"client_id": oc["client_id"], **fields}
    if oc["client_secret"]:
        fields["client_secret"] = oc["client_secret"]
    return social._post_form(_endpoint(mode, "token"), fields)


def _store(data, now=None):
    now = now or datetime.utcnow()
    Setting.set("mail_oauth_access", data["access_token"])
    Setting.set("mail_oauth_until", (now + timedelta(
        seconds=int(data.get("expires_in") or 3600))).isoformat())
    if data.get("refresh_token"):
        Setting.set("mail_oauth_refresh", data["refresh_token"])
    Setting.set("mail_oauth_error", "")


def _granted(mode, data):
    """Whether the mail scope was granted — Google lets a person untick it."""
    if mode != "google" or "scope" not in data:
        return True
    return PROVIDERS["google"]["scope"] in str(data.get("scope") or "").split()


def exchange_code(code, redirect_uri, verifier):
    """The provider came back with a code: keep the tokens. ``(ok, said)``."""
    mode = auth_mode()
    if mode == "password" or not oauth_config()["client_id"]:
        raise MailRefused("not_ready")
    _, data = _token_call({"grant_type": "authorization_code", "code": code,
                           "redirect_uri": redirect_uri,
                           "code_verifier": verifier})
    if not data.get("access_token"):
        return False, str(data.get("error_description") or data.get("error") or "")[:200]
    if not _granted(mode, data):
        return False, "scope"
    if not data.get("refresh_token") and not oauth_config()["refresh"]:
        return False, "no_refresh_token"
    _store(data)
    return True, ""


def access_token(now=None):
    """A live access token, renewed from the refresh token when it is near
    its end. Raises :class:`MailRefused` when the box has to be connected
    again."""
    oc = oauth_config()
    now = now or datetime.utcnow()
    if not oc["refresh"]:
        raise MailRefused("not_ready")
    try:
        left = (datetime.fromisoformat(oc["until"]) - now).total_seconds()
    except ValueError:
        left = 0
    if oc["access"] and left > RENEW_BEFORE:
        return oc["access"]
    _, data = _token_call({"grant_type": "refresh_token",
                           "refresh_token": oc["refresh"],
                           **({"scope": PROVIDERS["microsoft"]["scope"]}
                              if auth_mode() == "microsoft" else {})})
    if not data.get("access_token"):
        said = str(data.get("error") or "refresh_failed")[:60]
        Setting.set("mail_oauth_error", said)
        db.session.commit()
        raise MailRefused(said)
    _store(data, now)
    db.session.commit()
    return data["access_token"]


def xoauth2(user, token):
    """The SASL XOAUTH2 initial response, before base64 (imaplib and
    smtplib encode it)."""
    return f"user={user}\x01auth=Bearer {token}\x01\x01"


def _answers(text):
    """The answers to a server's XOAUTH2 challenges: the response first,
    then the empty line both providers ask for after an error challenge."""
    sent = []

    def answer(challenge=None):
        if sent:
            return ""
        sent.append(1)
        return text
    return answer


# ------------------------------------------------------------- reading ---
def _is_automatic(msg, own):
    auto = (msg.get("Auto-Submitted") or "no").strip().lower()
    if auto != "no":
        return True
    if (msg.get("Precedence") or "").strip().lower() in ("bulk", "list", "junk"):
        return True
    if msg.get("List-Id"):
        return True
    _, sender = email.utils.parseaddr(msg.get("From") or "")
    return not sender or sender.lower() == own


_QUOTE_HEAD = re.compile(r"^(on .+ wrote:|في .+ كتب:|-----original message-----)",
                         re.IGNORECASE)


def _text_of(msg):
    """The new words in the message: the plain part, without the quoted
    thread under it."""
    part = msg.get_body(preferencelist=("plain", "html"))
    if part is None:
        return ""
    try:
        text = part.get_content()
    except (LookupError, ValueError):
        text = (part.get_payload(decode=True) or b"").decode("utf-8", "replace")
    if part.get_content_type() == "text/html":
        text = re.sub(r"<[^>]+>", " ", text)
    kept = []
    for line in text.splitlines():
        if line.strip().startswith(">") or _QUOTE_HEAD.match(line.strip()):
            break
        kept.append(line)
    return "\n".join(kept).strip()


def file_message(raw_bytes):
    """File one raw RFC 5322 message. Returns the log, or ``None`` when it
    was not a person writing (automatic, bulk, our own) or already filed."""
    from app.utils import leads, wa_media

    msg = email.message_from_bytes(raw_bytes, policy=email.policy.default)
    cfg = config()
    if _is_automatic(msg, cfg["address"]):
        return None
    msg_id = (msg.get("Message-ID") or "").strip()
    key = f"mail:{msg_id}"[:120] if msg_id else None
    if key and MessageLog.query.filter_by(provider_msg_id=key).first() is not None:
        return None
    name, sender = email.utils.parseaddr(msg.get("From") or "")
    contact = leads.contact_for(name or sender, {"email": sender})
    subject = str(msg.get("Subject") or "").strip()
    text = _text_of(msg)
    body = "\n".join(filter(None, [f"✉ {subject}" if subject else "", text])) or "[—]"
    # Filed at the time it was read: a sender's ``Date`` header is whatever
    # their machine said, and the inbox orders by what the clinic saw.
    log = MessageLog(direction="in", provider="email", channel="email",
                     contact_id=contact.id, patient_id=contact.patient_id,
                     body=body[:BODY_MAX], status="received",
                     provider_msg_id=key,
                     link=json.dumps({"subject": subject[:300], "message_id": msg_id}),
                     created_at=datetime.utcnow())
    db.session.add(log)
    db.session.flush()
    # The first picture or PDF attached — the same rules as WhatsApp's.
    for part in msg.iter_attachments():
        mime = part.get_content_type()
        if mime not in wa_media.MIME_EXT:
            continue
        data = part.get_payload(decode=True) or b""
        if not data or len(data) > wa_media.MAX_BYTES:
            continue
        stored = wa_media.store(data, mime)
        if stored:
            log.image_url = f"static/uploads/patient_docs/{stored}"
            if log.patient_id:
                from app.models import PatientAttachment
                kind = wa_media.kind_for(subject or text, mime)
                db.session.add(PatientAttachment(
                    patient_id=log.patient_id, filename=stored,
                    original_name=(part.get_filename() or subject)[:120] or None,
                    kind=kind, label=(subject or None) and subject[:160],
                    source="email",
                    investigation_id=wa_media.answered_order(log.patient_id, kind)))
            break
    from app.utils.service_desk import maybe_send_social_away
    maybe_send_social_away(log)
    return log


def _connect_imap(cfg):
    token = access_token() if auth_mode() != "password" else None
    box = imaplib.IMAP4_SSL(cfg["imap_host"], cfg["imap_port"],
                            ssl_context=ssl.create_default_context(),
                            timeout=TIMEOUT)
    if token is None:
        box.login(cfg["user"], cfg["password"])
    else:
        answer = _answers(xoauth2(cfg["user"], token))
        box.authenticate("XOAUTH2", lambda challenge: answer(challenge).encode())
    return box


def _smtp_login(server, cfg):
    if auth_mode() == "password":
        server.login(cfg["user"], cfg["password"])
        return
    server.ehlo()
    server.auth("XOAUTH2", _answers(xoauth2(cfg["user"], access_token())))


def poll():
    """Read the new mail. Returns ``(filed, error)``."""
    if not ready():
        return 0, "not_ready"
    cfg = config()
    try:
        box = _connect_imap(cfg)
    except MailRefused as exc:
        return 0, f"oauth: {exc.code}"[:200]
    except (OSError, imaplib.IMAP4.error) as exc:
        return 0, f"imap: {exc}"[:200]
    filed = 0
    try:
        typ, _ = box.select("INBOX", readonly=True)
        if typ != "OK":
            return 0, "imap: no INBOX"
        validity = (box.response("UIDVALIDITY")[1] or [b""])[0]
        validity = (validity or b"").decode() if isinstance(validity, bytes) else str(validity or "")
        last = Setting.get("mail_last_uid") or ""
        if validity != (Setting.get("mail_uidvalidity") or "") or not last.isdigit():
            # A new box (or one renumbered): start from what is there now.
            typ, data = box.uid("SEARCH", None, "ALL")
            uids = (data[0] or b"").split() if typ == "OK" else []
            Setting.set("mail_uidvalidity", validity)
            Setting.set("mail_last_uid", uids[-1].decode() if uids else "0")
            db.session.commit()
            return 0, None
        typ, data = box.uid("SEARCH", None, f"UID {int(last) + 1}:*")
        uids = [u for u in ((data[0] or b"").split() if typ == "OK" else [])
                if int(u) > int(last)][:BATCH]
        for uid in uids:
            typ, parts = box.uid("FETCH", uid, "(BODY.PEEK[])")
            raw = next((p[1] for p in parts or [] if isinstance(p, tuple)), None)
            if typ == "OK" and raw and file_message(raw) is not None:
                filed += 1
            Setting.set("mail_last_uid", uid.decode())
        db.session.commit()
        return filed, None
    finally:
        try:
            box.logout()
        except Exception:  # noqa: BLE001
            pass


def maybe_poll(min_gap_minutes=POLL_MINUTES):
    """Read the box at most every few minutes, from whichever screen's
    heartbeat comes first — the turn is taken with ``Setting.swap``, as the
    WhatsApp queue's is, so two workers never read it at once."""
    if not ready():
        return None
    try:
        now = datetime.utcnow()
        last = Setting._read("mail_last_poll")
        if last:
            try:
                if now - datetime.fromisoformat(last) < timedelta(minutes=min_gap_minutes):
                    return None
            except ValueError:
                pass
        if not Setting.swap("mail_last_poll", last, now.isoformat()):
            db.session.rollback()
            return None
        db.session.commit()
        return poll()
    except Exception:  # noqa: BLE001 — a heartbeat never breaks on mail
        db.session.rollback()
        return None


def after_response(response):
    """Read the box once the screen has its answer — a heartbeat request is
    never kept waiting on a mail server."""
    from flask import current_app

    if not ready():
        return response
    app = current_app._get_current_object()

    def work():
        with app.app_context():
            maybe_poll()
    response.call_on_close(work)
    return response


# ------------------------------------------------------------- sending ---
def send(to_address, body, last_inbound=None, automatic=False):
    """Reply by mail. ``last_inbound`` is the message being answered, for the
    subject and the thread headers. Returns ``(ok, message_id, error)``."""
    cfg = config()
    info = {}
    if last_inbound is not None:
        try:
            info = json.loads(last_inbound.link or "{}")
        except ValueError:
            info = {}
    subject = info.get("subject") or ""
    msg = EmailMessage()
    msg["From"] = cfg["address"]
    msg["To"] = to_address
    msg["Subject"] = (subject if subject.lower().startswith("re:")
                      else f"Re: {subject}" if subject else
                      (Setting.get("clinic_name") or "Clinic"))
    if info.get("message_id"):
        msg["In-Reply-To"] = info["message_id"]
        msg["References"] = info["message_id"]
    if automatic:
        msg["Auto-Submitted"] = "auto-replied"
    msg_id = email.utils.make_msgid(domain=cfg["address"].split("@")[-1] or None)
    msg["Message-ID"] = msg_id
    msg["Date"] = email.utils.formatdate(localtime=False)
    msg.set_content(body)
    context = ssl.create_default_context()
    try:
        if cfg["smtp_port"] == 465:
            server = smtplib.SMTP_SSL(cfg["smtp_host"], 465, context=context,
                                      timeout=TIMEOUT)
        else:
            server = smtplib.SMTP(cfg["smtp_host"], cfg["smtp_port"], timeout=TIMEOUT)
            server.starttls(context=context)
        with server:
            _smtp_login(server, cfg)
            server.send_message(msg)
    except MailRefused as exc:
        return False, None, f"oauth: {exc.code}"[:200]
    except (OSError, smtplib.SMTPException) as exc:
        return False, None, f"smtp: {exc}"[:200]
    return True, f"mail:{msg_id}"[:120], None


__all__ = ["AUTH_MODES", "MailRefused", "PROVIDERS", "access_token",
           "after_response", "auth_mode", "authorize_url", "config",
           "exchange_code", "file_message", "maybe_poll", "oauth_config",
           "pkce_pair", "poll", "ready", "send", "xoauth2"]
