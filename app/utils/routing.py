"""Who answers which conversation — CONNECTHUB_PLAN.md م٥.

The owner: *«خليه التحكم فيه ممكن، وخلّي التلقائي أقدر أعدّل عليه … حسب
الآلية اللي انت شايفها»*. So the clinic decides how much the program does:

``off``
    nothing changes — conversations are handed over by hand, as before.
``suggest``
    the program names who should take each new conversation, on the inbox and
    on the thread; a person accepts it in one press or hands it elsewhere.
``auto``
    the program hands it over itself, and anybody can still take it back or
    hand it on.

**How it chooses**, every rule the clinic's to edit on «توزيع المحادثات»:

1. the person already on the thread keeps it (a family does not start again
   with somebody new every message), unless they are away;
2. a rule for what the message is about (a complaint → customer service, a
   result → the nurse), then a rule for the channel it came on (e-mail → the
   secretary), then everybody in the pool;
3. never somebody marked away — each person says «I'm not taking any» from
   the inbox, and the clinic sees who is;
4. among those: whoever has the fewest open conversations now, or simply
   taking turns.

**Nobody replied.** After the clinic's minutes, the person holding a waiting
conversation sees it on their bell; after the longer time, the supervisors
see it on theirs — and, only if the clinic said so, the program hands it to
somebody else and writes that it did. Outside working hours the clock stops,
because «nobody answered at 2 a.m.» is the away reply's job, not a failing.

Nothing here writes to a family, and nothing is decided silently: every hand-
over by the program is on the record, and every one can be undone by a person.
"""
import json
from datetime import datetime, timedelta

from app.extensions import db

MODES = ("off", "suggest", "auto")
METHODS = ("least_open", "turns")
SETTING = "route_config"
TURN = "route_turn"
SWEEP = "route_sweep_at"
#: The sweep runs at most this often, riding on the desk's own refreshes.
SWEEP_SECONDS = 60
MODULE = "messages"

DEFAULTS = {
    "mode": "off",
    "pool": [],
    "away": [],
    "by_topic": {},
    "by_channel": {},
    "method": "least_open",
    "keep_owner": True,
    "alert_minutes": 15,
    "escalate_minutes": 45,
    "supervisors": [],
    "reassign": False,
    "open_hours_only": True,
}


# ------------------------------------------------------------- settings --
def config():
    from app.models import Setting

    try:
        data = json.loads(Setting.get(SETTING) or "{}")
    except (TypeError, ValueError):
        data = {}
    out = dict(DEFAULTS)
    if isinstance(data, dict):
        out.update({k: v for k, v in data.items() if k in DEFAULTS})
    if out["mode"] not in MODES:
        out["mode"] = "off"
    if out["method"] not in METHODS:
        out["method"] = "least_open"
    return out


def _save(cfg):
    from app.models import Setting

    Setting.set(SETTING, json.dumps(cfg, ensure_ascii=False))


def _ids(values, allowed):
    out = []
    for v in values or []:
        try:
            v = int(v)
        except (TypeError, ValueError):
            continue
        if v in allowed and v not in out:
            out.append(v)
    return out


def _minutes(raw, default):
    try:
        n = int(str(raw).strip())
    except (TypeError, ValueError):
        return default
    return max(0, min(n, 24 * 60))


def save_settings(form, user):
    """The screen's form, checked: only people who can reach the inbox, only
    topics and channels the program knows."""
    from app.models import ActivityLog
    from app.utils.triage import TOPICS

    staff_ids = {u.id for u in desk_staff()}
    cfg = config()
    cfg["mode"] = form.get("mode") if form.get("mode") in MODES else "off"
    cfg["method"] = form.get("method") if form.get("method") in METHODS else "least_open"
    cfg["pool"] = _ids(form.getlist("pool"), staff_ids)
    cfg["supervisors"] = _ids(form.getlist("supervisors"), staff_ids)
    cfg["by_topic"] = {topic: ids for topic in TOPICS
                       if (ids := _ids(form.getlist(f"topic_{topic}"), staff_ids))}
    cfg["by_channel"] = {ch: ids for ch in channels()
                         if (ids := _ids(form.getlist(f"channel_{ch}"), staff_ids))}
    cfg["keep_owner"] = bool(form.get("keep_owner"))
    cfg["reassign"] = bool(form.get("reassign"))
    cfg["open_hours_only"] = bool(form.get("open_hours_only"))
    cfg["alert_minutes"] = _minutes(form.get("alert_minutes"), 15)
    cfg["escalate_minutes"] = _minutes(form.get("escalate_minutes"), 45)
    if cfg["escalate_minutes"] and cfg["alert_minutes"] and cfg["escalate_minutes"] < cfg["alert_minutes"]:
        cfg["escalate_minutes"] = cfg["alert_minutes"]
    _save(cfg)
    ActivityLog.record("inbox.routing", user_id=user.id, entity="setting",
                       detail=f"mode={cfg['mode']}")
    return cfg


def set_away(user, away):
    """A person says they are (not) taking conversations right now."""
    from app.models import ActivityLog

    cfg = config()
    ids = [i for i in cfg["away"] if i != user.id]
    if away:
        ids.append(user.id)
    cfg["away"] = ids
    _save(cfg)
    ActivityLog.record("inbox.away" if away else "inbox.back", user_id=user.id,
                       entity="user", entity_id=user.id)
    return away


def is_away(user):
    return bool(user) and user.id in config()["away"]


def channels():
    """The channels a rule can name."""
    from app.utils.channels import CHANNELS

    # Only the ones a message arrives on — a walk-in has no thread to route.
    return [k for k, v in CHANNELS.items() if v.get("direct") and k != "page"]


def desk_staff():
    """Everybody who can reach the inbox."""
    from app.models import User

    rows = User.query.filter_by(is_active=True).order_by(User.full_name).all()
    return [u for u in rows if u.can_access(MODULE)]


# --------------------------------------------------------------- choice --
def candidates(topic=None, channel=None, cfg=None):
    """Who may take a conversation about ``topic`` on ``channel``: the
    topic's rule, else the channel's, else the pool, else everybody — less
    whoever is away. ``[]`` when everybody is."""
    cfg = cfg or config()
    staff = {u.id: u for u in desk_staff()}
    for ids in ((cfg["by_topic"] or {}).get(topic or ""),
                (cfg["by_channel"] or {}).get(channel or ""),
                cfg["pool"] or list(staff)):
        people = [staff[i] for i in ids or [] if i in staff and i not in cfg["away"]]
        if people:
            return people
    return []


def open_load(user_ids):
    """``{user id: conversations they hold that are not marked answered}``."""
    from app.models import Conversation

    if not user_ids:
        return {}
    rows = (db.session.query(Conversation.assigned_to, db.func.count(Conversation.id))
            .filter(Conversation.assigned_to.in_(user_ids), Conversation.resolved_at.is_(None))
            .group_by(Conversation.assigned_to).all())
    out = {i: 0 for i in user_ids}
    out.update({uid: n for uid, n in rows})
    return out


def _next_turn(people):
    from app.models import Setting

    ids = sorted(u.id for u in people)
    try:
        last = int(Setting.get(TURN) or 0)
    except (TypeError, ValueError):
        last = 0
    after = [i for i in ids if i > last]
    chosen = after[0] if after else ids[0]
    Setting.set(TURN, str(chosen))
    return next(u for u in people if u.id == chosen)


def choose(topic=None, channel=None, cfg=None, exclude=()):
    """The person the clinic's rules name for this conversation, or ``None``."""
    cfg = cfg or config()
    people = [u for u in candidates(topic, channel, cfg) if u.id not in exclude]
    if not people:
        return None
    if cfg["method"] == "turns":
        return _next_turn(people)
    load = open_load([u.id for u in people])
    return min(people, key=lambda u: (load.get(u.id, 0), u.full_name or "", u.id))


def _topic_of(record, log):
    from app.utils.triage import suggest_topic

    if record is not None and record.topic:
        return record.topic
    return suggest_topic(getattr(log, "body", "") or "")


def route(key, log=None, cfg=None):
    """A message arrived on thread ``key``: name or hand over its person.
    Returns the chosen user (or ``None``). The caller commits."""
    from app.models import ActivityLog
    from app.utils import inbox

    cfg = cfg or config()
    if cfg["mode"] == "off" or not key:
        return None
    record = inbox.conversation_for(key)
    # The person already on the thread keeps it — if they still can and are here.
    present = {u.id for u in desk_staff() if u.id not in cfg["away"]}
    if cfg["keep_owner"] and record.assigned_to and record.assigned_to in present:
        return record.assignee
    channel = getattr(log, "channel_key", None) if log is not None else None
    person = choose(_topic_of(record, log), channel, cfg)
    if person is None:
        return None
    if cfg["mode"] == "auto":
        if record.assigned_to != person.id:
            record.assigned_to, record.assigned_at = person.id, datetime.utcnow()
            record.assigned_by = "auto"
            record.suggested_to = None
            ActivityLog.record("inbox.auto_assign", entity="conversation",
                               entity_id=record.id, detail=f"{key} → {person.id}")
    else:
        record.suggested_to = person.id
    return person


def on_inbound(log):
    """Called for every message that arrives, after it is filed."""
    try:
        from app.utils import inbox

        cfg = config()
        if cfg["mode"] == "off" or log is None or log.direction != "in":
            return None
        return route(inbox.thread_key(log), log, cfg)
    except Exception:  # noqa: BLE001 — routing never loses a message
        return None


# ------------------------------------------------------- nobody replied --
def _clock_runs(cfg):
    if not cfg["open_hours_only"]:
        return True
    from app.utils.service_desk import is_open

    try:
        return is_open()
    except Exception:  # noqa: BLE001
        return True


_LATE = {"at": 0.0, "data": None}
#: The bell asks on every page; the inbox list is read at most this often.
LATE_TTL = 30


def forget():
    _LATE["at"], _LATE["data"] = 0.0, None


def late():
    """``(alert, escalate)``: who holds each waiting conversation past the
    clinic's two times — lists of ``(thread key, holder id or None)``, kept
    for :data:`LATE_TTL` seconds because the bell asks on every page."""
    import time

    if _LATE["data"] is not None and time.time() - _LATE["at"] < LATE_TTL:
        return _LATE["data"]
    alert, escalate = _late(config())

    def brief(rows):
        return [(c["key"], c["record"].assigned_to if c["record"] is not None else None)
                for c in rows]
    result = (brief(alert), brief(escalate))
    _LATE["at"], _LATE["data"] = time.time(), result
    return result


def _late(cfg):
    from app.utils import inbox

    if cfg["mode"] == "off" or not _clock_runs(cfg):
        return [], []
    a, e = cfg["alert_minutes"], cfg["escalate_minutes"]
    if not a and not e:
        return [], []
    rows = [c for c in inbox.conversations(only_open=True) if c["open"]]
    alert = [c for c in rows if a and (c.get("waiting_hours") or 0) * 60 >= a]
    escalate = [c for c in rows if e and (c.get("waiting_hours") or 0) * 60 >= e]
    return alert, escalate


def mine_late(user):
    """How many of this person's conversations wait past the alert time."""
    if user is None:
        return 0
    alert, _ = late()
    return sum(1 for _key, holder in alert if holder == user.id)


def for_supervisor(user):
    """How many conversations wait past the escalation time, for a supervisor."""
    cfg = config()
    if user is None or user.id not in cfg["supervisors"]:
        return 0
    _, escalate = late()
    return len(escalate)


def sweep(now=None):
    """Run at most once a minute on the desk's refresh: in ``auto``, hand out
    waiting conversations nobody holds; past the escalation time, and only if
    the clinic asked, hand each one on once. Returns what it did."""
    from app.models import ActivityLog, Setting

    cfg = config()
    if cfg["mode"] != "auto":
        return {"assigned": 0, "moved": 0}
    now = now or datetime.utcnow()
    stamp = Setting.get(SWEEP)
    try:
        last = datetime.fromisoformat(stamp) if stamp else None
    except ValueError:
        last = None
    if last is not None and (now - last) < timedelta(seconds=SWEEP_SECONDS):
        return {"assigned": 0, "moved": 0}
    if not Setting.swap(SWEEP, stamp, now.isoformat()):
        return {"assigned": 0, "moved": 0}
    from app.utils import inbox

    assigned = moved = 0
    for conv in inbox.conversations(only_open=True):
        record = conv["record"]
        if record is None or not record.assigned_to:
            if route(conv["key"], conv["last"], cfg):
                assigned += 1
    if cfg["reassign"] and cfg["escalate_minutes"] and _clock_runs(cfg):
        _, escalate = _late(cfg)
        for conv in escalate:
            record = conv["record"]
            # Once per wait: a reply and a new message start the clock again.
            if record is None or (record.escalated_at is not None
                                  and record.escalated_at >= conv["last"].created_at):
                continue
            channel = conv["last"].channel_key if conv.get("last") is not None else None
            person = choose(_topic_of(record, conv["last"]), channel, cfg,
                            exclude=(record.assigned_to,) if record.assigned_to else ())
            record.escalated_at = now
            if person is not None and person.id != record.assigned_to:
                ActivityLog.record("inbox.escalated", entity="conversation", entity_id=record.id,
                                   detail=f"{conv['key']} {record.assigned_to} → {person.id}")
                record.assigned_to, record.assigned_at = person.id, now
                record.assigned_by = "escalated"
                moved += 1
    forget()
    return {"assigned": assigned, "moved": moved}
