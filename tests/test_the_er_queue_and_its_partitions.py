"""رقم الطابور وأماكن الجلسات في الطوارئ.

صاحب العيادة: *«اعمل رقم الطابور وعدد أماكن الجلسات»* — و*«أماكن الجلسات
غالباً هي البارتيشن، خد بالك السرير اللي في البارتيشن»*.

* **الأماكن هي البارتيشنات** اللي اتبنت في إعداد الأسرّة — مش رقم يتكتب
  تاني: كام بارتيشن، مشغول كام، فاضي كام؛
* الطفل اللي **دخل بارتيشن لجلسة** من غير إقامة بيخلّي السرير «مشغول» في كل
  البرنامج — محدّش يقدر يدخّل عليه طفل تاني، ولوحة الأسرّة بتقول مين فيه؛
  ولو الطبيب قرر يحجزه، بيتحجز في نفس البارتيشن؛
* **رقم الطابور** للي مستنيين مكان: العاجل الأول، وبعدين اللي لسه ما
  اتفرزش، وبعدين الباقي — وكل مجموعة باللي وصل الأول؛
* لو الطوارئ مليانة الشاشة بتقول «مليانة — N في الطابور»؛ ولو فيه مكان، أول
  واحد عليه الدور بينوّر وجنبه «دخّله».
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def er(clinic):
    """An emergency unit with three partitions, and a ward bed elsewhere."""
    from app.models import Setting
    from app.models.place import Bed, Space, Unit

    db = clinic["db"]
    with clinic["app"].app_context():
        for module in ("emergency", "beds", "ward"):
            Setting.set(f"mod_enabled:{module}", "1")
        for key, kind, beds in (("er", "emergency", ["ب١", "ب٢", "ب٣"]),
                                ("ward", "ward", ["د١"])):
            unit = Unit(name=f"قسم {key}", kind=kind)
            db.session.add(unit)
            db.session.flush()
            space = Space(unit_id=unit.id, name=f"حيّز {key}", kind="room")
            db.session.add(space)
            db.session.flush()
            for order, name in enumerate(beds):
                db.session.add(Bed(space_id=space.id, name=name, sort_order=order))
        db.session.commit()
        clinic["beds"] = {b.name: b.id for b in Bed.query.all()}
    return clinic


def _arrive(env, name, minutes_ago=0, urgent=None, triaged=True):
    from app.models import EmergencyVisit, Patient
    from app.utils.clock import local_today

    db = env["db"]
    with env["app"].app_context():
        kid = Patient(patient_number=f"E-{name}", full_name=name, gender="male",
                      is_active=True, date_of_birth=local_today() - timedelta(days=900))
        db.session.add(kid)
        db.session.flush()
        at = datetime.utcnow() - timedelta(minutes=minutes_ago)
        row = EmergencyVisit(patient_id=kid.id, arrival="walk_in", arrived_at=at,
                             treatment_only=True, urgent=urgent,
                             level=("أحمر" if urgent else "أخضر") if triaged else None,
                             triaged_at=at if triaged else None)
        db.session.add(row)
        db.session.commit()
        return row.id


def test_the_places_are_the_partitions_built_in_the_bed_setup(er):
    from app.utils import emergency as e

    with er["app"].app_context():
        p = e.partitions()
        assert (p["total"], p["busy"], len(p["free"])) == (3, 0, 3)
        assert [r["bed"].name for r in p["rows"]] == ["ب١", "ب٢", "ب٣"], "the ward bed is not one"


def test_the_queue_is_urgent_first_then_untriaged_then_the_rest(er):
    from app.models import EmergencyVisit
    from app.utils import emergency as e

    calm_early = _arrive(er, "هادي بدري", minutes_ago=50)
    untriaged = _arrive(er, "لسه", minutes_ago=30, triaged=False)
    urgent_late = _arrive(er, "عاجل", minutes_ago=5, urgent=True)
    calm_late = _arrive(er, "هادي متأخر", minutes_ago=20)
    with er["app"].app_context():
        q = e.queue(EmergencyVisit.query.all())
    assert [k for k, _ in sorted(q.items(), key=lambda kv: kv[1])] == [
        urgent_late, untriaged, calm_early, calm_late]


def test_a_child_in_a_partition_takes_it_everywhere(er):
    from app.models import EmergencyVisit, Patient
    from app.models.place import Bed
    from app.utils import beds as place
    from app.utils import emergency as e

    first = _arrive(er, "أول", minutes_ago=10)
    second = _arrive(er, "تاني", minutes_ago=5)
    b1 = er["beds"]["ب١"]
    er["sign_in"]("boss").post(f"/emergency/attendance/{first}/seat", data={"bed_id": b1})
    with er["app"].app_context():
        row = er["db"].session.get(EmergencyVisit, first)
        assert row.place_bed_id == b1 and row.placed_at is not None
        assert b1 in place.occupied_bed_ids()
        assert b1 not in [b.id for b in place.free_beds()]
        p = e.partitions()
        assert (p["busy"], len(p["free"])) == (1, 2)
        assert e.queue(EmergencyVisit.query.all()) == {second: 1}, "out of the queue"
        # Nobody admits another child into it…
        other = er["db"].session.get(EmergencyVisit, second).patient
        with pytest.raises(place.BedTaken):
            place.admit(other, er["db"].session.get(Bed, b1))
        # …and nobody seats a second child in it.
        with pytest.raises(e.NoPlace):
            e.seat(er["db"].session.get(EmergencyVisit, second), er["db"].session.get(Bed, b1))
        # The child sitting there may be admitted into the same partition.
        mine = er["db"].session.get(Patient, row.patient_id)
        stay = place.admit(mine, er["db"].session.get(Bed, b1))
        er["db"].session.commit()
        assert stay.current_stay.bed_id == b1 and row.place_bed_id is None


def test_only_a_partition_and_only_a_free_one(er):
    from app.models import EmergencyVisit

    kid = _arrive(er, "مستني")
    boss = er["sign_in"]("boss")
    boss.post(f"/emergency/attendance/{kid}/seat", data={"bed_id": er["beds"]["د١"]})
    with er["app"].app_context():
        assert er["db"].session.get(EmergencyVisit, kid).place_bed_id is None, "a ward bed"
    with er["app"].app_context():
        from app.models.place import Bed

        er["db"].session.get(Bed, er["beds"]["ب٢"]).is_active = False
        er["db"].session.commit()
    boss.post(f"/emergency/attendance/{kid}/seat", data={"bed_id": er["beds"]["ب٢"]})
    with er["app"].app_context():
        assert er["db"].session.get(EmergencyVisit, kid).place_bed_id is None, "out of service"


def test_done_frees_the_partition_and_leaving_frees_it_too(er):
    from app.models import EmergencyVisit
    from app.utils import beds as place

    a = _arrive(er, "جلسة")
    b = _arrive(er, "حقنة")
    boss = er["sign_in"]("boss")
    boss.post(f"/emergency/attendance/{a}/seat", data={"bed_id": er["beds"]["ب١"]})
    boss.post(f"/emergency/attendance/{b}/seat", data={"bed_id": er["beds"]["ب٢"]})
    boss.post(f"/emergency/attendance/{a}/unseat")
    with er["app"].app_context():
        assert er["beds"]["ب١"] not in place.occupied_bed_ids()
        row = er["db"].session.get(EmergencyVisit, b)
        row.departed_at = datetime.utcnow()
        er["db"].session.commit()
        assert er["beds"]["ب٢"] not in place.occupied_bed_ids()
        assert row.place_bed_id == er["beds"]["ب٢"], "kept as where they sat"


def test_the_board_says_full_and_numbers_the_queue(er):
    kids = [_arrive(er, f"طفل {i}", minutes_ago=60 - i) for i in range(5)]
    boss = er["sign_in"]("boss")
    page = boss.get("/emergency/").get_data(as_text=True)
    assert "data-er-places" in page and "data-er-turn" in page
    assert page.count("data-its-turn") == 3, "three free partitions, three called"
    assert 'data-queue-no="5"' in page and "data-seat-form" in page
    for kid, bed in zip(kids, ("ب١", "ب٢", "ب٣")):
        boss.post(f"/emergency/attendance/{kid}/seat", data={"bed_id": er["beds"][bed]})
    page = boss.get("/emergency/").get_data(as_text=True)
    assert "data-er-full" in page and "الطوارئ مليانة — 2 في الطابور" in page
    assert "data-its-turn" not in page and "data-seat-form" not in page
    assert page.count("data-unseat-form") == 3
    assert 'data-queue-no="1"' in page and 'data-queue-no="3"' not in page

    beds = boss.get("/beds/").get_data(as_text=True)
    assert beds.count("data-bed-session=") == 3, "the bed board shows who sits there"


def test_no_partitions_no_places_card(clinic):
    from app.models import Setting

    with clinic["app"].app_context():
        Setting.set("mod_enabled:emergency", "1")
        clinic["db"].session.commit()
    _arrive(clinic, "وحيد")
    page = clinic["sign_in"]("boss").get("/emergency/").get_data(as_text=True)
    assert "data-er-places" not in page and "data-seat-form" not in page
    assert "data-bedless" in page
