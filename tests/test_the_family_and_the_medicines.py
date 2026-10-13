"""الأهل والأدوية — GAHAR MMS.14 دليل ٤، MMS.15 دليل ٣ و٥، MMS.16 دليل ٢.

* أول جرعة من دوا في قايمة المستشفى بتفضل على الإقامة لحد ما حد يكتب اتشاف إيه، والتفاعل بيودّي للعرض الجانبي؛
* الأهل اتقالّهم، والإعطاء بالأهل بعد ما يتعلّموا ويوضّحوا ومع متابعة مكتوبة؛
* تثقيف الصيدلي عند الخروج على صفحة صيدلية الخروج.
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402,F401

from tests.test_the_chart_nobody_read import _admit, _child, ward  # noqa: E402,F401


def test_first_dose_watched_family_told_and_taught_and_discharge_counselling(ward):
    from app.models import (Drug, FirstDoseObservation, GenericDrug, MedCounselling, MedicationOrder,
                            SelfAdministration, User)
    from app.models.admission import Admission
    from app.models.medication import GIVEN
    from app.utils import drug_round

    stay = _admit(ward, _child(ward, "ليلى"))
    with ward["app"].app_context():
        db = ward["db"]
        g = GenericDrug(name_en="ceftriaxone", name_ar="سيفترياكسون")
        db.session.add(g)
        db.session.flush()
        box = Drug(trade_name="Rocephin 1 g", generic_id=g.id)
        db.session.add(box)
        db.session.flush()
        boss = User.query.filter_by(username="boss").first()
        o = drug_round.order(db.session.get(Admission, stay), "Rocephin 1 g", boss, drug=box,
                             dose="1 g", route="iv", every_hours=24,
                             when=datetime.utcnow() - timedelta(hours=2))
        db.session.flush()
        drug_round.give(o, GIVEN, boss)
        db.session.commit()
        oid, gid = o.id, g.id
    chem = ward["sign_in"]("chem")
    chem.post("/pharmacy/dtc/first-dose", data={"generic_id": gid, "watch_for": "طفح، ضيق نفس"})
    boss_c = ward["sign_in"]("boss")
    page = boss_c.get(f"/beds/admission/{stay}").get_data(as_text=True)
    assert f'data-first-dose="{oid}"' in page and "'family-meds': 'treatment'" in page
    boss_c.post(f"/beds/medication/{oid}/first-dose", data={"outcome": "reaction"})
    r = boss_c.post(f"/beds/medication/{oid}/first-dose", data={"outcome": "reaction", "note": "طفح خفيف"})
    assert r.headers["Location"].endswith("#adr")
    with ward["app"].app_context():
        assert FirstDoseObservation.query.filter_by(order_id=oid).one().outcome == "reaction"

    boss_c.post(f"/beds/admission/{stay}/meds-told", data={"order_id": oid, "to_whom": "الأم", "questions": "1"})
    boss_c.post(f"/beds/medication/{oid}/self-admin", data={"by_whom": "family", "supervision": "الممرضة حاضرة"})
    with ward["app"].app_context():
        assert SelfAdministration.query.count() == 0, "not before they show they can"
    boss_c.post(f"/beds/medication/{oid}/self-admin",
                data={"by_whom": "family", "able": "1", "supervision": "الممرضة حاضرة"})
    with ward["app"].app_context():
        assert SelfAdministration.query.count() == 1
        assert MedCounselling.query.filter_by(kind="informed").one().questions is True
        assert ward["db"].session.get(MedicationOrder, oid) is not None

    chem.post(f"/pharmacy/ward/{stay}/counselled", data={"to_whom": "الأب", "questions": "1", "note": "الحفظ في التلاجة"})
    page = chem.get(f"/pharmacy/ward/{stay}/discharge").get_data(as_text=True)
    assert "data-counselled" in page and "الحفظ في التلاجة" in page
