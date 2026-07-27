"""Does this clinic answer people, and how fast.

Everything else in the desk module is about handling one conversation. This
is the question a manager actually has, and until now nothing in the program
could answer it: the send screen counted messages by status, which says how
the *provider* is doing, not how the clinic is doing.

Three numbers matter, in this order:

* **how long the first answer takes** — the one the family experiences;
* **how many got no answer at all before the window shut** — money and
  goodwill, both gone quietly;
* **who is carrying the work** — because "someone will answer it" is how a
  message goes unanswered for two days.

Computed from the message log rather than from a column filled going forward.
A column would have been cheaper to read and would have started at zero on
the day it shipped — a service metric that says nothing about last month is
a service metric nobody trusts, and a manager cannot wait a month to find out
whether the desk is coping.

The median is reported next to the mean on purpose. One conversation answered
after three days drags a mean into uselessness; the median says what the
ordinary family actually waits.
"""
from datetime import datetime, timedelta

WINDOW_HOURS = 24


def _thread_of(log):
    """The conversation key a log row belongs to — same rule as the inbox."""
    return f"p{log.patient_id}" if log.patient_id else (log.to_phone or "?")


def first_replies(days=30, now=None):
    """Every inbound message that opened a conversation, and what happened.

    Returns ``[{key, asked_at, replied_at, hours, answered, in_window}]`` —
    one row per *question*, not per message: a family sending three lines in
    a row asked once, and counting that as three questions answered in
    seconds each is how a service report flatters itself.
    """
    from app.extensions import db
    from app.models import MessageLog

    now = now or datetime.utcnow()
    since = now - timedelta(days=days)
    rows = (db.session.query(MessageLog.id, MessageLog.direction,
                             MessageLog.patient_id, MessageLog.to_phone,
                             MessageLog.created_at, MessageLog.status)
            .filter(MessageLog.created_at >= since)
            .order_by(MessageLog.created_at).all())

    threads = {}
    for row in rows:
        log = _Row(row)
        threads.setdefault(_thread_of(log), []).append(log)

    out = []
    for key, msgs in threads.items():
        pending = None                      # the question still unanswered
        for msg in msgs:
            if msg.direction == "in":
                # Only the first of a run counts: the follow-up lines are the
                # same question said again.
                if pending is None:
                    pending = msg
                continue
            if pending is None:
                continue                    # the clinic spoke first
            gap = (msg.created_at - pending.created_at).total_seconds() / 3600.0
            out.append({"key": key, "asked_at": pending.created_at,
                        "replied_at": msg.created_at,
                        "hours": max(gap, 0), "answered": True,
                        "in_window": gap <= WINDOW_HOURS})
            pending = None
        if pending is not None:
            waited = (now - pending.created_at).total_seconds() / 3600.0
            out.append({"key": key, "asked_at": pending.created_at,
                        "replied_at": None, "hours": max(waited, 0),
                        "answered": False,
                        "in_window": waited <= WINDOW_HOURS})
    return out


class _Row:
    """A query row read by name — the tuple indexes were the bug waiting."""

    __slots__ = ("id", "direction", "patient_id", "to_phone", "created_at",
                 "status")

    def __init__(self, row):
        (self.id, self.direction, self.patient_id, self.to_phone,
         self.created_at, self.status) = row


def summary(days=30, now=None):
    """The board: response times, what went unanswered, and the shape of it."""
    replies = first_replies(days=days, now=now)
    answered = [r for r in replies if r["answered"]]
    times = sorted(r["hours"] for r in answered)

    # Unanswered *and* past the window: the ones that cost something. A
    # question asked twenty minutes ago is not a failure, it is a queue.
    missed = [r for r in replies if not r["answered"] and not r["in_window"]]
    waiting = [r for r in replies if not r["answered"] and r["in_window"]]

    return {
        "days": days,
        "asked": len(replies),
        "answered": len(answered),
        "waiting": len(waiting),
        "missed": len(missed),
        "median_hours": _median(times),
        "mean_hours": round(sum(times) / len(times), 2) if times else None,
        "within_hour": sum(1 for h in times if h <= 1),
        "answer_rate": (round(len(answered) * 100.0 / len(replies), 1)
                        if replies else None),
        "by_assignee": _by_assignee(),
        "by_topic": _by_topic(),
    }


def _median(values):
    if not values:
        return None
    middle = len(values) // 2
    if len(values) % 2:
        return round(values[middle], 2)
    return round((values[middle - 1] + values[middle]) / 2, 2)


def _by_assignee():
    """Who is carrying the open work — names, not a total."""
    from app.extensions import db
    from app.models import Conversation, User

    rows = (db.session.query(Conversation.assigned_to, db.func.count())
            .filter(Conversation.assigned_to.isnot(None))
            .group_by(Conversation.assigned_to).all())
    if not rows:
        return []
    names = {u.id: u for u in User.query.filter(
        User.id.in_([r[0] for r in rows])).all()}
    return sorted(({"user": names.get(uid), "count": n} for uid, n in rows),
                  key=lambda e: -e["count"])


def _by_topic():
    """What people write in about — which is what the clinic should fix."""
    from app.extensions import db
    from app.models import Conversation

    rows = (db.session.query(Conversation.topic, db.func.count())
            .filter(Conversation.topic.isnot(None))
            .group_by(Conversation.topic).all())
    return sorted(({"topic": topic, "count": n} for topic, n in rows),
                  key=lambda e: -e["count"])
