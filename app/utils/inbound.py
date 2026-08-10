"""Inbound WhatsApp handling — provider-agnostic normalize + route.

Normalizes Meta Cloud API and WaPilot v2 webhook payloads to one shape, matches
the sender to a patient — a guardian's number, the patient's own, or a number
reception linked by hand — logs the message, saves any file it carries onto
the patient's record, and, when it is a rating reply, fills the patient's open
satisfaction survey. The result lands in
the same ``Feedback`` model, so the existing stars/analytics keep working; only
the collection *channel* differs.
"""
import re
from datetime import datetime, timedelta

from app.extensions import db
from app.models import Feedback, MessageLog
from app.utils.whatsapp import normalize_phone


# --- Provider payload normalizers --------------------------------------
def normalize_meta(payload):
    """Meta Cloud API webhook → list of normalized items."""
    items = []
    for entry in (payload or {}).get("entry", []):
        for change in entry.get("changes", []):
            for m in (change.get("value") or {}).get("messages", []):
                items.append(_meta_message(m))
    return [i for i in items if i and i.get("from_phone")]


def _meta_message(m):
    mtype = m.get("type")
    item = {"from_phone": m.get("from"), "text": None, "button_id": None, "media": None}
    if mtype == "text":
        item["text"] = (m.get("text") or {}).get("body")
    elif mtype == "interactive":
        inter = m.get("interactive") or {}
        reply = inter.get("button_reply") or inter.get("list_reply") or {}
        item["button_id"] = reply.get("id")
        item["text"] = reply.get("title")
    elif mtype in ("image", "document", "audio", "video"):
        media = m.get(mtype) or {}
        item["media"] = {"id": media.get("id"), "mime": media.get("mime_type"), "kind": mtype}
        item["text"] = media.get("caption")
    return item


def normalize_meta_statuses(payload):
    """Meta delivery receipts → ``{msg_id, status, error}`` items.

    The same webhook that carries a family's reply also carries these, in
    ``value["statuses"]`` — and this program read only ``value["messages"]``
    and dropped them on the floor. That is why a message here could never say
    more than "the provider accepted it": a number disconnected a year ago and
    a message somebody read looked exactly alike on every screen.

    Meta's own vocabulary is kept (``sent`` / ``delivered`` / ``read`` /
    ``failed``) rather than translated, so what the log says and what the Meta
    dashboard says are the same word.
    """
    items = []
    for entry in (payload or {}).get("entry", []):
        for change in entry.get("changes", []):
            for st in (change.get("value") or {}).get("statuses", []):
                items.append({
                    "msg_id": st.get("id"),
                    "status": st.get("status"),
                    "error": _status_error(st),
                })
    return [i for i in items if i.get("msg_id") and i.get("status")]


def _status_error(st):
    """The provider's own words for why a message failed, or None.

    Shown as it arrived. "This number is not on WhatsApp" is something
    reception can act on; a code is something they will ask somebody about.
    """
    errors = st.get("errors") or []
    if not errors:
        return None
    first = errors[0] or {}
    text = (first.get("title") or first.get("message")
            or str(first.get("code") or ""))
    return (text or None) and text[:200]


def apply_status(item):
    """Record one delivery receipt against the message it belongs to.

    Two rules, both learned from how these actually arrive:

    * **Only ever upward.** Receipts come out of order — a ``delivered`` lands
      after a ``read`` often enough that a plain assignment would quietly
      downgrade the better fact and the clinic would read fewer opens than
      really happened.
    * **``failed`` always wins.** It is not a rung on the ladder; it is the
      message not arriving, and it is the one status somebody has to act on.

    Returns the row it touched, or None when the id is unknown — a receipt for
    a message this clinic never sent is not an error, it is a webhook for
    somebody else's message or one sent before this column existed.
    """
    from app.models import DELIVERY_RANK

    row = (MessageLog.query
           .filter_by(provider_msg_id=item.get("msg_id")).first())
    if row is None:
        return None
    incoming = item.get("status")
    if incoming == "failed":
        row.status = "failed"
        row.error = item.get("error") or row.error or "provider_failed"
        return row
    if incoming not in DELIVERY_RANK:
        return None
    if DELIVERY_RANK[incoming] > DELIVERY_RANK.get(row.status, 0):
        row.status = incoming
    return row


def normalize_wapilot(payload):
    """WaPilot v2 ``message`` webhook → list of normalized items."""
    m = (payload or {}).get("message") or {}
    if not m:
        return []
    reply = m.get("list_reply") or m.get("button_reply") or {}
    return [{
        "from_phone": m.get("chat_id") or m.get("from"),
        "text": m.get("text"),
        "button_id": reply.get("id") or m.get("button_id"),
        "media": None,
    }]


# --- Matching + rating capture -----------------------------------------
def _match_patients(phone):
    """Who this number belongs to: a guardian's family, the patient's own
    number, or whoever reception already said it was."""
    from app.utils.inbox import known_patient_for_phone, match_patients

    found = match_patients(phone)
    if found:
        return found
    # Nothing on file matches, but a human may have linked this number to a
    # patient before — that decision stands for every message after it.
    known = known_patient_for_phone(normalize_phone(phone))
    return [known] if known is not None else []


_RATE_RE = re.compile(r"([0-9]{1,2})")


def _extract_rating(item):
    """A 1..5 rating from a button id (``rate_5``) or a numeric reply."""
    raw = (item.get("button_id") or item.get("text") or "").strip()
    if not raw:
        return None
    m = _RATE_RE.search(raw)
    if not m:
        return None
    try:
        n = int(m.group(1))
    except ValueError:
        return None
    return n if 1 <= n <= 5 else None


def _capture_rating(patients, item):
    """Fill the most recent open survey for these patients from a reply."""
    if not patients:
        return False
    rating = _extract_rating(item)
    if rating is None:
        return False
    pids = [p.id for p in patients]
    fb = (Feedback.query
          .filter(Feedback.patient_id.in_(pids), Feedback.status == "sent",
                  Feedback.created_at >= datetime.utcnow() - timedelta(days=14))
          .order_by(Feedback.created_at.desc()).first())
    if fb is None:
        return False
    fb.doctor_rating = rating
    fb.status = "submitted"
    fb.submitted_at = datetime.utcnow()
    return True


def handle_inbound(item, provider):
    """Log one normalized inbound message and capture a rating if present.

    Caller commits. Returns ``{"matched", "captured"}``.
    """
    phone = normalize_phone(item.get("from_phone"))
    patients = _match_patients(phone)
    body = (item.get("text") or item.get("button_id")
            or ("[media]" if item.get("media") else ""))
    log = MessageLog(direction="in", provider=provider, to_phone=phone,
                     body=body or "", status="received",
                     patient_id=(patients[0].id if patients else None))
    db.session.add(log)
    # A file is usually the X-ray or the lab report the doctor asked for.
    # Download it and file it on the child's record — noticing that a file
    # existed and then throwing it away is worse than not supporting files.
    attachment = None
    if item.get("media"):
        from app.utils.wa_media import capture
        db.session.flush()
        attachment = capture(item, log)
    captured = _capture_rating(patients, item)
    # Outside working hours, say so — a parent writing at 1 a.m. shouldn't be
    # left wondering whether the message arrived at all. At most once a day
    # per conversation, and never for a reply that just answered a survey.
    away = None
    if not captured:
        from app.utils.service_desk import maybe_send_away_reply
        away = maybe_send_away_reply(log)
    return {"matched": bool(patients), "captured": captured,
            "away": away is not None, "attachment": attachment is not None}
