"""How far the ICD-11 import has got, readable from another request.

The importer already counted. ``icd_who.walk`` takes an ``on_progress``
callback and its own docstring says why — *"this takes minutes, and a spinner
with no number is indistinguishable from a hang"* — and then the route called
``import_all()`` with no callback at all. The number was computed on every
entity and thrown away, and the screen sat still for minutes.

The count is kept in one settings row rather than in memory because the thing
that needs to read it is **a different request**: the import blocks its own
request for the whole walk, so the only way to show progress is for the page
to ask a second time.

**On the percentage.** A percentage needs a denominator, and this walk
discovers the size of the classification as it goes — the total is not known
until it finishes. So the first import reports a count and no percentage, and
every import after it reports a percentage against *the last successful
import's own total*, marked as an estimate. Dividing by a number invented here
would produce a bar that reads 90% at the halfway mark, which is worse than no
bar: it does not just fail to inform, it misinforms with confidence.
"""
import json
import time

KEY = "icd11_import_progress"
TOTAL_KEY = "icd11_last_total"

# How often the count is written. Every entity would mean a database write per
# HTTP request to WHO, on a walk of tens of thousands — the write would cost
# more than the fetch. Two seconds is under the interval a person reads a
# changing number at, so nothing visible is lost.
WRITE_EVERY = 2.0


def _set(payload):
    from app.extensions import db
    from app.models import Setting

    Setting.set(KEY, json.dumps(payload))
    db.session.commit()


def start():
    """Mark an import as running, from zero."""
    _set({"running": True, "count": 0, "started": time.time()})


def note(count):
    """Record the running count — throttled, and never fatal.

    Wrapped because this is called from inside the walk: a settings row that
    would not write is a reason to lose the progress display, never a reason
    to lose an import that has been running for four minutes.
    """
    now = time.time()
    if now - note._last < WRITE_EVERY:
        return
    note._last = now
    try:
        state = read()
        _set({"running": True, "count": count,
              "started": state.get("started") or now})
    except Exception:                       # noqa: BLE001
        pass


note._last = 0.0


def finish(count=None, ok=True):
    """Import over. A finished total becomes the next run's denominator."""
    from app.extensions import db
    from app.models import Setting

    try:
        if ok and count:
            Setting.set(TOTAL_KEY, str(int(count)))
        Setting.set(KEY, json.dumps({"running": False, "count": count or 0,
                                     "ok": bool(ok)}))
        db.session.commit()
    except Exception:                       # noqa: BLE001
        pass
    note._last = 0.0


def read():
    """The current state, as a plain dict. Never raises."""
    from app.models import Setting

    try:
        raw = Setting.get(KEY) or ""
        state = json.loads(raw) if raw.strip() else {}
    except Exception:                       # noqa: BLE001
        state = {}
    if not isinstance(state, dict):
        state = {}
    return state


def status():
    """What the screen shows: the count, the elapsed seconds, and — only when
    a previous import gives us an honest denominator — a percentage."""
    from app.models import Setting

    state = read()
    count = int(state.get("count") or 0)
    started = state.get("started")
    out = {
        "running": bool(state.get("running")),
        "count": count,
        "elapsed": int(time.time() - started) if started else 0,
        "percent": None,
    }
    try:
        last = int((Setting.get(TOTAL_KEY) or "0").strip() or 0)
    except (TypeError, ValueError):
        last = 0
    if last > 0 and count:
        # Capped at 99 while it is still running: a bar that says 100% and
        # keeps going is the same lie as one that says 90% at the halfway
        # mark, and this estimate can legitimately overshoot when WHO's
        # classification has grown since the last import.
        pct = round(count * 100.0 / last)
        out["percent"] = min(pct, 99) if out["running"] else min(pct, 100)
        out["estimated_from"] = last
    return out
