"""Did any of it bring anybody back.

The desk can now send: a birthday, an overdue dose, a recall to a family
nobody has seen in a year. Nothing in the program could say whether that
was worth doing. The send log counts what left the building and the service
board counts how fast the clinic answers what arrives — neither of them
answers the only question a manager actually has about outbound, which is
whether it works.

**This is association, not cause, and the wording says so everywhere.** A
mother who books a week after a recall may well have been going to book
anyway. There is no way to tell from this data and pretending otherwise
would put a number on a screen that reads like proof. So the column is
"came back after", never "because of", and the docstring is here so the
next person to read the query knows the difference was deliberate.

**Only messages old enough to have worked are scored.** A recall sent
yesterday has had one day to produce a booking; counting it in the
denominator drags the rate down for no reason other than when somebody
happened to open the screen, which is how a metric becomes something people
explain away instead of act on. So the window is split: a message is
*mature* once ``FOLLOW_DAYS`` have passed, rates are computed on mature
messages alone, and the rest are reported separately as too recent to judge
rather than silently dropped — a number that quietly excludes things is
worse than one that shows its own gaps.

Two different returns are counted because they are two different facts. A
booking is the family responding; a visit is the family arriving. A recall
that fills the diary with appointments nobody attends has not worked, and
one number covering both would hide exactly that.

**The unit is the message, not the family, and where those differ both
messages get the credit.** Send one family a recall and a birthday in the
same fortnight and they book, and the booking is counted under each. That
is deliberate: the question each row answers is "when we send *this*, does a
booking follow?", which is the question that decides whether to keep sending
it, and the alternative is either dropping the signal from both or guessing
which one worked. There is nothing in the data that could tell them apart —
the same reason the screen says "after" and not "because of" — so a total
here reads as messages followed by a booking, not as families who came.

Everything here is computed from rows that already exist — no column was
added for it. A column filled going forward would have been cheaper to read
and would have started at zero on the day it shipped, and a manager cannot
wait a month to find out whether the recall is worth sending.
"""
from datetime import datetime, timedelta

# How long a message is given to produce a booking before it is judged. Short
# on purpose: past a fortnight, "they came back after the message" stops
# meaning very much even as association.
FOLLOW_DAYS = 14

# The reasons the desk sends for. Keyed by `MessageLog.template_type`, which
# is what the sending code already writes, so nothing here needs maintaining
# in step with the senders — an unknown type simply shows up under its own
# name rather than being dropped.
KNOWN_REASONS = ["patient_recall", "vaccine_due", "birthday",
                 "appointment_reminder"]


def _moment(log):
    """When the clinic actually said it.

    ``sent_at`` is the truth and ``created_at`` is the fallback: a row queued
    and sent later would otherwise be scored from the moment it was written,
    giving the message credit for days it had not been said in.
    """
    return log.sent_at or log.created_at


def reach_report(days=30, now=None, follow_days=FOLLOW_DAYS):
    """Per reason: how many went out, and how many of those families came back.

    Three queries, not one per message: the sends in the window, then every
    booking and every visit made since the earliest of them, matched up in
    memory. Per-message queries would be a screen that gets slower every
    month the clinic uses it.
    """
    from app.extensions import db
    from app.models import Appointment, MessageLog, Visit

    now = now or datetime.utcnow()
    since = now - timedelta(days=days)
    mature_before = now - timedelta(days=follow_days)

    sends = (MessageLog.query
             .filter(MessageLog.direction != "in",
                     MessageLog.status == "sent",
                     MessageLog.patient_id.isnot(None))
             .all())
    sends = [s for s in sends
             if _moment(s) is not None and _moment(s) >= since]

    if not sends:
        return {"days": days, "follow_days": follow_days, "rows": [],
                "totals": _blank_row("")}

    earliest = min(_moment(s) for s in sends)

    # Bookings by the moment the booking was *made*, not the day booked for:
    # an appointment already in the diary before the message went out was not
    # a response to it.
    booked = {}
    for pid, made in (db.session.query(Appointment.patient_id,
                                       Appointment.created_at)
                      .filter(Appointment.created_at >= earliest).all()):
        if made is not None:
            booked.setdefault(pid, []).append(made)

    attended = {}
    for pid, made in (db.session.query(Visit.patient_id, Visit.created_at)
                      .filter(Visit.created_at >= earliest).all()):
        if made is not None:
            attended.setdefault(pid, []).append(made)

    buckets = {}
    for log in sends:
        reason = log.template_type or "other"
        buckets.setdefault(reason, []).append(log)

    rows = [_score(reason, logs, booked, attended, mature_before, follow_days)
            for reason, logs in buckets.items()]
    # Most-sent first: the reason the clinic spends the most breath on is the
    # one whose rate matters most.
    rows.sort(key=lambda r: -r["sent"])

    totals = _score("", sends, booked, attended, mature_before, follow_days)
    return {"days": days, "follow_days": follow_days,
            "rows": rows, "totals": totals}


def _blank_row(reason):
    return {"reason": reason, "sent": 0, "mature": 0, "too_recent": 0,
            "booked": 0, "attended": 0, "booked_rate": None,
            "attended_rate": None, "median_days": None}


def _score(reason, logs, booked, attended, mature_before, follow_days):
    """One row of the table: sends, and what followed them."""
    row = _blank_row(reason)
    row["sent"] = len(logs)

    gaps = []
    for log in logs:
        said = _moment(log)
        if said > mature_before:
            row["too_recent"] += 1
            continue
        row["mature"] += 1
        deadline = said + timedelta(days=follow_days)

        after = [m for m in booked.get(log.patient_id, [])
                 if said < m <= deadline]
        if after:
            row["booked"] += 1
            gaps.append((min(after) - said).total_seconds() / 86400.0)

        if any(said < m <= deadline for m in attended.get(log.patient_id, [])):
            row["attended"] += 1

    if row["mature"]:
        row["booked_rate"] = round(row["booked"] * 100.0 / row["mature"], 1)
        row["attended_rate"] = round(row["attended"] * 100.0 / row["mature"], 1)
    row["median_days"] = _median(sorted(gaps))
    return row


def _median(values):
    """The ordinary wait, not the average one.

    One family who booked on day thirteen drags a mean somewhere nobody
    recognises; the median says what usually happened.
    """
    if not values:
        return None
    middle = len(values) // 2
    if len(values) % 2:
        return round(values[middle], 1)
    return round((values[middle - 1] + values[middle]) / 2, 1)


def delivery_health(days=30, now=None, limit=8):
    """What is failing to arrive, and which numbers keep failing.

    Grouped by the provider's own error text because that is what
    distinguishes "this number is not on WhatsApp" — a wrong number in a
    patient file, which somebody can go and fix — from the connection being
    down, which is nobody at the desk's problem. A single failure count
    conflates the two and so gets ignored.
    """
    from app.extensions import db
    from app.models import MessageLog

    now = now or datetime.utcnow()
    since = now - timedelta(days=days)

    rows = (MessageLog.query
            .filter(MessageLog.direction != "in",
                    MessageLog.status == "failed",
                    MessageLog.created_at >= since)
            .all())

    by_error, by_number = {}, {}
    for log in rows:
        by_error[log.error or "—"] = by_error.get(log.error or "—", 0) + 1
        if log.to_phone:
            by_number[log.to_phone] = by_number.get(log.to_phone, 0) + 1

    sent = (db.session.query(db.func.count(MessageLog.id))
            .filter(MessageLog.direction != "in",
                    MessageLog.status == "sent",
                    MessageLog.created_at >= since).scalar() or 0)

    return {
        "days": days,
        "failed": len(rows),
        "sent": sent,
        "fail_rate": (round(len(rows) * 100.0 / (len(rows) + sent), 1)
                      if (len(rows) + sent) else None),
        "by_error": sorted(({"error": k, "count": v}
                            for k, v in by_error.items()),
                           key=lambda r: -r["count"])[:limit],
        # A number that failed once was a blip; one that failed repeatedly is
        # almost always a wrong number sitting in a patient file.
        "repeat_numbers": sorted(({"phone": k, "count": v}
                                  for k, v in by_number.items() if v > 1),
                                 key=lambda r: -r["count"])[:limit],
    }
