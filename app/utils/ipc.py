"""Infection control told when an alert organism grows — and its answer.

The laboratory marks the organisms that need acting on (``MicroOrganism.alert``
— MRSA, ESBL, CRE…). When one is reported on a culture, preliminary or final,
:func:`raise_for` writes an :class:`~app.models.micro.IpcAlert` and the bell
rings for whoever holds ``infection_control``.

**The program suggests; a person decides.** :func:`suggestion` says what is
known — the precaution infection control itself set for that organism, where
the child is now, whether that space isolates, and which isolation beds are
free — and :func:`review` records the decision with the reviewer's name.
Nothing here moves a child, writes an order or picks a precaution on its own.
"""
from datetime import datetime

from app.extensions import db
from app.models.micro import ISOLATION, IpcAlert, MicroOrganism

CAPABILITY = "infection_control"


class IpcError(ValueError):
    """A refusal with a locale key (``ipc.err_<key>``)."""


def may_review(user):
    return bool(user is not None and getattr(user, "is_authenticated", False)
                and (user.is_admin or user.can(CAPABILITY)))


# --------------------------------------------------------------- raising ---
def raise_for(order, culture):
    """An alert for every alert-organism isolate on this culture that has
    none yet. Returns the new alerts."""
    if culture is None:
        return []
    have = {a.isolate_id for a in IpcAlert.query.filter(
        IpcAlert.isolate_id.in_([i.id for i in culture.isolates] or [0])).all()}
    new = []
    for iso in culture.isolates:
        if iso.id is None or iso.id in have or not iso.organism.alert:
            continue
        row = IpcAlert(patient_id=order.patient_id, order_id=order.id,
                       isolate_id=iso.id, organism_id=iso.organism_id)
        db.session.add(row)
        new.append(row)
    if new:
        db.session.flush()
        from app.utils import notifications
        notifications.invalidate()
    return new


def isolate_gone(isolate):
    """The laboratory took an isolate back. An unanswered alert goes with
    it; an answered one stays, readable, without the link."""
    row = IpcAlert.query.filter_by(isolate_id=isolate.id).first()
    if row is None:
        return
    if row.is_open:
        db.session.delete(row)
    else:
        row.isolate_id = None
    db.session.flush()


def open_count():
    return IpcAlert.query.filter(IpcAlert.reviewed_at.is_(None)).count()


# ------------------------------------------------------------ suggesting ---
def suggestion(alert):
    """What is known, for the person deciding:

    ``precaution`` — what infection control set for this organism, or None;
    ``admission`` / ``bed`` — where the child is now, if in a bed;
    ``isolated`` — whether that space isolates;
    ``free`` — isolation beds nobody is in, when the child is not in one.
    """
    from app.utils import beds

    stay = beds.open_admission(alert.patient_id)
    bed = stay.bed if stay is not None else None
    isolated = bool(bed is not None and bed.is_isolation)
    free = beds.free_beds(isolation=True) if stay is not None and not isolated else []
    return {"precaution": alert.organism.precaution, "admission": stay,
            "bed": bed, "isolated": isolated, "free": free}


# ------------------------------------------------------------- deciding ---
def review(alert, form, user):
    """The decision, in the reviewer's name. Precautions as on the theatre
    list — ``standard`` dropped beside a transmission-based one."""
    from app.models.theatre import EXTRA_PRECAUTIONS, PRECAUTIONS

    chosen = set(form.getlist("precautions"))
    keep = [p for p in PRECAUTIONS if p in chosen]
    if not keep:
        raise IpcError("precautions")
    keep = [p for p in keep if p in EXTRA_PRECAUTIONS] or ["standard"]
    isolation = form.get("isolation")
    if isolation not in ISOLATION:
        raise IpcError("isolation")
    alert.precautions = ",".join(keep)
    alert.isolation = isolation
    alert.note = (form.get("note") or "").strip() or None
    alert.reviewed_by = getattr(user, "id", None)
    alert.reviewed_at = datetime.utcnow()
    db.session.flush()
    from app.utils import notifications
    notifications.invalidate()
    return alert


def set_precaution(organism, value):
    """What infection control advises for this organism, or nothing."""
    from app.models.theatre import EXTRA_PRECAUTIONS

    if value and value not in EXTRA_PRECAUTIONS:
        raise IpcError("precaution")
    organism.precaution = value or None
    db.session.flush()
    return organism


# --------------------------------------------------------------- reading ---
def for_patient(patient_id, since=None):
    """This child's alerts, newest first — open ones, and answered ones that
    asked for more than standard precautions. ``since`` narrows the
    answered ones to a stay; an open one shows whenever it was raised —
    nobody has answered it yet."""
    rows = (IpcAlert.query.filter(IpcAlert.patient_id == patient_id)
            .order_by(IpcAlert.raised_at.desc(), IpcAlert.id.desc()).all())
    return [a for a in rows if a.is_open or (
        (since is None or a.raised_at >= since)
        and any(p != "standard" for p in a.precaution_list))]


def board(start, end):
    """Open alerts (all of them, oldest first) and the period's answered
    ones, with the alert organisms for the precaution settings."""
    from app.utils.clock import to_utc

    since = to_utc(datetime.combine(start, datetime.min.time()))
    until = to_utc(datetime.combine(end, datetime.max.time()))
    open_rows = (IpcAlert.query.filter(IpcAlert.reviewed_at.is_(None))
                 .order_by(IpcAlert.raised_at, IpcAlert.id).all())
    done = (IpcAlert.query.filter(IpcAlert.reviewed_at.isnot(None),
                                  IpcAlert.raised_at >= since,
                                  IpcAlert.raised_at <= until)
            .order_by(IpcAlert.raised_at.desc(), IpcAlert.id.desc()).all())
    organisms = (MicroOrganism.query.filter_by(alert=True)
                 .order_by(MicroOrganism.name).all())
    return {"open": [(a, suggestion(a)) for a in open_rows], "done": done,
            "organisms": organisms}


__all__ = ["CAPABILITY", "IpcError", "board", "for_patient", "isolate_gone",
           "may_review", "open_count", "raise_for", "review", "set_precaution",
           "suggestion"]
