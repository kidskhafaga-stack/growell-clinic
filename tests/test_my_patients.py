"""«مرضايا» — a doctor's own work list.

What is held here:

* a child is the doctor's who saw them last;
* a missed follow-up is ``utils/followup``'s missed or overdue, the latest
  instruction per child, oldest-late first; a child who came back is off it;
* "we called" is written down with the name and quiets the row for the day;
* a long-standing problem not seen for the months the doctor picks;
* a late vaccine is the clinic's own sweep, narrowed to the doctor's children;
* a doctor sees their own list; an admin may pick any doctor; reception none.
"""
import os
import sys
from datetime import date, time, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.utils.clock import local_today  # noqa: E402


def _doctor(clinic, username="doc2", name="د. منى"):
    from app.models import User

    with clinic["app"].app_context():
        row = User(username=username, full_name=name, role="doctor", is_active=True)
        row.set_password("secret")
        clinic["db"].session.add(row)
        clinic["db"].session.commit()
        return row.id


def _child(clinic, number, born=None):
    from app.models import Patient

    with clinic["app"].app_context():
        row = Patient(patient_number=number, full_name=f"طفل {number}", gender="female",
                      date_of_birth=born or date(2023, 5, 1), is_active=True)
        clinic["db"].session.add(row)
        clinic["db"].session.commit()
        return row.id


def _visit(clinic, patient_id, days_ago, doctor=None, due_in=None, told=None):
    from app.models import Visit

    with clinic["app"].app_context():
        day = local_today() - timedelta(days=days_ago)
        row = Visit(patient_id=patient_id, doctor_id=doctor or clinic["ids"]["doctor"],
                    visit_date=day,
                    followup_due=day + timedelta(days=due_in) if due_in is not None else None,
                    followup_instructions=told)
        clinic["db"].session.add(row)
        clinic["db"].session.commit()
        return row.id


def test_a_child_is_the_doctors_who_saw_them_last(clinic):
    from app.utils import my_patients

    other = _doctor(clinic)
    moved = _child(clinic, "M1")
    _visit(clinic, moved, 30)
    _visit(clinic, moved, 5, doctor=other)
    stayed = _child(clinic, "M2")
    _visit(clinic, stayed, 40, doctor=other)
    _visit(clinic, stayed, 3)
    with clinic["app"].app_context():
        mine = my_patients.mine(clinic["ids"]["doctor"])
        theirs = my_patients.mine(other)
    assert stayed in mine and moved not in mine and moved in theirs


def test_missed_follow_ups_are_the_latest_per_child_and_come_off_when_they_came(clinic):
    from app.models import Appointment
    from app.utils import my_patients

    late = _child(clinic, "F1")
    _visit(clinic, late, 40, due_in=7)
    _visit(clinic, late, 20, due_in=5, told="ارجع بعد أسبوع")       # the latest
    came = _child(clinic, "F2")
    _visit(clinic, came, 30, due_in=7)
    soon = _child(clinic, "F3")
    _visit(clinic, soon, 2, due_in=10)                              # not due yet
    later = _child(clinic, "F4")
    _visit(clinic, later, 12, due_in=2)                             # 10 days late
    with clinic["app"].app_context():
        clinic["db"].session.add(Appointment(
            patient_id=came, doctor_id=clinic["ids"]["doctor"],
            appt_date=local_today() - timedelta(days=22), appt_time=time(10, 0),
            status="completed"))
        clinic["db"].session.commit()
        rows = my_patients.followups(clinic["ids"]["doctor"])
        # Longest late first.
        assert [(r["visit"].patient_id, r["late"], r["state"]) for r in rows] == [
            (late, 15, "overdue"), (later, 10, "overdue")]
        assert my_patients.followups(clinic["ids"]["doctor"], "F1")
        assert not my_patients.followups(clinic["ids"]["doctor"], "لا يوجد")


def test_we_called_is_written_down_and_quiets_the_row_for_today(clinic):
    from app.models import ActivityLog

    kid = _child(clinic, "C1")
    visit = _visit(clinic, kid, 20, due_in=5)
    doc = clinic["sign_in"]("doc")
    page = doc.get("/visits/mine").get_data(as_text=True)
    assert f'data-visit="{visit}"' in page and "data-call" in page
    reply = doc.post(f"/visits/mine/called/{visit}", data={"preset": "30"})
    assert reply.status_code == 302 and "#followups" in reply.headers["Location"]
    page = doc.get("/visits/mine").get_data(as_text=True)
    row = page.split(f'data-visit="{visit}"')[1].split("</tr>")[0]
    assert "data-call" not in row and "mn-done" in row
    with clinic["app"].app_context():
        assert ActivityLog.query.filter_by(action="followup.called", entity_id=visit).count() == 1
    # A call yesterday does not quiet the row today.
    from datetime import datetime

    with clinic["app"].app_context():
        entry = ActivityLog.query.filter_by(action="followup.called", entity_id=visit).one()
        entry.created_at = datetime.utcnow() - timedelta(days=2)
        clinic["db"].session.commit()
    row = doc.get("/visits/mine").get_data(as_text=True).split(f'data-visit="{visit}"')[1].split("</tr>")[0]
    assert "data-call" in row
    csv = doc.get("/visits/mine/followups.csv").get_data(as_text=True)
    assert "C1" in csv and "overdue" in csv


def test_long_standing_problems_not_seen_for_the_months_the_doctor_picks(clinic):
    from app.models.patient import PatientProblem
    from app.utils import my_patients

    asthma = _child(clinic, "A1")
    _visit(clinic, asthma, 200)
    recent = _child(clinic, "A2")
    _visit(clinic, recent, 30)
    middle = _child(clinic, "A3")
    _visit(clinic, middle, 100)
    with clinic["app"].app_context():
        for pid, title in ((asthma, "ربو"), (recent, "صرع"), (middle, "أنيميا")):
            clinic["db"].session.add(PatientProblem(patient_id=pid, title=title, status="active"))
        clinic["db"].session.add(PatientProblem(patient_id=asthma, title="قديمة",
                                                status="resolved"))
        clinic["db"].session.commit()
        six = my_patients.chronic_unseen(clinic["ids"]["doctor"], 6)
        three = my_patients.chronic_unseen(clinic["ids"]["doctor"], 3)
        twelve = my_patients.chronic_unseen(clinic["ids"]["doctor"], 12)
        junk = my_patients.chronic_unseen(clinic["ids"]["doctor"], 2)     # → 6
    assert [(r["patient"].id, r["problems"]) for r in six] == [(asthma, ["ربو"])]
    assert [r["patient"].id for r in three] == [asthma, middle] and twelve == []
    assert [r["patient"].id for r in junk] == [asthma]


def test_late_vaccines_are_the_clinics_sweep_for_my_children(clinic):
    from app.models import PatientVaccine
    from app.utils import my_patients

    other = _doctor(clinic)
    mine = _child(clinic, "V1", born=local_today() - timedelta(days=400))
    theirs = _child(clinic, "V2", born=local_today() - timedelta(days=400))
    _visit(clinic, mine, 10)
    _visit(clinic, theirs, 10, doctor=other)
    with clinic["app"].app_context():
        for pid in (mine, theirs):
            clinic["db"].session.add(PatientVaccine(
                patient_id=pid, vaccine_id=clinic["ids"]["pcv"], brand_id=clinic["ids"]["brand"],
                dose_number=1, given_date=local_today() - timedelta(days=340),
                event_type="given"))
        clinic["db"].session.commit()
        late = my_patients.late_vaccines(clinic["ids"]["doctor"])
    assert late and {r["patient"].id for r in late} == {mine}


def test_whose_list_it_is(clinic):
    other = _doctor(clinic, "doc3", "د. كريم")
    kid = _child(clinic, "W1")
    _visit(clinic, kid, 20, doctor=other, due_in=3)
    # A doctor opens on themselves; asking for another is ignored.
    doc = clinic["sign_in"]("doc").get(f"/visits/mine?doctor={other}").get_data(as_text=True)
    assert "طفل W1" not in doc and "data-pick-doctor" not in doc
    boss = clinic["sign_in"]("boss").get(f"/visits/mine?doctor={other}").get_data(as_text=True)
    assert "طفل W1" in boss and "data-pick-doctor" in boss and "data-board-tabs" in boss
    assert clinic["sign_in"]("desk").get("/visits/mine").status_code in (302, 403)
    from app.models import User
    from app.models.role import Role

    with clinic["app"].app_context():
        clinic["db"].session.add(Role(name="clerk", label_ar="كاتب", modules="dashboard,visits",
                                      capabilities=""))
        person = User(username="clerk", full_name="كاتب", role="clerk", is_active=True)
        person.set_password("secret")
        clinic["db"].session.add(person)
        clinic["db"].session.commit()
    assert clinic["sign_in"]("clerk").get("/visits/mine").status_code in (302, 403)
    assert "data-mine-link" in clinic["sign_in"]("doc").get("/visits/").get_data(as_text=True)


def test_the_doctor_is_picked_by_search_and_the_list_searches_as_you_type(clinic):
    """«ممكن نخلي بحث حي + اختيار عادي» — the shared picker, which searches
    as you type and opens to the whole list; and the follow-up search that
    follows the typing and says when a child is in the files but not on it."""
    other = _doctor(clinic, "doc4", "د. سلمى")
    late = _child(clinic, "S1")
    _visit(clinic, late, 20, doctor=other, due_in=3)
    _child(clinic, "S2")                                    # in the files, no follow-up
    boss = clinic["sign_in"]("boss")
    page = boss.get(f"/visits/mine?doctor={other}").get_data(as_text=True)
    assert "gcDoctorPicker" in page and '<select class="input" id="doctor"' not in page
    assert 'data-live-search="#followups-results"' in page and 'id="followups-results"' in page
    found = boss.get(f"/visits/mine?doctor={other}&q=S1").get_data(as_text=True)
    assert f'data-visit=' in found and "data-found-elsewhere" not in found
    elsewhere = boss.get(f"/visits/mine?doctor={other}&q=S2").get_data(as_text=True)
    assert "data-found-elsewhere" in elsewhere and "طفل S2" in elsewhere
    nobody = boss.get(f"/visits/mine?doctor={other}&q=مفيش حد كده").get_data(as_text=True)
    assert "data-found-elsewhere" not in nobody and "مفيش طفل بالاسم ده في الملفات" in nobody


def test_the_lab_names_a_test_in_the_screen_s_language_and_says_why_one_box(clinic):
    """«ليه ظاهر عربي فى الشاشة الانجليزي» and «صورة الدم الكاملة ليه ظاهر
    كده» — the order's English name on the English screen, and the single
    box explained when the test has no components yet."""
    from app.models import Investigation, Setting, VisitInvestigation

    with clinic["app"].app_context():
        Setting.set("mod_enabled:labs", "1")
        inv = Investigation(name_ar="صورة دم كاملة", name_en="Complete blood count", kind="lab")
        clinic["db"].session.add(inv)
        clinic["db"].session.flush()
        row = VisitInvestigation(visit_id=clinic["ids"]["visit"], patient_id=clinic["ids"]["child"],
                                 investigation_id=inv.id, kind="lab", name="صورة دم كاملة")
        clinic["db"].session.add(row)
        clinic["db"].session.commit()
        oid = row.id
    boss = clinic["sign_in"]("boss")
    boss.get("/lang/en")
    board = boss.get("/labs/").get_data(as_text=True)
    assert "Complete blood count" in board and "صورة دم كاملة" not in board
    page = boss.get(f"/labs/order/{oid}").get_data(as_text=True)
    assert "data-no-analytes" in page and "/ranges" in page
