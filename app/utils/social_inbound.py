"""Filing what Messenger, Instagram and Telegram send into the one inbox.

``CONNECTHUB_PLAN.md`` stage two. ``utils/social`` reads the platform's
notification into one shape; this decides what it means here:

* **the same notification twice is one message** — Meta says outright that
  it retries and the receiver deduplicates; Telegram repeats ``update_id``;
* **who wrote is an identity, never a name** (``utils/leads``): the
  platform's id for them, their handle, the number they shared about
  themselves on Telegram. A child's file is linked by a person, so a
  message lands on a file only when somebody already linked that contact;
* **a deleted message is deleted** — Instagram's terms require it;
* **a comment** is filed as a comment, to be answered once and privately,
  and is a lead: somebody asked in public;
* **an ad or a link with a ``ref``** that brought them becomes the lead's
  campaign, so "which ad brings bookings" is read from the families
  themselves;
* **the Page's own replies** (typed in Meta's inbox) are kept as outbound,
  so the thread here is the whole conversation.

Nothing here sends anything. The caller commits.
"""
from datetime import datetime, timedelta

from app.extensions import db
from app.models import MessageLog
from app.utils import leads
from app.utils.social import SENDER_KIND

#: A platform timestamp further in the future than this is not believed.
_CLOCK_SLACK = timedelta(minutes=5)


def thread_key_for(contact):
    return f"p{contact.patient_id}" if contact.patient_id else f"c{contact.id}"


def _when(item):
    now = datetime.utcnow()
    at = item.at or now
    return at if at <= now + _CLOCK_SLACK else now


def _body(item):
    lines = [item.text.strip()] if item.text and item.text.strip() else []
    for kind, ref in item.media:
        lines.append(f"[{kind}]" + (f" {ref}" if ref.startswith("http") else ""))
    return "\n".join(lines) or "[—]"


def _identities(item):
    ids = {item.sender_kind or SENDER_KIND[item.channel]: item.sender_id}
    if item.username and item.channel in ("instagram", "telegram"):
        ids[item.channel] = item.username
    if item.own_phone:
        ids["phone"] = item.own_phone
    return ids


def _seen(msg_id):
    return bool(msg_id) and db.session.query(
        MessageLog.query.filter_by(provider_msg_id=msg_id).exists()).scalar()


def _campaign(item):
    ad = item.ad or {}
    return ad.get("ad_title") or ad.get("ref") or ad.get("ad_id") or None


def receive(item):
    """File one :class:`~app.utils.social.Inbound`. Returns ``{"status",
    "key", "lead"}`` — status is ``filed``, ``duplicate``, ``deleted`` or
    ``ignored``."""
    if item.kind == "deleted":
        rows = (MessageLog.query.filter_by(provider_msg_id=item.msg_id,
                                           direction="in").all()
                if item.msg_id else [])
        for row in rows:
            db.session.delete(row)
        return {"status": "deleted", "key": None, "lead": None}
    if not item.sender_id:
        return {"status": "ignored", "key": None, "lead": None}
    if _seen(item.msg_id):
        return {"status": "duplicate", "key": None, "lead": None}

    name = (item.name or (f"@{item.username}" if item.username else "")
            or f"{item.channel} …{item.sender_id[-4:]}")
    contact = leads.contact_for(name, _identities(item))
    log = MessageLog(
        direction="out" if item.kind == "echo" else "in",
        provider=item.channel, channel=item.channel, contact_id=contact.id,
        patient_id=contact.patient_id, body=_body(item)[:4000],
        status="sent" if item.kind == "echo" else "received",
        provider_msg_id=item.msg_id or None,
        event={"comment": "comment", "echo": "echo"}.get(item.kind),
        image_url=next((ref for kind, ref in item.media
                        if kind == "image" and ref.startswith("http")), None),
        created_at=_when(item), sent_at=_when(item) if item.kind == "echo" else None)
    db.session.add(log)
    db.session.flush()
    key = thread_key_for(contact)

    lead = None
    if item.kind == "comment" or item.ad:
        # Somebody asked in public, or an ad brought them: a lead with where
        # they came from. One open lead per person — a second comment is a
        # step on the first.
        post_url = (f"https://www.facebook.com/{item.post_ref}"
                    if item.kind == "comment" and item.channel == "messenger"
                    and item.post_ref else None)
        lead, _ = leads.open_lead(
            None, contact.name, _identities(item), item.channel,
            source_kind="comment" if item.kind == "comment" else "ad",
            campaign=_campaign(item) or (item.post_ref or None),
            source_url=post_url, message=item.text or None,
            conversation_key=key)
    return {"status": "filed", "key": key, "lead": lead}


__all__ = ["receive", "thread_key_for"]
