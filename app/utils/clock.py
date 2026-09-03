"""What time it is where the clinic is.

The program stores every moment with ``datetime.utcnow()`` — no marker, no
offset — and that is fine as long as it only ever subtracts one stored moment
from another. Waiting times, consultation lengths and the live counters are
all UTC minus UTC, so they were right without anybody thinking about it.

The moment that stops being enough is when a stored time has to be compared
with a time a **person typed**. An appointment at 10:00 is ten in the morning
in the clinic, not ten UTC, so "did the doctor start on time" is
``local(started_at) − appt_time`` and there is no way to work out ``local``
without knowing where the clinic is. Doing the subtraction anyway would report
every doctor in Egypt as two or three hours late — a number wrong enough to
discredit the screen around it, which is why that metric waited for this file.

**Windows needs the data shipped to it.** Linux and macOS carry the IANA
timezone database; Windows does not, so ``ZoneInfo("Africa/Cairo")`` raises
there unless the ``tzdata`` package is installed — and the clinics this runs
in are Windows. It is in requirements for that reason alone.

**When the zone cannot be resolved, this says so instead of guessing.**
:func:`clinic_tz` returns ``None`` rather than quietly falling back to UTC,
because a silent fallback is how the wrong-by-three-hours number gets shipped
after all — it would look like a working feature.
"""
from datetime import datetime

# Where most of these clinics are. A default that is right for the room the
# software was written in, and changeable for everybody else.
DEFAULT_TZ = "Africa/Cairo"

# Offered on the settings screen. Not the full IANA list — a clinic picking
# its own city from four hundred entries is a worse experience than typing it,
# and anything not here can still be saved by hand.
COMMON_ZONES = [
    "Africa/Cairo", "Asia/Riyadh", "Asia/Dubai", "Asia/Kuwait",
    "Asia/Qatar", "Asia/Amman", "Asia/Beirut", "Asia/Baghdad",
    "Africa/Khartoum", "Africa/Tripoli", "Africa/Algiers", "Africa/Casablanca",
    "Europe/London", "Europe/Paris", "UTC",
]


def tz_name():
    """The zone the clinic has chosen, as a string.

    Reading it needs a database, and therefore an application context. Some
    callers legitimately have neither: ``group_plan`` sorts an already-built
    vaccination plan and touches nothing, and its tests call it with a plain
    list — which is what a function like that *should* allow.

    So a missing context falls back to the default zone rather than raising.
    That is the same bargain :func:`to_utc` already makes and for the same
    reason: the honest alternative is to make every pure helper that mentions
    a date require a database, and a day's arithmetic in the default zone is
    a far smaller error than that.
    """
    from app.models import Setting

    try:
        chosen = Setting.get("clinic_timezone")
    except Exception:                       # no app context, or no database
        return DEFAULT_TZ
    return (chosen or "").strip() or DEFAULT_TZ


def clinic_tz(name=None):
    """The clinic's timezone, or ``None`` when it cannot be resolved.

    ``None`` is a real answer and callers have to handle it: on Windows
    without ``tzdata`` every zone fails to load, and a caller that treated
    that as UTC would produce exactly the wrong numbers this module exists to
    prevent.
    """
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    try:
        return ZoneInfo(name or tz_name())
    except (ZoneInfoNotFoundError, ValueError, KeyError, ModuleNotFoundError):
        return None


def valid_zone(name):
    """Whether a typed zone name is one the machine can actually resolve."""
    return bool(name) and clinic_tz(name) is not None


def to_local(moment, tz=None):
    """A stored UTC moment as the wall clock in the clinic showed it.

    Returns ``None`` when the zone is unknown, so a comparison against a typed
    time is skipped rather than made wrongly.
    """
    if moment is None:
        return None
    # ``tz`` may be a zone *name* or an already-resolved zone. Taking only the
    # second was a trap: every setting, every form field and every caller with
    # a zone to hand has the name, and passing it raised deep inside
    # ``astimezone`` with a message about tzinfo subclasses.
    if isinstance(tz, str):
        zone = clinic_tz(tz)
    elif tz is not None:
        zone = tz
    else:
        zone = clinic_tz()
    if zone is None:
        return None
    from datetime import timezone

    # The stored value is naive UTC — it has to be told so before it can be
    # moved, or Python reads it as local and the conversion does nothing.
    return moment.replace(tzinfo=timezone.utc).astimezone(zone)


def to_utc(moment, tz=None):
    """A wall-clock moment in the clinic as the naive UTC the database stores.

    The inverse of :func:`to_local`, and it exists for one thing: scheduling.
    An appointment is "Tuesday at 10:00" in the clinic's own time, while
    ``MessageLog.scheduled_at`` is compared against ``datetime.utcnow()``.
    Sending a reminder means converting between the two, and doing it by
    subtraction somewhere in a route is how the reminder for a 10 a.m.
    appointment goes out at 7 a.m.

    Unlike :func:`to_local` this **falls back** to treating the moment as UTC
    when the zone cannot be resolved, because refusing would mean scheduling
    nothing at all. A reminder a few hours off is a poor reminder; no reminder
    is a missed appointment. The settings screen already says out loud when
    the zone is unreadable.
    """
    if moment is None:
        return None
    zone = clinic_tz(tz) if isinstance(tz, str) else (tz or clinic_tz())
    if zone is None:
        return moment
    from datetime import timezone

    # Naive in, naive out: the caller's moment is the clinic's wall clock, and
    # what goes back into the column has to be naive UTC like every other
    # stored time here.
    return (moment.replace(tzinfo=zone)
            .astimezone(timezone.utc).replace(tzinfo=None))


def local_now(tz=None):
    """The wall-clock **time** in the clinic right now.

    The companion to :func:`local_today`, and it exists because ``date`` was
    only half the problem. ``datetime.now()`` answers with the *server's* wall
    clock — neither UTC nor the clinic's — so on any install where the machine
    sits in a different zone from the clinic it is wrong by the whole offset,
    all day, not for a few hours a night.

    Two things were reading it: the time stamped on a walk-in when the grid is
    full, and the answer to "is the clinic open right now" that decides whether
    a message gets an out-of-hours reply. A Cairo clinic on a UTC server booked
    a 10:00 walk-in as 07:00 and thought it was closed for the first three
    hours of every morning.

    Falls back to ``utcnow`` on an unreadable zone, like everything else here:
    a time is not optional.
    """
    return to_local(datetime.utcnow(), tz) or datetime.utcnow()


def local_today(tz=None):
    """Today's date in the clinic, which is not always today's date in UTC.

    This is what a record should be **stamped** with and what a screen should
    mean by "today". A visit opened at half past midnight in Cairo is a visit
    today; dated from ``utcnow()`` it lands on yesterday and stays there — in
    the day's list, in the month's revenue, and in the child's history. The
    window is small (two or three hours a night) and a paediatric clinic is
    exactly the kind that is open inside it.

    Falls back to the UTC date when the zone cannot be resolved, because a
    date is not optional: every caller here needs *a* day, and the settings
    screen already says out loud when the zone is unreadable.
    """
    local = to_local(datetime.utcnow(), tz)
    return local.date() if local else datetime.utcnow().date()


def stamp(moment, shape="%Y-%m-%d %H:%M"):
    """A stored moment, printed as the clock on the clinic's wall.

    Screens have been printing ``moment.strftime(...)`` straight from the
    column, which is UTC. For a date that is usually harmless; for an **hour**
    it is wrong by however far the clinic is from Greenwich, and a chart of
    readings taken every fifteen minutes is nothing but hours. A round taken
    at 03:10 in Cairo would print as midnight, and the nurse who took it would
    be looking at somebody else's night.

    Falls back to printing the stored value when the zone cannot be resolved.
    That is the same bargain :func:`local_today` makes: the alternative here is
    a blank where a time should be, and a blank on a rounds chart reads as a
    reading that was never taken.
    """
    if moment is None:
        return ""
    return (to_local(moment) or moment).strftime(shape)


def hhmm(moment):
    """Just the time of day, in the clinic's own hours."""
    return stamp(moment, "%H:%M")


def init_app(app):
    """Give templates the two above, so no screen converts by hand.

    Registered rather than imported per template for the reason the bands
    table lives in one file: a second way to print a time is a second way to
    print it wrong, and this one has already cost four money reports.
    """
    app.jinja_env.filters["clinic_stamp"] = stamp
    app.jinja_env.filters["clinic_time"] = hhmm
