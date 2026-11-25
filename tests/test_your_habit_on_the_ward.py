"""«عادتك مع التشخيص ده» on the ward — SMART_PATTERNS_PLAN ج-٤ (the ward
after the emergency department, in the document's order).

* counted from stays that ended in a ward bed — intensive care and the incubators are
  their own part, later — from the diagnosis on the stay's encounter, the
  tests the stay owns and its standing orders, each drug with its usual
  interval and route;
* the strip is on the stay for the doctor looking at it, each his own, and
  never for someone without the order right;
* a press writes a standing order through the stay's own form, with the
  usual interval and the dose from today's weight; «مش عايز ده» returns to
  the stay.
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

from tests.test_the_chart_nobody_read import ward  # noqa: E402,F401


def _past_stay(c, code, ago, tests=(), drugs=()):
    from app.models import (Diagnosis, MedicationOrder, Visit, VisitInvestigation)
    from app.models.admission import Admission, BedStay
    from app.utils.clock import local_today

    db, ids = c["db"], c["ids"]
    when = datetime.utcnow() - timedelta(days=ago)
    v = Visit(patient_id=ids["child"], doctor_id=ids["doctor"], channel="ward",
              status="completed", visit_date=local_today() - timedelta(days=ago))
    db.session.add(v)
    db.session.flush()
    db.session.add(Diagnosis(visit_id=v.id, code=code, title="التهاب رئوي"))
    a = Admission(patient_id=ids["child"], visit_id=v.id, doctor_id=ids["doctor"],
                  admitted_at=when, discharged_at=when + timedelta(days=3), outcome="home")
    db.session.add(a)
    db.session.flush()
    db.session.add(BedStay(admission_id=a.id, bed_id=c["beds"][1], since=when,
                           until=when + timedelta(days=3)))
    for inv in tests:
        db.session.add(VisitInvestigation(visit_id=v.id, patient_id=ids["child"],
                                          admission_id=a.id, investigation_id=inv, name="CRP"))
    for drug, every, route in drugs:
        db.session.add(MedicationOrder(admission_id=a.id, patient_id=ids["child"], drug_id=drug,
                                       drug_name="x", route=route, every_hours=every,
                                       started_at=when, ordered_by=ids["doctor"]))
    return a


@pytest.fixture()
def stays(ward):
    """Ten pneumonia stays: a CRP in 8, ceftriaxone IV every 12 hours in 9,
    paracetamol by mouth every 6 hours in 4. Today's stay is open on a ward
    bed with its pneumonia written on its encounter; the child weighs 12 kg."""
    from app.models import Diagnosis, Drug, GenericDrug, GrowthRecord, Investigation
    from app.models.admission import Admission
    from app.utils import stay_orders
    from app.utils.clock import local_today
    from tests.test_the_chart_nobody_read import _admit

    c = ward
    with c["app"].app_context():
        db = c["db"]
        crp = Investigation(name_ar="بروتين سي التفاعلي", name_en="CRP", kind="lab", is_active=True)
        g = GenericDrug(name_ar="سيفترياكسون", name_en="Ceftriaxone", dose_per_kg=50, doses_per_day=2)
        db.session.add_all([crp, g])
        db.session.flush()
        cef = Drug(trade_name="Rocephin", strength="1 g", generic_id=g.id)
        para = Drug(trade_name="Cetal")
        db.session.add_all([cef, para])
        db.session.flush()
        for i in range(10):
            drugs = [(cef.id, 12, "iv")] if i < 9 else []
            if i < 4:
                drugs.append((para.id, 6, "oral"))
            _past_stay(c, "J18.9", 20 + i * 5, tests=[crp.id] if i < 8 else [], drugs=drugs)
        db.session.add(GrowthRecord(patient_id=c["ids"]["child"], weight_kg=12,
                                    record_date=local_today()))
        db.session.commit()
        c["ids"].update(crp=crp.id, cef=cef.id, para=para.id)
    stay_id = _admit(c, c["ids"]["child"])
    with c["app"].app_context():
        from app.models import User

        stay = db.session.get(Admission, stay_id)
        enc = stay_orders.encounter(stay, db.session.get(User, c["ids"]["doctor"]))
        db.session.add(Diagnosis(visit_id=enc.id, code="J18.9", title="التهاب رئوي"))
        db.session.commit()
        c["ids"].update(stay=stay_id, stay_visit=stay.visit_id)
    return c


def _refresh(c):
    from app.utils import doctor_patterns as dp

    with c["app"].app_context():
        dp.refresh()
        c["db"].session.commit()


def test_counted_from_the_ward_s_stays(stays):
    from app.models import OrderPattern

    _refresh(stays)
    ids = stays["ids"]
    with stays["app"].app_context():
        rows = {(r.kind, r.item_id): r for r in OrderPattern.query.filter_by(
            dept="ward", doctor_id=ids["doctor"], dx_key="J18.9")}
        assert rows[("test", ids["crp"])].share == 80.0
        cef = rows[("drug", ids["cef"])]
        assert (cef.share, cef.frequency, cef.route) == (90.0, "12", "iv")
        assert rows[("drug", ids["para"])].share == 40.0, "faded"


def test_the_strip_on_the_stay(stays):
    _refresh(stays)
    ids = stays["ids"]
    page = stays["sign_in"]("doc").get(f"/beds/admission/{ids['stay']}").get_data(as_text=True)
    assert 'data-habits-dept="ward"' in page
    assert f'data-habit-item="drug:{ids["cef"]}" data-habit-strong="1"' in page
    # 50 mg/kg × 12 kg = 600 mg, IV, every 12 hours.
    assert 'name="dose" value="600 mg"' in page and 'name="every_hours" value="12"' in page
    assert 'name="route" value="iv"' in page
    chem = stays["sign_in"]("chem").get(f"/beds/admission/{ids['stay']}").get_data(as_text=True)
    assert "data-habits" not in chem, "the pharmacist does not write orders"


def test_a_press_writes_the_standing_order(stays):
    from app.models import MedicationOrder, SuggestionFeedback, VisitInvestigation

    _refresh(stays)
    ids = stays["ids"]
    doc = stays["sign_in"]("doc")
    doc.post(f"/beds/admission/{ids['stay']}/medication",
             data={"drug_id": ids["cef"], "drug_name": "Rocephin", "dose": "600 mg",
                   "route": "iv", "every_hours": "12", "habit_dx": "J18.9"})
    doc.post(f"/beds/admission/{ids['stay']}/test",
             data={"investigation_id": ids["crp"], "habit_dx": "J18.9"})
    with stays["app"].app_context():
        o = MedicationOrder.query.filter_by(admission_id=ids["stay"]).one()
        assert (o.drug_id, o.dose, o.route, o.every_hours) == (ids["cef"], "600 mg", "iv", 12)
        assert VisitInvestigation.query.filter_by(admission_id=ids["stay"],
                                                  investigation_id=ids["crp"]).count() == 1
        assert SuggestionFeedback.query.filter_by(action="taken").count() == 2
    page = doc.get(f"/beds/admission/{ids['stay']}").get_data(as_text=True)
    assert f'data-habit-item="drug:{ids["cef"]}"' not in page, "already running"


def test_not_this_returns_to_the_stay(stays):
    _refresh(stays)
    ids = stays["ids"]
    back = stays["sign_in"]("doc").post(
        f"/visits/{ids['stay_visit']}/habits/never",
        data={"habit_dx": "J18.9", "kind": "drug", "item_id": ids["para"],
              "admission_id": ids["stay"]})
    assert back.status_code == 302 and f"/beds/admission/{ids['stay']}" in back.location
    page = stays["sign_in"]("doc").get(f"/beds/admission/{ids['stay']}").get_data(as_text=True)
    assert f'data-habit-item="drug:{ids["para"]}"' not in page


def test_my_habits_names_the_ward(stays):
    _refresh(stays)
    page = stays["sign_in"]("doc").get("/visits/my-habits").get_data(as_text=True)
    assert 'data-habits-row="J18.9" data-habits-dept="ward"' in page
    assert "كل 12 ساعات" in page


def test_the_ward_is_not_counted_as_the_clinics(stays):
    from app.models import OrderPattern

    _refresh(stays)
    with stays["app"].app_context():
        assert OrderPattern.query.filter_by(dept="clinic").count() == 0
    page = stays["sign_in"]("doc").get(
        f"/visits/{stays['ids']['stay_visit']}/record").get_data(as_text=True)
    assert "data-habits" not in page, "the stay's strip is on the stay"
