"""«الأداء» (REPORTS_PLAN.md ت-٨).

* visits by their type: how many, how long against the time booked, the
  shortest and the longest, how many ran over — a forgotten record is not
  counted;
* the doctor's day: time with children and time between, overlaps once;
* today: when each doctor will be done with who is waiting;
* «today» and «yesterday» on the period bar, on every board;
* money only with the finance rights;
* a clinic sees the clinic only; a department's tab only with its module.
"""
import os
import sys
from datetime import datetime, time, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def _visit(clinic, day, start, minutes, kind="followup", booked=15, status="completed",
           doctor=None, checked=True):
    from app.models import Appointment

    db = clinic["db"]
    a = Appointment(patient_id=clinic["ids"]["child"], doctor_id=doctor or clinic["ids"]["doctor"],
                    appt_date=day, appt_time=time(9, 0), duration_minutes=booked,
                    appt_type=kind, status=status)
    began = datetime.combine(day, time(9, 0)) + timedelta(minutes=start)
    a.checked_in_at = began - timedelta(minutes=5) if checked else None
    if minutes is not None:
        a.started_at = began
        a.completed_at = began + timedelta(minutes=minutes) if status == "completed" else None
    db.session.add(a)
    db.session.commit()
    return a


def _module(clinic, key, on):
    from app.models import Setting

    with clinic["app"].app_context():
        Setting.set(f"mod_enabled:{key}", "1" if on else "0")
        clinic["db"].session.commit()


def test_visits_by_type_against_the_time_booked(clinic):
    from app.utils import perf_board
    from app.utils.clock import local_today

    day = local_today() - timedelta(days=2)
    with clinic["app"].test_request_context():
        _visit(clinic, day, 0, 10, "followup", 15)
        _visit(clinic, day, 20, 25, "followup", 15)
        _visit(clinic, day, 60, 30, "new", 20)
        _visit(clinic, day, 120, 600, "new", 20)            # left open: not counted
        _visit(clinic, day, 0, None, "new", 20, status="cancelled")
        data = perf_board.clinic(day, day)
    types = {r["key"]: r for r in data["types"]}
    assert types["followup"]["n"] == 2 and types["followup"]["median"] == 17.5
    assert types["followup"]["shortest"] == 10 and types["followup"]["longest"] == 25
    assert types["followup"]["over"] == 1 and types["followup"]["over_pct"] == 50.0
    assert types["new"]["n"] == 2 and types["new"]["counted"] == 1, "a forgotten record is not timed"
    assert data["all"]["n"] == 4, "a cancelled visit is not a visit"
    assert dict(data["days"])[day] == 4


def test_the_day_with_children_and_between(clinic):
    from app.utils import perf_board
    from app.utils.clock import local_today

    day = local_today() - timedelta(days=1)
    with clinic["app"].test_request_context():
        _visit(clinic, day, 0, 20)
        _visit(clinic, day, 10, 20)          # overlaps the first by 10 minutes
        _visit(clinic, day, 60, 30)
        work = perf_board.clinic(day, day)["work"]
    assert work["span"] == 90 and work["busy"] == 60 and work["idle"] == 30
    assert work["busy_pct"] == round(100 * 60 / 90, 1)


def test_when_today_will_be_done(clinic):
    from app.utils import perf_board
    from app.utils.clock import local_today

    today = local_today()
    with clinic["app"].test_request_context():
        _visit(clinic, today, 0, None, "followup", 15, status="waiting")
        _visit(clinic, today, 0, None, "new", 20, status="waiting")
        rows = perf_board.finish_today()
    assert len(rows) == 1
    assert rows[0]["waiting"] == 2 and rows[0]["minutes"] == 35, \
        "with no history yet, each child at the time booked for the type"


def test_the_board_and_its_door(clinic):
    from app.utils.clock import local_today

    with clinic["app"].app_context():
        _visit(clinic, local_today(), 0, 12)
    boss = clinic["sign_in"]("boss")
    page = boss.get("/reports/performance?preset=today").get_data(as_text=True)
    assert "data-perf-headline" in page and 'data-type-row="followup"' in page
    assert 'data-kpi="revenue"' in page, "the admin holds the finance rights"
    for hospital_part in ("emergency", "units", "theatres"):
        assert f'data-part="{hospital_part}"' not in page, "a clinic sees no hospital department"
    assert "reports.performance_board" not in page
    assert "/reports/performance" in boss.get("/reports/").get_data(as_text=True)
    medical = boss.get("/reports/medical?preset=yesterday").get_data(as_text=True)
    assert "/reports/performance" in medical, "the board sits beside the others"
    assert "preset=today" in medical and "preset=yesterday" in medical


def test_money_needs_the_finance_rights(clinic):
    from app.models import User

    with clinic["app"].app_context():
        doc = User.query.filter_by(username="doc").first()
        allowed = doc.can_open("reports") and not doc.can("finance_manage")
    if not allowed:
        return
    page = clinic["sign_in"]("doc").get("/reports/performance").get_data(as_text=True)
    assert 'data-kpi="revenue"' not in page


def test_a_department_tab_only_with_its_module(clinic):
    boss = clinic["sign_in"]("boss")
    page = boss.get("/reports/performance?tab=theatres").get_data(as_text=True)
    assert 'data-part-body="theatres"' not in page, "no theatres module, no theatres tab"
    _module(clinic, "theatres", True)
    _module(clinic, "labs", True)
    _module(clinic, "inventory", True)
    page = boss.get("/reports/performance").get_data(as_text=True)
    assert 'data-part="theatres"' in page and 'data-part="labs"' in page
    for tab in ("theatres", "labs", "store"):
        page = boss.get(f"/reports/performance?tab={tab}&preset=30").get_data(as_text=True)
        assert f'data-part-body="{tab}"' in page, tab


def test_yesterday_and_today_are_one_day_each():
    from datetime import date

    from app.utils import med_board

    today = date(2026, 10, 26)
    w = med_board.window(preset="yesterday", today=today)
    assert w["from"] == w["to"] == date(2026, 10, 25) and w["days"] == 1
    w = med_board.window(preset="today", today=today)
    assert w["from"] == w["to"] == today and w["prev_from"] == date(2026, 10, 25)


def test_every_department_tab_opens(clinic):
    from app.utils import perf_board

    for key in ("emergency", "beds", "ward", "theatres", "labs", "imaging", "pharmacy",
                "inventory", "programs", "ambulance"):
        _module(clinic, key, True)
    boss = clinic["sign_in"]("boss")
    for key, _modules, _icon in perf_board.PARTS:
        res = boss.get(f"/reports/performance?tab={key}&preset=90")
        assert res.status_code == 200, key
        assert f'data-part-body="{key}"' in res.get_data(as_text=True), key
