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


def periods_for(on_date):
    """**Every** period covering ``on_date``, narrowest first.

    There can be more than one, and that is the point of having quarters and
    years at all: February 2026 sits inside الربع الأول *and* inside 2026. The
    old code asked for a single period and took the one that started latest,
    which meant closing a quarter locked nothing — the month inside it starts
    later, so it was the one found, and it was still open. The books would have
    been reported as closed and still accepted a back-dated invoice.
    """
    if not on_date:
        return []
    rows = (AccountingPeriod.query
            .filter(AccountingPeriod.start_date <= on_date,
                    AccountingPeriod.end_date >= on_date).all())
    return sorted(rows, key=lambda p: (p.end_date - p.start_date, p.start_date))


def period_for(on_date):
    """The narrowest period covering ``on_date``, if the clinic defined one."""
    rows = periods_for(on_date)
    return rows[0] if rows else None


def is_locked(on_date):
    """Whether money may no longer be written on ``on_date``."""
    return locked_period(on_date) is not None


def locked_period(on_date):
    """A closed period blocking ``on_date`` (or None when it's writable).

    **Any** closed period covering the date is enough. Somebody who closed
    2026 has said the year is done; that it was said on the year rather than on
    each of its months does not make it less true, and a lock you can slip past
    by picking a different granularity is not a lock.

    The narrowest closed one is returned, because it is the most precise answer
    to "why can't I write here".
    """
    for period in periods_for(on_date):
        if period.is_closed:
            return period
    return None


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


KINDS = ["month", "quarter", "half", "year"]

# What each granularity is called, per language. Quarters and halves are how
# an accountant actually hands over — a clinic reviews the quarter, signs it,
# and the months inside it stop being writable.
_NAMES = {
    "ar": {"quarter": "الربع {n} {year}", "half": "النصف {n} {year}",
           "year": "سنة {year}"},
    "en": {"quarter": "Q{n} {year}", "half": "H{n} {year}",
           "year": "Year {year}"},
}
_HALF_AR = {1: "الأول", 2: "الثاني"}
_QUARTER_AR = {1: "الأول", 2: "الثاني", 3: "الثالث", 4: "الرابع"}


def span_name(kind, year, n=None, lang="ar"):
    """What to call a quarter/half/year period."""
    if kind == "month":
        return month_name(year, n, lang)
    template = _NAMES.get(lang, _NAMES["ar"])[kind]
    if lang == "ar" and kind == "quarter":
        n = _QUARTER_AR[n]
    elif lang == "ar" and kind == "half":
        n = _HALF_AR[n]
    return template.replace("{n}", str(n or "")).replace("{year}", str(year))


def _spans(kind, year):
    """``(name_index, start, end)`` for each period of ``kind`` in ``year``."""
    if kind == "month":
        return [(m, date(year, m, 1),
                 date(year, m, calendar.monthrange(year, m)[1]))
                for m in range(1, 13)]
    if kind == "quarter":
        return [(q, date(year, q * 3 - 2, 1),
                 date(year, q * 3, calendar.monthrange(year, q * 3)[1]))
                for q in range(1, 5)]
    if kind == "half":
        return [(h, date(year, h * 6 - 5, 1),
                 date(year, h * 6, calendar.monthrange(year, h * 6)[1]))
                for h in range(1, 3)]
    return [(None, date(year, 1, 1), date(year, 12, 31))]


def generate_periods(year, kind="month", lang="ar"):
    """Create any missing period of ``kind`` in ``year``; returns how many.

    Idempotent — matched on the dates, so pressing the button twice is not a
    way to end up with two copies of March. The four granularities coexist on
    purpose: a clinic that reviews quarterly closes the quarter, a clinic that
    reviews monthly closes the month, and whichever is closed refuses money
    inside it.
    """
    if kind not in KINDS:
        kind = "month"
    made = 0
    for n, start, end in _spans(kind, year):
        if AccountingPeriod.query.filter_by(start_date=start,
                                            end_date=end).first() is not None:
            continue
        db.session.add(AccountingPeriod(
            name=span_name(kind, year, n, lang), kind=kind,
            start_date=start, end_date=end, status="open"))
        made += 1
    if made:
        db.session.flush()
    return made


def generate_months(year):
    """Create any missing month of ``year``; returns how many were created."""
    return generate_periods(year, "month")


def selectable_years(back=5, forward=2):
    """Years the screen **suggests**. Any year can still be typed.

    This started as a closed list and that was the mistake: the suggestions are
    a convenience for the years a clinic actually wants nine times out of ten,
    and turning them into the only reachable years meant a clinic entering
    2019's books — or opening 2030 — was told no by a dropdown, with nothing on
    the screen explaining why.
    """
    this_year = date.today().year
    years = {y for y in range(this_year - back, this_year + forward + 1)}
    years |= {p.start_date.year for p in AccountingPeriod.query.all()}
    return sorted(years)


# The books are not a time machine. Outside this, a "year" is a typo — a
# stray keystroke turning 2026 into 22026 would otherwise create twelve
# periods twenty thousand years out and leave somebody hunting for them.
YEAR_MIN = 1900
YEAR_MAX = 2200


def valid_year(value, fallback=None):
    """``value`` as a usable year, else ``fallback`` (today's year by default).

    Typed years are the point, so this is deliberately permissive about which
    year and strict only about it being one.
    """
    try:
        year = int(str(value).strip())
    except (TypeError, ValueError, AttributeError):
        return fallback if fallback is not None else date.today().year
    if YEAR_MIN <= year <= YEAR_MAX:
        return year
    return fallback if fallback is not None else date.today().year


def count_periods(year, kind=None):
    """How many periods this year already has — for "you did this already"."""
    query = AccountingPeriod.query.filter(
        AccountingPeriod.start_date >= date(year, 1, 1),
        AccountingPeriod.start_date <= date(year, 12, 31))
    if kind:
        query = query.filter(AccountingPeriod.kind == kind)
    return query.count()


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
