"""The count that keeps a sponge out of a child — GAHAR SAS.09 · GSR.17.

> The surgical team should spend all efforts to prevent missing any foreign
> body … by meticulously counting any item used **before, during the closure
> of each body space, and after the closure of the skin**.
>
> Once a miscount is identified, the team shall **conduct re-counting, check
> the missing item, make provisions using imaging studies, and report the
> miscount**.

**This replaces a tick.** ``counts_correct`` was an ordinary box on the
sign-out stop; it is now derived from the counts that were actually recorded,
in the way ``consent``, ``site_marked``, ``identity`` and ``imaging_ready``
already are. Deriving an item that **already exists** is the safe move here —
adding a new one would make every checklist signed before today read as short.

**Three moments, and ``intra`` may happen more than once.** The intent says
the counting happens at the closure of *each body space*, so a case that
enters two cavities counts twice in the middle. Nothing here is unique per
moment; what :func:`state` asks is that each of the three has *at least* one.
"""
from datetime import datetime

from app.extensions import db
from app.models.surgical_count import (COUNT_ITEMS, COUNT_MOMENTS,
                                       SurgicalCount, SurgicalCountItem)
from app.models.theatre import Operation

#: Re-exported so screens and tests read one name.
MOMENTS = COUNT_MOMENTS
ITEMS = COUNT_ITEMS

#: The checklist item this answers. It is an **existing** item on the sign-out
#: stop, which is the whole reason this is safe: `SafetyCheck.missed` computes
#: against the current item list, so a *new* item would make every checklist
#: ever signed read as short. Deriving one that was already there changes what
#: the tick means and not how many there are.
COUNTS_ITEM = "counts_correct"

#: What :func:`state` can answer.
STATES = ("unasked", "short", "miscount", "ok")


def counts_for(operation):
    """Every counting event on this case, oldest first."""
    if operation is None:
        return []
    return sorted(operation.counts, key=lambda c: (c.at, c.id))


def at_moment(operation, moment):
    """The counts recorded at one moment — a list, because the middle one
    happens once per body space."""
    return [c for c in counts_for(operation) if c.moment == moment]


def missing_moments(operation):
    """Which of the three the record does not have, in the standard's order."""
    return [m for m in MOMENTS if not at_moment(operation, m)]


def open_miscounts(operation):
    """Counts whose numbers disagreed and which nobody has closed out.

    **Closed out means somebody wrote what happened**, not that the numbers
    were made to agree. A sponge found on the floor and a sponge found in an
    X-ray are both resolutions; a blank is neither.
    """
    return [c for c in counts_for(operation)
            if not c.agrees and not (c.resolution or "").strip()]


def state(operation):
    """``unasked`` · ``short`` · ``miscount`` · ``ok``.

    **A miscount outranks a short record.** A case missing its post-closure
    count *and* holding four sponges against three is not "incomplete
    paperwork" — it is the event this standard exists for, and the word the
    screen shows has to be that one.
    """
    if operation is None or not counts_for(operation):
        return "unasked"
    if open_miscounts(operation):
        return "miscount"
    return "short" if missing_moments(operation) else "ok"


def counts_ok(operation):
    """The one question the checklist item asks.

    Deliberately **not** true for ``unasked``: a case nobody counted is the
    thing the box used to claim had been done.
    """
    return state(operation) == "ok"


def signed(operation):
    """Whether the performing physician has signed the count record (EOC 3)."""
    return getattr(operation, "counts_signed_at", None) is not None


# ------------------------------------------------------- recording it -----
class NotTwoPeople(Exception):
    """One person counted, or counted and witnessed themselves.

    Raised rather than returned because evidence 2 makes the second person
    *the control*: *"the second one acts as a witness for the first one"*. A
    caller that could ignore this by not checking a return value would be able
    to record a one-person count, which is the exact practice the standard was
    written against.
    """


def record(operation, moment, items, counted_by=None, witnessed_by=None,
           note=None, at=None):
    """Write down one counting event. Returns the row, or ``None``.

    ``items`` is ``{item_key: (expected, found)}``. Unknown keys are dropped
    rather than stored: the vocabulary is the standard's, and a screen posting
    something else is a bug in the screen, not a new kind of swab.

    Refused when there is nothing to count — an event with no items is not a
    count, and a row holding none would make :func:`state` read ``ok`` for a
    case nobody counted.

    Raises :class:`NotTwoPeople` for a missing or self-appointed witness.
    """
    if operation is None or moment not in MOMENTS:
        return None
    counter = getattr(counted_by, "id", counted_by)
    witness = getattr(witnessed_by, "id", witnessed_by)
    if counter is None or witness is None or counter == witness:
        raise NotTwoPeople(moment)

    clean = {k: v for k, v in (items or {}).items() if k in ITEMS}
    if not clean:
        return None

    row = SurgicalCount(operation=operation, moment=moment,
                        counted_by=counter, witnessed_by=witness,
                        at=at or datetime.utcnow(),
                        note=(note or "").strip()[:255] or None)
    db.session.add(row)
    for key in ITEMS:                      # stored in the standard's order
        if key not in clean:
            continue
        expected, found = clean[key]
        db.session.add(SurgicalCountItem(
            count=row, item=key,
            expected=max(0, int(expected or 0)),
            found=max(0, int(found or 0))))
    return row


def handle_miscount(count, recounted=None, imaging=None, resolution=None,
                    user=None):
    """Record what the team did about a miscount — evidence 4.

    Every argument is optional and ``None`` **stays** ``None``: the three-state
    rule this table is built on is that *nobody has said* and *it was decided
    against* are different answers, and a call that left one out must not
    silently write "no".
    """
    if count is None:
        return None
    if recounted is not None:
        count.recounted = bool(recounted)
    if imaging is not None:
        count.imaging = bool(imaging)
    if resolution is not None:
        count.resolution = (resolution or "").strip() or None
    return count


def report(count, user=None, at=None):
    """Stamp that the miscount was reported. Returns the row, or ``None``.

    **Once.** Reporting twice is somebody chasing, and moving the stamp would
    lose when the incident actually reached whoever collects them — which is
    the number evidence 5 monitors.
    """
    if count is None or count.reported_at:
        return None
    count.reported_at = at or datetime.utcnow()
    count.reported_by = getattr(user, "id", None)
    return count


def sign(operation, user=None, at=None):
    """The performing physician signs the count record — evidence 3.

    **Refused on a case with no counts.** A signature under an empty record is
    the same false green tick the box was, wearing a name.
    """
    if operation is None or not counts_for(operation):
        return None
    operation.counts_signed_by = getattr(user, "id", None)
    operation.counts_signed_at = at or datetime.utcnow()
    return operation


# -------------------------------------------------------- watching it ----
def miscounts(start=None, end=None):
    """Every count that disagreed over a period, most recent first.

    Evidence 5 — *"The hospital monitors the reported data on the counting
    process and takes actions to control or improve the process."* The program
    counts; what to do about it is the theatre's.
    """
    query = (SurgicalCount.query.join(Operation,
                                      SurgicalCount.operation_id == Operation.id))
    if start is not None:
        query = query.filter(Operation.on_date >= start)
    if end is not None:
        query = query.filter(Operation.on_date <= end)
    rows = query.order_by(Operation.on_date.desc(), SurgicalCount.id.desc()).all()
    return [c for c in rows if not c.agrees]


def miscount_summary(start=None, end=None):
    """``{"cases", "miscounts", "reported", "by_item"}`` over a period.

    ``reported`` beside ``miscounts`` on purpose: a theatre that finds its
    miscounts and never reports them has a different problem from one that
    reports every one, and a single total hides which.
    """
    rows = miscounts(start, end)
    by_item = {}
    for count in rows:
        for item in count.short:
            by_item[item.item] = by_item.get(item.item, 0) + 1
    return {
        "cases": len({c.operation_id for c in rows}),
        "miscounts": len(rows),
        "reported": sum(1 for c in rows if c.reported),
        "by_item": sorted(({"item": k, "count": n} for k, n in by_item.items()),
                          key=lambda r: (-r["count"], r["item"])),
    }
