"""Shifts added up per person and per till, over a window.

Asked for while the design of the safe was still undecided: a report that reads
the shifts the program already records, so a clinic can *look at what actually
happens* before deciding how the drawer should work.

Every number here is the shift's own — ``collected``, ``expected_cash``,
``variance`` — read off :class:`CashierShift` rather than recomputed. A summary
that disagreed with the shift reports it totals would be worse than no summary.

**Over and short are kept apart, and that is the whole point of the report.**
Somebody 200 over on Monday and 200 short on Tuesday nets to zero, and a net of
zero reads as "this desk is fine". It is not fine: it is two differences nobody
explained, and quite possibly one of them being used to cover the other. So the
totals carry three numbers — what was short, what was over, and the net — and
the count of shifts that came out wrong at all.

**An open shift has no verdict.** ``variance`` is ``None`` until somebody
counts, and None is not zero: treating an unfinished shift as balanced would
quietly improve everybody's record by leaving shifts open.

**And the difference is a cash difference.** Card takings do not sit in a
drawer and are never part of what gets counted, so a till that mostly takes
cards will show small variances against large collections. The report says what
was collected in total and what was collected in cash, side by side, so nobody
reads the first against the second.
"""
from app.extensions import db


def _shifts(date_from, date_to, account_id=None, user_id=None):
    """Closed and open shifts that started inside the window.

    By ``opened_at``, not by close: a shift that runs past midnight belongs to
    the day it was opened, which is the day the person worked and the day the
    clinic will look for it under.

    **And "the day it was opened" is the clinic's day, not the server's.** The
    dates arriving here are a person's — typed into a report screen, or
    `local_today()` — while `opened_at` is stored as naive UTC. Combining the
    one with `time.min` and comparing it to the other reads the clinic's
    midnight as UTC midnight, so for the two or three hours a night when Cairo
    is already tomorrow, every shift opened in that window was reported under
    the previous day: missing from its own night's reconciliation and sitting
    in the total of the night before, against whoever worked that one.

    `to_utc` is the conversion, and it was already being used correctly for the
    same shape in `app/utils/live.py`. Nothing here was hard; it was simply not
    done, and no test could see it because the suite ran on a machine whose
    clock agreed with the clinic's.
    """
    from datetime import datetime, time

    from sqlalchemy.orm import selectinload

    from app.models import CashierShift
    from app.utils.clock import to_utc

    start = to_utc(datetime.combine(date_from, time.min))
    end = to_utc(datetime.combine(date_to, time.max))
    query = (CashierShift.query
             .options(selectinload(CashierShift.payments))
             .filter(CashierShift.opened_at >= start,
                     CashierShift.opened_at <= end))
    if account_id:
        query = query.filter(CashierShift.account_id == account_id)
    if user_id:
        query = query.filter(CashierShift.opened_by == user_id)
    return query.order_by(CashierShift.opened_at).all()


def _blank():
    return {"shifts": 0, "open": 0, "collected": 0.0, "cash": 0.0,
            "refunds": 0.0, "paid_out": 0.0, "expected": 0.0, "counted": 0.0,
            "short": 0.0, "over": 0.0, "net": 0.0, "off": 0}


def _fold(row, shift, paid_out):
    row["shifts"] += 1
    row["collected"] = round(row["collected"] + shift.collected, 2)
    row["cash"] = round(row["cash"] + shift.cash_collected, 2)
    row["refunds"] = round(row["refunds"] + shift.refunds, 2)
    row["paid_out"] = round(row["paid_out"] + paid_out, 2)

    if shift.counted_cash is None:
        # Still open, or closed without a count. Either way there is nothing
        # to reconcile yet, and folding a zero in would say it reconciled.
        row["open"] += 1
        return row

    row["expected"] = round(row["expected"] + shift.expected_cash, 2)
    row["counted"] = round(row["counted"] + shift.counted_cash, 2)
    difference = shift.variance or 0
    if difference < 0:
        row["short"] = round(row["short"] + abs(difference), 2)
    elif difference > 0:
        row["over"] = round(row["over"] + difference, 2)
    if difference:
        row["off"] += 1
    row["net"] = round(row["over"] - row["short"], 2)
    return row


def summary(date_from, date_to, account_id=None, user_id=None):
    """``{people, tills, totals, shifts}`` for the window.

    ``people`` and ``tills`` are the same shifts folded two ways, because the
    question "is this person short" and the question "is this desk short" have
    different answers whenever more than one person works a desk — which is the
    case the whole report exists to make visible.
    """
    from app.models import CashierShift, User

    rows = _shifts(date_from, date_to, account_id, user_id)
    paid = CashierShift.paid_out_for([s.id for s in rows])

    people, tills, totals = {}, {}, _blank()
    for shift in rows:
        out = paid.get(shift.id, 0.0)
        _fold(people.setdefault(shift.opened_by, dict(_blank(), key=shift.opened_by)),
              shift, out)
        _fold(tills.setdefault(shift.account_id, dict(_blank(), key=shift.account_id)),
              shift, out)
        _fold(totals, shift, out)

    named = {u.id: u for u in User.query.filter(
        User.id.in_([k for k in people if k])).all()} if people else {}
    for key, row in people.items():
        row["who"] = named.get(key)
    accounts = _accounts([k for k in tills if k])
    for key, row in tills.items():
        row["till"] = accounts.get(key)

    # Most shifts first, then the busiest desks: a person or a desk with one
    # shift in the window is noise at the top of a list somebody is scanning
    # for a pattern.
    order = lambda r: (-r["shifts"], -r["collected"])  # noqa: E731
    return {
        "people": sorted(people.values(), key=order),
        "tills": sorted(tills.values(), key=order),
        "totals": totals,
        "shifts": rows,
    }


def _accounts(ids):
    from app.models import CashAccount

    if not ids:
        return {}
    return {a.id: a for a in
            CashAccount.query.filter(CashAccount.id.in_(ids)).all()}


def shared_tills(result):
    """Tills that more than one person worked in the window.

    The report's own finding, and the reason it was asked for. Where a desk was
    worked by two people, "who is short" and "which drawer is short" stop being
    the same question — and if the money is handed over at the end of each
    shift rather than left in the drawer, they should never have been.
    """
    seen = {}
    for shift in result.get("shifts", []):
        if shift.account_id and shift.opened_by:
            seen.setdefault(shift.account_id, set()).add(shift.opened_by)
    return {till: people for till, people in seen.items() if len(people) > 1}
