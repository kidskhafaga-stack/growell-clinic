"""سلامة المنشأة — GAHAR `EFS.03`/`GSR.23`، `EFS.04`/`GSR.24`، `EFS.11`/`GSR.28`.

* **تجربة الإخلاء** بالتاريخ والوقت والوردية والأماكن واللي شاركوا،
  والتقييم والإجراء التصحيحي — في نفس الفورم؛
* السنة قصاد أرقام المعيار: تجربة كل ربع، وواحدة من غير إعلان، وكل موظف
  في تجربة؛
* فحص نظام حريق أو مرفق فيه مشكلة لازم إجراء؛
* المرفق الحرج لازم بديله، والمتأخر بس قصاد المدة المكتوبة له؛
* التدريب السنوي ومين لسه؛
* لمين بيدير المنشأة بس.
"""
import os
import sys
from datetime import timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.utils.clock import local_today  # noqa: E402


def _boss(c):
    return c["sign_in"]()


def test_only_whoever_runs_the_building(clinic):
    assert clinic["sign_in"]("doc").get("/facility/").status_code == 403
    page = _boss(clinic).get("/facility/").get_data(as_text=True)
    assert "data-drills" in page and "data-utilities" in page
    assert "/facility/" in _boss(clinic).get("/reports/").get_data(as_text=True)


def test_a_drill_carries_its_evaluation_and_its_action(clinic):
    from app.models import FireDrill

    today = local_today()
    form = {"held_at": f"{today.isoformat()}T10:30", "shift": "morning",
            "areas": "العيادات الخارجية", "participants": [str(clinic["ids"]["doctor"])],
            "evaluation": "الإخلاء خد ٦ دقايق"}
    _boss(clinic).post("/facility/drill", data=form)                    # no action
    with clinic["app"].app_context():
        assert FireDrill.query.count() == 0
    _boss(clinic).post("/facility/drill", data={**form, "corrective_action": "لافتة جديدة للسلم",
                                                "unannounced": "1"})
    with clinic["app"].app_context():
        row = FireDrill.query.one()
        assert row.unannounced and [p.id for p in row.participants] == [clinic["ids"]["doctor"]]
    page = _boss(clinic).get("/facility/").get_data(as_text=True)
    assert 'data-unannounced="yes"' in page and f'data-drill="{row.id}"' in page


def test_the_year_against_the_standard_s_figures(clinic):
    from app.utils import facility_safety as fs

    with clinic["app"].app_context():
        year = fs.year_of_drills()
        current_q = (local_today().month - 1) // 3 + 1
        assert year["missing_quarters"] == list(range(1, current_q + 1))
        assert not year["unannounced"] and len(year["not_yet"]) >= 3


def test_a_failed_check_needs_its_action(clinic):
    from app.models import FireSystemCheck

    today = local_today().isoformat()
    form = {"system": "extinguisher", "location": "الدور الأول", "checked_on": today,
            "result": "fail"}
    _boss(clinic).post("/facility/fire-check", data=form)
    with clinic["app"].app_context():
        assert FireSystemCheck.query.count() == 0
    _boss(clinic).post("/facility/fire-check", data={**form, "action": "اتغيّرت الطفاية"})
    page = _boss(clinic).get("/facility/").get_data(as_text=True)
    assert "data-fire-check=" in page and "اتغيّرت الطفاية" in page


def test_a_utility_is_overdue_only_against_its_own_interval(clinic):
    from app.models import UtilitySystem
    from app.utils import facility_safety as fs

    boss = _boss(clinic)
    boss.post("/facility/utility", data={"name": "المولد", "kind": "generator", "is_critical": "1"})
    with clinic["app"].app_context():
        assert UtilitySystem.query.count() == 0, "critical without a backup"
    boss.post("/facility/utility", data={"name": "المولد", "kind": "generator", "is_critical": "1",
                                         "backup": "مولد احتياطي"})
    boss.post("/facility/utility", data={"name": "خزان المية", "kind": "water",
                                         "check_every_days": "30"})
    with clinic["app"].app_context():
        gen = UtilitySystem.query.filter_by(kind="generator").one()
        tank = UtilitySystem.query.filter_by(kind="water").one()
        tank.created_at = tank.created_at - timedelta(days=40)
        clinic["db"].session.commit()
        rows = {r["system"].name: r for r in fs.utilities_now()}
        assert rows["خزان المية"]["overdue"] and rows["المولد"]["due"] is None
        gid = gen.id
    today = local_today().isoformat()
    boss.post(f"/facility/utility/{gid}/check", data={"kind": "generator_load", "done_on": today,
                                                      "result": "fail"})
    boss.post(f"/facility/utility/{gid}/check", data={"kind": "generator_load", "done_on": today,
                                                      "result": "fail", "fuel": "نص التانك",
                                                      "action": "اتغيّر فلتر الوقود"})
    with clinic["app"].app_context():
        gen = clinic["db"].session.get(UtilitySystem, gid)
        assert len(gen.checks) == 1 and gen.checks[0].fuel == "نص التانك"


def test_the_yearly_training_and_who_is_still_owed_it(clinic):
    from app.utils import facility_safety as fs

    with clinic["app"].app_context():
        before = len(fs.untrained_this_year())
    _boss(clinic).post("/facility/training", data={"user_ids": [str(clinic["ids"]["doctor"])],
                                                   "trained_on": local_today().isoformat(),
                                                   "trainer": "الدفاع المدني"})
    with clinic["app"].app_context():
        assert len(fs.untrained_this_year()) == before - 1
