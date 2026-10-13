"""The minimal retesting interval — GAHAR DAS.14 (h) and ICD.17 ev. 5.

*"Minimal retesting intervals are defined as the minimum time before a test
should be repeated"* (ICD.17), and *"requests to repeat tests are restricted
… and the reasons to override the rules are explained"* (ev. 5). The
interval is the laboratory's, per test; until it is written nothing is a
repeat. A repeat is never refused — a child can deteriorate in an hour — it
is flagged, and the reason written beside it.
"""
from datetime import timedelta

from app.extensions import db


class RetestError(ValueError):
    """A refusal with a locale key (``lab_retest.err_<key>``)."""


def previous(order):
    """The same test for the same child inside the interval before this
    order — the earlier order, or ``None``."""
    from app.models import VisitInvestigation

    test = getattr(order, "investigation", None)
    hours = getattr(test, "retest_hours", None)
    if not hours or order.investigation_id is None or order.created_at is None:
        return None
    since = order.created_at - timedelta(hours=hours)
    return (VisitInvestigation.query
            .filter(VisitInvestigation.patient_id == order.patient_id,
                    VisitInvestigation.investigation_id == order.investigation_id,
                    VisitInvestigation.id != order.id,
                    VisitInvestigation.status != "cancelled",
                    VisitInvestigation.created_at >= since,
                    VisitInvestigation.created_at <= order.created_at)
            .order_by(VisitInvestigation.created_at.desc()).first())


def explain(order, reason, user=None):
    reason = (reason or "").strip()[:200]
    if previous(order) is None:
        raise RetestError("not_repeat")
    if not reason:
        raise RetestError("reason")
    order.repeat_reason, order.repeat_reason_by = reason, getattr(user, "id", None)
    db.session.flush()
    return order


__all__ = ["RetestError", "explain", "previous"]
