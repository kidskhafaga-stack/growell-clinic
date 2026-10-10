"""مطابقة الأدوية في الداخلي — GAHAR `MMS.10` / `GSR.18`.

* **عند الدخول**: أدوية البيت، كل واحد بقرار — يكمّل أو يتوقف أو يتغيّر؛
* **عند النقل لقسم تاني**: أدوية القسم، والفريق اللي استلم بيقرر — والنقل
  لسرير في نفس القسم مش نقل؛
* **عند الخروج أو التحويل**: الاتنين مع بعض — واللي اتوقف من البيت بيتشال
  من قايمته، ودوا القسم اللي «يروّح بيه» بيتضاف لها؛
* القرار للكل مرة واحدة، أو مفيش حاجة بتتحفظ؛
* **ومفيش حاجة بتستنى**: الخروج بيتعمل من غير مطابقة، والشاشة بتقول اللي لسه.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def stay(clinic):
    """A child in a bed with one medicine from home and one ward order, and a
    bed in another unit to move to."""
    from app.models import MedicationOrder, PatientMedication, Setting, User
    from app.models.place import Bed, Space, Unit
    from app.utils import beds

    with clinic["app"].app_context():
        db = clinic["db"]
        Setting.set("mod_enabled:beds", "1")
        ward = Unit(name="الداخلي", kind="ward")
        icu = Unit(name="الرعاية", kind="ward")
        db.session.add_all([ward, icu])
        db.session.flush()
        room_a = Space(unit_id=ward.id, name="غرفة ١", kind="room")
        room_b = Space(unit_id=icu.id, name="غرفة ٢", kind="room")
        db.session.add_all([room_a, room_b])
        db.session.flush()
        a1, a2 = Bed(space_id=room_a.id, name="أ١"), Bed(space_id=room_a.id, name="أ٢")
        b1 = Bed(space_id=room_b.id, name="ب١")
        db.session.add_all([a1, a2, b1])
        db.session.flush()
        boss = db.session.get(User, clinic["ids"]["admin"])
        from app.models import Patient
        child = db.session.get(Patient, clinic["ids"]["child"])
        row = beds.admit(child, a1, user=boss)
        db.session.flush()
        home = PatientMedication(patient_id=child.id, name="فيتامين د", dose="400 وحدة")
        order = MedicationOrder(admission_id=row.id, patient_id=child.id,
                                drug_name="سيفترياكسون", dose="500mg", every_hours=24)
        db.session.add_all([home, order])
        db.session.commit()
        clinic["ids"].update(admission=row.id, home=home.id, order=order.id,
                             same_unit_bed=a2.id, other_unit_bed=b1.id)
    return clinic


def _url(c, interface, **q):
    extra = "".join(f"&{k}={v}" for k, v in q.items())
    return f"/beds/admission/{c['ids']['admission']}/reconcile/{interface}?x=1{extra}"


def test_the_stay_says_what_is_still_open(stay):
    page = stay["sign_in"]().get(f"/beds/admission/{stay['ids']['admission']}").get_data(as_text=True)
    assert "data-reconcile" in page and 'data-recon-step="admission"' in page
    assert "data-recon-open" in page


def test_admission_decides_each_home_medicine_all_at_once(stay):
    from app.models import MedReconciliation
    from app.utils import med_reconciliation as rec

    boss = stay["sign_in"]()
    page = boss.get(_url(stay, "admission")).get_data(as_text=True)
    key = f"home_{stay['ids']['home']}"
    assert f'data-recon-item="{key}"' in page and f"order_{stay['ids']['order']}" not in page
    boss.post(_url(stay, "admission"), data={})                       # nothing chosen
    with stay["app"].app_context():
        assert MedReconciliation.query.count() == 0
    boss.post(_url(stay, "admission"), data={f"d_{key}": "continue"})
    with stay["app"].app_context():
        from app.models import Admission
        row = stay["db"].session.get(Admission, stay["ids"]["admission"])
        assert rec.is_done(row, rec.ADMISSION)
        assert MedReconciliation.query.one().decision == "continue"


def test_a_move_in_the_same_unit_is_not_a_transfer_and_another_unit_is(stay):
    from app.models import Admission
    from app.models.place import Bed
    from app.utils import beds
    from app.utils import med_reconciliation as rec

    with stay["app"].app_context():
        db = stay["db"]
        row = db.session.get(Admission, stay["ids"]["admission"])
        beds.move(row, db.session.get(Bed, stay["ids"]["same_unit_bed"]))
        db.session.commit()
        assert rec.transfers(row) == []
        beds.move(row, db.session.get(Bed, stay["ids"]["other_unit_bed"]))
        db.session.commit()
        moved = rec.transfers(row)
        assert len(moved) == 1
        stay_id = moved[0].id
    boss = stay["sign_in"]()
    key = f"order_{stay['ids']['order']}"
    page = boss.get(_url(stay, "transfer", stay=stay_id)).get_data(as_text=True)
    assert f'data-recon-item="{key}"' in page
    boss.post(_url(stay, "transfer", stay=stay_id), data={f"d_{key}": "modify", f"n_{key}": "250mg"})
    with stay["app"].app_context():
        row = stay["db"].session.get(Admission, stay["ids"]["admission"])
        assert rec.status(row)["transfers"][0]["done"]
    assert boss.get(_url(stay, "transfer", stay=999)).status_code == 404


def test_discharge_carries_the_decisions_to_the_home_list(stay):
    from app.models import Admission, PatientMedication
    from app.utils import beds
    from app.utils import med_reconciliation as rec

    with stay["app"].app_context():
        row = stay["db"].session.get(Admission, stay["ids"]["admission"])
        beds.discharge(row, "home")                       # nothing waited
        stay["db"].session.commit()
        assert rec.status(row)["open"] >= 1
    home, order = f"home_{stay['ids']['home']}", f"order_{stay['ids']['order']}"
    stay["sign_in"]().post(_url(stay, "discharge"),
                           data={f"d_{home}": "stop", f"d_{order}": "continue"})
    with stay["app"].app_context():
        db = stay["db"]
        assert db.session.get(PatientMedication, stay["ids"]["home"]).stopped_on is not None
        running = PatientMedication.query.filter(
            PatientMedication.patient_id == stay["ids"]["child"],
            PatientMedication.stopped_on.is_(None)).all()
        assert [m.name for m in running] == ["سيفترياكسون"]
        row = db.session.get(Admission, stay["ids"]["admission"])
        assert rec.status(row)["discharge"]["done"]


def test_only_the_ward_reconciles(stay):
    assert stay["sign_in"]("acct").get(_url(stay, "admission")).status_code in (302, 403, 404)
