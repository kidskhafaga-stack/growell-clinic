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
* a child is admitted from the map by their file number;
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
