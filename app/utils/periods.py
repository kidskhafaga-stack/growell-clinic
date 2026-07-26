"""Accounting periods (فترات محاسبة) — closing the books on a month.

A report printed for January has to still say the same thing in March. That
only holds if nothing can be written into January after it was reviewed, so a
**closed period** refuses back-dated money: no invoice, payment, refund,
expense or manual journal entry inside it.

Nothing is closed by default — a clinic that doesn't work this way never
notices the feature. Closing (and reopening, which is a deliberate and logged
act) is an admin's decision.
"""
import calendar
from datetime import date, datetime

from app.extensions import db
from app.models import AccountingPeriod

MONTHS_AR = ["يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو", "يوليو",
             "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر"]


def month_name(year, month, lang="ar"):
    if lang == "en":
        return f"{calendar.month_name[month]} {year}"
    return f"{MONTHS_AR[month - 1]} {year}"


def period_for(on_date):
    """The period covering ``on_date``, if the clinic defined one."""
    if not on_date:
        return None
    return (AccountingPeriod.query
            .filter(AccountingPeriod.start_date <= on_date,
                    AccountingPeriod.end_date >= on_date)
            .order_by(AccountingPeriod.start_date.desc()).first())


def is_locked(on_date):
    """Whether money may no longer be written on ``on_date``."""
    p = period_for(on_date)
    return bool(p and p.is_closed)


def locked_period(on_date):
    """The closed period blocking ``on_date`` (or None when it's writable)."""
    p = period_for(on_date)
    return p if (p and p.is_closed) else None


def period_blocked(on_date, flash_it=True):
    """Whether ``on_date`` falls inside a closed accounting period.

    A closed month is closed for **everything that carries a value**, not only
    for invoices. Stock is money sitting on a shelf: receiving a box into
    January after January's books are signed changes January's closing stock
    value, and the report a clinic printed then no longer matches the one it
    prints now. So the store obeys the same lock the till does.

    Callers bail out instead of writing. ``flash_it`` says the reason on the
    screen, which is the difference between a refusal and a bug.
    """
    from flask import flash

    from app.i18n import t

    period = locked_period(on_date)
    if period is None:
        return False
    if flash_it:
        try:
            flash(t("periods.locked_warn").replace("{name}", period.name),
                  "danger")
        except Exception:  # noqa: BLE001 - outside a request, the answer stands
            pass
    return True


def ensure_month(year, month):
    """Get (or create) the period for one calendar month."""
    start = date(year, month, 1)
    end = date(year, month, calendar.monthrange(year, month)[1])
    existing = (AccountingPeriod.query
                .filter_by(start_date=start, end_date=end).first())
    if existing is not None:
        return existing
    period = AccountingPeriod(name=month_name(year, month), start_date=start,
                              end_date=end, status="open")
    db.session.add(period)
    db.session.flush()
    return period


def generate_months(year):
    """Create any missing month of ``year``; returns how many were created."""
    made = 0
    for m in range(1, 13):
        start = date(year, m, 1)
        end = date(year, m, calendar.monthrange(year, m)[1])
        if AccountingPeriod.query.filter_by(start_date=start,
                                            end_date=end).first() is None:
            db.session.add(AccountingPeriod(
                name=month_name(year, m), start_date=start, end_date=end,
                status="open"))
            made += 1
    if made:
        db.session.flush()
    return made


def close_period(period, user_id=None):
    period.status = "closed"
    period.closed_at = datetime.utcnow()
    period.closed_by = user_id
    return period


def reopen_period(period, user_id=None):
    period.status = "open"
    period.closed_at = None
    period.closed_by = user_id
    return period
