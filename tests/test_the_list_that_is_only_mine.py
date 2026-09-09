"""One person's theatre day, out of everybody's.

The day list is grouped by room because whoever runs the theatres is asking
"what is theatre two doing at eleven". A surgeon and an anaesthetist are asking
something else — *"ليست للجراح وطبيب التخدير"* — and reading twenty cases to
find their four is how somebody stops reading the list at all.

**Either role counts.** They read the same day for different reasons, and a
filter that answered only "cases I am cutting" would hand the anaesthetist
somebody else's list and call it theirs.

Two things this file exists to stop, both of them mistakes made while writing
it and caught before they shipped:

* **the booking form losing rooms** — its picker looped the same filtered list,
  so a doctor on their own list could only book into rooms they already had a
  case in
* **"you have no cases" reading as "this clinic has no theatres"** — the empty
  screen told people to go and build a room, which is the program answering a
  question nobody asked
"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def hospital():
    """Two rooms, two doctors, three cases — one each and one they share."""
    from app import create_app
    from app.extensions import db

    app = create_app("testing")
    with app.app_context():
        db.create_all()
        from app.models import Patient, Setting, User
        from app.models.theatre import Operation, Theatre

        Setting.set("mod_enabled:theatres", "1")
        ids = {}
        # `idle` has no case today, and exists only to be absent from the
        # picker. Without somebody like them, "only the people operating" and
        # "every doctor in the clinic" are the same list and the test cannot
        # tell them apart — which is exactly what a mutation proved.
        for username, name in (("cutter", "د. الجرّاح"), ("gas", "د. المخدِّر"),
                               ("other", "د. تاني"), ("idle", "د. مش شغّال")):
            u = User(username=username, full_name=name, role="doctor",
                     is_active=True)
            u.set_password("secret")
            db.session.add(u)
            db.session.flush()
            ids[username] = u.id

        one = Theatre(name="غرفة ١", sort_order=1)
        two = Theatre(name="غرفة ٢", sort_order=2)
        db.session.add_all([one, two])
        db.session.flush()
        ids["room1"], ids["room2"] = one.id, two.id

        today = date.today()
        for n, (room, proc, surgeon, gas) in enumerate((
                (one, "لوز", ids["cutter"], ids["gas"]),      # both of them
                (one, "ختان", ids["cutter"], None),           # the surgeon only
                (two, "فتق", ids["other"], ids["gas"]),       # the anaesthetist only
        ), start=1):
            child = Patient(patient_number=f"P{n}", full_name=f"طفل {n}",
                            date_of_birth=date(2022, 1, 1), gender="male")
            db.session.add(child)
            db.session.flush()
            db.session.add(Operation(
                patient_id=child.id, theatre_id=room.id, procedure=proc,
                on_date=today, status="scheduled",
                surgeon_id=surgeon, anaesthetist_id=gas))
        db.session.commit()

    def sign_in(username="cutter"):
        client = app.test_client()
        client.post("/login", data={"username": username, "password": "secret"},
                    follow_redirects=True)
        return client

    return {"app": app, "db": db, "ids": ids, "sign_in": sign_in}


def _procedures(rooms):
    return {op["operation"].procedure
            for room in rooms for op in room["operations"]}


# ------------------------------------------------------------ whose list --
def test_the_whole_day_is_still_the_whole_day(hospital):
    from app.utils import theatres as theatre

    with hospital["app"].app_context():
        assert _procedures(theatre.day()) == {"لوز", "ختان", "فتق"}


def test_a_surgeon_sees_the_cases_they_are_cutting(hospital):
    from app.utils import theatres as theatre

    with hospital["app"].app_context():
        assert _procedures(theatre.day(who=hospital["ids"]["cutter"])) == \
            {"لوز", "ختان"}


def test_an_anaesthetist_sees_the_cases_they_are_giving(hospital):
    """**The half a surgeon-only filter would have got wrong.** The
    anaesthetist is not cutting any of these."""
    from app.utils import theatres as theatre

    with hospital["app"].app_context():
        assert _procedures(theatre.day(who=hospital["ids"]["gas"])) == \
            {"لوز", "فتق"}


def test_a_case_they_share_is_on_both_lists(hospital):
    from app.utils import theatres as theatre

    with hospital["app"].app_context():
        for who in ("cutter", "gas"):
            assert "لوز" in _procedures(theatre.day(who=hospital["ids"][who]))


def test_somebody_with_nothing_today_gets_nothing_not_everything(hospital):
    """An empty filter that fell back to the whole day would be worse than no
    filter: it would look like it worked."""
    from app.utils import theatres as theatre

    with hospital["app"].app_context():
        assert theatre.day(who=hospital["ids"]["other"] + 999) == []


def test_rooms_with_none_of_their_cases_drop_out(hospital):
    """A filter that leaves five empty rooms behind has not filtered
    anything."""
    from app.utils import theatres as theatre

    with hospital["app"].app_context():
        rooms = theatre.day(who=hospital["ids"]["cutter"])
        assert len(rooms) == 1
        assert rooms[0]["theatre"].name == "غرفة ١"


def test_but_the_whole_day_keeps_its_empty_rooms(hospital):
    """An idle theatre is a fact about the day, and whoever runs the list wants
    to see it. Only *one person's* list drops them."""
    from app.models.theatre import Theatre
    from app.utils import theatres as theatre

    with hospital["app"].app_context():
        hospital["db"].session.add(Theatre(name="غرفة ٣", sort_order=3))
        hospital["db"].session.commit()
        assert len(theatre.day()) == 3
        assert any(not r["operations"] for r in theatre.day())


# ---------------------------------------------------------- the dropdown --
def test_the_picker_lists_only_who_is_operating_today(hospital):
    """Forty names to find the two who are on today is the kind of picker
    somebody stops using."""
    from app.utils import theatres as theatre

    with hospital["app"].app_context():
        on = {p.id for p in theatre.people_on()}
        assert on == {hospital["ids"]["cutter"], hospital["ids"]["gas"],
                      hospital["ids"]["other"]}
        # The one that matters: a doctor with nothing on today is not offered.
        assert hospital["ids"]["idle"] not in on


def test_somebody_with_two_cases_appears_once(hospital):
    from app.utils import theatres as theatre

    with hospital["app"].app_context():
        people = theatre.people_on()
        assert len(people) == len({p.id for p in people})


# ------------------------------------------------------------ the screen --
def test_my_list_shortens_the_page(hospital):
    client = hospital["sign_in"]("cutter")
    everybody = client.get("/theatres/").get_data(as_text=True)
    mine = client.get("/theatres/?mine=1").get_data(as_text=True)
    assert "فتق" in everybody
    assert "فتق" not in mine, "somebody else's case is on my list"
    assert "ختان" in mine


def test_picking_a_person_works_from_the_dropdown(hospital):
    html = hospital["sign_in"]().get(
        f"/theatres/?who={hospital['ids']['gas']}").get_data(as_text=True)
    assert "فتق" in html and "ختان" not in html


# ------------------------------- the two mistakes this file was written for --
def test_the_booking_form_still_offers_every_room(hospital):
    """**Caught while writing this.** The room picker looped the same filtered
    list, so a doctor on their own list could only book into rooms they
    already had a case in — the filter quietly narrowing something it has no
    business touching."""
    html = hospital["sign_in"]("cutter").get(
        "/theatres/?mine=1").get_data(as_text=True)
    assert "غرفة ٢" in html, "the booking form lost a room to the filter"


def test_no_cases_today_does_not_say_go_build_a_theatre(hospital):
    """**The other one.** Empty meant "this clinic has no theatres" before the
    filter existed, and afterwards it also means "you have nothing on". One
    sentence for two facts, telling a doctor to go and build a room because
    their morning is free."""
    from app.i18n import t

    client = hospital["sign_in"]("other")
    html = client.get("/theatres/?who=99999").get_data(as_text=True)
    with hospital["app"].test_request_context("/"):
        assert t("theatre.no_rooms") not in html
        assert t("theatre.mine_none") in html or t("theatre.person_none") in html


def test_and_it_still_says_it_when_there_really_are_no_rooms(hospital):
    """The original sentence has to survive — it is the one door out of an
    empty module."""
    from app.i18n import t

    from app.models.theatre import Operation, Theatre

    with hospital["app"].app_context():
        Operation.query.delete()
        Theatre.query.delete()
        hospital["db"].session.commit()

    html = hospital["sign_in"]().get("/theatres/").get_data(as_text=True)
    with hospital["app"].test_request_context("/"):
        assert t("theatre.no_rooms") in html


def test_the_picker_is_not_just_the_staff_list(hospital):
    """**Caught by measurement.** Replacing `people_on` with "every active
    user" left all fourteen tests green, because every doctor in the fixture
    happened to be operating. Asserted on the rendered page as well as the
    helper — the dropdown is where somebody actually meets this."""
    from app.models import User

    with hospital["app"].app_context():
        idle = User.query.filter_by(username="idle").first().full_name

    html = hospital["sign_in"]().get("/theatres/").get_data(as_text=True)
    picker = html.split('name="who"')[1].split("</select>")[0]
    assert idle not in picker, "a doctor with no case today is in the picker"
    assert "د. الجرّاح" in picker
