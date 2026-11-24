"""«عادتك مع التشخيص ده» — a doctor's own habits (SMART_PATTERNS_PLAN ج-٣).

From the indicators document the owner brought: when a doctor writes a
diagnosis, show what he usually orders with it. These hold how it was
agreed (23 Nov):

* a habit is 10 visits or more with the diagnosis and the item in 60 % of
  them — the clinic's to change; 30 % shows faded; less is not shown;
* **only the visit's own doctor sees his habits**; a doctor with too few
  visits sees «زملاءك» — a count and a share, never a name;
* a press goes through the screen's own forms (a test is ordered, a
  medicine written, with its usual frequency and duration); **the dose is
  this child's, from today's weight**, never another child's;
* «مش عايز ده» hides it for good; shown, taken and refused are counted;
* «تحب تحفظها روشتة جاهزة؟» saves a ready prescription only on a press;
* the count runs once a day from the heartbeat, and «عاداتي» has its door.
"""
import os
import sys
from datetime import timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


def _visit(c, doctor_id, code, tests=(), drugs=(), ago=30):
    from app.models import Diagnosis, Visit, VisitInvestigation, VisitMedication
    from app.utils.clock import local_today

    db = c["db"]
    v = Visit(patient_id=c["ids"]["child"], doctor_id=doctor_id,
              visit_date=local_today() - timedelta(days=ago), status="completed")
    db.session.add(v)
    db.session.flush()
    db.session.add(Diagnosis(visit_id=v.id, code=code, title="نزلة برد"))
    for inv in tests:
        db.session.add(VisitInvestigation(visit_id=v.id, patient_id=v.patient_id,
                                          investigation_id=inv, name="CBC"))
    for drug, freq, dur in drugs:
        db.session.add(VisitMedication(visit_id=v.id, patient_id=v.patient_id,
                                       drug_id=drug, name="x", frequency=freq,
                                       duration=dur))
    return v


@pytest.fixture()
def habits(clinic):
    """Doctor «doc»: ten colds (J06.9) — a CBC in 7, paracetamol every six
    hours for three days in 8, amoxicillin in 4, a cough syrup in 2. Today's
    visit (the fixture's) is a cold too, and the child weighs 10 kg."""
    from app.models import (Diagnosis, Drug, GenericDrug, GrowthRecord, Investigation,
                            Visit)
    from app.utils.clock import local_today

    with clinic["app"].app_context():
        db = clinic["db"]
        cbc = Investigation(name_ar="صورة دم كاملة", name_en="CBC", kind="lab", is_active=True)
        para_g = GenericDrug(name_ar="باراسيتامول", name_en="Paracetamol",
                             dose_per_kg=15, doses_per_day=4)
        db.session.add_all([cbc, para_g])
        db.session.flush()
        para = Drug(trade_name="Cetal", strength="120 mg/5 ml", generic_id=para_g.id,
                    conc_mg_per_ml=24)
        amox = Drug(trade_name="Amoxil", strength="250 mg/5 ml")
        syrup = Drug(trade_name="Coughex")
        db.session.add_all([para, amox, syrup])
        db.session.flush()
        doc = clinic["ids"]["doctor"]
        for i in range(10):
            _visit(clinic, doc, "J06.9",
                   tests=[cbc.id] if i < 7 else [],
                   drugs=([(para.id, "كل 6 ساعات", "3 أيام")] if i < 8 else [])
                   + ([(amox.id, "كل 8 ساعات", "7 أيام")] if i < 4 else [])
                   + ([(syrup.id, None, None)] if i < 2 else []))
        db.session.add(GrowthRecord(patient_id=clinic["ids"]["child"], weight_kg=10,
                                    record_date=local_today()))
        today = db.session.get(Visit, clinic["ids"]["visit"])
        db.session.add(Diagnosis(visit_id=today.id, code="J06.9", title="نزلة برد"))
        db.session.commit()
        clinic["ids"].update(cbc=cbc.id, para=para.id, amox=amox.id, syrup=syrup.id)
    return clinic


def _refresh(c):
    from app.utils import doctor_patterns as dp

    with c["app"].app_context():
        n = dp.refresh()
        c["db"].session.commit()
        return n


def _strip(c, username="doc"):
    page = c["sign_in"](username).get(f"/visits/{c['ids']['visit']}/record")
    assert page.status_code == 200
    return page.get_data(as_text=True)


def test_the_count(habits):
    from app.models import OrderPattern

    _refresh(habits)
    with habits["app"].app_context():
        mine = {(r.kind, r.item_id): r for r in
                OrderPattern.query.filter_by(doctor_id=habits["ids"]["doctor"], dx_key="J06.9")}
        ids = habits["ids"]
        assert mine[("test", ids["cbc"])].share == 70.0
        para = mine[("drug", ids["para"])]
        assert (para.visits, para.seen, para.frequency, para.duration) == \
            (10, 8, "كل 6 ساعات", "3 أيام")
        assert mine[("drug", ids["amox"])].share == 40.0, "kept, shown faded"
        assert ("drug", ids["syrup"]) not in mine, "20 % is not a pattern"
        # The category too, and the clinics' doctors together.
        assert OrderPattern.query.filter_by(dx_key="J06", doctor_id=None).count() == 3


def test_the_strip_on_the_doctor_s_own_visit(habits):
    _refresh(habits)
    page = _strip(habits)
    ids = habits["ids"]
    assert 'data-habit-source="mine"' in page
    assert f'data-habit-item="test:{ids["cbc"]}" data-habit-strong="1"' in page
    assert f'data-habit-item="drug:{ids["amox"]}" data-habit-strong="0"' in page
    assert f'data-habit-item="drug:{ids["syrup"]}"' not in page
    # The dose is this child's: 15 mg/kg × 10 kg = 150 mg = 6.25 ml of 24 mg/ml.
    assert 'name="dose" value="6.25 ml"' in page and '<bdi dir="ltr">6.25 ml</bdi>' in page
    # A drug with no rule leaves the dose to the doctor — none is copied.
    assert "الجرعة: اكتبها إنت" in page
    assert "data-habit-preset" not in page, "one habitual drug is not a set"


def test_no_one_else_sees_it(habits):
    _refresh(habits)
    for who in ("boss", "desk"):
        page = habits["sign_in"](who).get(f"/visits/{habits['ids']['visit']}/record")
        assert "data-habits" not in page.get_data(as_text=True)


def test_a_new_doctor_sees_his_colleagues(habits):
    from app.models import User, Visit

    with habits["app"].app_context():
        db = habits["db"]
        new = User(username="new", full_name="د. جديد", role="doctor", is_active=True)
        new.set_password("secret")
        db.session.add(new)
        db.session.flush()
        db.session.get(Visit, habits["ids"]["visit"]).doctor_id = new.id
        db.session.commit()
    _refresh(habits)
    page = _strip(habits, "new")
    assert 'data-habit-source="colleagues"' in page
    assert "د. أحمد" not in page.split("data-habits", 1)[1].split("</div>\n<style>", 1)[0]


def test_a_press_goes_through_the_screen_s_own_forms(habits):
    from app.models import SuggestionFeedback, VisitInvestigation, VisitMedication

    _refresh(habits)
    doc = habits["sign_in"]("doc")
    vid, ids = habits["ids"]["visit"], habits["ids"]
    doc.get(f"/visits/{vid}/record")
    doc.post(f"/visits/{vid}/investigations",
             data={"investigation_id": ids["cbc"], "habit_dx": "J06.9"})
    doc.post(f"/visits/{vid}/medications",
             data={"drug_id": ids["para"], "dose": "6.25 ml", "frequency": "كل 6 ساعات",
                   "duration": "3 أيام", "habit_dx": "J06.9"})
    with habits["app"].app_context():
        assert VisitInvestigation.query.filter_by(visit_id=vid,
                                                  investigation_id=ids["cbc"]).count() == 1
        med = VisitMedication.query.filter_by(visit_id=vid, drug_id=ids["para"]).one()
        assert (med.dose, med.frequency, med.duration) == ("6.25 ml", "كل 6 ساعات", "3 أيام")
        assert SuggestionFeedback.query.filter_by(action="taken").count() == 2
        assert SuggestionFeedback.query.filter_by(action="shown").count() == 3
    page = doc.get(f"/visits/{vid}/record").get_data(as_text=True)
    assert f'data-habit-item="test:{ids["cbc"]}"' not in page, "already on the visit"
    with habits["app"].app_context():
        assert SuggestionFeedback.query.filter_by(action="shown").count() == 3, \
            "shown once per visit"


def test_not_this_hides_it_for_good(habits):
    from app.utils import doctor_patterns as dp

    _refresh(habits)
    vid, ids = habits["ids"]["visit"], habits["ids"]
    doc = habits["sign_in"]("doc")
    assert habits["sign_in"]("desk").post(f"/visits/{vid}/habits/never", data={
        "habit_dx": "J06.9", "kind": "drug", "item_id": ids["amox"]}).status_code in (302, 403)
    doc.post(f"/visits/{vid}/habits/never",
             data={"habit_dx": "J06.9", "kind": "drug", "item_id": ids["amox"]})
    assert f'data-habit-item="drug:{ids["amox"]}"' not in _strip(habits)
    with habits["app"].app_context():
        use = dp.usage(ids["doctor"])
        assert (use["never"], use["shown"]) == (1, 2), "the refused one is not shown"


def test_a_ready_prescription_on_a_press(habits):
    from app.models import RxPreset

    with habits["app"].app_context():
        # A second habitual medicine: six more colds with both drugs, so
        # paracetamol is 14 of 16 and amoxicillin 10 of 16.
        ids = habits["ids"]
        for _ in range(6):
            _visit(habits, ids["doctor"], "J06.9",
                   drugs=[(ids["para"], "كل 6 ساعات", "3 أيام"),
                          (ids["amox"], "كل 8 ساعات", "7 أيام")])
        habits["db"].session.commit()
    _refresh(habits)
    page = _strip(habits)
    assert "data-habit-preset" in page
    with habits["app"].app_context():
        assert RxPreset.query.count() == 0, "nothing saved without a press"
    habits["sign_in"]("doc").post(f"/visits/{habits['ids']['visit']}/habits/preset",
                                  data={"habit_dx": "J06.9"})
    with habits["app"].app_context():
        preset = RxPreset.query.one()
        assert preset.doctor_id == habits["ids"]["doctor"] and not preset.is_shared
        assert {i.drug_id for i in preset.items} == {habits["ids"]["para"], habits["ids"]["amox"]}
        assert all(i.dose is None for i in preset.items), "the dose is each child's"
    assert "data-habit-preset" not in _strip(habits)


def test_the_threshold_is_the_clinic_s(habits):
    from app.models import OrderPattern
    from app.utils import doctor_patterns as dp

    with habits["app"].app_context():
        assert dp.thresholds() == (10, 60)
    assert habits["sign_in"]("doc").post("/visits/my-habits",
                                         data={"min_visits": "5"}).status_code == 403
    habits["sign_in"]("boss").post("/visits/my-habits", data={"min_visits": "12", "share": "abc"})
    with habits["app"].app_context():
        assert dp.thresholds() == (12, 60), "a word is not a share"
    _refresh(habits)
    with habits["app"].app_context():
        assert OrderPattern.query.count() == 0, "ten colds are under twelve"


def test_counted_once_a_day_from_the_heartbeat(habits):
    from app.models import OrderPattern
    from app.utils import doctor_patterns as dp

    with habits["app"].app_context():
        assert dp.maybe_refresh() is True
        assert OrderPattern.query.count() > 0
        assert dp.maybe_refresh() is False, "once a day"


def test_my_habits_has_its_door(habits):
    _refresh(habits)
    doc = habits["sign_in"]("doc")
    assert "/visits/my-habits" in doc.get("/visits/visit-templates/mine").get_data(as_text=True)
    page = doc.get("/visits/my-habits").get_data(as_text=True)
    assert 'data-habits-row="J06.9"' in page and "data-habits-thresholds" not in page
    assert 'data-habits-row="J06"' not in page, "the same visits under their category"
    assert "data-habits-clinic" not in page, "a doctor sees his own use only"
    boss = habits["sign_in"]("boss").get("/visits/my-habits").get_data(as_text=True)
    assert "data-habits-thresholds" in boss and "data-habits-clinic" in boss
    assert 'data-habits-row="J06.9"' not in boss, "the boss sees no doctor's habits"
