"""سجل ضبط جودة التعقيم — GAHAR IPC.15.

* القيم المقبولة بتاعة المستشفى؛ القيمة بتتحكم عليها بس لو اتحددت؛
* أي فشل (قيمة برّه، مؤشر كيميائي، بيولوجي) ما يتسجّلش من غير إجراء؛
* اللوحة بتقول سحب الهواء اتعمل النهارده ولا لأ، والبيولوجي من كام يوم؛
* بابه من شريط مكافحة العدوى ومن شاشة العمليات.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def team(clinic):
    from app.models import Setting, User, UserCapability

    with clinic["app"].app_context():
        for m in ("beds", "theatres"):
            Setting.set(f"mod_enabled:{m}", "1")
        nurse = User(username="ipcnurse", full_name="مكافحة العدوى", role="nursing", is_active=True)
        nurse.set_password("secret")
        clinic["db"].session.add(nurse)
        clinic["db"].session.flush()
        clinic["db"].session.add(UserCapability(user_id=nurse.id, capability="infection_control",
                                                granted_by=clinic["ids"]["admin"]))
        clinic["db"].session.commit()
    return clinic


def test_a_failure_needs_its_action_and_limits_are_the_hospital_s(team):
    from app.models import Sterilizer, SterilizerCycle
    from app.utils import sterilization as st
    from datetime import date

    ipc = team["sign_in"]("ipcnurse")
    ipc.post("/infection-control/sterilization/sterilizer", data={"name": "Autoclave 1", "temp_min": "134"})
    with team["app"].app_context():
        sid = Sterilizer.query.one().id
        board = st.board(date.today())[0]
        assert not board["test_today"] and board["bi_late"]
    doc = team["sign_in"]("doc")
    doc.post(f"/infection-control/sterilization/{sid}/cycle", data={"kind": "bowie_dick", "chemical": "pass"})
    doc.post(f"/infection-control/sterilization/{sid}/cycle", data={"kind": "load", "temperature": "121",
                                                                   "minutes": "15", "chemical": "pass"})
    with team["app"].app_context():
        assert SterilizerCycle.query.count() == 1, "121 is under the hospital's 134 — refused without action"
    doc.post(f"/infection-control/sterilization/{sid}/cycle", data={"kind": "load", "temperature": "121",
                                                                   "chemical": "pass", "bi": "pending",
                                                                   "action": "Load recalled, rerun"})
    with team["app"].app_context():
        c = SterilizerCycle.query.filter_by(kind="load").one()
        assert c.failed and c.bi == "pending"
        cid = c.id
        board = st.board(date.today())[0]
        assert board["test_today"] and board["bi_days"] == 0 and not board["bi_late"]
    doc.post(f"/infection-control/sterilization/cycle/{cid}/bi", data={"bi": "pass"})
    with team["app"].app_context():
        assert team["db"].session.get(SterilizerCycle, cid).bi == "pass"


def test_hld_and_the_doors(team):
    from app.models import HldTest

    doc = team["sign_in"]("doc")
    doc.post("/infection-control/sterilization/hld", data={"solution": "OPA", "result": "fail"})
    doc.post("/infection-control/sterilization/hld", data={"solution": "OPA", "result": "pass"})
    with team["app"].app_context():
        assert HldTest.query.count() == 1, "a failed strip needs its action"
    home = team["sign_in"]("ipcnurse").get("/infection-control/").get_data(as_text=True)
    assert 'href="/infection-control/sterilization"' in home
    theatres = team["sign_in"]("boss").get("/theatres/").get_data(as_text=True)
    assert "data-to-sterilization" in theatres
    assert team["sign_in"]("desk").get("/infection-control/sterilization").status_code == 403
