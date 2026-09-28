"""A unit, a room or a bed typed wrong can be renamed — slept in or not.

Asked as: *«ده ليه مش بقدر امسحه واعدله؟»* — a unit built by hand as
"Patrions", with "Patrion 1" and "Bed 1" inside it. Deleting it is refused,
rightly: two children are staying in it, and a bed a child slept in carries
their stay. But there was **no way to edit it at all**, so a name typed wrong
stayed wrong for good.

The stay points at the bed, not at its name, so a new name shows everywhere
and changes no stay. A room's kind (room, partition, bay) and a bed's kind
(bed, incubator, capsule…) are the shape on the map and can change too. A
unit's kind cannot from here: it decides billing by the hour or the night and
the cost centre, which is a bigger decision than fixing a name.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402,F401

from tests.test_a_bed_bill_the_books_never_heard_of import (  # noqa: E402,F401
    _admit, _child, hospital)


def _rename(clinic, level, target, name, kind=None, who="boss"):
    data = {"level": level, "target_id": target, "name": name}
    if kind is not None:
        data["kind"] = kind
    return clinic["sign_in"](who).post("/beds/rename", data=data)


def _ids(clinic):
    from app.models.place import Bed, Space, Unit

    with clinic["app"].app_context():
        return {"unit": Unit.query.one().id, "space": Space.query.one().id,
                "bed": clinic["beds"]["د١"]}


def test_a_unit_a_child_is_staying_in_is_renamed_and_still_not_deleted(hospital):
    from app.models import ActivityLog
    from app.models.place import Unit

    _admit(hospital, _child(hospital, "باقي"))
    ids = _ids(hospital)
    _rename(hospital, "unit", ids["unit"], "الطوارئ")
    with hospital["app"].app_context():
        assert hospital["db"].session.get(Unit, ids["unit"]).name == "الطوارئ"
        log = ActivityLog.query.filter_by(action="place.rename").one()
        assert "الداخلي -> الطوارئ" in log.detail
    hospital["sign_in"]("boss").post(f"/beds/unit/{ids['unit']}/delete")
    with hospital["app"].app_context():
        assert hospital["db"].session.get(Unit, ids["unit"]) is not None


def test_a_room_and_a_bed_change_name_and_shape(hospital):
    from app.models.place import Bed, Space

    ids = _ids(hospital)
    _rename(hospital, "space", ids["space"], "بارتشن 1", kind="partition")
    _rename(hospital, "bed", ids["bed"], "ترولي 1", kind="trolley")
    with hospital["app"].app_context():
        space = hospital["db"].session.get(Space, ids["space"])
        bed = hospital["db"].session.get(Bed, ids["bed"])
        assert (space.name, space.kind) == ("بارتشن 1", "partition")
        assert (bed.name, bed.kind) == ("ترولي 1", "trolley")


def test_a_kind_that_is_not_one_is_ignored_and_a_unit_keeps_its_kind(hospital):
    from app.models.place import Bed, Unit

    ids = _ids(hospital)
    _rename(hospital, "bed", ids["bed"], "سرير أ", kind="spaceship")
    _rename(hospital, "unit", ids["unit"], "العناية", kind="icu")
    with hospital["app"].app_context():
        assert hospital["db"].session.get(Bed, ids["bed"]).kind == "bed"
        unit = hospital["db"].session.get(Unit, ids["unit"])
        assert (unit.name, unit.kind) == ("العناية", "ward")


def test_the_units_cost_centre_follows_unless_the_clinic_renamed_it(hospital):
    from app.utils import cost_centres
    from app.models.place import Unit

    ids = _ids(hospital)
    with hospital["app"].app_context():
        centre = cost_centres.for_unit(hospital["db"].session.get(Unit, ids["unit"]))
        hospital["db"].session.commit()
        centre_id = centre.id
    _rename(hospital, "unit", ids["unit"], "الباطنة")
    from app.models import CostCentre

    with hospital["app"].app_context():
        row = hospital["db"].session.get(CostCentre, centre_id)
        assert row.name_ar == "الباطنة"
        row.name_ar = "مركز الباطنة"            # the clinic's own name for it
        hospital["db"].session.commit()
    _rename(hospital, "unit", ids["unit"], "الداخلي ٢")
    with hospital["app"].app_context():
        assert hospital["db"].session.get(CostCentre, centre_id).name_ar == "مركز الباطنة"


def test_an_empty_name_is_refused(hospital):
    from app.models.place import Bed

    ids = _ids(hospital)
    _rename(hospital, "bed", ids["bed"], "   ")
    with hospital["app"].app_context():
        assert hospital["db"].session.get(Bed, ids["bed"]).name == "د١"


def test_only_the_owner_renames(hospital):
    from app.models.place import Unit

    ids = _ids(hospital)
    # A doctor works the beds screens; building and naming them is the
    # owner's, as adding and deleting always were.
    assert hospital["sign_in"]("doc").get("/beds/").status_code == 200
    reply = _rename(hospital, "unit", ids["unit"], "x", who="doc")
    assert reply.status_code == 403
    with hospital["app"].app_context():
        assert hospital["db"].session.get(Unit, ids["unit"]).name == "الداخلي"


def test_the_setup_screen_offers_it_on_every_level(hospital):
    _admit(hospital, _child(hospital, "شاشة"))
    ids = _ids(hospital)
    page = hospital["sign_in"]("boss").get("/beds/setup").get_data(as_text=True)
    for level in ("unit", "space", "bed"):
        assert f'data-rename-{level}="{ids[level]}"' in page
    # No delete button for a unit a child is in — and the screen says why.
    assert f'data-delete-unit="{ids["unit"]}"' not in page
    assert f'data-why-kept-unit="{ids["unit"]}"' in page
