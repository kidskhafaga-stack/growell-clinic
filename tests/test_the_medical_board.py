"""The medical board — counts and illnesses, from one date to another.

Asked for with the management board and «مرضايا», on the prototype the
clinic agreed. What is held here:

* a period is two dates and the same length just before it, whether picked
  from a preset or typed;
* diagnoses are counted by code, one per visit, and an ICD-10 and an ICD-11
  code are two rows — never merged by a guess; words written without a code
  are grouped by the words, and their share is shown;
* what "rose" is ordered by how many more cases, with no outbreak line;
* a drill-down shows ages and sexes to anybody with the reports, and the
  children's names only to whoever may open a child's file;
* the inpatient, emergency and theatre parts appear only when the clinic
  runs them, and read what was recorded — triage levels in the hospital's
  own words;
* the doctors' table is recorded figures, narrowed by where the case was.
"""
import os
import sys
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.utils.clock import local_today  # noqa: E402


def _child(clinic, number, gender="male", born=None):
    from app.models import Patient

    with clinic["app"].app_context():
        row = Patient(patient_number=number, full_name=f"طفل {number}", gender=gender,
                      date_of_birth=born or date(2024, 1, 1), is_active=True)
        clinic["db"].session.add(row)
        clinic["db"].session.commit()
        return row.id


def _seen(clinic, patient_id, days_ago=0, dx=(), doctor=None):
    """A visit ``days_ago`` with diagnoses ``(code, version, title, type)``."""
    from app.models import Diagnosis, Visit

    with clinic["app"].app_context():
        visit = Visit(patient_id=patient_id, doctor_id=doctor or clinic["ids"]["doctor"],
                      visit_date=local_today() - timedelta(days=days_ago))
        clinic["db"].session.add(visit)
        clinic["db"].session.flush()
        for code, version, title, kind in dx:
            clinic["db"].session.add(Diagnosis(visit_id=visit.id, code=code, title=title,
                                               icd_version=version, dx_type=kind))
        clinic["db"].session.commit()
        return visit.id


def test_a_period_is_two_dates_and_the_same_length_before(clinic):
    from app.utils.med_board import window

    day = date(2026, 9, 28)
    w = window(preset="7", today=day)
    assert (w["from"], w["to"], w["days"]) == (date(2026, 9, 22), day, 7)
    assert (w["prev_from"], w["prev_to"]) == (date(2026, 9, 15), date(2026, 9, 21))
    assert window(preset="month", today=day)["from"] == date(2026, 9, 1)
    assert window(preset="year", today=day)["from"] == date(2026, 1, 1)
    assert window(preset="nonsense", today=day)["days"] == 30
    typed = window("2026-03-31", "2026-03-01", "7", today=day)
    assert (typed["from"], typed["to"], typed["preset"]) == (
        date(2026, 3, 1), date(2026, 3, 31), None)


def test_diagnoses_are_counted_by_code_and_versions_are_never_merged(clinic):
    from app.utils import med_board

    a, b = _child(clinic, "A"), _child(clinic, "B")
    # Working and final with the same code on one visit is one case.
    _seen(clinic, a, dx=[("J06.9", "10", "عدوى تنفسية", "working"),
                         ("J06.9", "10", "عدوى تنفسية", "final")])
    _seen(clinic, b, dx=[("J06.9", "10", "عدوى تنفسية", "final")])
    _seen(clinic, b, days_ago=1, dx=[("CA40.Z", "11", "التهاب رئوي", "final"),
                                     ("J18.9", "10", "التهاب رئوي", "secondary")])
    # The same code under both versions is still two rows: which illness a
    # code names depends on its version, and the program does not map them.
    _seen(clinic, a, days_ago=3, dx=[("A09", "10", "نزلة", "final")])
    _seen(clinic, b, days_ago=3, dx=[("A09", "11", "كود تاني", "final")])
    _seen(clinic, a, days_ago=2, dx=[(None, "10", "كحة  وسخونية", "working")])
    _seen(clinic, b, days_ago=2, dx=[("", "10", "كحة وسخونية", "working")])
    with clinic["app"].app_context():
        today = local_today()
        got = med_board.diagnoses(today - timedelta(days=6), today)
    coded = {(r["version"], r["code"]): r["n"] for r in got["coded"]}
    assert coded == {("10", "J06.9"): 2, ("11", "CA40.Z"): 1, ("10", "J18.9"): 1,
                     ("10", "A09"): 1, ("11", "A09"): 1}
    assert [(r["title"], r["n"]) for r in got["free"]] == [("كحة وسخونية", 2)]
    assert got["total"] == 8 and got["free_share"] == 25


def test_what_rose_is_ordered_by_how_many_more(clinic):
    from app.utils.med_board import rising

    rows = [{"key": "a", "n": 2, "p": 1}, {"key": "b", "n": 30, "p": 20},
            {"key": "c", "n": 5, "p": 5}, {"key": "d", "n": 1, "p": 3},
            {"key": "e", "n": 12, "p": 0}]
    # e gained 12, b gained 10 though it is bigger, a gained 1.
    assert [r["key"] for r in rising(rows)] == ["e", "b", "a"]


def test_the_board_opens_with_its_figures_beside_the_period_before(clinic):
    kid = _child(clinic, "K")
    _seen(clinic, kid, days_ago=40, dx=[("A09", "10", "نزلة معوية", "final")])
    for d in (1, 2, 3):
        _seen(clinic, kid, days_ago=d, dx=[("A09", "10", "نزلة معوية", "final")])
    page = clinic["sign_in"]("boss").get("/reports/medical?preset=30").get_data(as_text=True)
    assert "data-board-kpis" in page and 'data-kpi="visits"' in page
    assert 'data-dx-key="10:A09"' in page and "ICD-10" in page
    assert "data-rising" in page
    # A clinic that runs no beds, emergency or theatre sees none of them.
    assert 'data-kpi="admissions"' not in page and "data-emergency" not in page
    assert "data-wards" not in page and 'data-kpi="deaths"' not in page
    assert "/reports/medical" in clinic["sign_in"]("boss").get("/reports/").get_data(as_text=True)


def test_names_in_a_drill_down_only_for_whoever_may_open_the_file(clinic):
    kid = _child(clinic, "N1", gender="female")
    _seen(clinic, kid, dx=[("H66.9", "10", "التهاب الأذن", "final")])
    url = "/reports/medical?preset=30&dx=10:H66.9"
    boss = clinic["sign_in"]("boss").get(url).get_data(as_text=True)
    assert "data-dx-detail" in boss and "data-cases" in boss and "طفل N1" in boss
    csv = clinic["sign_in"]("boss").get("/reports/medical/cases.csv?preset=30&dx=10:H66.9")
    assert csv.status_code == 200 and "N1" in csv.get_data(as_text=True)
    acct = clinic["sign_in"]("acct").get(url).get_data(as_text=True)
    assert "data-dx-detail" in acct and "data-cases-hidden" in acct
    assert "طفل N1" not in acct and "data-cases-csv" not in acct
    assert clinic["sign_in"]("acct").get(
        "/reports/medical/cases.csv?preset=30&dx=10:H66.9").status_code in (302, 403)
    assert clinic["sign_in"]("desk").get("/reports/medical").status_code in (302, 403)
    counts = clinic["sign_in"]("acct").get("/reports/medical/diagnoses.csv?preset=30")
    assert "H66.9" in counts.get_data(as_text=True) and "N1" not in counts.get_data(as_text=True)


def test_a_drill_down_counts_ages_on_the_day_and_sexes(clinic):
    from app.utils import med_board

    today = local_today()
    baby = _child(clinic, "B1", gender="female", born=today - timedelta(days=100))
    older = _child(clinic, "B2", gender="male", born=today - timedelta(days=365 * 6))
    for kid in (baby, older):
        _seen(clinic, kid, dx=[(None, "10", "مغص", "working")])
    with clinic["app"].app_context():
        split = med_board.breakdown(today - timedelta(days=6), today, "t:مغص")
        assert dict(split["ages"])["infant"] == 1 and dict(split["ages"])["school"] == 1
        assert split["sexes"] == {"female": 1, "male": 1}
        rows, total = med_board.cases(today - timedelta(days=6), today, "t:مغص")
        assert total == 2 and len(rows) == 2
        assert med_board.breakdown(today, today, "junk") is None


def test_the_doctors_table_is_what_was_recorded(clinic):
    from app.models import User
    from app.utils import med_board

    with clinic["app"].app_context():
        other = User(username="doc2", full_name="د. منى", role="doctor", is_active=True)
        other.set_password("secret")
        clinic["db"].session.add(other)
        clinic["db"].session.commit()
        other_id = other.id
    kid = _child(clinic, "D1")
    _seen(clinic, kid, days_ago=5, dx=[("A09", "10", "نزلة", "final")])
    _seen(clinic, kid, days_ago=2, dx=[(None, "10", "مغص", "working")], doctor=other_id)
    with clinic["app"].app_context():
        today = local_today()
        rows = {r["doctor"].id: r for r in med_board.doctors(today - timedelta(days=9), today,
                                                               on={})}
    mine = rows[clinic["ids"]["doctor"]]
    # The fixture's own visit today plus this one; the child came back in 3 days.
    assert mine["cases"] == 2 and mine["back_pct"] == 50.0 and mine["nocode_pct"] == 0.0
    assert mine["fresh"] == 2
    theirs = rows[other_id]
    assert (theirs["cases"], theirs["fresh"], theirs["back_pct"], theirs["nocode_pct"]) == (
        1, 0, 0.0, 100.0)


# --- a hospital -------------------------------------------------------------
from tests.test_a_bed_bill_the_books_never_heard_of import (  # noqa: E402,F401
    _admit, hospital)
from tests.test_a_bed_bill_the_books_never_heard_of import _child as _bed_child  # noqa: E402


def _leave(clinic, admission_id, days_ago, outcome="home"):
    from app.models import Admission

    with clinic["app"].app_context():
        row = clinic["db"].session.get(Admission, admission_id)
        row.discharged_at = datetime.utcnow() - timedelta(days=days_ago)
        row.outcome = outcome
        for stay in row.stays:
            stay.until = stay.until or row.discharged_at
        clinic["db"].session.commit()


def test_the_wards_read_their_stays(hospital):
    from app.utils import med_board

    kid = _bed_child(hospital, "عائد")
    first = _admit(hospital, kid, days_ago=20)
    _leave(hospital, first, days_ago=16)
    again = _admit(hospital, kid, days_ago=6)            # back within 30 days
    _leave(hospital, again, days_ago=2, outcome="died")
    other = _bed_child(hospital, "تاني")
    # Its last stay ended fifty days ago: coming back now is not a readmission.
    long_ago = _admit(hospital, other, "د٢", days_ago=55)
    _leave(hospital, long_ago, days_ago=50)
    _admit(hospital, other, "د٢", days_ago=1)
    with hospital["app"].app_context():
        today = local_today()
        (row,) = med_board.wards(today - timedelta(days=29), today)
        now = med_board.counts(today - timedelta(days=29), today, {"beds": True})
    assert row["unit"].name == "الداخلي" and row["admissions"] == 3
    assert row["readmit_pct"] == 33.3 and row["deaths"] == 1 and row["discharges"] == 2
    assert row["alos"] == 4.0 and row["occupancy"] is not None
    assert (now["admissions"], now["discharges"], now["deaths"]) == (3, 2, 1)
    page = hospital["sign_in"]("boss").get("/reports/medical?preset=30").get_data(as_text=True)
    assert "data-wards" in page and 'data-kpi="deaths"' in page and "50.0%" in page


def test_triage_levels_are_the_hospitals_own_words(hospital):
    from app.models import Setting
    from app.models.emergency_visit import EmergencyVisit

    with hospital["app"].app_context():
        Setting.set("mod_enabled:emergency", "1")
        for level, went in (("ESI 2", "admitted"), ("ESI 2", "home"),
                            (None, "left_unseen"), ("أحمر", "died")):
            hospital["db"].session.add(EmergencyVisit(
                patient_id=hospital["ids"]["child"], level=level, disposition=went,
                arrived_at=datetime.utcnow() - timedelta(hours=5)))
        hospital["db"].session.commit()
    page = hospital["sign_in"]("boss").get("/reports/medical?preset=7").get_data(as_text=True)
    er = page.split("data-emergency")[1].split("</div>\n  </div>")[0]
    assert "ESI 2" in er and "أحمر" in er and "ما اتفرزش" in er
    # Not triaged is its own row, after the levels that were written.
    assert er.index("ما اتفرزش") > er.index("ESI 2") and er.index("ما اتفرزش") > er.index("أحمر")
    assert 'data-kpi="emergency"' in page
    # The death in the emergency department counts with the ward's.
    deaths = page.split('data-kpi="deaths"')[1][:400]
    assert '<span class="v num">1' in deaths
