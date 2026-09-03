"""A child who is here until Thursday, in a program whose visit is one day.

أساس ٢ of ``HOSPITAL_PLAN.md``, asked for in two words: *"ابدأ في الإقامة
والسرير"*.

``Visit.visit_date`` is a ``Date``. That is right for an outpatient — they
come, they are seen, they go home, and the encounter belongs to a date. A stay
runs across days, ends in a decision, and at every hour of it the child is in
a *place*. None of that fits in a date column, and widening the visit would
have put three meaningless columns on every outpatient consultation.

The shape of the place came from the floor, not from a diagram:

    "الطوارئ بيبقوا شغالين بارتشن بيتسكن فيه السرير، والداخلي غرفة بيتسكن فيها
     سرير، وفي العناية فيه عزل لوحده وبيبقى فيه ٢ او ١ بارتشن عزل والباقي سرير
     تقريباً، والحضانة فيه سرير وفيه حضانة وفيه كبسولة."

Which is why the middle level is a **space** and not a room, why isolation is
a property of the space rather than a kind of its own or a flag on a bed, and
why the incubator unit holds three kinds of bed at once.

The rule this file exists to hold: **occupancy is counted, never stored.**
"""
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

MODULE = "beds"


@pytest.fixture()
def ward(clinic):
    """A small hospital: emergency partitions, a nursery bay, an ICU with one
    isolation partition — the layout as it was described."""
    from app.models import Bed, Setting, Space, Unit

    with clinic["app"].app_context():
        Setting.set(f"mod_enabled:{MODULE}", "1")
        db = clinic["db"]

        made = {}
        er = Unit(name="الطوارئ", kind="emergency", sort_order=0)
        nicu = Unit(name="الحضّانات", kind="nicu", sort_order=1)
        icu = Unit(name="العناية", kind="icu", sort_order=2)
        db.session.add_all([er, nicu, icu])
        db.session.flush()

        # Emergency: one bed per partition, which is what makes crowding
        # countable as "every partition occupied".
        for i in (1, 2):
            space = Space(unit_id=er.id, name=f"بارتشن {i}", kind="partition",
                          sort_order=i)
            db.session.add(space)
            db.session.flush()
            bed = Bed(space_id=space.id, name=f"سرير {i}", kind="trolley")
            db.session.add(bed)
            db.session.flush()
            made[f"er{i}"] = bed.id

        # The nursery: one bay, three kinds of bed in it.
        bay = Space(unit_id=nicu.id, name="صالة الحضّانات", kind="bay")
        db.session.add(bay)
        db.session.flush()
        for kind, name in (("cot", "سرير ١"), ("incubator", "حضّانة ١"),
                           ("capsule", "كبسولة")):
            bed = Bed(space_id=bay.id, name=name, kind=kind)
            db.session.add(bed)
            db.session.flush()
            made[kind] = bed.id

        # Intensive care: an open bay, and one isolation partition beside it.
        open_bay = Space(unit_id=icu.id, name="الصالة", kind="bay")
        iso = Space(unit_id=icu.id, name="بارتشن العزل", kind="partition",
                    is_isolation=True, sort_order=1)
        db.session.add_all([open_bay, iso])
        db.session.flush()
        for space, name, key in ((open_bay, "سرير عناية ١", "icu1"),
                                 (iso, "سرير العزل", "isolation")):
            bed = Bed(space_id=space.id, name=name, kind="bed")
            db.session.add(bed)
            db.session.flush()
            made[key] = bed.id
        db.session.commit()

    clinic["beds"] = made
    return clinic


def _admit(clinic, bed_key, patient_id=None):
    from app.models import Bed, Patient
    from app.utils import beds as ward_utils

    child = patient_id or clinic["ids"]["child"]
    patient = Patient.query.get(child)
    bed = Bed.query.get(clinic["beds"][bed_key])
    row = ward_utils.admit(patient, bed)
    clinic["db"].session.commit()
    return row


# --------------------------------------------------- the shape of a place ---
def test_a_visit_is_still_one_day_and_a_stay_is_not():
    """The reason this exists at all, held in place: the outpatient visit is
    not widened to carry a stay."""
    from app.models import Admission, Visit

    assert Visit.__table__.c.visit_date.type.python_type.__name__ == "date"
    for column in ("admitted_at", "discharged_at"):
        assert Admission.__table__.c[column].type.python_type.__name__ \
            == "datetime"


def test_isolation_belongs_to_the_space_and_not_to_the_bed():
    """A bay with six beds and one of them marked "isolated" is information
    that lies — there is no wall around it."""
    from app.models import Bed, Space

    assert "is_isolation" in Space.__table__.c
    assert "is_isolation" not in Bed.__table__.c


def test_a_bed_reads_its_isolation_from_the_space_it_stands_in(ward):
    from app.models import Bed

    with ward["app"].app_context():
        assert Bed.query.get(ward["beds"]["isolation"]).is_isolation
        assert not Bed.query.get(ward["beds"]["icu1"]).is_isolation


def test_nothing_stores_whether_a_bed_is_free():
    """The whole rule, as a guard. A flag is one forgotten discharge away from
    a ward that reports itself full with three beds standing empty."""
    from app.models import Bed

    for column in Bed.__table__.c.keys():
        assert "occupied" not in column and "is_free" not in column


def test_the_nursery_holds_three_kinds_of_bed_at_once(ward):
    """Cot, incubator and transport capsule — which is why the kind is on the
    bed and not on the unit."""
    from app.models import Bed

    with ward["app"].app_context():
        kinds = {Bed.query.get(ward["beds"][k]).kind
                 for k in ("cot", "incubator", "capsule")}
        assert kinds == {"cot", "incubator", "capsule"}


# ------------------------------------------------------------- occupancy ---
def test_a_bed_is_free_until_somebody_is_in_it(ward):
    from app.utils import beds as ward_utils

    with ward["app"].app_context():
        assert ward_utils.counts()["taken"] == 0
        _admit(ward, "er1")
        assert ward_utils.counts()["taken"] == 1
        assert ward["beds"]["er1"] in ward_utils.occupied_bed_ids()


def test_discharging_frees_the_bed_with_no_second_thing_to_update(ward):
    from app.utils import beds as ward_utils

    with ward["app"].app_context():
        admission = _admit(ward, "er1")
        ward_utils.discharge(admission, "home")
        ward["db"].session.commit()

        assert ward_utils.counts()["taken"] == 0
        assert ward["beds"]["er1"] not in ward_utils.occupied_bed_ids()
        assert not admission.is_open


def test_two_children_cannot_be_put_in_one_bed(ward):
    """Checked in the code and not only on the screen: the list of free beds
    was drawn seconds ago, and a ward fills up between a page loading and a
    button being pressed."""
    from app.models import Bed, Patient
    from app.utils import beds as ward_utils

    with ward["app"].app_context():
        _admit(ward, "er1")
        other = Patient(patient_number="P2", full_name="طفلة", gender="female",
                        date_of_birth=datetime(2024, 1, 1).date(),
                        is_active=True)
        ward["db"].session.add(other)
        ward["db"].session.commit()

        with pytest.raises(ward_utils.BedTaken):
            ward_utils.admit(other, Bed.query.get(ward["beds"]["er1"]))


def test_one_child_cannot_be_admitted_twice(ward):
    from app.models import Bed, Patient
    from app.utils import beds as ward_utils

    with ward["app"].app_context():
        _admit(ward, "er1")
        with pytest.raises(ward_utils.BedTaken):
            ward_utils.admit(Patient.query.get(ward["ids"]["child"]),
                             Bed.query.get(ward["beds"]["er2"]))


def test_a_bed_out_of_service_takes_nobody(ward):
    from app.models import Bed, Patient
    from app.utils import beds as ward_utils

    with ward["app"].app_context():
        bed = Bed.query.get(ward["beds"]["er1"])
        bed.is_active = False
        ward["db"].session.commit()
        with pytest.raises(ward_utils.BedTaken):
            ward_utils.admit(Patient.query.get(ward["ids"]["child"]), bed)


def test_an_isolation_bed_is_found_by_asking_for_one(ward):
    """The question is asked at the worst possible moment — an infectious
    child at the door — and it is answered from the space."""
    from app.utils import beds as ward_utils

    with ward["app"].app_context():
        free = ward_utils.free_beds(isolation=True)
        assert [b.id for b in free] == [ward["beds"]["isolation"]]

        _admit(ward, "isolation")
        assert ward_utils.free_beds(isolation=True) == []


# ------------------------------------------------------------ moving ------
def test_moving_keeps_the_hours_the_child_spent_in_the_old_bed(ward):
    """Overwriting the bed would answer "where are they now" and silently
    rewrite every earlier day of the stay — which is the question infection
    control asks afterwards."""
    from app.models import Bed
    from app.utils import beds as ward_utils

    with ward["app"].app_context():
        admission = _admit(ward, "icu1")
        first = admission.current_stay
        started = first.since

        ward_utils.move(admission, Bed.query.get(ward["beds"]["isolation"]),
                        note="مخالطة")
        ward["db"].session.commit()

        stays = admission.stays
        assert len(stays) == 2
        assert stays[0].bed_id == ward["beds"]["icu1"]
        assert stays[0].since == started and stays[0].until is not None
        assert stays[1].bed_id == ward["beds"]["isolation"]
        assert stays[1].is_open
        # And the bed they left is free again, counted the same way.
        assert ward["beds"]["icu1"] not in ward_utils.occupied_bed_ids()


def test_a_move_to_an_occupied_bed_is_refused(ward):
    from app.models import Bed, Patient
    from app.utils import beds as ward_utils

    with ward["app"].app_context():
        mine = _admit(ward, "er1")
        other = Patient(patient_number="P3", full_name="طفل تاني",
                        gender="male",
                        date_of_birth=datetime(2024, 1, 1).date(),
                        is_active=True)
        ward["db"].session.add(other)
        ward["db"].session.commit()
        ward_utils.admit(other, Bed.query.get(ward["beds"]["er2"]))
        ward["db"].session.commit()

        with pytest.raises(ward_utils.BedTaken):
            ward_utils.move(mine, Bed.query.get(ward["beds"]["er2"]))


def test_a_capsule_leaving_the_unit_does_not_end_the_stay(ward):
    """The baby goes to X-ray in the capsule, which *is* their bed. The stay
    ends when somebody discharges them, not when they leave the room — which
    is why a stay hangs off the bed and not off the space."""
    from app.utils import beds as ward_utils

    with ward["app"].app_context():
        admission = _admit(ward, "capsule")
        assert admission.is_open
        assert ward_utils.counts()["taken"] == 1
        assert admission.bed.kind == "capsule"


# ------------------------------------------------------------- the board ---
def test_the_board_counts_free_and_taken_from_the_stays(ward):
    from app.utils import beds as ward_utils

    with ward["app"].app_context():
        _admit(ward, "er1")
        rows = {row["unit"].kind: row for row in ward_utils.board()}
        assert rows["emergency"]["taken"] == 1
        assert rows["emergency"]["free"] == 1
        assert rows["nicu"]["taken"] == 0 and rows["nicu"]["free"] == 3


def test_a_bed_out_of_service_is_in_neither_count(ward):
    """It is not free — nobody can be put in it — and it is not occupied.
    Counting it as either would misreport the ward in one direction or the
    other."""
    from app.models import Bed
    from app.utils import beds as ward_utils

    with ward["app"].app_context():
        Bed.query.get(ward["beds"]["er1"]).is_active = False
        ward["db"].session.commit()
        rows = {row["unit"].kind: row for row in ward_utils.board()}
        assert rows["emergency"]["free"] == 1
        assert rows["emergency"]["taken"] == 0
        assert ward_utils.counts()["total"] == 6      # seven beds, one shut


def test_the_board_does_not_ask_once_per_bed(ward):
    """A hospital with sixty beds costs what one with seven costs. Measured as
    a comparison between two sizes rather than against a guessed ceiling."""
    from sqlalchemy import event
    from sqlalchemy.engine import Engine

    from app.models import Bed, Space
    from app.utils import beds as ward_utils

    def cost():
        seen = []

        def record(conn, cursor, statement, params, context, many):
            seen.append(statement)

        event.listen(Engine, "before_cursor_execute", record)
        try:
            rows = ward_utils.board()
        finally:
            event.remove(Engine, "before_cursor_execute", record)
        return sum(len(b["beds"]) for r in rows for b in r["spaces"]), len(seen)

    with ward["app"].app_context():
        ward_utils.board()                 # nothing measured pays for warm-up
        small_beds, small_queries = cost()

        space = Space.query.first()
        for i in range(40):
            ward["db"].session.add(
                Bed(space_id=space.id, name=f"سرير إضافي {i}", kind="bed"))
        ward["db"].session.commit()

        big_beds, big_queries = cost()

    assert big_beds == small_beds + 40
    assert big_queries == small_queries, (
        f"{small_queries} queries for {small_beds} beds and {big_queries} for "
        f"{big_beds} — something is querying inside the loop")


# ------------------------------------------------------------ the module ---
def test_the_module_is_off_until_a_clinic_asks_for_it(clinic):
    from app.utils.facility import OPT_IN_MODULES

    assert MODULE in OPT_IN_MODULES
    assert clinic["sign_in"]("boss").get("/beds/").status_code == 404


def test_a_clinic_that_says_it_has_a_ward_gets_the_beds(clinic):
    """The wizard, not a second switch to find afterwards."""
    from app.utils.facility import apply_facility, derive_modules, module_enabled

    for capability in ("ward", "nicu", "icu", "emergency_care", "day_care"):
        assert MODULE in derive_modules([capability]), capability

    with clinic["app"].app_context():
        apply_facility("hospital", "مستشفى", ["ward"], derive_modules(["ward"]))
        clinic["db"].session.commit()
        assert module_enabled(MODULE)


def test_an_outpatient_clinic_does_not_get_them(clinic):
    from app.utils.facility import apply_facility, derive_modules, module_enabled

    caps = ["general_consultation", "followup", "vaccination"]
    with clinic["app"].app_context():
        apply_facility("single_doctor", "عيادة", caps, derive_modules(caps))
        clinic["db"].session.commit()
        assert not module_enabled(MODULE)


# ------------------------------------------------------------ the screens --
def test_the_board_screen_shows_who_is_in_which_bed(ward):
    with ward["app"].app_context():
        _admit(ward, "er1")

    page = ward["sign_in"]("boss").get("/beds/").get_data(as_text=True)
    assert "الطوارئ" in page and "بارتشن 1" in page
    assert "طفل" in page                       # the child's name in the bed


def test_the_setup_screen_builds_a_unit_a_space_and_a_bed(ward):
    """From the screen, never from a release."""
    from app.models import Bed, Space, Unit

    client = ward["sign_in"]("boss")
    client.post("/beds/unit", data={"name": "الداخلي", "kind": "ward"},
                follow_redirects=True)
    with ward["app"].app_context():
        unit = Unit.query.filter_by(name="الداخلي").one()

    client.post(f"/beds/unit/{unit.id}/space",
                data={"name": "غرفة ١", "kind": "room"}, follow_redirects=True)
    with ward["app"].app_context():
        space = Space.query.filter_by(name="غرفة ١").one()
        assert not space.is_isolation

    client.post(f"/beds/space/{space.id}/bed",
                data={"name": "سرير الداخلي ١", "kind": "bed"},
                follow_redirects=True)
    with ward["app"].app_context():
        assert Space.query.get(space.id).beds[0].name == "سرير الداخلي ١"
        assert Bed.query.filter_by(name="سرير الداخلي ١").one().kind == "bed"


def test_a_kind_nobody_offers_builds_nothing(ward):
    from app.models import Unit

    client = ward["sign_in"]("boss")
    client.post("/beds/unit", data={"name": "قسم غريب", "kind": "spaceship"},
                follow_redirects=True)
    with ward["app"].app_context():
        assert Unit.query.filter_by(name="قسم غريب").count() == 0


def test_an_isolation_space_is_marked_as_one_when_it_is_built(ward):
    from app.models import Space, Unit

    client = ward["sign_in"]("boss")
    with ward["app"].app_context():
        unit = Unit.query.filter_by(kind="icu").one()
    client.post(f"/beds/unit/{unit.id}/space",
                data={"name": "عزل ٢", "kind": "partition", "is_isolation": "1"},
                follow_redirects=True)
    with ward["app"].app_context():
        assert Space.query.filter_by(name="عزل ٢").one().is_isolation


def test_only_the_owner_builds_the_place(ward):
    """Adding a unit is configuration, not care. A nurse moves children
    between beds; they do not decide the hospital has another ward."""
    from app.models import Unit, User

    with ward["app"].app_context():
        nurse = User(username="sister3", full_name="ممرضة", role="nursing",
                     is_active=True)
        nurse.set_password("secret")
        ward["db"].session.add(nurse)
        ward["db"].session.commit()

    refused = ward["sign_in"]("sister3").post(
        "/beds/unit", data={"name": "قسم", "kind": "ward"})
    assert refused.status_code == 403
    with ward["app"].app_context():
        assert Unit.query.filter_by(name="قسم").count() == 0


def test_admitting_from_a_screen_puts_the_child_in_the_bed(ward):
    from app.utils import beds as ward_utils

    client = ward["sign_in"]("boss")
    client.post(f"/beds/admit/{ward['ids']['child']}",
                data={"bed_id": ward["beds"]["er1"], "reason": "جفاف"},
                follow_redirects=True)

    with ward["app"].app_context():
        admission = ward_utils.open_admission(ward["ids"]["child"])
        assert admission is not None
        assert admission.bed.id == ward["beds"]["er1"]
        assert admission.reason == "جفاف"


def test_the_stay_screen_shows_every_bed_it_passed_through(ward):
    from app.models import Bed
    from app.utils import beds as ward_utils

    with ward["app"].app_context():
        admission = _admit(ward, "icu1")
        ward_utils.move(admission, Bed.query.get(ward["beds"]["isolation"]))
        ward["db"].session.commit()
        stay_id = admission.id

    page = ward["sign_in"]("boss").get(
        f"/beds/admission/{stay_id}").get_data(as_text=True)
    assert "سرير عناية ١" in page and "سرير العزل" in page


def test_discharging_from_the_screen_records_which_ending_it_was(ward):
    """"Went home" and "was moved to another hospital" look identical in a
    table that stores only a time, and they are not the same event."""
    from app.models import Admission

    with ward["app"].app_context():
        admission = _admit(ward, "er1")
        stay_id = admission.id

    ward["sign_in"]("boss").post(
        f"/beds/admission/{stay_id}/discharge",
        data={"outcome": "transferred", "note": "تحوّل لمركز قلب"},
        follow_redirects=True)

    with ward["app"].app_context():
        row = Admission.query.get(stay_id)
        assert row.outcome == "transferred"
        assert row.discharge_note == "تحوّل لمركز قلب"
        assert not row.is_open


def test_an_ending_nobody_offers_falls_back_rather_than_inventing_one(ward):
    from app.models import Admission

    with ward["app"].app_context():
        admission = _admit(ward, "er1")
        stay_id = admission.id

    ward["sign_in"]("boss").post(f"/beds/admission/{stay_id}/discharge",
                                 data={"outcome": "abducted by aliens"},
                                 follow_redirects=True)
    with ward["app"].app_context():
        assert Admission.query.get(stay_id).outcome == "home"


# --------------------------------------------------- the door from the file --
def test_the_childs_file_offers_a_bed_when_there_is_one(ward):
    """A stay that can only be started from a board is a stay nobody starts:
    the one screen where somebody is already looking at the child they mean to
    admit is the child's own file."""
    page = ward["sign_in"]("boss").get(
        f"/patients/{ward['ids']['child']}").get_data(as_text=True)
    assert f'action="/beds/admit/{ward["ids"]["child"]}"' in page
    assert 'name="bed_id"' in page


def test_the_file_shows_the_stay_once_the_child_is_in_one(ward):
    """And stops offering a second bed, which the code refuses anyway."""
    with ward["app"].app_context():
        admission = _admit(ward, "er1")
        stay_id = admission.id

    page = ward["sign_in"]("boss").get(
        f"/patients/{ward['ids']['child']}").get_data(as_text=True)
    assert f'/beds/admission/{stay_id}' in page
    assert 'name="bed_id"' not in page


def test_a_child_already_in_a_bed_costs_no_search_for_a_free_one(ward):
    """The template would not offer it anyway — but working out every free bed
    in the hospital to answer a question nobody asked is a query on every file
    of every admitted child, all day. Written after a mutation slipped: the
    template's branch hid the waste, so the waste is measured directly.
    """
    from sqlalchemy import event
    from sqlalchemy.engine import Engine

    with ward["app"].app_context():
        _admit(ward, "er1")

    seen = []

    def record(conn, cursor, statement, params, context, many):
        if "care_beds" in statement and "JOIN" in statement.upper():
            seen.append(statement)

    client = ward["sign_in"]("boss")
    event.listen(Engine, "before_cursor_execute", record)
    try:
        client.get(f"/patients/{ward['ids']['child']}")
    finally:
        event.remove(Engine, "before_cursor_execute", record)
    assert not seen, "the free-bed search ran for a child who is already in one"


def test_the_file_says_nothing_about_beds_when_the_module_is_off(clinic):
    """Rule one: a module that is off is absent, not disabled."""
    page = clinic["sign_in"]("boss").get(
        f"/patients/{clinic['ids']['child']}").get_data(as_text=True)
    assert "/beds/" not in page


def test_a_file_costs_no_extra_query_when_the_module_is_off(clinic):
    """The context is asked for only where there are beds. A query per patient
    file for a module nobody switched on is work for nothing."""
    from sqlalchemy import event
    from sqlalchemy.engine import Engine

    seen = []

    def record(conn, cursor, statement, params, context, many):
        if "care_beds" in statement or "admissions" in statement:
            seen.append(statement)

    client = clinic["sign_in"]("boss")
    event.listen(Engine, "before_cursor_execute", record)
    try:
        client.get(f"/patients/{clinic['ids']['child']}")
    finally:
        event.remove(Engine, "before_cursor_execute", record)
    assert not seen, f"{len(seen)} bed queries on a clinic with no beds"
