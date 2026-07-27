"""The patient inbox — conversations, what is waiting, and how fast we answer.

Receiving a patient's message was already solved: the webhook normalises it,
matches the sender and logs it. What was missing is everything after that. A
reply landed in a list nobody had a reason to open, no screen said "this one is
still waiting", and a number the system couldn't match stayed orphaned forever.

This module is the customer-service side of the same data:

* **a conversation** is every message to and from one patient (or one phone we
  haven't matched yet), newest activity first;
* **open** means the last word was the patient's — that is the only definition
  of "needs an answer" that can't drift out of date, because it is the thread
  itself saying so;
* **how long they waited** is measured from each inbound message to the first
  reply after it, which is the number a clinic actually manages.

Nothing here sends anything; it only reads the log.
"""
from datetime import datetime, timedelta

from app.extensions import db
from app.models import MessageLog, Parent, Patient
from app.utils.whatsapp import normalize_phone

# A conversation older than this stops counting towards "waiting" — a message
# from three months ago that was never answered is history, not a task.
WAITING_WINDOW_DAYS = 30
RESPONSE_WINDOW_DAYS = 7


def thread_key(log):
    """The conversation a message belongs to: the patient, else the number."""
    if log.patient_id:
        return f"p{log.patient_id}"
    return log.to_phone or "?"


def phone_variants(phone):
    """The spellings one number may already be stored under.

    Outbound and inbound both normalise now, but rows written before that —
    and anything typed by hand — can carry the local form (``01…``) while the
    same person's newer messages carry the international one (``201…``). A
    lookup that only matches one of them splits a family across two threads,
    so every lookup asks for both.
    """
    if not phone:
        return []
    raw = phone.strip()
    out = []
    for candidate in (raw, normalize_phone(raw), _local_form(raw),
                      _local_form(normalize_phone(raw))):
        if candidate and candidate not in out:
            out.append(candidate)
    return out


def _local_form(phone):
    """``201234…`` → ``01234…`` — the way the number is written locally."""
    from app.utils.whatsapp import DEFAULT_COUNTRY_CODE

    if not phone:
        return None
    code = DEFAULT_COUNTRY_CODE
    if phone.startswith(code) and len(phone) > len(code) + 6:
        return "0" + phone[len(code):]
    return None


def thread_query(key):
    """Every message in one conversation."""
    if key.startswith("p") and key[1:].isdigit():
        return MessageLog.query.filter(MessageLog.patient_id == int(key[1:]))
    return MessageLog.query.filter(MessageLog.patient_id.is_(None),
                                   MessageLog.to_phone.in_(phone_variants(key)))


def unread_count():
    """Inbound messages nobody has opened yet — what the bell counts."""
    return (MessageLog.query
            .filter(MessageLog.direction == "in",
                    MessageLog.status != "read").count())


def _matches(conv, needle):
    """Free-text search over the patient's name, the number and the last body."""
    if not needle:
        return True
    needle = needle.strip().lower()
    haystack = " ".join(filter(None, [
        (conv["patient"].full_name if conv["patient"] else ""),
        (conv["patient"].full_name_en if conv["patient"] else ""),
        (conv["patient"].patient_number if conv["patient"] else ""),
        conv["phone"] or "",
        conv["last"].body or "",
    ])).lower()
    return needle in haystack


def conversations(search=None, only_open=False, limit=200, assignee=None):
    """One row per conversation, most recent first.

    Built from the log rather than a conversations table, so nothing has to be
    kept in sync — but grouped by a query over *all* messages, not a slice of
    the newest few, so an old quiet thread never silently disappears. The
    conversation record on the side carries only what the messages can't say:
    who owns it, and whether a human has declared it answered.
    """
    # One row per thread: the id of its newest message. Grouping in SQL keeps
    # this honest on a clinic with years of history behind it.
    newest = (db.session.query(db.func.max(MessageLog.id))
              .group_by(db.case((MessageLog.patient_id.is_(None),
                                 MessageLog.to_phone),
                                else_=db.cast(MessageLog.patient_id,
                                              db.String)))
              .subquery())
    lasts = (MessageLog.query.filter(MessageLog.id.in_(db.select(newest)))
             .order_by(MessageLog.created_at.desc()).limit(limit).all())
    if not lasts:
        return []

    keys = [thread_key(m) for m in lasts]
    counts, unread = _thread_counts(keys)
    records = conversation_records(keys)
    out = []
    for last in lasts:
        key = thread_key(last)
        record = records.get(key)
        # "The patient spoke last" is the only definition of waiting that can't
        # drift — but a thread ending in "شكراً" would sit in the work list for
        # ever, so a human can say it's answered. A message arriving after that
        # moment re-opens it by itself.
        waiting = last.direction == "in"
        if waiting and record is not None and record.is_resolved_for(last.created_at):
            waiting = False
        conv = {
            "key": key,
            "patient": last.patient,
            "phone": last.to_phone,
            "last": last,
            "count": counts.get(key, 1),
            "unread": unread.get(key, 0),
            "open": waiting,
            "orphan": last.patient_id is None,
            "record": record,
            "assignee": record.assignee if record is not None else None,
            "resolved": (record is not None
                         and record.is_resolved_for(last.created_at)),
        }
        if only_open and not conv["open"]:
            continue
        if assignee is not None and (
                record is None or record.assigned_to != assignee):
            continue
        if not _matches(conv, search):
            continue
        conv["waiting_hours"] = waiting_since(conv)
        window = session_window(conv["key"])
        # How long the clinic may still answer for free. A thread with forty
        # minutes left is more urgent than one that has waited longer but has
        # a day in hand — after the window shuts, the reply costs money and
        # can only go out as an approved template.
        conv["hours_left"] = (window or {}).get("hours_left")
        conv["closing"] = bool(window and window["open"]
                               and window["hours_left"] <= CLOSING_SOON_HOURS)
        out.append(conv)
    # Closing windows first, then whoever has waited longest — a work list
    # ordered by "newest" puts the person ignored for three days at the bottom.
    out.sort(key=lambda c: (not c["open"], not c["closing"],
                            c["hours_left"] if c["closing"] else 0,
                            -c["waiting_hours"],
                            -c["last"].created_at.timestamp()))
    return out


def conversation_records(keys):
    """The side-table rows for these threads, keyed by thread key."""
    from app.models import Conversation

    if not keys:
        return {}
    rows = Conversation.query.filter(Conversation.thread_key.in_(keys)).all()
    return {r.thread_key: r for r in rows}


def conversation_for(key, create=True):
    """The conversation record for a thread, created on first use."""
    from app.models import Conversation

    row = Conversation.query.filter_by(thread_key=key).first()
    if row is not None or not create:
        return row
    last = thread_query(key).order_by(MessageLog.created_at.desc()).first()
    row = Conversation(thread_key=key,
                       patient_id=(last.patient_id if last else None),
                       phone=(last.to_phone if last else None))
    db.session.add(row)
    db.session.flush()
    return row


def last_inbound_at(key):
    """When the patient last wrote in this thread."""
    row = (thread_query(key).filter(MessageLog.direction == "in")
           .order_by(MessageLog.created_at.desc()).first())
    return row.created_at if row is not None else None


# WhatsApp's own rule, and the one that surprises every clinic that switches
# to the Business API: you may only write freely for 24 hours after the
# patient's last message. Afterwards nothing goes out except a pre-approved
# template. A reply box that doesn't say so lets a receptionist type a careful
# answer, press send, and never learn it was refused.
SESSION_HOURS = 24
# How near the end of that window counts as "answer this one now".
CLOSING_SOON_HOURS = 2


def session_window(key, provider=None):
    """How long the clinic may still reply freely → dict, or None.

    Returns None when the rule doesn't apply: click-to-send links open the
    staff member's own WhatsApp, which is an ordinary conversation with no
    window at all.
    """
    from app.utils import whatsapp as wa

    provider = provider or wa.resolve_provider(wa.get_config())
    if provider == "web":
        return None
    last = last_inbound_at(key)
    if last is None:
        return {"open": False, "hours_left": 0, "expires_at": None,
                "never_wrote": True}
    expires = last + timedelta(hours=SESSION_HOURS)
    left = (expires - datetime.utcnow()).total_seconds() / 3600.0
    return {"open": left > 0, "hours_left": max(round(left, 1), 0),
            "expires_at": expires, "never_wrote": False}


def waiting_since(conv):
    """How long this conversation has been waiting, in hours (0 if it isn't).

    A thread waiting five minutes and one waiting three days look identical on
    a screen that only prints a timestamp.
    """
    if not conv.get("open"):
        return 0
    last = conv["last"].created_at
    return max((datetime.utcnow() - last).total_seconds() / 3600.0, 0)


def _thread_counts(keys):
    """Message totals and unread counts per conversation, in two queries."""
    pids = [int(k[1:]) for k in keys if k.startswith("p") and k[1:].isdigit()]
    phones = [k for k in keys if not (k.startswith("p") and k[1:].isdigit())]
    counts, unread = {}, {}
    clauses = []
    if pids:
        clauses.append(MessageLog.patient_id.in_(pids))
    if phones:
        clauses.append(db.and_(MessageLog.patient_id.is_(None),
                               MessageLog.to_phone.in_(phones)))
    if not clauses:
        return counts, unread
    where = db.or_(*clauses) if len(clauses) > 1 else clauses[0]
    for row in MessageLog.query.filter(where).all():
        key = thread_key(row)
        counts[key] = counts.get(key, 0) + 1
        if row.direction == "in" and row.status != "read":
            unread[key] = unread.get(key, 0) + 1
    return counts, unread


def waiting_count():
    """Conversations whose last word was the patient's, within the window."""
    since = datetime.utcnow() - timedelta(days=WAITING_WINDOW_DAYS)
    return sum(1 for c in conversations()
               if c["open"] and c["last"].created_at >= since)


def response_stats(days=RESPONSE_WINDOW_DAYS):
    """How the clinic answered lately → ``{asked, answered, waiting, avg_minutes}``.

    Each inbound message is paired with the first outbound one after it in the
    same conversation. An inbound message with nothing after it is still
    waiting — counted, never averaged, because a question we never answered
    would otherwise flatter the average by being invisible.
    """
    since = datetime.utcnow() - timedelta(days=days)
    rows = (MessageLog.query.filter(MessageLog.created_at >= since)
            .order_by(MessageLog.created_at).all())
    threads = {}
    for row in rows:
        threads.setdefault(thread_key(row), []).append(row)

    asked = answered = waiting = 0
    minutes = []
    for msgs in threads.values():
        for i, msg in enumerate(msgs):
            if msg.direction != "in":
                continue
            asked += 1
            reply = next((m for m in msgs[i + 1:] if m.direction == "out"), None)
            if reply is None:
                waiting += 1
                continue
            answered += 1
            gap = (reply.created_at - msg.created_at).total_seconds() / 60.0
            minutes.append(max(gap, 0))
    return {
        "asked": asked,
        "answered": answered,
        "waiting": waiting,
        "avg_minutes": round(sum(minutes) / len(minutes), 1) if minutes else None,
    }


def match_patients(phone):
    """Patients reachable on this number — guardians' phones and their own.

    A number on the child's own record used to match nobody, so a teenager who
    wrote in landed as an unknown caller next to their own file.
    """
    if not phone:
        return []
    target = normalize_phone(phone)
    if not target:
        return []
    fam_ids = set()
    for parent in Parent.query.filter(Parent.phone.isnot(None)).all():
        if not parent.family_id:
            continue
        if (normalize_phone(parent.phone) == target
                or (parent.phone_alt
                    and normalize_phone(parent.phone_alt) == target)):
            fam_ids.add(parent.family_id)

    found = {}
    if fam_ids:
        for row in Patient.query.filter(Patient.family_id.in_(fam_ids)).all():
            found[row.id] = row
    for row in Patient.query.filter(Patient.own_phone.isnot(None)).all():
        if normalize_phone(row.own_phone) == target:
            found[row.id] = row
    return [found[i] for i in sorted(found)]


def known_patient_for_phone(phone):
    """A patient this number was already linked to, from the log itself.

    Reception's decision has to stick. Once someone says "this number is
    Youssef's aunt", the next message from it must land in Youssef's
    conversation without anyone doing it again — and without guessing a number
    onto the child's record, which is how wrong phone numbers get into files.
    """
    variants = phone_variants(phone)
    if not variants:
        return None
    row = (MessageLog.query
           .filter(MessageLog.to_phone.in_(variants),
                   MessageLog.patient_id.isnot(None))
           .order_by(MessageLog.created_at.desc()).first())
    return row.patient if row is not None else None


def link_phone_to_patient(phone, patient):
    """Adopt an unmatched number into a patient's file.

    Reception recognises the caller the system couldn't. Every message already
    logged under the bare number joins the patient's conversation, and — thanks
    to ``known_patient_for_phone`` — so does every message that comes after.
    Returns how many messages moved.
    """
    variants = phone_variants(phone)
    if not variants or patient is None:
        return 0
    rows = (MessageLog.query
            .filter(MessageLog.patient_id.is_(None),
                    MessageLog.to_phone.in_(variants)).all())
    for row in rows:
        row.patient_id = patient.id
    return len(rows)


def normalize_logged_phones():
    """Rewrite stored numbers into their international form (fill-only).

    Grouping happens on the number as it is stored, so a clinic whose older
    rows kept the local ``01…`` form saw the same family as two conversations.
    Idempotent: a row already in international form is untouched. Returns how
    many rows moved."""
    fixed = 0
    for row in MessageLog.query.filter(MessageLog.to_phone.isnot(None)).all():
        clean = normalize_phone(row.to_phone)
        if clean and clean != row.to_phone:
            row.to_phone = clean
            fixed += 1
    return fixed
