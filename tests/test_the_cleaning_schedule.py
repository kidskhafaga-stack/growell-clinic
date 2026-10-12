"""جدول تنظيف وتطهير البيئة — GAHAR IPC.09.

* الأماكن والأنشطة والتكرار بتاعة المستشفى، والإعداد لمكافحة العدوى؛
* النشاط اليومي متأخر لحد ما يتعمل النهارده؛ العميق بيستحق بعد عدد الأيام
  اللي المستشفى حددته؛
* التمريض بيسجّل من لوحة الأسرّة، والباب موجود.
"""
import os
import sys
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def team(clinic):
    from app.models import Setting, User, UserCapability

    with clinic["app"].app_context():
        Setting.set("mod_enabled:beds", "1")
        nurse = User(username="ipcnurse", full_name="مكافحة العدوى", role="nursing", is_active=True)
        nurse.set_password("secret")
        clinic["db"].session.add(nurse)
        clinic["db"].session.flush()
        clinic["db"].session.add(UserCapability(user_id=nurse.id, capability="infection_control",
                                                granted_by=clinic["ids"]["admin"]))
        clinic["db"].session.commit()
    return clinic


def test_the_schedule_is_the_hospital_s_and_says_what_is_late(team):
    from app.models import CleaningArea, CleaningDone, CleaningTask
    from app.utils import cleaning

    ipc = team["sign_in"]("ipcnurse")
    team["sign_in"]("desk").post("/infection-control/cleaning/area", data={"name": "X", "risk": "high"})
    with team["app"].app_context():
        assert CleaningArea.query.count() == 0
    ipc.post("/infection-control/cleaning/area", data={"name": "NICU", "risk": "high"})
    with team["app"].app_context():
        aid = CleaningArea.query.one().id
    ipc.post(f"/infection-control/cleaning/area/{aid}/task", data={
        "activity": "High-touch surfaces", "frequency": "daily", "disinfectant": "Chlorine 1000 ppm"})
    ipc.post(f"/infection-control/cleaning/area/{aid}/task", data={"activity": "Walls", "frequency": "deep"})
    ipc.post(f"/infection-control/cleaning/area/{aid}/task", data={
        "activity": "Walls and ceilings", "frequency": "deep", "every_days": "7"})
    with team["app"].app_context():
        tasks = {t.activity: t for t in CleaningTask.query}
        assert set(tasks) == {"High-touch surfaces", "Walls and ceilings"}, "deep needs its interval"
        daily, deep = tasks["High-touch surfaces"].id, tasks["Walls and ceilings"].id
        team["db"].session.add(CleaningDone(task_id=deep, done_at=datetime.utcnow() - timedelta(days=3)))
        team["db"].session.commit()
        rows = {r["task"].id: r for r in cleaning.board(date.today())[0]["rows"]}
        assert rows[daily]["late"] is True
        assert rows[deep]["late"] is False and rows[deep]["due"] == date.today() + timedelta(days=4)
    team["sign_in"]("doc").post(f"/infection-control/cleaning/task/{daily}/done", data={})
    with team["app"].app_context():
        rows = {r["task"].id: r for r in cleaning.board(date.today())[0]["rows"]}
        assert rows[daily]["late"] is False and len(rows[daily]["today"]) == 1


def test_the_doors(team):
    home = team["sign_in"]("ipcnurse").get("/infection-control/").get_data(as_text=True)
    assert 'href="/infection-control/cleaning"' in home
    board = team["sign_in"]("boss").get("/beds/").get_data(as_text=True)
    assert "data-to-cleaning" in board
    assert team["sign_in"]("desk").get("/infection-control/cleaning").status_code == 403
