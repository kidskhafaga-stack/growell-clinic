"""الإبلاغ عن الأمراض المعدية والتفشّي — GAHAR IPC.18.

* الاشتباه بيفضل «لسه ما اتبلّغش» والجرس بيرن لحد ما يتسجّل البلاغ؛
* التفشّي بفريق وتعريف حالة وحالات وخطوات المعيار العشرة، وما يتقفلش من
  غير استنتاج وإجراءات؛
* التجمّعات بتتعرض بس — البرنامج مش بيعلن تفشّي؛
* وكل ده ليه باب من شريط مكافحة العدوى، وللفريق بس.
"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def team(clinic):
    from app.models import User, UserCapability

    with clinic["app"].app_context():
        nurse = User(username="ipcnurse", full_name="مكافحة العدوى", role="nursing", is_active=True)
        nurse.set_password("secret")
        clinic["db"].session.add(nurse)
        clinic["db"].session.flush()
        clinic["db"].session.add(UserCapability(user_id=nurse.id, capability="infection_control",
                                                granted_by=clinic["ids"]["admin"]))
        clinic["db"].session.commit()
    return clinic


def test_a_suspicion_rings_until_it_is_reported(team):
    from app.models import DiseaseReport, User
    from app.utils.notifications import get_notifications, invalidate

    nurse = team["sign_in"]("ipcnurse")
    assert team["sign_in"]("doc").get("/infection-control/reports").status_code == 403
    nurse.post("/infection-control/reports", data={"patient_number": "P1", "disease": "Measles",
                                                   "suspected_on": date.today().isoformat()})
    with team["app"].test_request_context():
        invalidate()
        who = User.query.filter_by(username="ipcnurse").first()
        assert any(n["key"] == "disease_reports" for n in get_notifications(who))
        rid = DiseaseReport.query.one().id
    nurse.post(f"/infection-control/reports/{rid}", data={"reported_on": date.today().isoformat()})
    with team["app"].app_context():
        assert team["db"].session.get(DiseaseReport, rid).reported_on is None, "to whom is required"
    nurse.post(f"/infection-control/reports/{rid}", data={"reported_on": date.today().isoformat(),
                                                          "reported_to": "Health directorate",
                                                          "reference": "R-17"})
    with team["app"].test_request_context():
        invalidate()
        assert team["db"].session.get(DiseaseReport, rid).reference == "R-17"
        who = User.query.filter_by(username="ipcnurse").first()
        assert not any(n["key"] == "disease_reports" for n in get_notifications(who))


def test_an_outbreak_is_worked_and_closed_with_its_measures(team):
    from app.models import Outbreak

    nurse = team["sign_in"]("ipcnurse")
    nurse.post("/infection-control/outbreaks", data={
        "title": "Klebsiella in NICU", "agent": "Klebsiella pneumoniae (ESBL)",
        "opened_on": date.today().isoformat(), "team": "IPC, NICU, lab, pharmacy"})
    with team["app"].app_context():
        oid = Outbreak.query.one().id
    nurse.post(f"/infection-control/outbreak/{oid}/step", data={
        "step": "3", "done_on": date.today().isoformat(), "note": "ESBL Klebsiella in NICU since 1 Oct"})
    nurse.post(f"/infection-control/outbreak/{oid}/case", data={"patient_number": "P1"})
    nurse.post(f"/infection-control/outbreak/{oid}/close", data={"conclusion": "Shared sink",
                                                                  "closed_on": date.today().isoformat()})
    with team["app"].app_context():
        o = team["db"].session.get(Outbreak, oid)
        assert o.is_open, "no close without the measures"
        assert o.case_definition.startswith("ESBL"), "step 3 is the case definition"
        assert len(o.cases) == 1 and len(o.steps) == 1
    nurse.post(f"/infection-control/outbreak/{oid}/close", data={
        "conclusion": "Shared sink", "measures": "Sink replaced; cohorting",
        "closed_on": date.today().isoformat()})
    with team["app"].app_context():
        assert not team["db"].session.get(Outbreak, oid).is_open
    page = nurse.get(f"/infection-control/outbreak/{oid}").get_data(as_text=True)
    assert 'data-step="10"' in page and "data-outbreak-closed" in page


def test_clusters_are_listed_never_declared(team):
    from app.models import HaiCase, Outbreak, Patient
    from app.utils import ipc_outbreak as ob

    with team["app"].app_context():
        db = team["db"]
        p2 = Patient(patient_number="P2", full_name="تاني", gender="female",
                     date_of_birth=date(2024, 1, 1), is_active=True)
        db.session.add(p2)
        db.session.flush()
        for pid in (team["ids"]["child"], p2.id):
            db.session.add(HaiCase(patient_id=pid, kind="cauti", onset_on=date.today()))
        db.session.commit()
        cl = ob.clusters(date.today())
        assert len(cl) == 1 and cl[0]["n"] == 2
        assert Outbreak.query.count() == 0, "nothing is declared"


def test_the_screens_have_their_doors(team):
    home = team["sign_in"]("ipcnurse").get("/infection-control/").get_data(as_text=True)
    assert 'href="/infection-control/outbreaks"' in home
    assert 'href="/infection-control/reports"' in home
