"""Replying on Messenger, Instagram, Telegram, TikTok and e-mail — the one place the
platforms' reply rules are applied (``CONNECTHUB_PLAN.md``).

The inbox screen and the out-of-hours reply both come through here, so a
rule cannot hold on one and not the other:

* a **comment** is answered once, privately, within seven days (Meta); on
  TikTok it is answered in TikTok itself;
* Messenger and Instagram: inside 24 hours of the person's last message,
  then only a **person** under the human-agent tag, when the clinic's app
  is approved for it — an automatic message never uses that tag;
* TikTok: ten replies within 48 hours of the person's last message;
* Telegram: whenever the person has written to the bot;
* e-mail: no window — in the same thread, ``Re:`` its subject.

A refusal is returned before anything is tried. Every reply that is tried
is logged in the thread, sent or failed. The caller commits.
"""
from datetime import datetime, timedelta

from app.extensions import db
from app.models import MessageLog
from app.utils import social


def _last_inbound(msgs, channel):
    return next((m for m in reversed(msgs) if m.direction == "in"
                 and m.channel_key == channel), None)


def reply_state(channel, msgs, automated=False):
    """What a reply on ``channel`` may be right now: ``{"ready", "comment",
    "comment_open", "mode", "refused"}`` — ``None`` for WhatsApp."""
    if channel not in social.SOCIAL_CHANNELS:
        return None
    from app.utils import mail_channel

    ready = {"telegram": social.telegram_ready, "tiktok": social.tiktok_ready,
             "email": mail_channel.ready}.get(channel, social.meta_ready)()
    state = {"ready": ready, "comment": None, "comment_open": False,
             "mode": None, "refused": None}
    last_in = _last_inbound(msgs, channel)
    if channel == "email":
        # Mail has no window: a reply goes whenever somebody writes it.
        state["mode"] = "RESPONSE"
        return state
    if channel == "tiktok":
        state["comment"] = last_in if (last_in is not None
                                       and last_in.event == "comment") else None
        if state["comment"] is None:
            since = [m for m in msgs if m.direction == "out"
                     and m.channel_key == "tiktok" and last_in is not None
                     and m.created_at >= last_in.created_at]
            try:
                state["mode"] = social.tiktok_mode(
                    last_in.created_at if last_in else None, len(since))
            except social.SendRefused as exc:
                state["refused"] = exc.code
        return state
    if last_in is not None and last_in.event == "comment":
        used = MessageLog.query.filter_by(
            reply_to=last_in.provider_msg_id, event="private_reply").first()
        state["comment"] = last_in
        state["comment_open"] = (
            used is None and last_in.created_at >= datetime.utcnow()
            - timedelta(days=social.PRIVATE_REPLY_DAYS))
        return state
    if channel in social.META_CHANNELS:
        try:
            state["mode"] = social.meta_mode(
                last_in.created_at if last_in else None,
                # The human-agent tag is for a person's reply, never an
                # automatic one (Meta's policy).
                human_agent=social.meta_config()["human_agent"] and not automated)
        except social.SendRefused as exc:
            state["refused"] = exc.code
    return state


def reply(key, channel, body, user_id=None, template_type=None, automated=False):
    """Send ``body`` in thread ``key`` on ``channel``. Returns ``(log,
    None)`` when it was tried (sent or failed), or ``(None, code)`` when it
    was refused before being tried."""
    from app.utils.inbox import thread_query

    msgs = thread_query(key).order_by(MessageLog.created_at).all()
    last_in = _last_inbound(msgs, channel)
    if last_in is None or last_in.contact is None:
        return None, "no_contact"
    contact = last_in.contact
    state = reply_state(channel, msgs, automated=automated)
    event = reply_to = None
    try:
        if not state["ready"]:
            raise social.SendRefused("not_ready")
        if state["comment"] is not None:
            if channel == "tiktok":
                raise social.SendRefused("tiktok_comment")
            if automated or not state["comment_open"]:
                # The one private reply a comment gets is a person's.
                raise social.SendRefused("comment_used")
            event, reply_to = "private_reply", last_in.provider_msg_id
            ok, msg_id, error = social.send_meta(
                channel, {"comment_id": reply_to}, body)
        elif channel == "email":
            from app.utils import mail_channel
            ident = contact.identity("email")
            if ident is None:
                raise social.SendRefused("not_ready")
            ok, msg_id, error = mail_channel.send(ident.value, body, last_in,
                                                  automatic=automated)
        elif channel == "telegram":
            ident = contact.identity("telegram_id")
            if ident is None:
                raise social.SendRefused("not_ready")
            ok, msg_id, error = social.send_telegram(ident.value, body)
        elif channel == "tiktok":
            if state["refused"]:
                raise social.SendRefused(state["refused"])
            ident = contact.identity("tiktok_conversation")
            if ident is None:
                raise social.SendRefused("window")
            ok, msg_id, error = social.send_tiktok(ident.value, body)
        else:
            if state["refused"]:
                raise social.SendRefused(state["refused"])
            ident = contact.identity(social.SENDER_KIND[channel])
            if ident is None:
                raise social.SendRefused("window")
            ok, msg_id, error = social.send_meta(
                channel, {"id": ident.value}, body, mode=state["mode"])
    except social.SendRefused as exc:
        return None, exc.code
    now = datetime.utcnow()
    log = MessageLog(
        direction="out", provider=channel, channel=channel,
        contact_id=contact.id, patient_id=last_in.patient_id, body=body,
        status="sent" if ok else "failed", provider_msg_id=msg_id or None,
        error=error, event=event, reply_to=reply_to,
        template_type=template_type, created_by=user_id, created_at=now,
        sent_at=now if ok else None)
    db.session.add(log)
    db.session.flush()
    return log, None


__all__ = ["reply", "reply_state"]
