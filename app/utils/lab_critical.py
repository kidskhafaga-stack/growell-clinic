"""The lab's own part in a critical value: saying it, and telling a doctor.

Asked as *«القيم الحرجة مش المفروض المعمل يقدر يكتبها»*. The critical limits
are the laboratory's (set on each test's ranges), and a number past them is
flagged by itself; the doctor then says they read it. What the lab could not
do was its own two acts:

* **mark a result critical by hand** — a positive blood culture, a smear
  with blasts: no number crosses a limit, and the technician is the one who
  knows. The reason is written, and no later number takes the mark away;
* **record telling a doctor** — whom, how (telephone, in person, a message),
  when, by whom, and whether the doctor read the value back. The doctor's
  own «I read it» stays the doctor's (`lab_results.mark_read`).
"""
from datetime import datetime

from app.extensions import db

CALL_METHODS = ("phone", "in_person", "message")


class CriticalError(ValueError):
    """A refusal with a key the screen can name (``lab_critical.err_<key>``)."""


def mark(order, reason, user=None, at=None):
    """The technician says this result is critical."""
    from app.utils.lab_results import invalidate

    reason = (reason or "").strip()[:200]
    if order is None or order.kind != "lab":
        raise CriticalError("not_lab")
    if not reason:
        raise CriticalError("need_reason")
    if not (order.result_text or order.result_value is not None or order.analytes_resulted):
        raise CriticalError("no_result")
    order.critical_manual = reason
    if order.critical_at is None:
        order.critical_at = at or datetime.utcnow()
        order.critical_seen_at = order.critical_seen_by = None
    invalidate()
    db.session.flush()
    return order


def call(order, called_to, method, read_back, user=None, at=None):
    """The lab told a doctor."""
    called_to = (called_to or "").strip()[:120]
    if order is None or order.critical_at is None:
        raise CriticalError("not_critical")
    if not called_to:
        raise CriticalError("need_who")
    if method not in CALL_METHODS:
        raise CriticalError("bad_method")
    order.critical_called_to = called_to
    order.critical_call_method = method
    order.critical_read_back = bool(read_back)
    order.critical_called_at = at or datetime.utcnow()
    order.critical_called_by = getattr(user, "id", None)
    db.session.flush()
    return order
