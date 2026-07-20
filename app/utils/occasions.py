"""Occasion campaigns (عيد الفطر، عيد الأم، ذكرى العيادة…).

A seasonal/greeting template can carry an ``occasion_date``. When that day
arrives the campaign is *queued*, not blasted: one message per family (dedup
by guardian phone, opt-outs skipped) enters the normal outbox as scheduled
rows, and ``dispatch_due`` drains them under the clinic's daily cap and send
window — whatever doesn't fit today rolls to tomorrow until the campaign is
done. The campaign report then shows how many went out over how many days.

Recurrence: ``yearly`` re-arms the same Gregorian day next year (عيد الأم,
clinic anniversary). Hijri events (رمضان/العيدين) shift ~11 days back each
year, so they stay ``once`` and the clinic sets next year's date by hand —
the campaigns panel highlights any occasion left without an upcoming date.
"""
from datetime import date, datetime

from sqlalchemy import func

from app.extensions import db
from app.models import MessageLog, MessageTemplate, Patient


def _next_year(d):
    try:
        return d.replace(year=d.year + 1)
    except ValueError:          # Feb 29 → Feb 28 next year
        return d.replace(year=d.year + 1, day=28)


def _recipients():
    """One patient per family: active, not opted out, with a reachable phone
    (contact_phone is derived — own phone, else a guardian's), de-duplicated
    by that phone so one household gets one greeting, not one per sibling."""
    seen, out = set(), []
    rows = (Patient.query
            .filter(Patient.is_active.is_(True),
                    Patient.wa_opt_out.is_(False))
            .order_by(Patient.id).all())
    for p in rows:
        phone = p.contact_phone
        key = "".join(ch for ch in (phone or "") if ch.isdigit())
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out


def enqueue_occasion(tpl, user_id=None, on_date=None):
    """Queue one campaign run of ``tpl`` (idempotent per occasion date).

    Creates scheduled MessageLog rows the dispatcher drains under the daily
    cap. Marks the occasion date as enqueued and, for yearly campaigns,
    re-arms next year's date. Returns the number of messages queued."""
    from app.utils import whatsapp as wa

    on_date = on_date or tpl.occasion_date or date.today()
    if tpl.last_enqueued_on and tpl.last_enqueued_on >= on_date:
        return 0                      # this occasion was already queued
    from datetime import timedelta

    from app.models import Setting
    cfg = wa.get_config()
    now = datetime.utcnow()
    clinic = Setting.get("clinic_name_ar") or Setting.get("clinic_name") or ""
    # Smart pacing: plan the whole campaign upfront against the daily cap —
    # the first cap-full is due now, the next cap-full tomorrow at the window
    # start, and so on. The dispatcher still enforces the cap live (operational
    # messages sent today shrink what a campaign day can take).
    cap = cfg.get("daily_cap", 0) or 0
    win_start = max(cfg.get("send_from", 0), 0)
    queued = 0
    for i, p in enumerate(_recipients()):
        day = (i // cap) if cap > 0 else 0
        when = now if day == 0 else (
            (now + timedelta(days=day)).replace(hour=win_start, minute=0,
                                                second=0, microsecond=0))
        body = wa.render(tpl.body, {
            "patient": p.display_name("ar"), "clinic": clinic})
        db.session.add(MessageLog(
            patient_id=p.id, to_phone=p.contact_phone, body=body,
            image_url=tpl.image_url, provider=cfg.get("provider"),
            status="scheduled", scheduled_at=when,
            template_type=tpl.occasion, template_id=tpl.id,
            created_by=user_id))
        queued += 1

    tpl.last_enqueued_on = on_date
    if tpl.repeat_rule == "yearly" and tpl.occasion_date:
        tpl.occasion_date = _next_year(tpl.occasion_date)
    db.session.flush()
    return queued


def enqueue_due_occasions(user_id=None):
    """Queue every active campaign whose occasion date has arrived. Called by
    the dispatcher, so the existing send-due button/CLI drives campaigns too."""
    today = date.today()
    total = 0
    due = (MessageTemplate.query
           .filter(MessageTemplate.is_active.is_(True),
                   MessageTemplate.occasion_date.isnot(None),
                   MessageTemplate.occasion_date <= today)
           .all())
    for tpl in due:
        if tpl.last_enqueued_on and tpl.last_enqueued_on >= tpl.occasion_date:
            continue
        total += enqueue_occasion(tpl, user_id=user_id,
                                  on_date=tpl.occasion_date)
    return total


def campaign_report(tpl):
    """Roll-up of the template's latest campaign: totals per status, and how
    many days the sending actually spanned (the queue trickles under the cap)."""
    rows = (db.session.query(MessageLog.status, func.count(MessageLog.id))
            .filter(MessageLog.template_id == tpl.id)
            .group_by(MessageLog.status).all())
    by_status = {s: int(n) for s, n in rows}
    days = (db.session.query(func.count(func.distinct(func.date(MessageLog.sent_at))))
            .filter(MessageLog.template_id == tpl.id,
                    MessageLog.sent_at.isnot(None)).scalar() or 0)
    total = sum(by_status.values())
    return {
        "total": total,
        "sent": by_status.get("sent", 0) + by_status.get("link", 0),
        "pending": by_status.get("scheduled", 0) + by_status.get("queued", 0),
        "failed": by_status.get("failed", 0),
        "skipped": by_status.get("skipped", 0),
        "days": int(days),
    }
