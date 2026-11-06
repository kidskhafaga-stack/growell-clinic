"""A saved report that sends itself — REPORTS_PLAN.md ت-٤.

*«تقرير محفوظ بيتبعت كل أسبوع أو شهر للمدير، على الإيميل أو واتساب.»*

* **Which period:** the last **complete** one — last week (Saturday to
  Friday, the Egyptian week) or last month. Never a period still running:
  a Wednesday report of "this week" is half a week that reads like a bad one.
* **Whose numbers:** the report runs with the rights of the person who saved
  it, exactly as when they open it. If they no longer may (rights changed,
  account closed), nothing is sent and the screen says why.
* **What goes:** a short message — the report's name, the period, the total
  and the first rows — and the whole table as an Excel file.
* **When:** there is no scheduler in this program (``utils/heartbeat``): the
  desk's screens refresh all day and this rides on them, at most every
  :data:`TICK_MINUTES`, its turn taken with ``Setting.swap`` so two server
  processes never send the same report. A period goes once: the last day of
  the period sent is kept on the report.
* **Through:** the clinic's own mailbox (``mail_channel.send_with_file``) or
  WhatsApp (``whatsapp.send_document``) — the same ways out as the payer's
  approval request, with the same reasons when one cannot go.
"""
import io
from datetime import datetime, timedelta

from app.extensions import db

EVERY = ("week", "month")
VIA = ("email", "whatsapp")
TICK_MINUTES = 30
TOP_ROWS = 5
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class ScheduleError(ValueError):
    """A refusal with a key (``rsched.err_<key>``)."""


def period(every, today):
    """``(first_day, last_day)`` of the last complete week or month."""
    if every == "week":
        back = (today.weekday() - 4) % 7 or 7          # back to the last Friday
        end = today - timedelta(days=back)
        return end - timedelta(days=6), end
    end = today.replace(day=1) - timedelta(days=1)
    return end.replace(day=1), end


def due(report, today):
    if report.send_every not in EVERY or not report.send_to:
        return False
    return report.last_sent_for != period(report.send_every, today)[1]


def set_schedule(report, form):
    """The «ابعته لوحده» form. Empty ``every`` switches it off."""
    every = form.get("every") or ""
    if every == "":
        report.send_every = None
        report.send_error = None
        return report
    if every not in EVERY:
        raise ScheduleError("every")
    via = form.get("via")
    if via not in VIA:
        raise ScheduleError("via")
    to = (form.get("to") or "").strip()[:160]
    if via == "email" and ("@" not in to or " " in to):
        raise ScheduleError("email")
    if via == "whatsapp" and sum(c.isdigit() for c in to) < 8:
        raise ScheduleError("phone")
    report.send_every, report.send_via, report.send_to = every, via, to
    report.send_error = None
    return report


def build(report, d_from, d_to, lang="ar"):
    """``(text, xlsx_bytes)`` for the period, run with the owner's rights —
    or ``None`` when the owner may no longer run it."""
    from urllib.parse import parse_qsl

    from openpyxl import Workbook
    from werkzeug.datastructures import MultiDict

    from app.i18n import t
    from app.utils import report_builder as rb

    owner = report.owner
    if owner is None or not getattr(owner, "is_active", True):
        return None
    args = MultiDict([(k, v) for k, v in parse_qsl(report.args or "")
                      if k not in ("from", "to", "preset", "from2", "to2")])
    args["from"], args["to"] = d_from.isoformat(), d_to.isoformat()
    spec = rb.spec_from(args, owner)
    # ``spec_from`` falls back to another source when this one is not
    # allowed; for a report that goes out by itself that is a different
    # report, so it is not sent at all.
    if spec is None or (args.get("src") and spec["src"] != args.get("src")):
        return None
    table = rb.run(spec, lang)
    head, body = rb.export_rows(spec, table)

    lines = [t("rsched.msg_title", name=report.name),
             t("rsched.msg_period", d_from=d_from.isoformat(), d_to=d_to.isoformat())]
    rows = [r for r in body[:-1] if r and r[0] != ""]
    for r in rows[:TOP_ROWS]:
        lines.append(f"• {r[0]}: {r[1] if len(r) > 1 else ''}")
    if len(rows) > TOP_ROWS:
        lines.append(t("rsched.msg_more", n=len(rows) - TOP_ROWS))
    total = body[-1] if body else []
    if len(total) > 1:
        lines.append(t("rsched.msg_total", total=total[1]))
    lines.append(t("rsched.msg_file"))

    wb = Workbook()
    ws = wb.active
    ws.title = "Report"
    ws.sheet_view.rightToLeft = lang == "ar"
    ws.append(head)
    for row in body:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return "\n".join(lines), buf.getvalue()


def send(report, today=None, lang="ar"):
    """See :func:`_send`. The report and its wording are built the way a
    screen builds them, so off a screen (the heartbeat runs after the
    response) a request is made up for them."""
    from flask import current_app, has_request_context

    if has_request_context():
        return _send(report, today, lang)
    with current_app.test_request_context("/"):
        return _send(report, today, lang)


def _send(report, today=None, lang="ar"):
    """Send the last complete period now. Returns ``None`` when it went, or
    why not (``rights`` / ``no_mailbox`` / ``not_sent`` / ``no_way``). Records
    the period as sent only when it went. The caller commits."""
    from app.utils import mail_channel
    from app.utils.clock import local_today

    today = today or local_today()
    d_from, d_to = period(report.send_every or "week", today)
    built = build(report, d_from, d_to, lang)
    if built is None:
        report.send_error = "rights"
        return "rights"
    text, xlsx = built
    filename = f"report_{d_from.isoformat()}_{d_to.isoformat()}.xlsx"
    if report.send_via == "email":
        from app.i18n import t

        why = mail_channel.send_with_file(
            report.send_to, t("rsched.msg_title", name=report.name), text,
            (xlsx, filename, XLSX))
    elif report.send_via == "whatsapp":
        from app.utils import whatsapp

        log = whatsapp.send_document(text, report.send_to, xlsx, filename, mime=XLSX,
                                     user_id=report.owner_id, template_type="report")
        why = None
        if log is not None and log.status in ("failed", "skipped") and not log.link:
            why = "not_sent"
    else:
        why = "no_way"
    report.send_error = why
    if why is None:
        report.last_sent_for = d_to
        from app.models import ActivityLog

        ActivityLog.record("report.sent", user_id=report.owner_id, entity="saved_report",
                           entity_id=report.id, detail=f"{report.send_via}:{d_from}..{d_to}")
    return why


def maybe_send(today=None):
    """From the heartbeat: every report whose period is due, at most every
    :data:`TICK_MINUTES`, and by one server process only."""
    from app.models import SavedReport, Setting
    from app.utils.clock import local_today

    now = datetime.utcnow()
    last = Setting._read("report_send_tick")
    if last:
        try:
            if now - datetime.fromisoformat(last) < timedelta(minutes=TICK_MINUTES):
                return 0
        except ValueError:
            pass
    if not Setting.swap("report_send_tick", last, now.isoformat()):
        db.session.rollback()
        return 0
    db.session.commit()
    today = today or local_today()
    sent = 0
    for report in SavedReport.query.filter(SavedReport.send_every.isnot(None)).all():
        if not due(report, today):
            continue
        try:
            if send(report, today) is None:
                sent += 1
        except Exception:  # noqa: BLE001 — one report never stops the others
            db.session.rollback()
            # Said on the screen, not lost: the period stays due and is tried
            # again on the next turn.
            report.send_error = "not_sent"
        db.session.commit()
    return sent
