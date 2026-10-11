"""ميكروب منذر نما — مكافحة العدوى بتتبلّغ، وبترد.

* أول ما المعمل يكتب عزلة لميكروب معلَّم «إنذار» — حتى في المبدئي — بيتعمل
  تنبيه، والجرس بيرن عند اللي معاه صلاحية ``infection_control`` بس؛
* الاقتراح بيقول اللي معروف: الاحتياط اللي مكافحة العدوى حدّدته للميكروب، والطفل
  فين، وأسرّة العزل الفاضية — **ومفيش حاجة بتتغير لوحدها**؛
* القرار بيتسجّل باسم اللي سجّله، وبيظهر على إقامة الطفل؛
* عزلة المعمل رجع فيها قبل الرد بتشيل التنبيه معاها.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

from tests.test_what_grew_and_what_it_answers_to import _isolate, _order  # noqa: E402

MRSA = "Staphylococcus aureus (MRSA)"


@pytest.fixture()
def ward(clinic):
    from app.models import (Bed, Investigation, Setting, Space, Unit, User,
                            UserCapability)

    with clinic["app"].app_context():
        db = clinic["db"]
        for m in ("labs", "beds"):
            Setting.set(f"mod_enabled:{m}", "1")
        urine = Investigation(name_ar="مزرعة بول", name_en="Urine culture", kind="lab",
                              is_culture=True)
        icu = Unit(name="العناية", kind="icu", sort_order=0)
        db.session.add_all([urine, icu])
        db.session.flush()
        bay = Space(unit_id=icu.id, name="الصالة", kind="bay")
        iso = Space(unit_id=icu.id, name="بارتشن العزل", kind="partition",
                    is_isolation=True, sort_order=1)
        db.session.add_all([bay, iso])
        db.session.flush()
        open_bed = Bed(space_id=bay.id, name="سرير ١", kind="bed")
        iso_bed = Bed(space_id=iso.id, name="سرير العزل", kind="bed")
        nurse = User(username="ipcnurse", full_name="ممرضة مكافحة العدوى",
                     role="nursing", is_active=True)
        nurse.set_password("secret")
        db.session.add_all([open_bed, iso_bed, nurse])
        db.session.flush()
        db.session.add(UserCapability(user_id=nurse.id, capability="infection_control",
                                      granted_by=clinic["ids"]["admin"]))
        db.session.commit()
        clinic["urine"] = urine.id
        clinic["beds"] = {"open": open_bed.id, "iso": iso_bed.id}
    boss = clinic["sign_in"]("boss")
    boss.post("/labs/micro/organisms", data={"names": f"Escherichia coli\n{MRSA}"})
    boss.post("/labs/micro/antibiotics", data={"names": "Vancomycin\nOxacillin"})
    from app.models import MicroAntibiotic, MicroOrganism
    with clinic["app"].app_context():
        clinic["org"] = {o.name: o.id for o in MicroOrganism.query}
        clinic["abx"] = {a.name: a.id for a in MicroAntibiotic.query}
    boss.post(f"/labs/micro/organisms/{clinic['org'][MRSA]}", data={"action": "alert"})
    return clinic


def _admit(c, bed_key):
    from app.models import Bed, Patient
    from app.utils import beds

    with c["app"].app_context():
        row = beds.admit(c["db"].session.get(Patient, c["ids"]["child"]),
                         c["db"].session.get(Bed, c["beds"][bed_key]))
        c["db"].session.commit()
        return row.id


def _alerts(c):
    from app.models import IpcAlert

    with c["app"].app_context():
        return [(a.id, a.organism.name, a.is_open) for a in IpcAlert.query.order_by(IpcAlert.id)]


def test_only_an_alert_organism_raises_and_only_once(ward):
    order = _order(ward)
    _isolate(ward, order, "Escherichia coli", {"Oxacillin": "S"})
    assert _alerts(ward) == [], "an ordinary organism tells nobody"
    _isolate(ward, order, MRSA, {"Oxacillin": "R", "Vancomycin": "S"})
    alerts = _alerts(ward)
    assert len(alerts) == 1 and alerts[0][1] == MRSA and alerts[0][2]
    # Saving the culture again — final this time — is the same isolate.
    ward["sign_in"]("boss").post(f"/labs/order/{order}/culture",
                                 data={"outcome": "growth", "final": "1"})
    assert len(_alerts(ward)) == 1
    page = ward["sign_in"]("boss").get(f"/labs/order/{order}").get_data(as_text=True)
    assert "data-ipc-told" in page


def test_the_bell_and_the_board_are_infection_control_s(ward):
    from app.models import User
    from app.utils.notifications import get_notifications, invalidate

    order = _order(ward)
    _isolate(ward, order, MRSA, {"Oxacillin": "R"})
    with ward["app"].test_request_context():
        invalidate()
        nurse = User.query.filter_by(username="ipcnurse").first()
        doc = User.query.filter_by(username="doc").first()
        assert any(n["key"] == "ipc_alerts" for n in get_notifications(nurse))
        assert not any(n["key"] == "ipc_alerts" for n in get_notifications(doc))
    assert ward["sign_in"]("doc").get("/infection-control/").status_code == 403
    page = ward["sign_in"]("ipcnurse").get("/infection-control/").get_data(as_text=True)
    assert "data-ipc-alert" in page and "data-nav-ipc" in page


def test_the_suggestion_says_what_is_known_and_changes_nothing(ward):
    from app.models import Admission, IpcAlert, MicroOrganism

    stay = _admit(ward, "open")
    nurse = ward["sign_in"]("ipcnurse")
    mrsa = ward["org"][MRSA]
    nurse.post(f"/infection-control/organism/{mrsa}", data={"precaution": "contact"})
    with ward["app"].app_context():
        assert ward["db"].session.get(MicroOrganism, mrsa).precaution == "contact"
    order = _order(ward)
    _isolate(ward, order, MRSA, {"Oxacillin": "R"})
    page = nurse.get("/infection-control/").get_data(as_text=True)
    assert 'data-ipc-free="1"' in page, "the free isolation bed is named"
    assert 'value="contact" checked' in page, "infection control's own precaution is suggested"
    with ward["app"].app_context():
        admission = ward["db"].session.get(Admission, stay)
        assert admission.bed.id == ward["beds"]["open"], "nobody was moved"
        alert = IpcAlert.query.one()
        assert alert.is_open and alert.precautions is None, "nothing decided by itself"
    stay_page = ward["sign_in"]("boss").get(f"/beds/admission/{stay}").get_data(as_text=True)
    assert 'data-stay-ipc="open"' in stay_page


def test_a_person_decides_and_the_stay_shows_it(ward):
    from app.models import IpcAlert, User

    stay = _admit(ward, "iso")
    order = _order(ward)
    _isolate(ward, order, MRSA, {"Oxacillin": "R"})
    nurse = ward["sign_in"]("ipcnurse")
    alert_id = _alerts(ward)[0][0]
    # Nothing ticked is refused — «standard» is an answer, silence is not.
    nurse.post(f"/infection-control/alert/{alert_id}", data={"isolation": "isolated"})
    assert _alerts(ward)[0][2]
    nurse.post(f"/infection-control/alert/{alert_id}",
               data={"precautions": ["standard", "contact"], "isolation": "isolated",
                     "note": "في بارتشن العزل من الأول"})
    with ward["app"].app_context():
        alert = ward["db"].session.get(IpcAlert, alert_id)
        who = User.query.filter_by(username="ipcnurse").first()
        assert alert.precautions == "contact", "standard dropped beside contact"
        assert alert.isolation == "isolated" and alert.reviewed_by == who.id
    stay_page = ward["sign_in"]("boss").get(f"/beds/admission/{stay}").get_data(as_text=True)
    assert 'data-stay-ipc="answered"' in stay_page
    board = nurse.get("/infection-control/").get_data(as_text=True)
    assert f'data-ipc-done-row="{alert_id}"' in board and "data-ipc-none" in board


def test_an_isolate_taken_back_before_an_answer_takes_its_alert(ward):
    order = _order(ward)
    iso = _isolate(ward, order, MRSA, {"Oxacillin": "R"})
    assert len(_alerts(ward)) == 1
    ward["sign_in"]("boss").post(f"/labs/order/{order}/culture/isolate/{iso}",
                                 data={"remove": "1"})
    assert _alerts(ward) == []


def test_infection_control_reads_the_hand_hygiene_reports(ward):
    assert ward["sign_in"]("ipcnurse").get("/hand-hygiene/").status_code == 200
