"""«المريض بيعمل الفحص إمتى» — the last check-up and the next, on the file
(asked: «سطر في ملف الطفل وفلتر اللي فاتهم ميعادهم»).

The next date is the earliest of a booking, a follow-up the doctor asked for
that nobody has come for, and the next vaccine dose — each a date somebody
wrote, never the program's own — with how many days late it is.
"""
import os
import sys
from datetime import time, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def _visit(c, days_ago, followup_in=None):
    from app.models import Visit
    from app.utils.clock import local_today

    with c["app"].app_context():
        today = local_today()
        v = Visit(patient_id=c["ids"]["child"], doctor_id=c["ids"]["doctor"],
                  visit_date=today - timedelta(days=days_ago))
        if followup_in is not None:
            v.followup_due = today - timedelta(days=days_ago) + timedelta(days=followup_in)
        c["db"].session.add(v)
        c["db"].session.commit()
        return v.id


def _info(c, vaccine_next=None):
    from app.models import Patient
    from app.utils.checkup_dates import for_patient

    with c["app"].app_context():
        return for_patient(c["db"].session.get(Patient, c["ids"]["child"]),
                           vaccine_next=vaccine_next)


def test_the_last_check_up_and_a_follow_up_nobody_came_for(clinic):
    from app.utils.clock import local_today

    _visit(clinic, days_ago=20, followup_in=14)          # due six days ago
    info = _info(clinic)
    with clinic["app"].app_context():
        today = local_today()
    assert info["last"]["date"] == today, "the fixture's own visit today is the last"
    assert info["next"]["kind"] == "followup"
    assert info["next"]["late_days"] == 6
    page = clinic["sign_in"]("doc").get(f"/patients/{clinic['ids']['child']}").get_data(as_text=True)
    assert 'data-checkup-next="followup"' in page and 'data-checkup-late="6"' in page


def test_a_booking_answers_the_follow_up(clinic):
    from app.models import Appointment
    from app.utils.clock import local_today

    _visit(clinic, days_ago=20, followup_in=14)
    with clinic["app"].app_context():
        clinic["db"].session.add(Appointment(
            patient_id=clinic["ids"]["child"], doctor_id=clinic["ids"]["doctor"],
            appt_date=local_today() + timedelta(days=3), appt_time=time(11, 0),
            status="scheduled"))
        clinic["db"].session.commit()
    info = _info(clinic)
    assert info["next"]["kind"] == "booked" and info["next"]["late_days"] == 0
    assert info["next"]["what"] == "11:00"


def test_the_earliest_of_the_three_wins(clinic):
    from app.utils.clock import local_today

    _visit(clinic, days_ago=2, followup_in=30)               # in four weeks
    with clinic["app"].app_context():
        soon = local_today() + timedelta(days=5)

    class Vaccine:
        def display_name(self, lang):
            return "MMR"

    info = _info(clinic, vaccine_next=(soon.isoformat(), Vaccine(), None, {}))
    assert info["next"]["kind"] == "vaccine" and info["next"]["what"] == "MMR"
    assert info["next"]["date"] == soon


def test_nothing_owed_says_so(clinic):
    info = _info(clinic)
    assert info["next"] is None
    page = clinic["sign_in"]("doc").get(f"/patients/{clinic['ids']['child']}").get_data(as_text=True)
    assert "data-checkup-none" in page


def test_the_list_of_those_who_missed_their_date(clinic):
    from app.models import Patient
    from datetime import date

    _visit(clinic, days_ago=20, followup_in=14)
    with clinic["app"].app_context():
        other = Patient(patient_number="P2", full_name="طفل تاني", gender="female",
                        date_of_birth=date(2024, 5, 1), is_active=True)
        clinic["db"].session.add(other)
        clinic["db"].session.commit()
    desk = clinic["sign_in"]("desk")
    assert "data-missed-checkup-door" in desk.get("/patients/").get_data(as_text=True)
    page = desk.get("/patients/?flag=missed_checkup").get_data(as_text=True)
    assert "data-missed-checkup" in page
    assert "P1" in page and "P2" not in page
