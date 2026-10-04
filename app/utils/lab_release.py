"""A laboratory result reviewed and released — GAHAR DAS.20 (ب) and (أ-٨).

*"Reviewing, verifying, and reporting of results by authorized staff
member"*, and the final report names *"the verifying individual"*.

**Off until the hospital switches it on** (``lab_verify_required``). A clinic
whose doctor types what a paper report said has nobody to verify it, and a
step it never asked for would only leave every result looking unfinished.

**On, it is a record and a word on every screen, not a wall.** The result is
still on the child's file the moment it is written — a doctor waiting on a
potassium is never kept from it — but it says «not verified yet» wherever it
is shown, the printed report says «preliminary», and the lab has a list of
what is waiting for release. A critical value is told at once, verified or
not (`lab_critical`): GSR.03 does not wait for paperwork.

**Who may release** is the hospital's to say, with the ``lab_release``
capability. The person who typed the result may release it if they hold it:
in a small laboratory the senior technician is both.
"""
from datetime import datetime

from app.extensions import db

SETTING = "lab_verify_required"
CAPABILITY = "lab_release"


class ReleaseError(ValueError):
    """A refusal with a key the screen can name (``lab_release.err_<key>``)."""


def required():
    from app.models import Setting

    try:
        return Setting.get(SETTING) == "1"
    except Exception:                   # noqa: BLE001 — settings not ready
        return False


def may_release(user):
    return bool(user is not None and getattr(user, "is_authenticated", False)
                and user.can(CAPABILITY))


def awaiting(order):
    """Written, a lab order, and not yet released — where release is asked."""
    return bool(order is not None and order.kind == "lab"
                and order.status == "resulted" and order.verified_at is None
                and required())


def verify(order, user, at=None):
    """Release the result as it stands."""
    if order is None or order.kind != "lab":
        raise ReleaseError("not_lab")
    if order.status != "resulted":
        raise ReleaseError("no_result")
    if not may_release(user):
        raise ReleaseError("not_allowed")
    order.verified_at = at or datetime.utcnow()
    order.verified_by = user.id
    db.session.flush()
    return order


def waiting(limit=200):
    """Results waiting for release, oldest first — empty where release is
    not asked for."""
    from sqlalchemy.orm import selectinload

    from app.models import VisitInvestigation

    if not required():
        return []
    return (VisitInvestigation.query
            .options(selectinload(VisitInvestigation.patient))
            .filter(VisitInvestigation.kind == "lab",
                    VisitInvestigation.status == "resulted",
                    VisitInvestigation.verified_at.is_(None),
                    VisitInvestigation.done_outside.is_not(True))
            .order_by(VisitInvestigation.resulted_at, VisitInvestigation.id)
            .limit(limit).all())


def waiting_count():
    from app.models import VisitInvestigation

    if not required():
        return 0
    return (db.session.query(db.func.count(VisitInvestigation.id))
            .filter(VisitInvestigation.kind == "lab",
                    VisitInvestigation.status == "resulted",
                    VisitInvestigation.verified_at.is_(None),
                    VisitInvestigation.done_outside.is_not(True))
            .scalar() or 0)


def report_rows(ids, user=None):
    """The resulted lab orders to print on one report — one child's only,
    in the order they were asked for. ``(patient, rows)`` or ``(None, [])``."""
    from app.models import VisitInvestigation

    ids = [i for i in ids if isinstance(i, int)][:40]
    if not ids:
        return None, []
    rows = (VisitInvestigation.query
            .filter(VisitInvestigation.id.in_(ids),
                    VisitInvestigation.kind == "lab",
                    VisitInvestigation.status == "resulted")
            .order_by(VisitInvestigation.created_at, VisitInvestigation.id).all())
    if not rows:
        return None, []
    patient_id = rows[0].patient_id
    rows = [r for r in rows if r.patient_id == patient_id]
    return rows[0].patient, rows
