"""ترشيد المضادات الحيوية — GAHAR MMS.02.

* المضاد المقيّد بيستنى قرار الفريق — والجرعة ما بتستناش؛
* المضاد الشغال اللي مزرعة الطفل طلعت بعد ما بدأ محتاج مراجعة، لحد ما تتسجّل؛
* الاستهلاك بأيام العلاج لكل ١٠٠٠ يوم إقامة، بعد ما المستشفى تختار المجموعات؛
* القرار لصاحب الصلاحية بس؛ وفيه باب من الصيدلية ومن مكافحة العدوى.
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def ward(clinic):
    from app.models import (Admission, Bed, Drug, DrugClass, GenericDrug, Patient, Setting,
                            Space, Unit, User)
    from app.utils import beds, drug_round

    with clinic["app"].app_context():
        db = clinic["db"]
        for m in ("beds", "pharmacy"):
            Setting.set(f"mod_enabled:{m}", "1")
        u = Unit(name="الباطنة", kind="ward", sort_order=0)
        db.session.add(u)
        db.session.flush()
        sp = Space(unit_id=u.id, name="عنبر", kind="bay")
        db.session.add(sp)
        db.session.flush()
        bed = Bed(space_id=sp.id, name="1", kind="bed")
        abx = DrugClass(code="T-ABX", name_ar="مضادات", name_en="Antibiotics")
        db.session.add_all([bed, abx])
        db.session.flush()
        mero = GenericDrug(name_en="meropenem", name_ar="ميروبينيم", class_id=abx.id)
        db.session.add(mero)
        db.session.flush()
        box = Drug(trade_name="Meronem 500", generic_id=mero.id)
        db.session.add(box)
        db.session.flush()
        stay = beds.admit(db.session.get(Patient, clinic["ids"]["child"]), bed,
                          when=datetime.utcnow() - timedelta(days=2))
        boss = User.query.filter_by(username="boss").first()
        order = drug_round.order(db.session.get(Admission, stay.id), "Meronem 500", boss, drug=box,
                                 dose="20 mg/kg", route="iv", every_hours=8,
                                 when=datetime.utcnow() - timedelta(days=1))
        db.session.commit()
        clinic.update(stay=stay.id, order=order.id, mero=mero.id, abx=abx.id)
    return clinic


def test_restricted_waits_for_the_team_and_the_dose_does_not(ward):
    from app.models import MedicationOrder, User
    from app.models.medication import GIVEN
    from app.utils import drug_round

    boss = ward["sign_in"]("boss")
    boss.post("/pharmacy/stewardship/setup", data={"what": "restricted", "generic_id": ward["mero"],
                                                  "rule": "بموافقة استشاري المعدية"})
    with ward["app"].app_context():
        o = ward["db"].session.get(MedicationOrder, ward["order"])
        dose = drug_round.give(o, GIVEN, User.query.filter_by(username="boss").first())
        ward["db"].session.commit()
        assert dose is not None, "the dose is never held for the decision"
    page = boss.get("/pharmacy/stewardship").get_data(as_text=True)
    assert f'data-asp-order="{ward["order"]}"' in page
    doc = ward["sign_in"]("doc")
    assert doc.post(f"/pharmacy/stewardship/order/{ward['order']}",
                    data={"kind": "approval", "decision": "approved"}).status_code == 403
    boss.post(f"/pharmacy/stewardship/order/{ward['order']}", data={"kind": "approval", "decision": "stop"})
    assert f'data-asp-order="{ward["order"]}"' in boss.get("/pharmacy/stewardship").get_data(as_text=True)
    boss.post(f"/pharmacy/stewardship/order/{ward['order']}", data={"kind": "approval", "decision": "approved"})
    assert f'data-asp-order="{ward["order"]}"' not in boss.get("/pharmacy/stewardship").get_data(as_text=True)


def test_a_culture_back_asks_for_a_review_and_consumption_counts_days(ward):
    from app.models import Investigation, MedicationOrder, User, VisitInvestigation
    from app.models.medication import GIVEN
    from app.models.micro import CultureResult
    from app.utils import drug_round

    boss = ward["sign_in"]("boss")
    page = boss.get("/pharmacy/stewardship").get_data(as_text=True)
    assert "data-asp-unset" in page
    boss.post("/pharmacy/stewardship/setup", data={"what": "classes", "class_id": [str(ward["abx"])]})
    with ward["app"].app_context():
        db = ward["db"]
        inv = Investigation(name_ar="مزرعة دم", name_en="Blood culture", kind="lab")
        db.session.add(inv)
        db.session.flush()
        vi = VisitInvestigation(visit_id=ward["ids"]["visit"], patient_id=ward["ids"]["child"],
                                investigation_id=inv.id, kind="lab", name="Blood culture", status="collected")
        db.session.add(vi)
        db.session.flush()
        db.session.add(CultureResult(order_id=vi.id, outcome="growth", final=False))
        o = db.session.get(MedicationOrder, ward["order"])
        drug_round.give(o, GIVEN, User.query.filter_by(username="boss").first())
        db.session.commit()
    page = boss.get("/pharmacy/stewardship").get_data(as_text=True)
    assert f'data-asp-culture-order="{ward["order"]}"' in page and "data-asp-dot" in page
    boss.post(f"/pharmacy/stewardship/order/{ward['order']}",
              data={"kind": "culture", "decision": "deescalate", "note": "حسب الحساسية"})
    page = boss.get("/pharmacy/stewardship").get_data(as_text=True)
    assert f'data-asp-culture-order="{ward["order"]}"' not in page
    assert "data-to-stewardship" in boss.get("/pharmacy/").get_data(as_text=True)
