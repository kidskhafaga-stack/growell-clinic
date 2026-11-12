"""The emergency's places by the name a nurse looks for, and their number in
Settings (asked: «اعمل رقم الطابور وعدد أماكن الجلسات» — «في صفحة
والإعدادات»).

Three partitions built from the bed setup each hold a «سرير 1»; the board and
the list a child is seated from showed «سرير 1» three times. They now say
the partition, and the bed's own name only when a partition holds more than
one. Settings says how many there are, with the door to change it — only
where the emergency is on.
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def er(clinic):
    from app.models import EmergencyVisit, Patient, Setting
    from app.utils import ward_plan

    db = clinic["db"]
    with clinic["app"].app_context():
        Setting.set("facility_configured", "1")
        Setting.set("facility_capabilities", '["emergency_care"]')
        for m in ("emergency", "beds"):
            Setting.set(f"mod_enabled:{m}", "1")
        ward_plan.build(["emergency_care"], {ward_plan.field("emergency_care", "partitions"): "3"},
                        names=lambda k, n=None: ward_plan.named(k, n))
        kid = Patient(patient_number="E1", full_name="طفل الطوارئ", gender="male", is_active=True,
                      date_of_birth=datetime(2023, 1, 1).date())
        db.session.add(kid)
        db.session.flush()
        db.session.add(EmergencyVisit(patient_id=kid.id, arrival="walk_in",
                                      arrived_at=datetime.utcnow() - timedelta(minutes=5),
                                      treatment_only=True))
        db.session.commit()
    return clinic


def test_the_board_names_the_partition_not_its_bed(er):
    from app.models.place import Bed
    from app.utils import ward_plan

    with er["app"].app_context():
        beds = Bed.query.order_by(Bed.id).all()
        assert len({b.name for b in beds}) == 1, "each partition holds a bed of the same name"
        names = [b.place_name("ar") for b in beds]
        assert names == [ward_plan.named("space.partition", n) for n in (1, 2, 3)] or len(set(names)) == 3
    page = er["sign_in"]("boss").get("/emergency/").get_data(as_text=True)
    board = page[page.index("data-er-places"):]
    for name in names:
        assert name in board
    seat = page[page.index("data-bedless"):]
    assert all(f">{n}</option>" in seat for n in names), "the seat list says which partition"


def test_a_partition_with_two_beds_names_both(er):
    from app.models.place import Bed

    with er["app"].app_context():
        first = Bed.query.order_by(Bed.id).first()
        er["db"].session.add(Bed(space_id=first.space_id, name="سرير 2", sort_order=2))
        er["db"].session.commit()
        assert first.place_name("ar").endswith(" · " + first.name)


def test_settings_says_how_many_and_where_to_change_it(er):
    page = er["sign_in"]("boss").get("/settings/").get_data(as_text=True)
    assert 'data-er-places-total="3"' in page and "data-er-places-door" in page


def test_a_clinic_without_an_emergency_does_not_see_it(clinic):
    from app.models import Setting

    with clinic["app"].app_context():
        Setting.set("facility_configured", "1")
        Setting.set("mod_enabled:emergency", "0")
        clinic["db"].session.commit()
    page = clinic["sign_in"]("boss").get("/settings/").get_data(as_text=True)
    assert "data-er-places-setting" not in page
