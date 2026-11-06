"""A saved report that sends itself — REPORTS_PLAN.md ت-٤.

*«تقرير محفوظ بيتبعت كل أسبوع أو شهر للمدير، على الإيميل أو واتساب.»*

* the last **complete** period: the week Saturday–Friday, or last month;
* with the rights of the person who saved it — none, nothing goes;
* a short message and the whole table as Excel;
* each period once, and two server processes never send it twice;
* by the clinic's mailbox or WhatsApp, with the reason when it cannot go.
"""
from datetime import date, timedelta

import pytest


def test_the_last_complete_period():
    from app.utils.report_schedule import period

    wed = date(2026, 11, 4)                 # a Wednesday
    assert period("week", wed) == (date(2026, 10, 24), date(2026, 10, 30))
    assert period("week", date(2026, 10, 31)) == (date(2026, 10, 24), date(2026, 10, 30)), \
        "on Saturday, the week that ended yesterday"
    assert period("week", date(2026, 10, 30)) == (date(2026, 10, 17), date(2026, 10, 23)), \
        "on Friday the week is not over yet"
    assert period("month", wed) == (date(2026, 10, 1), date(2026, 10, 31))
    assert period("month", date(2026, 1, 15)) == (date(2025, 12, 1), date(2025, 12, 31))


@pytest.fixture()
def saved(clinic):
    from app.models import SavedReport, User, Visit
    from app.utils.clock import local_today
    from app.utils.report_schedule import period

    db = clinic["db"]
    with clinic["app"].app_context():
        boss = User.query.filter_by(username="boss").one()
        start, end = period("week", local_today())
        for d in (start, start + timedelta(days=2), end):
            db.session.add(Visit(patient_id=clinic["ids"]["child"], doctor_id=clinic["ids"]["doctor"],
                                 visit_date=d))
        row = SavedReport(name="زيارات الأسبوع", owner_id=boss.id,
                          args="src=visits&by=doctor&m=count&preset=30")
        db.session.add(row)
        db.session.commit()
        clinic["ids"]["report"] = row.id
    return clinic


def test_set_from_the_screen_and_sent_once_by_mail(saved, monkeypatch):
    from app.models import SavedReport
    from app.utils import mail_channel, report_schedule

    boss = saved["sign_in"]("boss")
    rid = saved["ids"]["report"]
    page = boss.get("/reports/builder").get_data(as_text=True)
    assert f'data-sched="{rid}"' in page
    boss.post(f"/reports/builder/{rid}/schedule", data={"every": "week", "via": "email", "to": "no-at-sign"})
    with saved["app"].app_context():
        assert saved["db"].session.get(SavedReport, rid).send_every is None, "a bad address is refused"
    boss.post(f"/reports/builder/{rid}/schedule",
              data={"every": "week", "via": "email", "to": "boss@clinic.example"})
    sent = []
    monkeypatch.setattr(mail_channel, "send_with_file",
                        lambda to, subject, body, attached=None: sent.append((to, subject, body, attached)))
    with saved["app"].app_context():
        assert report_schedule.maybe_send() == 1
        assert report_schedule.maybe_send() == 0, "the turn is taken at most every 30 minutes"
        row = saved["db"].session.get(SavedReport, rid)
        assert row.last_sent_for is not None and row.send_error is None
        assert not report_schedule.due(row, __import__("app.utils.clock", fromlist=["x"]).local_today()), \
            "this period went; it does not go again"
    (to, subject, body, attached), = sent
    assert to == "boss@clinic.example" and "زيارات الأسبوع" in subject
    assert "3" in body, "the week's three visits"
    data, filename, mime = attached
    assert data[:2] == b"PK" and filename.endswith(".xlsx")


def test_whatsapp_and_send_now_from_the_screen(saved, monkeypatch):
    from app.utils import whatsapp

    calls = []

    class Log:
        status, link = "sent", None

    monkeypatch.setattr(whatsapp, "send_document",
                        lambda body, to, data, filename, **kw: calls.append((to, filename)) or Log())
    boss = saved["sign_in"]("boss")
    rid = saved["ids"]["report"]
    boss.post(f"/reports/builder/{rid}/schedule",
              data={"every": "month", "via": "whatsapp", "to": "01000000001"})
    boss.post(f"/reports/builder/{rid}/send-now")
    assert calls and calls[0][0] == "01000000001" and calls[0][1].endswith(".xlsx")


def test_without_the_rights_nothing_goes_and_the_screen_says_why(saved, monkeypatch):
    from app.models import SavedReport, User
    from app.utils import mail_channel, report_schedule

    sent = []
    monkeypatch.setattr(mail_channel, "send_with_file", lambda *a, **k: sent.append(a))
    with saved["app"].app_context():
        doc = User.query.filter_by(username="doc").one()
        row = SavedReport(name="فلوس", owner_id=doc.id, args="src=bills&by=month",
                          send_every="month", send_via="email", send_to="x@y.example")
        saved["db"].session.add(row)
        saved["db"].session.commit()
        assert report_schedule.send(row) == "rights"
        assert row.send_error == "rights" and row.last_sent_for is None
    assert not sent, "money is not sent to someone without the finance rights"


def test_only_the_owner_or_an_admin_schedules_it(saved):
    rid = saved["ids"]["report"]
    resp = saved["sign_in"]("doc").post(f"/reports/builder/{rid}/schedule",
                                        data={"every": "week", "via": "email", "to": "a@b.example"})
    assert resp.status_code in (302, 403)
    from app.models import SavedReport

    with saved["app"].app_context():
        assert saved["db"].session.get(SavedReport, rid).send_every is None
