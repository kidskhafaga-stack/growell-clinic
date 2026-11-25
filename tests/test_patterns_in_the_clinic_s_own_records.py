"""«أنماط المرضى» — SMART_PATTERNS_PLAN ج-٥ ب.

Four questions the clinic's records already answer, each with its reason —
counted, never guessed, and nothing recorded by the program:

* who will probably not come in the next 7 days: missed twice or a third of
  their appointments (high), once (medium), or a day and time missed more
  (medium); and whether the reminder went out;
* the series about to drop: the next dose due within 30 days for a child
  late on the dose before, or with no phone; a programme with no session in
  21 days;
* three emergency visits or more in 90 days: a count, also on the visit
  screen, only where the emergency department runs;
* next month in the years before: visits, diagnoses, medicines — a medicine
  written in the room and carried to the prescription counted once.
"""
import os
import sys
from datetime import datetime, time, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def _appt(db, pid, doctor, on, status, at=time(10, 0)):
    from app.models import Appointment

    a = Appointment(patient_id=pid, doctor_id=doctor, appt_date=on, appt_time=at, status=status)
    db.session.add(a)
    db.session.flush()
    return a


def _kid(db, n, **kw):
    from app.models import Patient
    from datetime import date

    p = Patient(patient_number=f"K{n}", full_name=f"طفل {n}", gender="male",
                date_of_birth=kw.pop("born", date(2023, 1, 1)), is_active=True, **kw)
    db.session.add(p)
    db.session.flush()
    return p


def test_who_will_probably_not_come(clinic):
    from app.models import MessageLog
    from app.utils import patient_patterns as pp
    from app.utils.clock import local_today

    today = local_today()
    with clinic["app"].app_context():
        db, doc = clinic["db"], clinic["ids"]["doctor"]
        missy = _kid(db, 1, own_phone="0100")
        for ago, status in ((100, "no_show"), (60, "no_show"), (30, "completed")):
            _appt(db, missy.id, doc, today - timedelta(days=ago), status)
        once = _kid(db, 2)
        _appt(db, once.id, doc, today - timedelta(days=40), "no_show")
        for ago in (10, 20, 50):
            _appt(db, once.id, doc, today - timedelta(days=ago), "completed")
        fine = _kid(db, 3)
        _appt(db, fine.id, doc, today - timedelta(days=12), "completed")
        tomorrow = today + timedelta(days=1)
        a1 = _appt(db, missy.id, doc, tomorrow, "scheduled")
        a2 = _appt(db, once.id, doc, tomorrow, "scheduled", time(11, 0))
        _appt(db, fine.id, doc, tomorrow, "scheduled", time(12, 0))
        _appt(db, missy.id, doc, today + timedelta(days=9), "scheduled")   # past the week
        db.session.add(MessageLog(patient_id=once.id, appointment_id=a2.id, to_phone="0100",
                                  body="تذكير", provider="manual", direction="out",
                                  status="sent", template_type="appointment_reminder"))
        db.session.commit()
        rows = {r["appt"].id: r for r in pp.no_show_risk()}
        assert set(rows) == {a1.id, a2.id}, "a family with no misses is not on it, nor next week"
        assert rows[a1.id]["level"] == "high"
        assert [k for k, _ in rows[a1.id]["reasons"]] == ["missed", "no_reminder"]
        assert rows[a1.id]["reasons"][0][1] == {"missed": 2, "of": 3}
        assert rows[a2.id]["level"] == "medium"
        assert "no_reminder" not in [k for k, _ in rows[a2.id]["reasons"]], "the reminder went"


def test_a_day_and_time_missed_more(clinic):
    from app.utils import patient_patterns as pp
    from app.utils.clock import local_today

    today = local_today()
    with clinic["app"].app_context():
        db, doc = clinic["db"], clinic["ids"]["doctor"]
        nxt = today + timedelta(days=2)
        for i in range(20):
            kid = _kid(db, 100 + i)
            _appt(db, kid.id, doc, nxt - timedelta(days=7 * (i + 1)),
                  "no_show" if i < 6 else "completed", time(18, 0))
        new = _kid(db, 200)
        a = _appt(db, new.id, doc, nxt, "scheduled", time(18, 30))
        morning = _appt(db, new.id, doc, nxt, "scheduled", time(9, 0))
        db.session.commit()
        rows = {r["appt"].id: r for r in pp.no_show_risk()}
        assert rows[a.id]["level"] == "medium"
        assert rows[a.id]["reasons"][0] == ("slot", {"pct": 30})
        assert morning.id not in rows, "the evening is missed, not the morning"


def test_the_series_about_to_drop(clinic):
    from app.models import PatientVaccine
    from app.utils import patient_patterns as pp
    from app.utils.clock import local_today
    from app.utils.vaccines import add_months

    today = local_today()
    with clinic["app"].app_context():
        db, ids = clinic["db"], clinic["ids"]

        def give(pid, n, on):
            db.session.add(PatientVaccine(patient_id=pid, vaccine_id=ids["pcv"],
                                          brand_id=ids["brand"], dose_number=n,
                                          given_date=on, doctor_id=ids["doctor"]))

        born = add_months(today, -6) + timedelta(days=10)       # dose 3 at 6 months, in 10 days
        late = _kid(db, 1, born=born, own_phone="0100")
        give(late.id, 1, add_months(born, 2))
        give(late.id, 2, add_months(born, 4) + timedelta(days=20))
        on_time = _kid(db, 2, born=born, own_phone="0100")
        give(on_time.id, 1, add_months(born, 2))
        give(on_time.id, 2, add_months(born, 4))
        no_phone = _kid(db, 3, born=born)
        give(no_phone.id, 1, add_months(born, 2))
        give(no_phone.id, 2, add_months(born, 4))
        db.session.commit()
        rows = {r["patient"].id: r for r in pp.series_at_risk()}
        assert set(rows) == {late.id, no_phone.id}
        assert rows[late.id]["late_before"] == 20 and not rows[late.id]["no_phone"]
        assert rows[no_phone.id]["no_phone"] and rows[no_phone.id]["late_before"] is None


def test_a_programme_with_no_session_in_three_weeks(clinic):
    from app.models.care_program import ProgramEnrollment, ProgramSession
    from app.utils import patient_patterns as pp
    from app.utils.clock import local_today

    today = local_today()
    with clinic["app"].app_context():
        db, child = clinic["db"], clinic["ids"]["child"]
        quiet = ProgramEnrollment(patient_id=child, program="rehab", plan="تأهيل",
                                  started_on=today - timedelta(days=60))
        going = ProgramEnrollment(patient_id=child, program="speech", plan="تخاطب",
                                  started_on=today - timedelta(days=60))
        db.session.add_all([quiet, going])
        db.session.flush()
        db.session.add_all([
            ProgramSession(enrollment_id=quiet.id, pre_check="ok", cleared=True,
                           at=datetime.utcnow() - timedelta(days=30)),
            ProgramSession(enrollment_id=going.id, pre_check="ok", cleared=True,
                           at=datetime.utcnow() - timedelta(days=3))])
        db.session.commit()
        rows = pp.programs_at_risk()
        assert [r["enrollment"].id for r in rows] == [quiet.id]
        assert rows[0]["days"] >= 29


def test_always_in_the_emergency_department(clinic):
    from app.models import EmergencyVisit, Setting
    from app.utils import patient_patterns as pp

    with clinic["app"].app_context():
        db, child = clinic["db"], clinic["ids"]["child"]
        Setting.set("mod_enabled:emergency", "1")
        for ago in (5, 30, 70, 120):
            db.session.add(EmergencyVisit(patient_id=child,
                                          arrived_at=datetime.utcnow() - timedelta(days=ago)))
        db.session.commit()
        assert pp.er_visits(child) == 3, "the one 120 days ago is outside"
        assert [(p.id, n) for p, n in pp.frequent_er()] == [(child, 3)]
    doc = clinic["sign_in"]("doc")
    page = doc.get(f"/visits/{clinic['ids']['visit']}/record").get_data(as_text=True)
    assert 'data-er-count="3"' in page
    with clinic["app"].app_context():
        Setting.set("facility_configured", "1")
        Setting.set("mod_enabled:emergency", "0")
        clinic["db"].session.commit()
    page = doc.get(f"/visits/{clinic['ids']['visit']}/record").get_data(as_text=True)
    assert "data-er-count" not in page, "a clinic without an emergency department"
    tabs = clinic["sign_in"]("boss").get("/reports/patient-patterns").get_data(as_text=True)
    assert 'data-ppat-tab="er"' not in tabs


def test_next_month_in_the_years_before(clinic):
    from datetime import date

    from app.models import (Diagnosis, Prescription, PrescriptionItem, Visit,
                            VisitMedication)
    from app.utils import patient_patterns as pp
    from app.utils.clock import local_today

    today = local_today()
    month = pp._next_month(today)
    with clinic["app"].app_context():
        db, ids = clinic["db"], clinic["ids"]
        for i in range(3):
            v = Visit(patient_id=ids["child"], doctor_id=ids["doctor"], status="completed",
                      visit_date=date(month.year - 1, month.month, 5 + i))
            db.session.add(v)
            db.session.flush()
            db.session.add(Diagnosis(visit_id=v.id, code="J21.9", title="Bronchiolitis"))
            db.session.add(VisitMedication(visit_id=v.id, patient_id=ids["child"], name="Ventolin"))
            rx = Prescription(patient_id=ids["child"], doctor_id=ids["doctor"], visit_id=v.id)
            db.session.add(rx)
            db.session.flush()
            db.session.add(PrescriptionItem(prescription_id=rx.id, drug_name="Ventolin"))
        db.session.commit()
        s = pp.season()
        assert s["month"] == month and s["years"] == [(month.year - 1, 3)] and s["average"] == 3
        assert s["diagnoses"][0] == ("J21.9", "Bronchiolitis", 3)
        assert s["drugs"] == [("Ventolin", 3)], "the room and the prescription count once"


def test_the_screen_and_its_door(clinic):
    from app.models import Setting

    with clinic["app"].app_context():
        Setting.set("mod_enabled:emergency", "1")
        clinic["db"].session.commit()
    boss = clinic["sign_in"]("boss")
    assert "/reports/patient-patterns" in boss.get("/reports/").get_data(as_text=True)
    for tab in ("no_show", "series", "er", "season"):
        page = boss.get(f"/reports/patient-patterns?tab={tab}")
        assert page.status_code == 200
        assert f'data-ppat-body="{tab}"' in page.get_data(as_text=True)
