"""Reading a doctor's clinical privileges, and the booking that has to match.

GAHAR SAS.02 (أ): *"Surgeries and invasive procedures are booked **according to
granted clinical privileges**"*, and WFM.12's fourth item of evidence names
where that has to happen: *"Clinical privileges are **accessible to and used by
staff involved in booking** surgery/invasive procedures."*

**It warns; it does not refuse.** There is exactly one hard refusal in the
theatre module — a case cannot start without its sign-in — and this is not it.
At three in the morning the only surgeon in the building may be the one without
the privilege, and a program that blocks the booking does not make the child
safer, it makes the booking happen somewhere the program cannot see. So the
gap is named at the moment of booking, and going ahead **records who accepted
it and why**. That recorded exception is the "ongoing process to ensure that
booked procedures match" — a process, not a wall.

**And the answer is judged against the day of the operation**, never against
today. A case booked in March under a privilege that stood in March goes on
reading as correct after the privilege lapses; a privilege granted in April
does not retroactively make March's booking fine. The consent item follows the
same rule for the same reason.
"""
from app.extensions import db
from app.models import ClinicalPrivilege
from app.utils.clock import local_today

#: What a booking can be, once a surgeon and a procedure are both known.
#:
#: ``unknown`` is the one that has to exist: a case booked as free text with no
#: service behind it cannot be checked against anything, and calling that
#: ``ok`` would be the program reporting a verification it never did.
BOOKING_STATES = ("unknown", "ok", "supervised", "outside", "acknowledged")


def live(doctor_id, on_date=None):
    """This doctor's privileges in force on ``on_date``, newest grant first."""
    if not doctor_id:
        return []
    day = on_date or local_today()
    rows = (ClinicalPrivilege.query
            .filter_by(doctor_id=doctor_id)
            .order_by(ClinicalPrivilege.granted_at.desc(),
                      ClinicalPrivilege.id.desc()).all())
    return [r for r in rows if r.stands_on(day)]


def all_for(doctor_id):
    """Everything on this doctor's file, standing or not.

    The withdrawn and the lapsed are included on purpose: the screen that
    manages privileges is the one place somebody has to be able to see that a
    privilege *used* to be there — a list of only the live ones answers "what
    can he do" and never "what happened to the other one".
    """
    if not doctor_id:
        return []
    return (ClinicalPrivilege.query
            .filter_by(doctor_id=doctor_id)
            .order_by(ClinicalPrivilege.granted_at.desc(),
                      ClinicalPrivilege.id.desc()).all())


def covers(privilege, service):
    """Does this privilege authorise this procedure?

    A row names **either** one service or a whole service type, and the type
    grant is what makes a delineation list maintainable — "general surgery: all
    of it" is one row, not forty.
    """
    if privilege is None or service is None:
        return False
    if privilege.service_id:
        return privilege.service_id == service.id
    if privilege.service_type:
        # ``Service.kind`` and not ``service_type``: a service created before
        # the Service Engine has the column empty and its type derived from
        # its category, and a privilege list that missed those would read as
        # "unprivileged" for every procedure the clinic has had longest.
        return privilege.service_type == service.kind
    # A row scoped to nothing authorises nothing. It should not exist, and if
    # one does, reading it as "everything" would be the widest possible
    # failure from the narrowest possible bug.
    return False


def matching(doctor_id, service, on_date=None):
    """The privileges that cover this procedure, unsupervised ones first.

    Ordered so the caller reads the strongest answer without looking at the
    rest: a doctor holding both a supervised grant and a full one is not
    supervised for this case.
    """
    rows = [p for p in live(doctor_id, on_date) if covers(p, service)]
    return sorted(rows, key=lambda p: (p.is_supervised, p.id))


def state(doctor_id, service, on_date=None):
    """Where a booking stands against the privileges — in one word.

    ``unknown`` · ``ok`` · ``supervised`` · ``outside``.

    ``supervised`` is kept apart from ``ok`` because WFM.12 (g) keeps them
    apart: a privilege under supervision names an accountable supervisor, and a
    list that showed both as green would lose the one fact somebody rostering
    the day needs.
    """
    if not doctor_id or service is None:
        return "unknown"
    rows = matching(doctor_id, service, on_date)
    if not rows:
        return "outside"
    return "supervised" if rows[0].is_supervised else "ok"


def allowed(doctor_id, service, on_date=None):
    """The one question the booking form asks."""
    return state(doctor_id, service, on_date) in ("ok", "supervised")


def doctors_for(service, on_date=None):
    """Who may book this procedure, as ids.

    *"Clinical privileges are accessible to and used by staff involved in
    booking"* — this is that access. The booking form marks them rather than
    hiding everybody else, because hiding the unprivileged would make the
    emergency booking impossible instead of visible.
    """
    if service is None:
        return set()
    day = on_date or local_today()
    rows = ClinicalPrivilege.query.all()
    return {p.doctor_id for p in rows
            if p.stands_on(day) and covers(p, service)}


def grant(doctor_id, *, service_id=None, service_type=None, kind="standard",
          supervisor_id=None, supervision=None, valid_from=None,
          valid_until=None, note=None, user=None):
    """Write one privilege down. Returns it, or ``None``.

    Refused without a scope, and refused with **both** scopes: a row that names
    a type and a service at once has two different answers to "what does this
    authorise", and whichever the code picked would be a coin toss nobody
    recorded.
    """
    from app.models import PRIVILEGE_KINDS

    if not doctor_id or kind not in PRIVILEGE_KINDS:
        return None
    has_service = bool(service_id)
    has_type = bool((service_type or "").strip())
    if has_service == has_type:
        return None
    row = ClinicalPrivilege(
        doctor_id=doctor_id,
        service_id=service_id or None,
        service_type=(service_type or "").strip()[:20] or None,
        kind=kind,
        supervisor_id=supervisor_id or None,
        supervision=(supervision or "").strip()[:160] or None,
        valid_from=valid_from, valid_until=valid_until,
        granted_by=getattr(user, "id", None),
        note=(note or "").strip()[:200] or None)
    db.session.add(row)
    return row


def withdraw(privilege, reason=None, at=None):
    """Take one back. **Never deleted** — see the model.

    Withdrawing twice does not move the date: the moment it stopped standing is
    a fact, and a second click on a slow screen must not rewrite it.
    """
    from datetime import datetime

    if privilege is None or privilege.withdrawn_at:
        return None
    privilege.withdrawn_at = at or datetime.utcnow()
    privilege.withdrawn_reason = (reason or "").strip()[:200] or None
    return privilege
