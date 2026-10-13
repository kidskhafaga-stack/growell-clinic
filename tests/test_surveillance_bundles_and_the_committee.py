"""الترصّد والحزم واللجنة — GAHAR IPC.17 وIPC.11 وIPC.03.

* حالة العدوى المكتسبة «مشتبه» لحد ما الفريق يأكدها بسبب؛ الإقامة والقسطرة
  بتتلاقي من تاريخ البداية؛ والمعدل حساب على أيام القسطرة؛
* الحزمة بتاعة المستشفى، وبتتعلّم على كل قسطرة من نوعها، وكاملة بس لو كل
  عنصر اتعمل — الكل أو لا شيء؛ والجناح بيعلّم، والإعداد للفريق بس؛
* اللجنة: الاجتماع بقراراته، والقرار مفتوح لحد ما يتقفل، والشهور من غير
  اجتماع والأرباع اللي ما اتراجعتش بتتقال.
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.utils.clock import local_today  # noqa: E402

import pytest  # noqa: E402


@pytest.fixture()
def ward(clinic):
    from app.models import (Bed, Line, Setting, Space, Unit, User, UserCapability)
    from app.utils import beds

    with clinic["app"].app_context():
        db = clinic["db"]
        Setting.set("mod_enabled:beds", "1")
        icu = Unit(name="العناية", kind="icu", sort_order=0)
        db.session.add(icu)
        db.session.flush()
        bay = Space(unit_id=icu.id, name="الصالة", kind="bay")
        db.session.add(bay)
        db.session.flush()
        bed = Bed(space_id=bay.id, name="سرير ١", kind="bed")
        nurse = User(username="ipcnurse", full_name="مكافحة العدوى", role="nursing", is_active=True)
        nurse.set_password("secret")
        db.session.add_all([bed, nurse])
        db.session.flush()
        db.session.add(UserCapability(user_id=nurse.id, capability="infection_control",
                                      granted_by=clinic["ids"]["admin"]))
        from app.models import Patient
        stay = beds.admit(db.session.get(Patient, clinic["ids"]["child"]), bed,
                          when=datetime.utcnow() - timedelta(days=10))
        db.session.flush()
        cvc = Line(patient_id=clinic["ids"]["child"], admission_id=stay.id, kind="central",
                   inserted_at=datetime.utcnow() - timedelta(days=8))
        db.session.add(cvc)
        db.session.commit()
        clinic["stay"], clinic["cvc"] = stay.id, cvc.id
    return clinic


def test_a_case_is_suspected_until_the_team_decides(ward):
    from app.models import HaiCase

    nurse = ward["sign_in"]("ipcnurse")
    assert ward["sign_in"]("doc").get("/infection-control/surveillance").status_code == 403
    onset = (local_today() - timedelta(days=2)).isoformat()
    nurse.post("/infection-control/surveillance", data={
        "patient_number": "P1", "kind": "clabsi", "onset_on": onset,
        "organism": "Klebsiella pneumoniae", "criteria": "Positive culture, line > 2 days"})
    with ward["app"].app_context():
        case = HaiCase.query.one()
        assert case.status == "suspected"
        assert case.admission_id == ward["stay"] and case.line_id == ward["cvc"], \
            "the stay and the line are found from the onset date"
        cid = case.id
    nurse.post(f"/infection-control/surveillance/{cid}", data={"status": "confirmed"})
    with ward["app"].app_context():
        assert ward["db"].session.get(HaiCase, cid).status == "suspected", "a decision needs a reason"
    nurse.post(f"/infection-control/surveillance/{cid}", data={"status": "confirmed",
                                                               "note": "Meets criteria"})
    with ward["app"].app_context():
        assert ward["db"].session.get(HaiCase, cid).status == "confirmed"


def test_the_rate_is_counted_against_line_days(ward):
    from app.models import HaiCase
    from app.utils import ipc_program as prog

    with ward["app"].app_context():
        ward["db"].session.add(HaiCase(patient_id=ward["ids"]["child"], kind="clabsi",
                                       onset_on=local_today(), status="confirmed"))
        ward["db"].session.commit()
        start = local_today() - timedelta(days=30)
        data = prog.rates(start, local_today() + timedelta(days=1))
        clabsi = next(r for r in data["kinds"] if r["kind"] == "clabsi")
        assert clabsi["cases"] == 1 and clabsi["unit"] == "device_days"
        assert 7.5 < clabsi["denominator"] < 8.5, "eight days of the central line"
        assert clabsi["rate"] == pytest.approx(1000 / clabsi["denominator"])
        vap = next(r for r in data["kinds"] if r["kind"] == "vap")
        assert vap["unit"] == "patient_days" and vap["rate"] == 0
    page = ward["sign_in"]("ipcnurse").get("/infection-control/surveillance").get_data(as_text=True)
    assert 'data-hai-rate="clabsi"' in page


def test_bundles_are_the_hospital_s_and_all_or_none(ward):
    from app.models import BundleCheck, CareBundle

    nurse = ward["sign_in"]("ipcnurse")
    # Setting a bundle up is the team's; the ward (doc can reach beds? no) — desk cannot.
    ward["sign_in"]("desk").post("/infection-control/bundles", data={
        "name": "X", "kind": "clabsi", "scope": "line", "line_kinds": ["central"],
        "elements": "a"})
    with ward["app"].app_context():
        assert CareBundle.query.count() == 0
    nurse.post("/infection-control/bundles", data={
        "name": "CLABSI maintenance", "kind": "clabsi", "scope": "line",
        "line_kinds": ["central", "umbilical"],
        "elements": "Hand hygiene before access\nScrub the hub\nDaily review of need"})
    with ward["app"].app_context():
        b = CareBundle.query.one()
        els = [e.id for e in b.elements]
        bid = b.id
    page = nurse.get("/infection-control/bundles").get_data(as_text=True)
    assert f'data-bundle-due="{bid}"' in page
    nurse.post(f"/infection-control/bundles/{bid}/check", data={
        "line_id": ward["cvc"], f"e_{els[0]}": "yes", f"e_{els[1]}": "no", f"e_{els[2]}": "yes"})
    with ward["app"].app_context():
        assert BundleCheck.query.one().all_met is False, "one element missed is not met"
    # Unanswered is refused.
    nurse.post(f"/infection-control/bundles/{bid}/check", data={"line_id": ward["cvc"],
                                                                f"e_{els[0]}": "yes"})
    with ward["app"].app_context():
        assert BundleCheck.query.count() == 1
    from app.utils import ipc_program as prog
    with ward["app"].app_context():
        row = next(r for r in prog.compliance(local_today().replace(day=1),
                                              local_today() + timedelta(days=1))
                   if r["bundle"].id == bid)
        assert (row["checks"], row["met"], row["pct"]) == (1, 0, 0)


def test_the_committee_and_its_follow_up(ward):
    from app.models import IpcDecision, IpcMeeting
    from app.utils import ipc_program as prog

    nurse = ward["sign_in"]("ipcnurse")
    today = local_today()
    with ward["app"].app_context():
        assert len(prog.months_without_meeting(today)) == 6
        last_q = prog.quarter_of(prog.quarter_bounds(prog.quarter_of(today))[0] - timedelta(days=1))
        assert last_q in prog.unreviewed_quarters(today)
    nurse.post("/infection-control/committee", data={
        "held_on": today.isoformat(), "attendees": "Dr A (medicine), B (nursing)",
        "minutes": "Reviewed CLABSI.", "surveillance_quarter": last_q,
        "decision": ["Retrain on hub scrub", ""], "owner": ["Nursing director", ""],
        "due_on": [(today + timedelta(days=14)).isoformat(), ""]})
    with ward["app"].app_context():
        m = IpcMeeting.query.one()
        assert len(m.decisions) == 1
        did = m.decisions[0].id
        assert last_q not in prog.unreviewed_quarters(today)
    page = nurse.get("/infection-control/committee").get_data(as_text=True)
    assert f'data-decision="{did}"' in page
    nurse.post(f"/infection-control/decision/{did}", data={"note": "Done on 3 wards"})
    with ward["app"].app_context():
        assert ward["db"].session.get(IpcDecision, did).done_at is not None
        assert prog.open_decisions() == []


def test_every_screen_has_a_door(ward):
    """The team reaches all three from the sidebar's infection-control door;
    the ward reaches the bundles from the bed board."""
    team = ward["sign_in"]("ipcnurse")
    home = team.get("/infection-control/").get_data(as_text=True)
    assert "data-nav-ipc" in home
    for path in ("/infection-control/surveillance", "/infection-control/bundles",
                 "/infection-control/committee"):
        assert f'href="{path}"' in home, path
    board = ward["sign_in"]("boss").get("/beds/").get_data(as_text=True)
    assert "data-to-bundles" in board
