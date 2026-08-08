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
    """The zone the clinic has chosen, as a string."""
    from app.models import Setting

    return (Setting.get("clinic_timezone") or "").strip() or DEFAULT_TZ


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
    zone = tz if tz is not None else clinic_tz()
    if zone is None:
        return None
    from datetime import timezone

    # The stored value is naive UTC — it has to be told so before it can be
    # moved, or Python reads it as local and the conversion does nothing.
    return moment.replace(tzinfo=timezone.utc).astimezone(zone)


def local_today(tz=None):
    """Today's date in the clinic, which is not always today's date in UTC."""
    local = to_local(datetime.utcnow(), tz)
    return local.date() if local else datetime.utcnow().date()
