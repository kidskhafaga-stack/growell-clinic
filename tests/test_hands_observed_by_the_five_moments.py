"""نظافة الأيدي — GAHAR `IPC.04` / `GSR.22`.

* **الملاحظة** بأداة منظمة الصحة العالمية: الفئة (مش الاسم)، اللحظة أو
  اللحظات، واتعمل إيه — والنسبة = اللي اتعمل ÷ الفرص؛
* الصف الناقص بيترفض بدل ما يتخمّن، والصف الفاضي بيتساب؛
* النسبة لكل مكان وفئة ولحظة، وشهر بشهر؛
* **الهدف بتاع المستشفى**: من غيره ما فيش «تحت الهدف»؛
* **النقاط**: الحوض والصابون والمناديل والكحول والبوستر والسلة، والناقص
  لازم جنبه اتعمل إيه؛
* **القرارات** على نتايج الشهر، و**التدريب** — للي بيقرا التقارير.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

from app.utils.clock import local_today  # noqa: E402


@pytest.fixture()
def ward(clinic):
    from app.models import User
    from app.models.place import Unit

    with clinic["app"].app_context():
        nurse = User(username="nurse", full_name="الممرضة", role="nursing", is_active=True)
        nurse.set_password("secret")
        unit = Unit(name="الحضانة", name_en="Nursery", kind="ward")
        clinic["db"].session.add_all([nurse, unit])
        clinic["db"].session.commit()
        clinic["ids"]["nurse"] = nurse.id
        clinic["ids"]["unit"] = unit.id
    return clinic


def _observe(c, who="nurse", rows=(), **extra):
    form = {"observed_on": local_today().isoformat(), "unit_id": str(c["ids"]["unit"]), **extra}
    for i, (category, moments, action) in enumerate(rows):
        form[f"op-{i}-category"] = category
        form[f"op-{i}-m"] = [str(m) for m in moments]
        form[f"op-{i}-action"] = action
    return c["sign_in"](who).post("/hand-hygiene/observe", data=form)


def test_who_observes_and_who_decides(ward):
    assert ward["sign_in"]("desk").get("/hand-hygiene/").status_code == 403
    page = ward["sign_in"]("nurse").get("/hand-hygiene/").get_data(as_text=True)
    assert "data-to-observe" in page and "data-hh-decide" not in page
    assert ward["sign_in"]("nurse").get("/hand-hygiene/training").status_code == 403
    assert "data-hh-decide" in ward["sign_in"]().get("/hand-hygiene/").get_data(as_text=True)
    assert "/hand-hygiene/" in ward["sign_in"]().get("/reports/").get_data(as_text=True)


def test_an_observation_counts_actions_over_opportunities(ward):
    from app.models import HandHygieneOpportunity
    from app.utils import hand_hygiene as hh

    _observe(ward, rows=[("nurse", [1], "rub"), ("doctor", [2], "")])        # half a row
    _observe(ward, rows=[])                                                  # nothing
    with ward["app"].app_context():
        assert HandHygieneOpportunity.query.count() == 0
    got = _observe(ward, rows=[("nurse", [1, 4], "rub"), ("doctor", [4], "missed"),
                               ("nurse", [5], "wash"), ("doctor", [1], "rub")])
    assert "/hand-hygiene/session/" in got.headers["Location"]
    with ward["app"].app_context():
        data = hh.compliance(local_today(), local_today(), "en")
        assert (data["n"], data["done"], data["rate"]) == (4, 3, 75.0)
        assert data["by_area"][0]["name"] == "Nursery"
        moments = {r["key"]: (r["n"], r["rate"]) for r in data["by_moment"]}
        assert moments[1] == (2, 100.0) and moments[4] == (2, 50.0) and moments[3] == (0, None)
        cats = {r["key"]: r["rate"] for r in data["by_category"]}
        assert cats["nurse"] == 100.0 and cats["doctor"] == 50.0


def test_the_target_is_the_hospital_s_own(ward):
    _observe(ward, rows=[("nurse", [1], "rub"), ("nurse", [4], "missed")])
    page = ward["sign_in"]().get("/hand-hygiene/").get_data(as_text=True)
    assert "data-below-target" not in page, "no target, nothing below it"
    ward["sign_in"]().post("/hand-hygiene/target", data={"target": "80"})
    page = ward["sign_in"]().get("/hand-hygiene/").get_data(as_text=True)
    assert "data-below-target" in page
    assert ward["sign_in"]("nurse").post("/hand-hygiene/target",
                                         data={"target": "10"}).status_code == 403


def test_an_area_written_by_name_where_there_are_no_units(ward):
    from app.models import HandHygieneSession

    _observe(ward, unit_id="", rows=[("other", [3], "wash")])          # no area at all
    _observe(ward, unit_id="", area="غرفة التطعيمات", rows=[("other", [3], "wash")])
    with ward["app"].app_context():
        row = HandHygieneSession.query.one()
        assert row.unit_id is None and row.area_name() == "غرفة التطعيمات"


def test_a_missing_station_item_needs_what_was_done(ward):
    from app.models import HandHygieneFacilityCheck

    nurse = ward["sign_in"]("nurse")
    form = {"checked_on": local_today().isoformat(), "unit_id": str(ward["ids"]["unit"]),
            "sink": "1", "soap": "1", "towels": "1", "poster": "1", "waste": "1"}
    nurse.post("/hand-hygiene/stations", data=form)                     # no rub, no action
    with ward["app"].app_context():
        assert HandHygieneFacilityCheck.query.count() == 0
    nurse.post("/hand-hygiene/stations", data={**form, "action": "اتطلب كحول من المخزن"})
    page = nurse.get("/hand-hygiene/stations").get_data(as_text=True)
    assert "data-hh-station=" in page and "اتطلب كحول" in page


def test_the_month_s_decision_and_the_training_record(ward):
    from app.models import HandHygieneAction
    from app.utils import hand_hygiene as hh

    boss = ward["sign_in"]()
    month = local_today().strftime("%Y-%m")
    boss.post("/hand-hygiene/action", data={"month": month, "finding": "اللحظة ٤ ضعيفة"})
    boss.post("/hand-hygiene/action", data={"month": month, "finding": "اللحظة ٤ ضعيفة",
                                            "action": "محاضرة للأطباء"})
    assert ward["sign_in"]("nurse").post("/hand-hygiene/action", data={
        "month": month, "finding": "x", "action": "y"}).status_code == 403
    with ward["app"].app_context():
        assert HandHygieneAction.query.count() == 1
    page = boss.get("/hand-hygiene/").get_data(as_text=True)
    assert "data-hh-decision=" in page and "محاضرة للأطباء" in page

    today = local_today().isoformat()
    boss.post("/hand-hygiene/training", data={"user_id": str(ward["ids"]["nurse"]),
                                              "trained_on": today, "valid_until": today})
    boss.post("/hand-hygiene/training", data={"user_id": str(ward["ids"]["nurse"]),
                                              "trained_on": today, "trainer": "مكافحة العدوى"})
    with ward["app"].app_context():
        states = {r["user"].id: r["state"] for r in hh.training_board()}
        assert states[ward["ids"]["nurse"]] == "ok"
        assert states[ward["ids"]["admin"]] == "never"


def test_the_screen_speaks_the_screen_s_language(ward):
    _observe(ward, rows=[("nurse", [1], "rub")])
    boss = ward["sign_in"]()
    boss.get("/lang/en")
    page = boss.get("/hand-hygiene/").get_data(as_text=True)
    assert "Nursery" in page and "الحضانة" not in page
