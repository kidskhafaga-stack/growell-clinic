"""The management board — the money and the work of each part of the clinic.

What is held here:

* the revenue, costs and net are the ones the cost-centre report and the
  income statement add up to — the board reads them, it does not recount;
* what was collected is payments less refunds, by the day they were taken;
* what families owe is today's, and a bill overdue by more than 30 days is
  listed for attention;
* a department opens its detail, with the period before beside it;
* a doctor's billing and share are their own lines on the bills;
* the board is behind the finance capability, and the boards are tabs.
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.utils.clock import local_today  # noqa: E402
from tests.test_which_part_of_the_clinic_earned_it import (  # noqa: E402,F401
    _invoice, books)


def _pay(clinic, invoice_id, amount, method="cash", kind="payment", days_ago=0):
    from app.models import Invoice, Payment

    with clinic["app"].app_context():
        clinic["db"].session.add(Payment(invoice_id=invoice_id, amount=amount, method=method,
                                         kind=kind,
                                         paid_at=datetime.utcnow() - timedelta(days=days_ago)))
        inv = clinic["db"].session.get(Invoice, invoice_id)
        clinic["db"].session.flush()
        inv.recalc_status()
        clinic["db"].session.commit()


def _window(days=30):
    from app.utils.med_board import window

    return window(preset=str(days))


def test_the_money_is_the_cost_centre_reports(books):
    from app.utils import admin_board, cost_centre_report

    first = _invoice(books, [("exam", 200, {}), ("lab", 100, {})], number="A1")
    _invoice(books, [("exam", 200, {})], number="A2",
             on=local_today() - timedelta(days=40))
    _pay(books, first, 250, "card")
    _pay(books, first, 50, "cash")
    _pay(books, first, 20, "cash", kind="refund")
    with books["app"].app_context():
        w = _window()
        data = admin_board.board(w)
        report = cost_centre_report.report(w["from"], w["to"])
    assert data["now"]["revenue"] == report["revenue"] == 300.0
    assert data["now"]["net"] == report["net"]
    assert data["before"]["revenue"] == 200.0
    assert data["now"]["collected"] == 280.0
    assert dict(data["methods"]) == {"card": 250.0, "cash": 30.0}
    assert data["now"]["per_bill"] == 300.0 and data["now"]["bills"] == 1
    keys = {d["centre"].key: d for d in data["departments"]}
    assert keys["outpatient"]["revenue"] == 200.0 and keys["outpatient"]["before"] == 200.0
    assert keys["lab"]["revenue"] == 100.0 and keys["lab"]["before"] == 0
    assert sum(p["revenue"] for p in data["trend"]) == 300.0 and data["step"] == "day"


def test_what_is_owed_is_todays_and_the_overdue_wait_for_attention(books):
    from app.utils import admin_board

    _invoice(books, [("exam", 200, {})], number="OLD", on=local_today() - timedelta(days=45))
    # A free visit owes nothing, however old and whatever its status says.
    _invoice(books, [("exam", 0, {})], number="FREE", on=local_today() - timedelta(days=60))
    fresh = _invoice(books, [("exam", 200, {})], number="NEW")
    _pay(books, fresh, 150)
    with books["app"].app_context():
        owed = admin_board.owed_now()
        items = admin_board.attention(admin_board._report(*[local_today()] * 2), owed)
    assert owed == {"total": 250.0, "overdue": 200.0, "overdue_count": 1}
    assert ("overdue", 1) in [(a["key"], a["value"]) for a in items]


def test_the_trend_steps_by_day_week_or_month(books):
    from app.utils.admin_board import _step

    assert (_step(31), _step(32), _step(124), _step(125)) == ("day", "week", "week", "month")


def test_a_doctor_is_their_own_lines(books):
    from app.models import User
    from app.utils import admin_board

    with books["app"].app_context():
        surgeon = User(username="sur", full_name="د. جراح", role="doctor", is_active=True)
        surgeon.set_password("x")
        books["db"].session.add(surgeon)
        books["db"].session.commit()
        surgeon_id = surgeon.id
    _invoice(books, [("exam", 250, {"commission_amount": 80, "discount_value": 50}),
                     ("nebul", 150, {"doctor_id": surgeon_id, "commission_amount": 75})],
             number="D1")
    from datetime import time

    from app.models import Appointment

    with books["app"].app_context():
        for status in ("completed", "no_show", "completed", "completed"):
            books["db"].session.add(Appointment(
                patient_id=books["ids"]["child"], doctor_id=books["ids"]["doctor"],
                appt_date=local_today(), appt_time=time(9, 0), status=status))
        books["db"].session.commit()
        rows = {r["doctor"].id: r for r in admin_board.doctors(
            local_today() - timedelta(days=1), local_today())}
    mine = rows[books["ids"]["doctor"]]
    # Billed is after the line's discount; one of four bookings not kept.
    assert (mine["billed"], mine["share"], mine["bills"], mine["visits"]) == (200.0, 80.0, 1, 1)
    assert mine["no_show_pct"] == 25.0
    assert (rows[surgeon_id]["billed"], rows[surgeon_id]["share"]) == (150.0, 75.0)


def test_the_page_is_behind_the_finance_capability(books):
    invoice = _invoice(books, [("exam", 200, {}), ("lab", 100, {})], number="P1")
    _pay(books, invoice, 300, "card")
    page = books["sign_in"]("acct").get("/reports/management?preset=30")
    assert page.status_code == 200
    body = page.get_data(as_text=True)
    assert "data-board-kpis" in body and 'data-kpi="collected"' in body
    assert "data-departments" in body and "data-trend" in body and "data-methods" in body
    # The accountant holds the reports, so both boards are theirs to open.
    assert "data-board-tabs" in body
    centre = body.split('data-centre="')[1].split('"')[0]
    opened = books["sign_in"]("acct").get(
        f"/reports/management?preset=30&centre={centre}").get_data(as_text=True)
    assert "data-drawer" in opened
    assert books["sign_in"]("doc").get("/reports/management").status_code in (302, 403)
    # Reports without the finance capability: the medical board, not this one.
    from app.models import User
    from app.models.role import Role

    with books["app"].app_context():
        books["db"].session.add(Role(name="director", label_ar="مدير طبي",
                                     modules="dashboard,reports", capabilities=""))
        person = User(username="dir", full_name="المدير الطبي", role="director", is_active=True)
        person.set_password("secret")
        books["db"].session.add(person)
        books["db"].session.commit()
    director = books["sign_in"]("dir")
    assert director.get("/reports/medical").status_code == 200
    assert director.get("/reports/management").status_code in (302, 403)
    assert "/reports/management" not in director.get("/reports/").get_data(as_text=True)
    assert books["sign_in"]("desk").get("/reports/management").status_code in (302, 403)
    index = books["sign_in"]("acct").get("/reports/").get_data(as_text=True)
    assert "/reports/management" in index and "/reports/medical" in index
