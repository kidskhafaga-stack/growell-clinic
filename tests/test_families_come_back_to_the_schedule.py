"""Vaccination indicators and the session programmes' (SMART_PATTERNS ج-٢).

The vaccination unit's program measured whether families come back, not
only how many doses went in. These hold it:

* **back for the next dose** — a next dose falls due by the brand's
  schedule from the date of birth; given within 30 days is «back», within
  14 «on time»; a due date less than 30 days ago is not counted yet;
* **series completed** — started 6–12 months ago, every scheduled dose by now;
* **reminders that worked** — reminded, and a dose within 14 days;
* nothing behind a figure is «—», never 0 %; targets are the clinic's;
* the session programmes: the wait for the first session, and the children
  who stopped after the first three.
"""
import os
import sys
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

TODAY = date(2026, 11, 23)


def _dose(c, n, on):
    from app.models import PatientVaccine

    c["db"].session.add(PatientVaccine(
        patient_id=c["ids"]["child"], vaccine_id=c["ids"]["pcv"], brand_id=c["ids"]["brand"],
        dose_number=n, given_date=on, doctor_id=c["ids"]["doctor"]))
    c["db"].session.commit()


@pytest.fixture()
def course(clinic):
    """The clinic's child (born 1 Jan 2025) on Prevenar at 2, 4 and 6
    months: dose 1 on 1 March, dose 2 nine days after it fell due, dose 3
    never."""
    with clinic["app"].app_context():
        _dose(clinic, 1, date(2025, 3, 1))
        _dose(clinic, 2, date(2025, 5, 10))
    return clinic


def test_back_and_on_time(course):
    from app.utils import vaccine_kpis as vk

    with course["app"].app_context():
        got = vk.coming_back(date(2025, 4, 1), date(2025, 7, 31), today=TODAY)
        # Dose 2 fell due 1 May and came on the 10th; dose 3 fell due
        # 1 July and never came.
        assert (got["due"], got["came"], got["return"]) == (2, 1, 50.0)
        assert got["on_time"] == 100.0
        # A due date less than 30 days before «today» is still open.
        assert vk.coming_back(date(2025, 6, 15), date(2025, 7, 31),
                              today=date(2025, 7, 15))["due"] == 0
        # Nothing behind the figure is «—», not 0 %.
        assert vk.coming_back(date(2024, 1, 1), date(2024, 2, 1), today=TODAY)["return"] is None


def test_a_late_start_falls_due_after_the_gap(clinic):
    """A child who started at a year old is not «late» for dose 2 the day
    after dose 1: it falls due 28 days later."""
    from app.utils import vaccine_kpis as vk

    with clinic["app"].app_context():
        _dose(clinic, 1, date(2026, 1, 10))
        events = vk.due_events(date(2026, 1, 1), date(2026, 3, 1), today=TODAY)
        assert [due for due, _ in events] == [date(2026, 2, 7)]


def test_series_completed(course):
    from app.utils import vaccine_kpis as vk

    with course["app"].app_context():
        on = date(2025, 12, 1)
        assert vk.series(today=on) == {"series": 0.0, "started": 1, "done": 0}
        _dose(course, 3, date(2025, 7, 5))
        assert vk.series(today=on)["series"] == 100.0


def test_reminders_that_worked(course):
    from app.models import MessageLog
    from app.utils import vaccine_kpis as vk

    with course["app"].app_context():
        course["db"].session.add(MessageLog(
            patient_id=course["ids"]["child"], to_phone="0100", body="ميعاد التطعيم",
            provider="manual", direction="out", status="sent", template_type="vaccine_due",
            created_at=datetime(2025, 4, 30, 9, 0)))
        course["db"].session.commit()
        got = vk.reminders(date(2025, 4, 1), date(2025, 5, 31), today=TODAY)
        assert (got["sent"], got["came"], got["reminder"]) == (1, 1, 100.0)


def test_the_tab_and_its_targets(course):
    from app.utils import vaccine_kpis as vk

    boss = course["sign_in"]("boss")
    page = boss.get("/reports/performance?tab=vaccines").get_data(as_text=True)
    assert 'data-part="vaccines"' in page and 'data-part-body="vaccines"' in page
    assert 'data-kpi="return"' in page and 'data-target="45"' in page
    assert course["sign_in"]("desk").post("/reports/performance/targets",
                                          data={"t_return": "90"}).status_code in (302, 403)
    boss.post("/reports/performance/targets", data={"t_return": "60", "t_series": "abc"})
    with course["app"].app_context():
        assert (vk.target("return"), vk.target("series")) == (60, 70)


def test_a_clinic_without_vaccinations_has_no_tab(course):
    from app.models import Setting

    with course["app"].app_context():
        # A copy that ran the setup wizard and left vaccinations unticked.
        Setting.set("facility_configured", "1")
        Setting.set("mod_enabled:vaccinations", "0")
        course["db"].session.commit()
    page = course["sign_in"]("boss").get("/reports/performance").get_data(as_text=True)
    assert 'data-part="vaccines"' not in page


def test_the_session_programmes(clinic):
    from app.models.care_program import ProgramEnrollment, ProgramSession
    from app.utils import perf_board
    from app.utils.clock import local_today

    today = local_today()
    with clinic["app"].app_context():
        db = clinic["db"]
        stopped = ProgramEnrollment(patient_id=clinic["ids"]["child"], program="rehab",
                                    started_on=today - timedelta(days=90), plan="تأهيل")
        going = ProgramEnrollment(patient_id=clinic["ids"]["child"], program="chemo",
                                  started_on=today - timedelta(days=20), plan="كيماوي", cycles=6)
        db.session.add_all([stopped, going])
        db.session.flush()
        for e, ago in ((stopped, 80), (stopped, 75), (going, 16), (going, 2)):
            db.session.add(ProgramSession(enrollment_id=e.id, pre_check="ok", cleared=True,
                                          at=datetime.utcnow() - timedelta(days=ago)))
        db.session.commit()
        got = perf_board._program_flow(today - timedelta(days=30), today)
        assert (got["stopped"], got["stopped_pct"]) == (1, 50.0)
        assert got["first_wait"] == 4.0 and got["first_wait_n"] == 1
        assert (got["cycles_given"], got["cycles_planned"]) == (2, 6)
