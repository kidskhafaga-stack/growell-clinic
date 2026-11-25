"""«عادتك مع التشخيص ده» in intensive care and the incubators —
SMART_PATTERNS_PLAN ج-٤ ج.

* each unit its own habits, by the unit of the child's bed: a neonate's
  orders in the incubators are not a ward child's with the same code;
* the strip on a stay in an incubator shows the incubators' habits, with
  the dose from today's weight;
* nothing where the unit's module does not run.
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

from tests.test_the_chart_nobody_read import ward  # noqa: E402,F401


def _bed(c, kind):
    from app.models import Service
    from app.models.place import Bed, Space, Unit

    db = c["db"]
    night = Service(name=f"ليلة {kind}", category="other", price=900)
    db.session.add(night)
    db.session.flush()
    unit = Unit(name=kind, kind=kind, rate_service_id=night.id)
    db.session.add(unit)
    db.session.flush()
    space = Space(unit_id=unit.id, name=f"{kind} ١", kind="room")
    db.session.add(space)
    db.session.flush()
    beds = [Bed(space_id=space.id, name=f"{kind}-١"), Bed(space_id=space.id, name=f"{kind}-٢")]
    db.session.add_all(beds)
    db.session.flush()
    return [b.id for b in beds]


def _past(c, bed, ago, drugs):
    from app.models import Diagnosis, MedicationOrder, Visit
    from app.models.admission import Admission, BedStay

    db, ids = c["db"], c["ids"]
    when = datetime.utcnow() - timedelta(days=ago)
    v = Visit(patient_id=ids["child"], doctor_id=ids["doctor"], channel="ward",
              status="completed", visit_date=when.date())
    db.session.add(v)
    db.session.flush()
    db.session.add(Diagnosis(visit_id=v.id, code="P36.9", title="تسمم دم وليدي"))
    a = Admission(patient_id=ids["child"], visit_id=v.id, doctor_id=ids["doctor"],
                  admitted_at=when, discharged_at=when + timedelta(days=5), outcome="home")
    db.session.add(a)
    db.session.flush()
    db.session.add(BedStay(admission_id=a.id, bed_id=bed, since=when, until=when + timedelta(days=5)))
    for drug, every, route in drugs:
        db.session.add(MedicationOrder(admission_id=a.id, patient_id=ids["child"], drug_id=drug,
                                       drug_name="x", route=route, every_hours=every,
                                       started_at=when, ordered_by=ids["doctor"]))


@pytest.fixture()
def units(ward):
    """Ten neonatal sepsis stays in the incubators on ampicillin IV every
    12 hours, and ten with the same code on the ward on ceftriaxone — so the
    two units' habits differ. Today a newborn of 3 kg is in an incubator."""
    from app.models import Diagnosis, Drug, GenericDrug, GrowthRecord, Setting, User
    from app.models.admission import Admission
    from app.utils import beds as place
    from app.utils import stay_orders
    from app.utils.clock import local_today
    from app.models.place import Bed

    c = ward
    with c["app"].app_context():
        db = c["db"]
        for m in ("nicu", "icu"):
            Setting.set(f"mod_enabled:{m}", "1")
        nicu = _bed(c, "nicu")
        g = GenericDrug(name_ar="أمبيسيلين", name_en="Ampicillin", dose_per_kg=50, doses_per_day=2)
        db.session.add(g)
        db.session.flush()
        amp = Drug(trade_name="Ampicillin", strength="500 mg", generic_id=g.id)
        cef = Drug(trade_name="Rocephin", strength="1 g")
        db.session.add_all([amp, cef])
        db.session.flush()
        for i in range(10):
            _past(c, nicu[1], 20 + i * 4, [(amp.id, 12, "iv")])
            _past(c, c["beds"][1], 22 + i * 4, [(cef.id, 24, "iv")])
        db.session.add(GrowthRecord(patient_id=c["ids"]["child"], weight_kg=3,
                                    record_date=local_today()))
        db.session.commit()
        from app.models import Patient
        stay = place.admit(db.session.get(Patient, c["ids"]["child"]), db.session.get(Bed, nicu[0]),
                           when=datetime.utcnow() - timedelta(hours=6))
        db.session.flush()
        enc = stay_orders.encounter(stay, db.session.get(User, c["ids"]["doctor"]))
        db.session.add(Diagnosis(visit_id=enc.id, code="P36.9", title="تسمم دم وليدي"))
        db.session.commit()
        c["ids"].update(amp=amp.id, cef=cef.id, stay=stay.id)
        assert db.session.get(Admission, stay.id).visit_id == enc.id
    return c


def _refresh(c):
    from app.utils import doctor_patterns as dp

    with c["app"].app_context():
        dp.refresh()
        c["db"].session.commit()


def test_each_unit_its_own_habits(units):
    from app.models import OrderPattern

    _refresh(units)
    ids = units["ids"]
    with units["app"].app_context():
        def drugs(dept):
            return {r.item_id: r for r in OrderPattern.query.filter_by(
                dept=dept, doctor_id=ids["doctor"], dx_key="P36.9", kind="drug")}
        nicu, ward_ = drugs("nicu"), drugs("ward")
        assert set(nicu) == {ids["amp"]} and (nicu[ids["amp"]].frequency, nicu[ids["amp"]].route) == ("12", "iv")
        assert set(ward_) == {ids["cef"]}, "the ward's own, not the incubators'"


def test_the_strip_in_an_incubator(units):
    _refresh(units)
    ids = units["ids"]
    page = units["sign_in"]("doc").get(f"/beds/admission/{ids['stay']}").get_data(as_text=True)
    assert 'data-habits-dept="nicu"' in page
    assert f'data-habit-item="drug:{ids["amp"]}"' in page
    assert f'data-habit-item="drug:{ids["cef"]}"' not in page
    # 50 mg/kg × 3 kg = 150 mg, every 12 hours.
    assert 'name="dose" value="150 mg"' in page and 'name="every_hours" value="12"' in page


def test_my_habits_names_the_incubators(units):
    _refresh(units)
    page = units["sign_in"]("doc").get("/visits/my-habits").get_data(as_text=True)
    assert 'data-habits-row="P36.9" data-habits-dept="nicu"' in page
    assert "الحضّانة" in page


def test_nothing_where_the_unit_does_not_run(units):
    from app.models import OrderPattern, Setting

    with units["app"].app_context():
        Setting.set("facility_configured", "1")
        Setting.set("mod_enabled:nicu", "0")
        units["db"].session.commit()
    _refresh(units)
    with units["app"].app_context():
        assert OrderPattern.query.filter_by(dept="nicu").count() == 0
    page = units["sign_in"]("doc").get(f"/beds/admission/{units['ids']['stay']}").get_data(as_text=True)
    assert "data-habits" not in page
