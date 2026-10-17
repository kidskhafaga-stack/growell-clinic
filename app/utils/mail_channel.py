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

Accounts that only allow OAuth (Microsoft 365, and Google without an app
password) are not covered here — a mailbox that accepts IMAP/SMTP with a
password or an app password is.

There is no webhook for mail: the box is read on a ``check now`` button and
on the same heartbeat that drains the WhatsApp queue (``maybe_poll``).
"""
import email
import email.policy
import email.utils
import imaplib
import json
import re
import smtplib
import ssl
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
    return bool(cfg["imap_host"] and cfg["smtp_host"] and cfg["user"]
                and cfg["password"] and cfg["address"])


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
    box = imaplib.IMAP4_SSL(cfg["imap_host"], cfg["imap_port"],
                            ssl_context=ssl.create_default_context(),
                            timeout=TIMEOUT)
    box.login(cfg["user"], cfg["password"])
    return box


def poll():
    """Read the new mail. Returns ``(filed, error)``."""
    if not ready():
        return 0, "not_ready"
    cfg = config()
    try:
        box = _connect_imap(cfg)
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
            server.login(cfg["user"], cfg["password"])
            server.send_message(msg)
    except (OSError, smtplib.SMTPException) as exc:
        return False, None, f"smtp: {exc}"[:200]
    return True, f"mail:{msg_id}"[:120], None


__all__ = ["after_response", "config", "file_message", "maybe_poll", "poll",
           "ready", "send"]
