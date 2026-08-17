"""Marking the services a doctor actually performs.

Asked for in these words: mark the services a doctor provides so they are not
lost among services that do not exist for them. A clinic's catalogue grows to
cover everybody — nebuliser sessions, spirometry, a dozen lab panels — and
each doctor does a handful. The rest sit in front of the one they want, every
visit, all day.

**The rule this file exists to hold still: a doctor nobody has marked performs
everything.** Silence means "nobody has filled this in", never "provides
nothing". Read the other way round, the morning a clinic upgrades every
service list on every screen would come up empty, with patients in the room.
That failure is silent, total, and arrives without anybody having touched a
setting — which is why the rule lives in one function and is tested from both
ends here.

**Nothing is hidden.** Marked services come first, the rest stay in the list
under a heading. The complaint was about hunting, so the fix is order, not
permission — somebody covering an unusual case must not meet a wall built out
of a convenience feature.

The link table already existed: ``DoctorServiceCommission`` is the doctor–
service pairing with a unique constraint on it, so this is a column and a rule
rather than a second table to keep in step.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# The fixture dates its visit with `local_today()`, so this has to ask the
# same clock. `date.today()` is UTC and the clinic runs on Cairo time; after
# 21:00 UTC they are different days, and the guard below fired on the drift
# it exists to rule out.
from app.utils.clock import local_today  # noqa: E402

import pytest  # noqa: E402


def _mark(clinic, service_id, provides=True, doctor_id=None):
    with clinic["app"].app_context():
        from app.models import DoctorServiceCommission
        db = clinic["db"]
        db.session.add(DoctorServiceCommission(
            doctor_id=doctor_id or clinic["ids"]["doctor"],
            service_id=service_id, provides=provides))
        db.session.commit()


def _services(clinic):
    with clinic["app"].app_context():
        from app.models import Service
        return Service.query.order_by(Service.id).all()


# --- the rule -------------------------------------------------------------

def test_a_doctor_nobody_has_marked_performs_everything(clinic):
    """The failure this module exists to make impossible.

    If an empty set meant "provides nothing", the day this shipped every
    service list in the clinic would be empty — with no setting changed and
    nothing on screen to explain it.
    """
    with clinic["app"].app_context():
        from app.models import Service, User
        from app.utils.doctor_services import split

        db = clinic["db"]
        doctor = db.session.get(User, clinic["ids"]["doctor"])
        every = Service.query.all()
        mine, others = split(doctor, every)

        assert len(mine) == len(every), "an unmarked doctor lost their services"
        assert others == []


def test_marking_one_service_puts_the_rest_second(clinic):
    _mark(clinic, clinic["ids"]["nebul"])
    with clinic["app"].app_context():
        from app.models import User
        from app.utils.doctor_services import split

        db = clinic["db"]
        doctor = db.session.get(User, clinic["ids"]["doctor"])
        mine, others = split(doctor, _services(clinic))

        assert [s.id for s in mine] == [clinic["ids"]["nebul"]]
        assert clinic["ids"]["exam"] in [s.id for s in others]


def test_nothing_is_dropped_by_the_split(clinic):
    """Order, not permission. Every service is still in one of the two lists."""
    _mark(clinic, clinic["ids"]["nebul"])
    with clinic["app"].app_context():
        from app.models import User
        from app.utils.doctor_services import split

        db = clinic["db"]
        doctor = db.session.get(User, clinic["ids"]["doctor"])
        every = _services(clinic)
        mine, others = split(doctor, every)

        assert sorted(s.id for s in mine + others) == sorted(s.id for s in every)


def test_a_row_that_exists_but_says_no_is_not_a_mark(clinic):
    """A commission override is not a statement about who performs what.

    The same table carries both, so a doctor priced for a service they do not
    perform must not be counted as performing it.
    """
    _mark(clinic, clinic["ids"]["nebul"], provides=False)
    with clinic["app"].app_context():
        from app.models import User
        from app.utils.doctor_services import has_marks, split

        db = clinic["db"]
        doctor = db.session.get(User, clinic["ids"]["doctor"])
        assert has_marks(doctor) is False
        mine, others = split(doctor, _services(clinic))
        assert others == [], "a price override was read as a mark"


def test_one_doctors_marks_are_not_anothers(clinic):
    _mark(clinic, clinic["ids"]["nebul"], doctor_id=clinic["ids"]["admin"])
    with clinic["app"].app_context():
        from app.models import User
        from app.utils.doctor_services import has_marks

        db = clinic["db"]
        assert has_marks(db.session.get(User, clinic["ids"]["admin"])) is True
        assert has_marks(db.session.get(User, clinic["ids"]["doctor"])) is False


@pytest.mark.parametrize("doctor", [None])
def test_no_doctor_at_all_is_not_a_crash(clinic, doctor):
    """A visit with no doctor assigned still has to draw its service list."""
    with clinic["app"].app_context():
        from app.utils.doctor_services import split

        mine, others = split(doctor, _services(clinic))
        assert others == []
        assert len(mine) == len(_services(clinic))


# --- saving the mark ------------------------------------------------------

def test_ticking_performs_at_the_clinic_price_survives_the_save(clinic):
    """The bug the old delete condition would have caused.

    A doctor who performs a service at the clinic's own price sets no
    commission and no price override, and the row was deleted on save when
    both were empty — so the tick would have vanished on the redirect and the
    feature would have looked broken from the first minute.
    """
    admin = clinic["sign_in"]("boss")
    nebul = clinic["ids"]["nebul"]
    doctor_id = clinic["ids"]["doctor"]

    response = admin.post(f"/users/doctors/{doctor_id}/pricing",
                          data={f"provides_{nebul}": "1"},
                          follow_redirects=True)
    assert response.status_code == 200

    with clinic["app"].app_context():
        from app.models import DoctorServiceCommission

        row = DoctorServiceCommission.query.filter_by(
            doctor_id=doctor_id, service_id=nebul).first()
        assert row is not None, "the tick was deleted on save"
        assert row.provides is True
        assert row.price_override is None, "a price was invented"
        assert row.commission_type == "none"


def test_unticking_removes_the_mark(clinic):
    """It has to be reversible, or a mistake is permanent."""
    admin = clinic["sign_in"]("boss")
    nebul = clinic["ids"]["nebul"]
    doctor_id = clinic["ids"]["doctor"]

    admin.post(f"/users/doctors/{doctor_id}/pricing",
               data={f"provides_{nebul}": "1"}, follow_redirects=True)
    admin.post(f"/users/doctors/{doctor_id}/pricing", data={},
               follow_redirects=True)

    with clinic["app"].app_context():
        from app.models import DoctorServiceCommission

        row = DoctorServiceCommission.query.filter_by(
            doctor_id=doctor_id, service_id=nebul).first()
        assert row is None or row.provides is False


def test_the_mark_does_not_wipe_an_existing_commission(clinic):
    """The two live in one row and must not overwrite each other."""
    admin = clinic["sign_in"]("boss")
    nebul = clinic["ids"]["nebul"]
    doctor_id = clinic["ids"]["doctor"]

    admin.post(f"/users/doctors/{doctor_id}/pricing",
               data={f"provides_{nebul}": "1", f"type_{nebul}": "percent",
                     f"value_{nebul}": "30", f"price_{nebul}": "120"},
               follow_redirects=True)

    with clinic["app"].app_context():
        from app.models import DoctorServiceCommission

        row = DoctorServiceCommission.query.filter_by(
            doctor_id=doctor_id, service_id=nebul).first()
        assert row.provides is True
        assert row.commission_type == "percent"
        assert row.commission_value == 30
        assert row.price_override == 120


# --- the screen -----------------------------------------------------------

def test_the_visit_screen_groups_by_who_performs_what(clinic):
    """Grouped rather than filtered, and only once somebody has marked."""
    with clinic["app"].app_context():
        from app.models import Service
        db = clinic["db"]
        proc = Service(name="جلسة تنفس ٢", category="procedure", price=100,
                       is_active=True)
        db.session.add(proc)
        db.session.commit()
        proc_id = proc.id

    doc = clinic["sign_in"]("doc")
    visit_id = clinic["ids"]["visit"]

    before = doc.get(f"/visits/{visit_id}/record").get_data(as_text=True)
    assert "<optgroup" not in before, (
        "an unmarked clinic is being shown groupings it never asked for")

    _mark(clinic, proc_id)
    after = doc.get(f"/visits/{visit_id}/record").get_data(as_text=True)
    assert "<optgroup" in after
    assert "خدمات أخرى" in after, "the unmarked services lost their heading"


def test_the_unmarked_services_are_still_choosable(clinic):
    """The wall that must not exist."""
    with clinic["app"].app_context():
        from app.models import Service
        db = clinic["db"]
        mine = Service(name="سبيرومتري", category="procedure", price=100,
                       is_active=True)
        theirs = Service(name="تخطيط قلب", category="procedure", price=90,
                         is_active=True)
        db.session.add_all([mine, theirs])
        db.session.commit()
        mine_id, theirs_id = mine.id, theirs.id

    _mark(clinic, mine_id)
    body = (clinic["sign_in"]("doc").get(f"/visits/{clinic['ids']['visit']}/record")
            .get_data(as_text=True))
    assert f'value="{theirs_id}"' in body, (
        "a service this doctor has not been marked for cannot be picked at all")
    assert f'value="{mine_id}"' in body


def test_the_list_follows_the_visits_doctor_not_the_viewer(clinic):
    """An admin opening Dr X's visit is choosing from Dr X's list.

    The admin is the discriminator here because they have no marks of their
    own: if the split read the logged-in user, there would be no grouping on
    the page at all.

    (Reception cannot be used for this — the record screen is clinical and
    returns 403 to them, which is correct and not what this is about.)
    """
    with clinic["app"].app_context():
        from app.models import Service
        db = clinic["db"]
        svc = Service(name="مسح سمعي", category="procedure", price=150,
                      is_active=True)
        db.session.add(svc)
        db.session.commit()
        svc_id = svc.id

    _mark(clinic, svc_id)                       # marked for the visit's doctor
    response = clinic["sign_in"]("boss").get(
        f"/visits/{clinic['ids']['visit']}/record")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "<optgroup" in body, (
        "the admin sees an ungrouped list, so the split followed the viewer "
        "rather than the visit's doctor")


# --- the upgrade ----------------------------------------------------------

def test_an_existing_clinic_gets_the_column_switched_off():
    """It has to arrive as 0 — every doctor unmarked, every list unchanged."""
    from app.utils.schema import ADDITIONS

    ddl = next(d for t, n, d in ADDITIONS
               if t == "doctor_service_commissions" and n == "provides")
    assert "0" in ddl, f"provides arrives as {ddl!r}"


def test_the_marking_column_is_on_the_doctor_screen(clinic):
    admin = clinic["sign_in"]("boss")
    body = admin.get(f"/users/doctors/{clinic['ids']['doctor']}").get_data(as_text=True)
    assert "provides_" in body, "there is no way to mark anything"
    assert "بيقدمها" in body


def test_the_screen_says_what_no_ticks_means(clinic):
    """An admin looking at an empty column must not read it as "none"."""
    admin = clinic["sign_in"]("boss")
    body = admin.get(f"/users/doctors/{clinic['ids']['doctor']}").get_data(as_text=True)
    assert "الخدمات كلها" in body


def test_the_visit_date_is_unaffected(clinic):
    """Guard against the fixture drifting under these tests."""
    with clinic["app"].app_context():
        from app.models import Visit
        visit = clinic["db"].session.get(Visit, clinic["ids"]["visit"])
        assert visit.visit_date == local_today()


# --- booking, where the doctor is chosen in the same form ------------------

def test_the_booking_screens_carry_the_marks_for_the_browser(clinic):
    """Booking is where this matters most, and where a server split cannot work.

    The doctor is picked in the same form as the services, so the list has to
    reorder as that choice changes. The page therefore carries the map rather
    than a pre-split list.
    """
    _mark(clinic, clinic["ids"]["nebul"])
    desk = clinic["sign_in"]("desk")

    import json
    import re

    for url in ("/appointments/new", "/appointments/"):
        body = desk.get(url).get_data(as_text=True)
        found = re.search(r"marks:\s*(\{.*?\}),", body, re.S)
        assert found, f"{url} carries no marks map"
        # Parsed rather than searched for as a substring: every service id is
        # already on the page as a checkbox value, so "the id appears
        # somewhere" would pass with an empty map.
        marks = json.loads(found.group(1))
        assert marks.get(str(clinic["ids"]["doctor"])) == [clinic["ids"]["nebul"]], (
            f"{url} sent {marks!r}")


def test_an_unmarked_clinic_gets_an_empty_map(clinic):
    """Absent means "nobody has said" — the list must be left alone."""
    body = clinic["sign_in"]("desk").get("/appointments/new").get_data(as_text=True)
    assert "marks: {}" in body, "an unmarked clinic is being sent marks"


def test_the_map_is_keyed_by_doctor(clinic):
    from app.utils.doctor_services import marks_map

    _mark(clinic, clinic["ids"]["nebul"])
    _mark(clinic, clinic["ids"]["exam"], doctor_id=clinic["ids"]["admin"])
    with clinic["app"].app_context():
        found = marks_map()
        assert found[clinic["ids"]["doctor"]] == [clinic["ids"]["nebul"]]
        assert found[clinic["ids"]["admin"]] == [clinic["ids"]["exam"]]


def test_a_doctor_who_said_no_is_not_in_the_map(clinic):
    from app.utils.doctor_services import marks_map

    _mark(clinic, clinic["ids"]["nebul"], provides=False)
    with clinic["app"].app_context():
        assert marks_map() == {}


def test_every_service_is_still_offered_at_booking(clinic):
    """Ordering only. A marked doctor must not lose the rest of the catalogue."""
    _mark(clinic, clinic["ids"]["nebul"])
    body = clinic["sign_in"]("desk").get("/appointments/new").get_data(as_text=True)
    assert f'value="{clinic["ids"]["exam"]}"' in body, (
        "an unmarked service vanished from the booking form")
