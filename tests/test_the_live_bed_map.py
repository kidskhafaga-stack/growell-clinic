"""The live bed map: shapes, timers, how full, the case, and a unit retired.

Asked as: *«عايز أعمل شكل تفاعلي — الغرف شكل غرفة، والطوارئ شكل بارتشن،
وفي الرعاية شكل سرير رعاية، وفي الحضانة شكل حضانة وكبسولة … أدوس عليه
وأضيف مريض … ويبدأ يعدّ ساعة أو يوم … إشغال اليوم وإشغال المدة لكل قسم …
تفاصيل الحالة: متشخصة إيه، العلاج، أشعة، تحاليل، إيه اللي خلص وإيه اللي
مستني»* — and *«ده ليه مش بقدر أمسحه؟»* about a unit children had stayed in.

What is held here:

* every bed is drawn as its kind, and a taken one carries when the stay began
  and whether its unit counts hours or nights;
* how full a unit has been is the hours children spent in it over the hours
  its beds could hold;
* the case panel reads the diagnosis, the drugs still running and the tests
  still waiting from where each is written;
* a child is admitted from the map by their file number, or picked from a
  search by name or phone — «هنا لازم ابحث على المريض رقم التليفون او الاسم
  او لو مالاقتشت اضيف مريض جديد» — or registered there in three fields;
* a retired unit leaves the map once nobody is in it, and comes back when
  reopened;
* the map knows when to refresh: its fingerprint moves when a child does.
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

from tests.test_a_bed_bill_the_books_never_heard_of import (  # noqa: E402,F401
    _admit, _child, hospital)


def _map(clinic, who="boss"):
    return clinic["sign_in"](who).get("/beds/").get_data(as_text=True)


def test_every_bed_is_drawn_as_its_kind(hospital):
    from app.models.place import Bed

    with hospital["app"].app_context():
        bed = hospital["db"].session.get(Bed, hospital["beds"]["د٢"])
        bed.kind = "incubator"
        hospital["db"].session.commit()
    stay = _admit(hospital, _child(hospital, "شكل"))
    page = _map(hospital)
    assert page.count('class="bm-shape"') == 2
    assert "M10 34a29 22 0 0 1 58 0z" in page              # the incubator
    assert f'data-panel="/beds/panel/{stay}"' in page and "data-since=" in page
    assert 'data-basis="night"' in page and "data-free" in page


def test_the_rooms_of_a_unit_sit_side_by_side(hospital):
    """«ليه الداخلى مش بيترتب تلقائي افقي بدل رأسي» — the rooms are laid out
    in one wrapping row, each as wide as its own beds."""
    from app.models.place import Bed, Space, Unit

    with hospital["app"].app_context():
        unit = Unit.query.filter_by(name="الداخلي").one()
        for n in range(2, 5):
            room = Space(unit_id=unit.id, name=f"غرفة {n}", kind="room")
            hospital["db"].session.add(room)
            hospital["db"].session.flush()
            hospital["db"].session.add(Bed(space_id=room.id, name=f"س{n}"))
        hospital["db"].session.commit()
    page = _map(hospital)
    rows = page.split("data-spaces>")
    assert len(rows) == 2                        # one row for the unit's rooms
    rooms = rows[1].split('class="bm-space bm-space--')[1:]
    assert len(rooms) == 4
    assert '--beds:2;' in rooms[0] and all('--beds:1;' in r for r in rooms[1:])


def test_a_unit_counted_by_the_hour_shows_hours(hospital):
    from app.models.place import Unit

    with hospital["app"].app_context():
        Unit.query.one().billing_basis = "hour"
        hospital["db"].session.commit()
    _admit(hospital, _child(hospital, "ساعات"))
    assert 'data-basis="hour"' in _map(hospital)


def test_how_full_it_has_been(hospital):
    from app.models import BedStay
    from app.utils import bed_map
    from app.models.place import Unit

    stay = _admit(hospital, _child(hospital, "نص يوم"))
    now = datetime(2026, 5, 10, 12, 0)
    with hospital["app"].app_context():
        row = BedStay.query.filter_by(admission_id=stay).one()
        row.since, row.until = now - timedelta(hours=12), None
        hospital["db"].session.commit()
        got = bed_map.occupancy(days=1, now=now)[Unit.query.one().id]
    # One child for twelve hours, two beds for a day: a quarter.
    assert got == 25
    # A stay that began before the period counts only from its start.
    with hospital["app"].app_context():
        row = BedStay.query.filter_by(admission_id=stay).one()
        row.since = now - timedelta(hours=36)
        hospital["db"].session.commit()
        assert bed_map.occupancy(days=1, now=now)[Unit.query.one().id] == 50


def test_the_case_behind_a_bed(hospital):
    from app.models import Admission, MedicationOrder, Visit
    from app.models.diagnosis import Diagnosis
    from app.models.visit import VisitInvestigation

    pid = _child(hospital, "حالة")
    stay = _admit(hospital, pid)
    with hospital["app"].app_context():
        db = hospital["db"]
        visit = Visit(patient_id=pid, doctor_id=hospital["ids"]["doctor"])
        db.session.add(visit)
        db.session.flush()
        db.session.get(Admission, stay).visit_id = visit.id
        db.session.add(Diagnosis(visit_id=visit.id, title="التهاب رئوي", code="J18.9"))
        db.session.add(MedicationOrder(admission_id=stay, patient_id=pid,
                                       drug_name="أموكسيسيلين", dose="250mg", every_hours=8))
        db.session.add(MedicationOrder(admission_id=stay, patient_id=pid,
                                       drug_name="اتوقف", stopped_at=datetime.utcnow()))
        db.session.add(VisitInvestigation(visit_id=visit.id, patient_id=pid,
                                          kind="lab", name="صورة دم", status="requested"))
        db.session.add(VisitInvestigation(visit_id=visit.id, patient_id=pid,
                                          kind="imaging", name="أشعة صدر", status="resulted",
                                          result_text="ارتشاح يمين"))
        db.session.commit()
    page = hospital["sign_in"]("doc").get(f"/beds/panel/{stay}").get_data(as_text=True)
    assert "التهاب رئوي" in page and "أموكسيسيلين" in page and "اتوقف" not in page
    waiting = page[page.index("data-panel-waiting"):page.index("data-panel-done")]
    assert "صورة دم" in waiting and "أشعة صدر" not in waiting
    assert "ارتشاح يمين" in page[page.index("data-panel-done"):]
    assert "التهاب رئوي" in _map(hospital)                  # on the tile too


def test_admitted_from_the_map_by_file_number(hospital):
    from app.models import Admission, Patient

    pid = _child(hospital, "من الخريطة")
    with hospital["app"].app_context():
        number = hospital["db"].session.get(Patient, pid).patient_number
    boss = hospital["sign_in"]("boss")
    boss.post("/beds/admit-here", data={"patient_number": "nobody",
                                        "bed_id": hospital["beds"]["د١"]})
    with hospital["app"].app_context():
        assert Admission.query.count() == 0
    boss.post("/beds/admit-here", data={"patient_number": number, "reason": "جفاف",
                                        "bed_id": hospital["beds"]["د١"]})
    with hospital["app"].app_context():
        row = Admission.query.one()
        assert (row.patient_id, row.reason, row.bed.id) == (pid, "جفاف", hospital["beds"]["د١"])


def _family_child(clinic, name, phone):
    from datetime import date

    from app.models import Family, Parent, Patient

    with clinic["app"].app_context():
        db = clinic["db"]
        fam = Family(family_name=f"عائلة {name}")
        db.session.add(fam)
        db.session.flush()
        db.session.add(Parent(family_id=fam.id, full_name=f"أم {name}",
                              relation="mother", phone=phone))
        child = Patient(patient_number=f"F-{phone[-4:]}", family_id=fam.id,
                        full_name=name, date_of_birth=date(2022, 3, 1),
                        gender="female", is_active=True)
        db.session.add(child)
        db.session.commit()
        return child.id


def test_the_admit_box_finds_the_child_by_name_or_a_guardians_phone(hospital):
    from app.models import Admission

    sara = _family_child(hospital, "سارة حسن", "01012345678")
    other = _family_child(hospital, "ليلى عمر", "01198765432")
    inside = _family_child(hospital, "سارة جوّه", "01200001111")
    _admit(hospital, inside, "د٢")
    boss = hospital["sign_in"]("boss")

    def found(q):
        return boss.get("/beds/patient-search", query_string={"q": q}).get_json()

    by_phone = found("01012345678")
    assert [r["id"] for r in by_phone] == [sara]
    assert by_phone[0]["file"] == "F-5678" and by_phone[0]["inside"] is False
    by_name = {r["id"]: r for r in found("سارة")}
    assert set(by_name) == {sara, inside} and other not in by_name
    # A child already in a bed is listed, and said so, before the press.
    assert by_name[inside]["inside"] is True and by_name[sara]["inside"] is False
    assert found("س") == [] and found("لا أحد هنا") == []

    # Picked from the list: admitted by id, whatever is in the typed box.
    boss.post("/beds/admit-here", data={"patient_id": sara, "patient_number": "سارة",
                                        "bed_id": hospital["beds"]["د١"]})
    with hospital["app"].app_context():
        assert Admission.query.filter_by(patient_id=sara, discharged_at=None).count() == 1


def test_a_child_not_found_is_registered_from_the_admit_box(hospital):
    from app.models import ActivityLog, Patient

    boss = hospital["sign_in"]("boss")
    refused = boss.post("/beds/patient-quick", json={"full_name": "يوسف"})
    assert refused.status_code == 400 and refused.get_json()["ok"] is False
    made = boss.post("/beds/patient-quick", json={
        "full_name": "يوسف أحمد", "gender": "male", "date_of_birth": "2024-01-05"})
    body = made.get_json()
    assert made.status_code == 200 and body["ok"] is True
    with hospital["app"].app_context():
        child = hospital["db"].session.get(Patient, body["patient"]["id"])
        assert child.full_name == "يوسف أحمد"
        assert body["patient"]["file"] == child.patient_number
        assert ActivityLog.query.filter_by(action="patient.create",
                                           entity_id=child.id).count() == 1
    # And the search finds them straight after.
    assert [r["id"] for r in boss.get("/beds/patient-search?q=يوسف").get_json()] == [
        body["patient"]["id"]]


def test_the_admit_box_is_the_wards_own(hospital):
    desk = hospital["sign_in"]("desk")
    assert desk.get("/beds/patient-search?q=سارة").status_code in (302, 403, 404)
    assert desk.post("/beds/patient-quick", json={
        "full_name": "ممنوع", "gender": "male",
        "date_of_birth": "2024-01-05"}).status_code in (302, 403, 404)
    page = _map(hospital)
    form = page.split("<template data-admit-form>")[1].split("</template>")[0]
    for hook in ("data-find", "data-found", "data-picked-id", "data-quick-toggle",
                 "data-quick-save", 'name="patient_number"'):
        assert hook in form
    assert "/beds/patient-search" in page and "/beds/patient-quick" in page


def test_a_retired_unit_leaves_the_map_once_nobody_is_in_it(hospital):
    from app.models.place import Unit
    from app.utils import beds as ward

    stay = _admit(hospital, _child(hospital, "آخر واحد"))
    with hospital["app"].app_context():
        uid = Unit.query.one().id
    boss = hospital["sign_in"]("boss")
    boss.post("/beds/close", data={"level": "unit", "target_id": uid,
                                   "reason": "retired"})
    assert f'data-unit="{uid}"' in _map(hospital)          # a child is still in it
    with hospital["app"].app_context():
        from app.models import Admission
        ward.discharge(hospital["db"].session.get(Admission, stay), "home")
        hospital["db"].session.commit()
    assert f'data-unit="{uid}"' not in _map(hospital)
    boss.post("/beds/reopen", data={"level": "unit", "target_id": uid})
    assert f'data-unit="{uid}"' in _map(hospital)


def test_the_map_knows_when_to_refresh(hospital):
    boss = hospital["sign_in"]("boss")
    before = boss.get("/live/beds/0").get_json()["fp"]
    assert boss.get("/live/beds/0").get_json()["fp"] == before
    _admit(hospital, _child(hospital, "جديد"))
    assert boss.get("/live/beds/0").get_json()["fp"] != before


def test_a_retired_unit_folds_to_the_foot_of_the_setup_page(hospital):
    """Asked as: «خرجت الحالات اللي كانت في البارتشن ولسه مش ظاهر إني أمسحه».
    It still cannot be deleted — children stayed there — but once it is
    closed as no longer used and nobody is in it, it stops taking a page."""
    from app.models import Admission
    from app.models.place import Space, Unit
    from app.utils import beds as ward

    with hospital["app"].app_context():
        uid = Unit.query.one().id
        other = Unit(name="قسم شغّال", kind="ward")
        hospital["db"].session.add(other)
        hospital["db"].session.flush()
        hospital["db"].session.add(Space(unit_id=other.id, name="غرفة", kind="room"))
        hospital["db"].session.commit()
        other_id = other.id
    stay = _admit(hospital, _child(hospital, "لسه جوّه"))
    boss = hospital["sign_in"]("boss")
    boss.post("/beds/close", data={"level": "unit", "target_id": uid, "reason": "retired"})

    def setup():
        return boss.get("/beds/setup").get_data(as_text=True)

    page = setup()
    # A child still in it: it stays up top, at full size.
    assert f'data-retired-unit="{uid}"' not in page and "data-retired-title" not in page
    with hospital["app"].app_context():
        ward.discharge(hospital["db"].session.get(Admission, stay), "home")
        hospital["db"].session.commit()
    page = setup()
    assert f'data-retired-unit="{uid}"' in page and "data-retired-title" in page
    # Below the unit in use, and still not deletable, with the reason said.
    assert page.index(f'data-unit-team="{other_id}"') < page.index("data-retired-title")
    assert f'data-delete-unit="{uid}"' not in page and f'data-why-kept-unit="{uid}"' in page
    # Reopened, it is an ordinary unit again.
    boss.post("/beds/reopen", data={"level": "unit", "target_id": uid})
    page = setup()
    assert f'data-retired-unit="{uid}"' not in page and "data-retired-title" not in page
