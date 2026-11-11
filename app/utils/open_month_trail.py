"""Changes to the books before the month is closed (MONEY_SAFETY_PLAN.md ف-٧).

Asked: «نفّذ الحل الوسط وخلّي في المستشفيات تقدر تعدّل الإجراء ده من
الإعدادات … نخلّي القيود الكاملة تتكتب في بند تاني».

In an open month an entry is rebuilt in place, so the ledger keeps one entry
per document and every report stays as it was. Every such change now also
leaves a row in a separate book (``JournalRevision``, written by
``accounting.record_revision``): who, when, the lines before and after. The
ledger never reads that book, so it moves no total.

Two ways of reading it, the clinic's choice (``open_month_trail``):

* **summary** (every clinic, the default) — the review before closing: who
  changed which bill or expense, when, from how much to how much. A bill
  growing during its own day — a test added while the child is still in the
  clinic — is how a visit works, not an edit, and is counted but folded away.
* **full** (offered where the hospital's parts are on) — the same changes as
  the full book: for each one a reversal of what the entry said, dated as it
  was, and a new entry dated as it is now — the form an outside auditor
  reads — downloadable as a file.

Either way the record is written from the day this was installed, so a
hospital switching to the full book later sees its history, not an empty page.
"""
from datetime import timedelta

from app.extensions import db

KEY = "open_month_trail"
MODES = ("summary", "full")


def mode():
    from app.models import Setting

    value = (Setting.get(KEY) or "").strip()
    return value if value in MODES else "summary"


def offered():
    """Whether the full book is a choice here: a hospital's parts are on (the
    same test as the hospital reports), or the clinic already chose it."""
    from app.utils.facility import is_configured
    from app.utils.hospital_kpis import any_part

    return mode() == "full" or (is_configured() and any_part())


def full_book_on():
    return mode() == "full" and offered()


def _later(row):
    """A change made on a later day than the entry was written, or a removal
    — what the review is for. The same day is the bill still being made."""
    from app.utils.clock import local_date

    if row.kind != "changed" or row.entry_created_at is None:
        return True
    return local_date(row.created_at) != local_date(row.entry_created_at)


def changes(d_from, d_to, everything=False, limit=1000):
    """``(rows, folded)`` — the changes made between two of the clinic's days,
    newest first; ``folded`` is how many same-day changes were left out."""
    from app.models import JournalRevision
    from app.utils.med_board import utc

    start, end = utc(d_from, d_to)
    rows = (JournalRevision.query
            .filter(JournalRevision.created_at >= start, JournalRevision.created_at < end)
            .order_by(JournalRevision.created_at.desc(), JournalRevision.id.desc())
            .limit(limit).all())
    if everything:
        return rows, 0
    kept = [r for r in rows if _later(r)]
    return kept, len(rows) - len(kept)


def for_period(period):
    """How many later changes touched the entries of a period still open —
    the number its «close» button is read next to."""
    from app.models import JournalRevision

    rows = (JournalRevision.query
            .filter(db.or_(JournalRevision.old_date.between(period.start_date, period.end_date),
                           JournalRevision.new_date.between(period.start_date, period.end_date)))
            .all())
    return sum(1 for r in rows if _later(r))


def book(rows):
    """The full book: for each change a reversal of what the entry said
    (dated as it was) and, unless it was removed, the entry as it is now."""
    out = []
    for r in sorted(rows, key=lambda x: (x.created_at, x.id)):
        reversal = [{**ln, "debit": ln["credit"], "credit": ln["debit"]} for ln in r.before()]
        if reversal:
            out.append({"rev": r, "role": "reversal", "date": r.old_date, "lines": reversal})
        if r.kind != "removed" and r.after():
            out.append({"rev": r, "role": "restated", "date": r.new_date, "lines": r.after()})
    return out


def csv_text(rows, lang="ar"):
    import csv
    import io

    from app.i18n import translate as t
    from app.utils.clock import to_local

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([t("trail.col_changed_at"), t("trail.col_by"), t("trail.col_entry"),
                t("trail.col_document"), t("trail.col_role"), t("trail.col_date"),
                t("trail.col_account"), t("trail.col_debit"), t("trail.col_credit")])
    for item in book(rows):
        r = item["rev"]
        when = to_local(r.created_at)
        who = r.user.display_name(lang) if r.user else t("trail.by_program")
        for ln in item["lines"]:
            w.writerow([when.strftime("%Y-%m-%d %H:%M") if when else "", who, r.entry_number,
                        f"{r.source_type or ''} {r.source_id or ''}".strip(),
                        t("trail.role_" + item["role"]),
                        item["date"].isoformat() if item["date"] else "",
                        f"{ln['code']} {ln['name']}", f"{ln['debit']:.2f}", f"{ln['credit']:.2f}"])
    return "﻿" + buf.getvalue()


def default_range():
    """From the first of last month to today — the month being closed and
    the one being worked in."""
    from app.utils.clock import local_today

    today = local_today()
    first_this = today.replace(day=1)
    return (first_this - timedelta(days=1)).replace(day=1), today


__all__ = ["KEY", "MODES", "book", "changes", "csv_text", "default_range",
           "for_period", "full_book_on", "mode", "offered"]
