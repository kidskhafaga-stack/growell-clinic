"""«Pay first, then it is done» in emergency — for a child triaged
non-urgent, and never for anybody else.

Asked as *«خيار يدفع الاول وبعدين يتنفذ والحالة الخطر تتنفذ على طول»*, and
held to the law the hospital's lawyer confirmed: the Prime Minister's decree
1063 of 2014 makes emergency treatment free for the first 48 hours, and a
hospital that asks for money for it can be closed.

So the rule is narrow, and this module is the whole of it:

* **off unless the hospital switches it on** (``er_pay_first``);
* it holds **only a child the triage called non-urgent** — the hospital's
  own triage, read as ``urgent is False``. A child not triaged yet is not
  held: until somebody has looked, nobody knows the child is not critical;
* held means the treatment and the bedside study **wait to be given or
  done** — the doctor writes them as always, so nothing is lost while the
  family is at the desk;
* the desk lifts it — «paid, go ahead» — after taking the money; and the
  doctor lifts it by triaging the child urgent, at any moment, with no one's
  leave.

And the other half of the decree: the urgent attendances, and what their
first 48 hours were billed, are listed (`free_48h`) so they can be claimed
from whoever pays them.
"""
from datetime import datetime, timedelta

from app.extensions import db

KEY = "er_pay_first"


def enabled():
    from app.models import Setting

    return (Setting.get(KEY) or "0") == "1"


def waits(attendance):
    """Whether this attendance's treatment waits for the desk."""
    return bool(attendance is not None and enabled()
                and attendance.urgent is False
                and attendance.pay_cleared_at is None
                and attendance.departed_at is None)


def clear(attendance, user=None, at=None):
    """The desk took the money: go ahead."""
    if attendance is None:
        raise ValueError("no attendance")
    attendance.pay_cleared_at = at or datetime.utcnow()
    attendance.pay_cleared_by = getattr(user, "id", None)
    db.session.flush()
    return attendance


def free_48h(date_from, date_to):
    """``[{attendance, billed}]`` — urgent attendances that arrived in the
    window, and what was billed on their visit's invoices in the first 48
    hours after arrival."""
    from app.models import EmergencyVisit, Invoice

    start = datetime.combine(date_from, datetime.min.time())
    end = datetime.combine(date_to, datetime.max.time())
    rows = (EmergencyVisit.query
            .filter(EmergencyVisit.urgent.is_(True),
                    EmergencyVisit.arrived_at >= start,
                    EmergencyVisit.arrived_at <= end)
            .order_by(EmergencyVisit.arrived_at.desc()).all())
    out = []
    for a in rows:
        billed = 0.0
        if a.visit_id:
            limit = (a.arrived_at + timedelta(hours=48)).date()
            for inv in Invoice.query.filter(Invoice.visit_id == a.visit_id).all():
                for item in inv.items:
                    when = item.service_date or inv.invoice_date
                    if when is None or when <= limit:
                        billed += item.net
        out.append({"attendance": a, "billed": round(billed, 2)})
    return out
