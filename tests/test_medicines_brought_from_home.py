"""أدوية الطفل اللي جابها من البيت — GAHAR MMS.09 دليل ٥.

* بتتستلم على الإقامة بملصق فيه الطفل بمعرّفين؛
* بتتعرف ويتاخد فيها قرار، وبتخرج لحد اتكتب اسمه؛
* اللي لسه مع القسم بعد قفل الإقامة بيبان.
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def stay(clinic):
    from app.models import Bed, Patient, Setting, Space, Unit
    from app.utils import beds

    with clinic["app"].app_context():
        db = clinic["db"]
        Setting.set("mod_enabled:beds", "1")
        u = Unit(name="الباطنة", kind="ward", sort_order=0)
        db.session.add(u)
        db.session.flush()
        sp = Space(unit_id=u.id, name="عنبر", kind="bay")
        db.session.add(sp)
        db.session.flush()
        bed = Bed(space_id=sp.id, name="1", kind="bed")
        db.session.add(bed)
        db.session.flush()
        row = beds.admit(db.session.get(Patient, clinic["ids"]["child"]), bed,
                         when=datetime.utcnow() - timedelta(days=1))
        db.session.commit()
        clinic.update(stay=row.id)
    return clinic


def test_received_labelled_identified_and_handed_back(stay):
    from app.models import OwnMedicine

    doc = stay["sign_in"]("doc")
    doc.post(f"/beds/admission/{stay['stay']}/own-meds", data={"name": " "})
    with stay["app"].app_context():
        assert OwnMedicine.query.count() == 0
    r = doc.post(f"/beds/admission/{stay['stay']}/own-meds",
                 data={"name": "Depakine 200 mg/ml", "quantity": "زجاجة", "expiry": "2027-03"})
    with stay["app"].app_context():
        row = OwnMedicine.query.one()
        rid = row.id
    assert r.headers["Location"].endswith(f"/beds/own-meds/{rid}/label")
    label = doc.get(f"/beds/own-meds/{rid}/label").get_data(as_text=True)
    assert "Depakine" in label and "2025-01-01" in label and "P1" in label
    page = doc.get(f"/beds/admission/{stay['stay']}").get_data(as_text=True)
    assert "data-own-unidentified" in page and "'own-meds': 'treatment'" in page
    doc.post(f"/beds/own-meds/{rid}/identify", data={"decision": "use"})
    doc.post(f"/beds/own-meds/{rid}/out", data={"out_to": " "})
    with stay["app"].app_context():
        row = stay["db"].session.get(OwnMedicine, rid)
        assert row.decision == "use" and row.identified_at and row.held
    doc.post(f"/beds/own-meds/{rid}/out", data={"out_to": "الأم"})
    with stay["app"].app_context():
        assert not stay["db"].session.get(OwnMedicine, rid).held


def test_still_held_after_the_stay_closes_is_shown(stay):
    from app.models import Admission

    doc = stay["sign_in"]("doc")
    doc.post(f"/beds/admission/{stay['stay']}/own-meds", data={"name": "Ventolin inhaler"})
    with stay["app"].app_context():
        a = stay["db"].session.get(Admission, stay["stay"])
        a.discharged_at = datetime.utcnow()
        stay["db"].session.commit()
    page = stay["sign_in"]("boss").get(f"/beds/admission/{stay['stay']}").get_data(as_text=True)
    assert "data-own-still-held" in page
