"""«عادتك مع التشخيص ده» in emergency — SMART_PATTERNS_PLAN ج-٤.

The owner chose the emergency department first after the clinics (25 Nov).
The same rules as the clinics, on the attendance page:

* counted from the attendances' encounters (``channel="emergency"``): the
  tests on them and what our doctors wrote — a cancelled line and an
  outside doctor's paper are not a habit; a drug keeps its usual route;
* the strip is on the attendance, for the doctor looking at it — any of our
  doctors on the shift, each his own — never for the desk;
* a press goes through the page's own forms, as our order, with the dose
  from today's weight; «مش عايز ده» returns to the attendance;
* nothing here where the emergency department does not run, and the
  clinic strip stays off an emergency encounter.
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


def _attendance(c, code, ago, tests=(), drugs=(), open_=False):
    from app.models import Diagnosis, EmergencyOrder, EmergencyVisit, Visit, VisitInvestigation
    from app.utils.clock import local_today

    db, ids = c["db"], c["ids"]
    when = datetime.utcnow() - timedelta(days=ago)
    v = Visit(patient_id=ids["child"], doctor_id=ids["doctor"], channel="emergency",
              status="completed", visit_date=local_today() - timedelta(days=ago))
    db.session.add(v)
    db.session.flush()
    db.session.add(Diagnosis(visit_id=v.id, code=code, title="ربو"))
    row = EmergencyVisit(patient_id=ids["child"], visit_id=v.id, arrived_at=when,
                         departed_at=None if open_ else when + timedelta(hours=2),
                         disposition=None if open_ else "home")
    db.session.add(row)
    db.session.flush()
    for inv in tests:
        db.session.add(VisitInvestigation(visit_id=v.id, patient_id=ids["child"],
                                          investigation_id=inv, name="CBC"))
    for drug, route, extra in drugs:
        db.session.add(EmergencyOrder(emergency_visit_id=row.id, patient_id=ids["child"],
                                      drug_id=drug, name="x", route=route,
                                      prescriber_id=ids["doctor"], **extra))
    return row


@pytest.fixture()
def er(clinic):
    """Ten asthma attendances: a CBC in 7, salbutamol by nebuliser in 8,
    hydrocortisone written in 3 but cancelled in 2 of them, and an outside
    doctor's dexamethasone in 9. Today's attendance is open, asthma too,
    and the child weighs 10 kg."""
    from app.models import Drug, GenericDrug, GrowthRecord, Investigation, Setting
    from app.utils.clock import local_today

    with clinic["app"].app_context():
        db = clinic["db"]
        Setting.set("mod_enabled:emergency", "1")
        cbc = Investigation(name_ar="صورة دم كاملة", name_en="CBC", kind="lab", is_active=True)
        g = GenericDrug(name_ar="سالبيوتامول", name_en="Salbutamol", dose_per_kg=0.15,
                        doses_per_day=4)
        db.session.add_all([cbc, g])
        db.session.flush()
        salb = Drug(trade_name="Farcolin", strength="5 mg/ml", generic_id=g.id, conc_mg_per_ml=5)
        hydro = Drug(trade_name="Solu-Cortef")
        dexa = Drug(trade_name="Dexamethasone")
        db.session.add_all([salb, hydro, dexa])
        db.session.flush()
        for i in range(10):
            drugs = [(dexa.id, "im", {"source": "outside_rx", "outside_doctor": "د. برّه"})] if i < 9 else []
            if i < 8:
                drugs.append((salb.id, "nebulised", {}))
            if i < 3:
                drugs.append((hydro.id, "iv",
                              {"cancelled_at": datetime.utcnow()} if i < 2 else {}))
            _attendance(clinic, "J45.9", 5 + i, tests=[cbc.id] if i < 7 else [], drugs=drugs)
        today = _attendance(clinic, "J45.9", 0, open_=True)
        db.session.add(GrowthRecord(patient_id=clinic["ids"]["child"], weight_kg=10,
                                    record_date=local_today()))
        db.session.commit()
        clinic["ids"].update(cbc=cbc.id, salb=salb.id, hydro=hydro.id, dexa=dexa.id,
                             today=today.id, today_visit=today.visit_id)
    return clinic


def _refresh(c):
    from app.utils import doctor_patterns as dp

    with c["app"].app_context():
        dp.refresh()
        c["db"].session.commit()


def test_counted_from_the_department_s_own_orders(er):
    from app.models import OrderPattern

    _refresh(er)
    ids = er["ids"]
    with er["app"].app_context():
        rows = {(r.kind, r.item_id): r for r in OrderPattern.query.filter_by(
            dept="emergency", doctor_id=ids["doctor"], dx_key="J45.9")}
        assert rows[("test", ids["cbc"])].share == 70.0
        salb = rows[("drug", ids["salb"])]
        assert (salb.share, salb.route) == (80.0, "nebulised")
        assert ("drug", ids["hydro"]) not in rows, "1 of 10 once the cancelled are out"
        assert ("drug", ids["dexa"]) not in rows, "an outside doctor's paper is not a habit"
        assert OrderPattern.query.filter_by(dept="clinic").count() == 0, \
            "an emergency encounter is not a clinic visit"


def test_the_strip_on_the_attendance(er):
    _refresh(er)
    ids = er["ids"]
    page = er["sign_in"]("doc").get(f"/emergency/attendance/{ids['today']}").get_data(as_text=True)
    assert 'data-habits-dept="emergency"' in page
    assert f'data-habit-item="drug:{ids["salb"]}" data-habit-strong="1"' in page
    # 0.15 mg/kg × 10 kg = 1.5 mg = 0.3 ml of 5 mg/ml, by nebuliser.
    assert 'name="dose" value="0.3 ml"' in page and 'name="route" value="nebulised"' in page
    desk = er["sign_in"]("desk").get(f"/emergency/attendance/{ids['today']}").get_data(as_text=True)
    assert "data-habits" not in desk, "the desk is not a doctor"


def test_a_press_writes_our_order_and_counts(er):
    from app.models import EmergencyOrder, SuggestionFeedback, VisitInvestigation

    _refresh(er)
    ids = er["ids"]
    doc = er["sign_in"]("doc")
    doc.get(f"/emergency/attendance/{ids['today']}")
    doc.post(f"/emergency/attendance/{ids['today']}/order",
             data={"source": "ours", "drug_id": ids["salb"], "name": "Farcolin",
                   "dose": "0.3 ml", "route": "nebulised", "habit_dx": "J45.9"})
    doc.post(f"/emergency/attendance/{ids['today']}/test",
             data={"investigation_id": ids["cbc"], "habit_dx": "J45.9"})
    with er["app"].app_context():
        order = EmergencyOrder.query.filter_by(emergency_visit_id=ids["today"]).one()
        assert (order.drug_id, order.dose, order.route, order.source, order.prescriber_id) == \
            (ids["salb"], "0.3 ml", "nebulised", "ours", ids["doctor"])
        assert VisitInvestigation.query.filter_by(visit_id=ids["today_visit"],
                                                  investigation_id=ids["cbc"]).count() == 1
        assert SuggestionFeedback.query.filter_by(action="taken").count() == 2
    page = doc.get(f"/emergency/attendance/{ids['today']}").get_data(as_text=True)
    assert f'data-habit-item="drug:{ids["salb"]}"' not in page, "already written here"


def test_not_this_returns_to_the_attendance(er):
    _refresh(er)
    ids = er["ids"]
    doc = er["sign_in"]("doc")
    back = doc.post(f"/visits/{ids['today_visit']}/habits/never",
                    data={"habit_dx": "J45.9", "kind": "test", "item_id": ids["cbc"],
                          "attendance_id": ids["today"]})
    assert back.status_code == 302 and f"/emergency/attendance/{ids['today']}" in back.location
    page = doc.get(f"/emergency/attendance/{ids['today']}").get_data(as_text=True)
    assert f'data-habit-item="test:{ids["cbc"]}"' not in page
    assert er["sign_in"]("desk").post(
        f"/visits/{ids['today_visit']}/habits/never",
        data={"habit_dx": "J45.9", "kind": "drug", "item_id": ids["salb"]}).status_code in (302, 403)


def test_the_clinic_strip_stays_off_the_encounter(er):
    _refresh(er)
    page = er["sign_in"]("doc").get(f"/visits/{er['ids']['today_visit']}/record").get_data(as_text=True)
    assert "data-habits" not in page


def test_my_habits_names_the_department(er):
    _refresh(er)
    page = er["sign_in"]("doc").get("/visits/my-habits").get_data(as_text=True)
    assert 'data-habits-row="J45.9" data-habits-dept="emergency"' in page


def test_nothing_where_the_department_does_not_run(er):
    from app.models import OrderPattern, Setting

    with er["app"].app_context():
        Setting.set("facility_configured", "1")
        Setting.set("mod_enabled:emergency", "0")
        er["db"].session.commit()
    _refresh(er)
    with er["app"].app_context():
        assert OrderPattern.query.filter_by(dept="emergency").count() == 0
