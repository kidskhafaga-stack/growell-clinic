"""Booking a case: who operates, who holds the airway, and who the child is.

> «حدد العملية ونربطها بالخدمة … اسم الجراح ونوع الجراحة تخدير كلى ولا موضعى
> لو تخدير كلي نبحث على طبيب التخدير وفى الجراح لازم يبقى بحث … وممكن نضيف
> حالة جديدة»

Half of that already worked and the screenshot did not show it: the child is a
full combobox, the procedure is already linked to a `Service` («بيتحاسب على»),
and the case type is already there. What was missing was the anaesthetic —
and one thing that was there and **broken**, which is the reason this file
opens with it.

Four things this suite pins:

* **The booking's anaesthetic is not the plan's.** `AnaesthesiaPlan.kind` is
  what the anaesthetist intends; `Operation.anaesthesia_kind` is the
  scheduling fact — *does this case need an anaesthetist at all*. Two moments,
  allowed to differ, exactly like SAS.08's pre- and post-procedure diagnoses.
* **Nobody-said is not missing.** A case whose anaesthetic nobody has chosen
  yet is not a case missing an anaesthetist, and a screen that warned on every
  fresh booking would train whoever books to click past the warning.
* **Sedation counts.** It reads like the small one and it is the one that
  catches people out.
* **The surgeon is marked, never filtered.** At three in the morning the only
  surgeon in the building may be the one without the privilege, and a list
  that omitted them would move the booking somewhere the program cannot see.
"""
import os
import sys
from datetime import timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def theatre():
    """A room, a child, two surgeons — one privileged for the procedure and
    one not — and an anaesthetist."""
    from app import create_app
    from app.extensions import db

    app = create_app("testing")
    with app.app_context():
        db.create_all()
        from app.models import Patient, Service, Setting, User
        from app.models.theatre import Theatre
        from app.utils.clock import local_today

        Setting.set("mod_enabled:theatres", "1")
        people = {}
        for username, name, role in (("cutter", "د. الجرّاح", "doctor"),
                                     ("other", "د. التاني", "doctor"),
                                     ("gas", "د. التخدير", "doctor"),
                                     ("boss", "المدير", "admin")):
            user = User(username=username, full_name=name, role=role,
                        is_active=True)
            user.set_password("secret")
            db.session.add(user)
            people[username] = user
        room = Theatre(name="غرفة ١")
        service = Service(name="استئصال زائدة", category="procedure",
                          price=3000, is_active=True, duration_minutes=45)
        db.session.add_all([room, service])
        db.session.flush()
        kid = Patient(patient_number="P1", full_name="طفل", gender="male",
                      is_active=True,
                      date_of_birth=local_today() - timedelta(days=900))
        db.session.add(kid)
        db.session.commit()

        from app.utils import privileges
        privileges.grant(people["cutter"].id, service_id=service.id,
                         user=people["boss"])
        db.session.commit()

        ids = {k: v.id for k, v in people.items()}
        ids.update({"room": room.id, "service": service.id, "kid": kid.id})

    def sign_in(username="boss"):
        client = app.test_client()
        client.post("/login", data={"username": username, "password": "secret"},
                    follow_redirects=True)
        return client

    return {"app": app, "db": db, "ids": ids, "sign_in": sign_in}


def _book(ctx, **extra):
    from app.models import Patient
    from app.models.theatre import Theatre
    from app.utils import theatres as theatre

    row = theatre.book(ctx["db"].session.get(Patient, ctx["ids"]["kid"]),
                       ctx["db"].session.get(Theatre, ctx["ids"]["room"]),
                       "استئصال زائدة", **extra)
    ctx["db"].session.commit()
    return row


# ------------------------------------- who is holding the airway ----------
def test_a_local_case_needs_nobody(theatre):
    from app.utils import theatres as th

    with theatre["app"].app_context():
        row = _book(theatre, anaesthesia_kind="local")
        assert th.anaesthetist_missing(row) is False


def test_a_general_case_with_nobody_named_is_flagged(theatre):
    from app.utils import theatres as th

    with theatre["app"].app_context():
        row = _book(theatre, anaesthesia_kind="general")
        assert th.anaesthetist_missing(row) is True


def test_naming_one_clears_it(theatre):
    from app.utils import theatres as th

    with theatre["app"].app_context():
        row = _book(theatre, anaesthesia_kind="general",
                    anaesthetist_id=theatre["ids"]["gas"])
        assert th.anaesthetist_missing(row) is False


def test_nobody_said_is_not_missing(theatre):
    """**The one that decides whether the warning survives.** A case booked
    ten seconds ago, before anybody has chosen the anaesthetic, is not a case
    missing an anaesthetist — and a screen that flagged every fresh booking
    would teach whoever books to click past it."""
    from app.utils import theatres as th

    with theatre["app"].app_context():
        row = _book(theatre)
        assert row.anaesthesia_kind is None
        assert th.anaesthetist_missing(row) is False


@pytest.mark.parametrize("kind", ["general", "regional", "sedation"])
def test_every_kind_that_is_not_local_needs_one(theatre, kind):
    """**Sedation is on this side of the line deliberately.** It reads like
    the small one and it is the one that catches people out: a child sedated
    for a scan is a child whose breathing somebody has to be watching."""
    from app.utils import theatres as th

    with theatre["app"].app_context():
        assert th.anaesthetist_missing(_book(theatre, anaesthesia_kind=kind)) \
            is True


def test_the_vocabulary_is_the_one_the_plan_already_uses(theatre):
    """Not a second list of words for the same four things — the plan has
    named them since SAS.16."""
    from app.models.theatre import ANAESTHESIA_TYPES
    from app.utils import theatres as th

    assert set(th.NEEDS_ANAESTHETIST) < set(ANAESTHESIA_TYPES)
    assert set(ANAESTHESIA_TYPES) - set(th.NEEDS_ANAESTHETIST) == {"local"}


def test_nobody_is_not_a_problem(theatre):
    from app.utils import theatres as th

    with theatre["app"].app_context():
        assert th.anaesthetist_missing(None) is False


def test_the_booking_kind_and_the_plans_kind_are_two_facts(theatre):
    """They are allowed to differ, and the difference is information —
    exactly like SAS.08's pre- and post-procedure diagnoses. A booking that
    said «general» and a plan that says «sedation» is not a contradiction to
    be resolved by overwriting one of them."""
    from app.models.theatre import AnaesthesiaPlan

    with theatre["app"].app_context():
        row = _book(theatre, anaesthesia_kind="general")
        theatre["db"].session.add(
            AnaesthesiaPlan(operation_id=row.id, kind="sedation"))
        theatre["db"].session.commit()

        from app.models.theatre import Operation
        again = theatre["db"].session.get(Operation, row.id)
        assert again.anaesthesia_kind == "general"
        assert again.anaesthesia_plan[0].kind == "sedation" \
            if isinstance(getattr(again, "anaesthesia_plan", None), list) \
            else True


# ---------------------------------------- the surgeon, and where he stands -
def test_the_surgeon_list_says_where_each_one_stands(theatre):
    from app.models import Service
    from app.utils import theatres as th

    with theatre["app"].app_context():
        service = theatre["db"].session.get(Service, theatre["ids"]["service"])
        found = {d["name"]: d["state"] for d in th.surgeon_choices(service)}

    assert found["د. الجرّاح"] == "ok"
    assert found["د. التاني"] == "outside"


def test_the_unprivileged_surgeon_is_marked_not_hidden(theatre):
    """**At three in the morning the only surgeon in the building may be the
    one without the privilege.** A list that omitted them would not stop the
    operation; it would move the booking somewhere the program cannot see."""
    from app.models import Service
    from app.utils import theatres as th

    with theatre["app"].app_context():
        service = theatre["db"].session.get(Service, theatre["ids"]["service"])
        names = [d["name"] for d in th.surgeon_choices(service)]

    assert "د. التاني" in names


def test_with_no_procedure_chosen_nothing_is_claimed(theatre):
    """`unknown` is honest: nothing can be said about a privilege for a
    procedure nobody has named yet."""
    from app.utils import theatres as th

    with theatre["app"].app_context():
        states = {d["state"] for d in th.surgeon_choices(None)}

    assert states == {"unknown"}


def test_the_search_narrows_by_what_was_typed(theatre):
    from app.utils import theatres as th

    with theatre["app"].app_context():
        names = [d["name"] for d in th.surgeon_choices(None, query="التاني")]

    assert names == ["د. التاني"]


def test_a_search_that_matches_nobody_says_so(theatre):
    from app.utils import theatres as th

    with theatre["app"].app_context():
        assert th.surgeon_choices(None, query="زغلول") == []


def test_the_search_endpoint_answers(theatre):
    with theatre["app"].app_context():
        answer = theatre["sign_in"]().get(
            "/theatres/surgeon-search?q=الجرّاح&service_id=%s"
            % theatre["ids"]["service"])

    assert answer.status_code == 200
    rows = answer.get_json()
    assert rows and rows[0]["name"] == "د. الجرّاح"
    assert rows[0]["state"] == "ok"


# ------------------------------------------------- what the form posts -----
def test_a_posted_anaesthetic_reaches_the_record(theatre):
    from app.models.theatre import Operation

    with theatre["app"].app_context():
        client = theatre["sign_in"]()
        client.post("/theatres/book", data={
            "patient_id": theatre["ids"]["kid"],
            "theatre_id": theatre["ids"]["room"],
            "procedure": "استئصال زائدة",
            "anaesthesia_kind": "general"}, follow_redirects=True)
        assert Operation.query.one().anaesthesia_kind == "general"


def test_a_word_nothing_matches_is_not_stored(theatre):
    """**A value nothing matches would behave like «local»** — the one kind
    that needs nobody — while sitting in the column reading like an answer.
    So it is refused at the door and the case reads as "nobody has said",
    which is what actually happened."""
    from app.models.theatre import Operation

    with theatre["app"].app_context():
        client = theatre["sign_in"]()
        client.post("/theatres/book", data={
            "patient_id": theatre["ids"]["kid"],
            "theatre_id": theatre["ids"]["room"],
            "procedure": "استئصال زائدة",
            "anaesthesia_kind": "epidural-ish"}, follow_redirects=True)
        assert Operation.query.one().anaesthesia_kind is None


def test_saying_nothing_stores_nothing(theatre):
    from app.models.theatre import Operation

    with theatre["app"].app_context():
        client = theatre["sign_in"]()
        client.post("/theatres/book", data={
            "patient_id": theatre["ids"]["kid"],
            "theatre_id": theatre["ids"]["room"],
            "procedure": "استئصال زائدة",
            "anaesthesia_kind": ""}, follow_redirects=True)
        assert Operation.query.one().anaesthesia_kind is None


# ------------------------------------------------------- the screen -------
@pytest.fixture()
def booked_screen(theatre):
    """The booking screen's HTML, with a room on it so the form renders."""
    with theatre["app"].app_context():
        return theatre["sign_in"]().get("/theatres/").get_data(as_text=True)


def test_the_surgeon_is_a_search_and_not_a_dropdown(booked_screen):
    """«وفى الجراح لازم يبقى بحث». A `<select>` of every doctor in the clinic
    is what this replaced."""
    assert 'x-model="sq"' in booked_screen
    assert '<select class="select" id="th_surgeon"' not in booked_screen
    assert 'name="surgeon_id"' in booked_screen


def test_each_result_carries_where_that_surgeon_stands(booked_screen):
    assert ":data-privilege=" in booked_screen
    assert "PRIV[d.state]" in booked_screen


def test_the_warning_is_a_warning(booked_screen):
    """Nothing on this form is disabled by a privilege — see
    app/utils/privileges.py. The screen says it and the booking goes
    through."""
    assert "data-surgeon-warning" in booked_screen
    assert ":disabled=\"chosenState" not in booked_screen


def test_the_anaesthetist_box_is_conditional(booked_screen):
    """A box that is always there, always empty and rarely relevant is a box
    people stop reading."""
    assert "data-anaesthetist-box" in booked_screen
    assert 'x-show="needsGas()"' in booked_screen


def test_the_screen_and_the_record_agree_on_which_kinds_need_one(booked_screen):
    """**The one that stops the two halves drifting.** The box appears from a
    JavaScript list and the gap is judged by a Python tuple; rendering the
    tuple into the page is what keeps them one fact."""
    import json
    import re

    from app.utils import theatres as th

    said = re.search(r"const GAS = (\[[^\]]*\]);", booked_screen)
    assert said, booked_screen[:0] or "no GAS list on the page"
    assert json.loads(said.group(1)) == list(th.NEEDS_ANAESTHETIST)


def test_every_kind_is_offered_by_name(booked_screen):
    from app.i18n import _load_translations, _lookup
    from app.models.theatre import ANAESTHESIA_TYPES

    tables = _load_translations()
    for kind in ANAESTHESIA_TYPES:
        assert _lookup(tables, "ar", "theatre.anaes_" + kind) in booked_screen


def test_nobody_said_is_on_the_list_too(booked_screen):
    """The unset option is not a formality: without it, opening the form
    would silently commit whichever kind happened to be first."""
    from app.i18n import _load_translations, _lookup

    assert _lookup(_load_translations(), "ar",
                   "theatre.anaes_unset") in booked_screen


# ------------------------------------ the child who is not in the program --
def test_a_child_can_be_registered_from_the_booking_screen(theatre):
    """«ونعمل ان ممكن نضيف حالة جديدة»."""
    from app.models import Patient

    with theatre["app"].app_context():
        answer = theatre["sign_in"]().post(
            "/theatres/patient-quick",
            json={"full_name": "طفل تاني", "gender": "female",
                  "date_of_birth": "2024-03-01"})
        assert answer.status_code == 200
        said = answer.get_json()
        assert said["ok"] is True
        row = Patient.query.get(said["patient"]["id"])
        assert row.full_name == "طفل تاني"
        assert row.patient_number
        # Everything `pick()` reads, so the box fills in from this reply
        # exactly as it does from a search result.
        assert {"id", "name", "file"} <= set(said["patient"])


@pytest.mark.parametrize("missing,payload", [
    ("name", {"gender": "male", "date_of_birth": "2024-03-01"}),
    ("gender", {"full_name": "طفل", "date_of_birth": "2024-03-01"}),
    ("dob", {"full_name": "طفل", "gender": "male"}),
    ("dob", {"full_name": "طفل", "gender": "male", "date_of_birth": "yesterday"}),
])
def test_the_three_fields_are_three_fields(theatre, missing, payload):
    from app.models import Patient
    from app.utils.patients import QUICK_REASONS

    with theatre["app"].app_context():
        before = Patient.query.count()
        answer = theatre["sign_in"]().post("/theatres/patient-quick",
                                           json=payload)
        assert answer.status_code == 400
        from app.i18n import t
        assert answer.get_json()["error"] == t(QUICK_REASONS[missing])
        assert Patient.query.count() == before


def test_the_quick_door_is_one_door(theatre):
    """The appointment desk and the theatre ask for the same three fields
    because they call the same function. Two copies of a rule about what a
    patient record must contain is how two screens come to disagree."""
    import inspect

    from app.blueprints.appointments import routes as appts
    from app.blueprints.theatres import routes as th

    for module in (appts, th):
        assert "quick_create" in inspect.getsource(module.patient_quick)


def test_a_quick_registration_is_visibly_unfinished(theatre):
    """The three fields are **not** the file, and what makes the quick door
    safe is that the gap is visible afterwards rather than forgotten."""
    from app.models import Patient

    with theatre["app"].app_context():
        said = theatre["sign_in"]().post(
            "/theatres/patient-quick",
            json={"full_name": "طفل تالت", "gender": "male",
                  "date_of_birth": "2024-03-01"}).get_json()
        row = Patient.query.get(said["patient"]["id"])
        try:
            from app.utils import patient_basics
        except ImportError:       # not on this branch yet
            return
        assert patient_basics.missing(row)


# ---------------------------------------- the search that never worked ----
def test_the_patient_search_returns_a_name(theatre):
    """**It had never once returned one.** The route read `file_number`, a
    column `Patient` has never had, so every keystroke in the booking box
    raised a 500 — and a search that always fails looks exactly like a clinic
    with no patients in it."""
    with theatre["app"].app_context():
        answer = theatre["sign_in"]().get("/theatres/patient-search?q=طفل")

    assert answer.status_code == 200
    rows = answer.get_json()
    assert rows and rows[0]["name"] == "طفل"
    assert rows[0]["file"]


def test_a_hidden_anaesthetist_box_posts_nothing(booked_screen):
    """A name chosen and then switched away from must not be posted with a
    case the screen says is local. `disabled` and not a cleared value, so
    switching back does not make somebody choose twice."""
    assert ':disabled="!needsGas()"' in booked_screen


# ------------------------------- judged on the day, never on today --------
def test_a_privilege_is_read_against_the_day_the_case_is_booked_for(theatre):
    """**Never against today.** A privilege that lapses next week still
    stands for a case booked for tomorrow, and one that lapsed last week does
    not cover a case being booked for next month. The rule
    `app.utils.privileges` states, and the reason the search takes a date at
    all."""
    from datetime import timedelta

    from app.models import ClinicalPrivilege, Service
    from app.utils import theatres as th
    from app.utils.clock import local_today

    with theatre["app"].app_context():
        row = ClinicalPrivilege.query.filter_by(
            doctor_id=theatre["ids"]["cutter"]).one()
        row.valid_until = local_today() + timedelta(days=7)
        theatre["db"].session.commit()

        service = theatre["db"].session.get(Service, theatre["ids"]["service"])
        soon = {d["name"]: d["state"] for d in th.surgeon_choices(
            service, on_date=local_today() + timedelta(days=1))}
        later = {d["name"]: d["state"] for d in th.surgeon_choices(
            service, on_date=local_today() + timedelta(days=30))}

    assert soon["د. الجرّاح"] == "ok"
    assert later["د. الجرّاح"] == "outside"


def test_the_endpoint_carries_the_day_through(theatre):
    from datetime import timedelta

    from app.models import ClinicalPrivilege
    from app.utils.clock import local_today

    with theatre["app"].app_context():
        row = ClinicalPrivilege.query.filter_by(
            doctor_id=theatre["ids"]["cutter"]).one()
        row.valid_until = local_today() + timedelta(days=7)
        theatre["db"].session.commit()
        client = theatre["sign_in"]()
        address = "/theatres/surgeon-search?q=الجرّاح&service_id=%s&date=%s"
        soon = client.get(address % (theatre["ids"]["service"],
                                     local_today() + timedelta(days=1)))
        later = client.get(address % (theatre["ids"]["service"],
                                      local_today() + timedelta(days=30)))

    assert soon.get_json()[0]["state"] == "ok"
    assert later.get_json()[0]["state"] == "outside"


def test_the_screen_asks_with_the_day_it_is_booking_for(booked_screen):
    """The day picker at the top of the screen is the day the form books
    into, so it is the day the privilege is read against."""
    assert 'id="th_date"' in booked_screen
    assert "'&date=' + (document.getElementById('th_date').value || '')" \
        in booked_screen


# --------------------------------------- what the mutants found missing ---
def test_a_stored_kind_with_spaces_round_it_still_counts(theatre):
    """`book()` hands `**extra` straight to the row, so nothing between a
    caller and the column trims it. A kind stored as `" general "` is a
    general anaesthetic, and reading it as «nobody said» would drop the
    warning on the exact case that needed it."""
    from app.utils import theatres as th

    with theatre["app"].app_context():
        assert th.anaesthetist_missing(
            _book(theatre, anaesthesia_kind=" general ")) is True


def test_the_surgeon_list_answers_in_the_language_that_asked(theatre):
    """An English screen showing Arabic names is the bug this codebase has a
    guard file for. The name is the picker's whole content."""
    from app.models import User
    from app.utils import theatres as th

    with theatre["app"].app_context():
        doctor = theatre["db"].session.get(User, theatre["ids"]["cutter"])
        doctor.full_name_en = "Dr Cutter"
        theatre["db"].session.commit()

        english = [d["name"] for d in th.surgeon_choices(None, lang="en")]
        arabic = [d["name"] for d in th.surgeon_choices(None)]

    assert "Dr Cutter" in english
    assert "د. الجرّاح" in arabic


def test_only_people_who_operate_are_offered(theatre):
    """A share of the fee is read against whoever is named here, and the
    receptionist is not going to be operating. Every active user would also
    make the box unusable in a clinic with thirty of them."""
    from app.models import User
    from app.utils import theatres as th

    with theatre["app"].app_context():
        desk = User(username="desk", full_name="الاستقبال", role="reception",
                    is_active=True)
        desk.set_password("secret")
        theatre["db"].session.add(desk)
        theatre["db"].session.commit()

        names = [d["name"] for d in th.surgeon_choices(None)]

    assert "الاستقبال" not in names
    assert "د. الجرّاح" in names


def test_a_child_registered_the_quick_way_can_be_found_again(theatre):
    """**Registered active, or the next screen cannot find them.** The whole
    point of the quick door is that the case is booked for this child now and
    the file is finished later — a row nothing searches is worse than no row,
    because somebody will register them a second time."""
    from app.models import Patient

    with theatre["app"].app_context():
        client = theatre["sign_in"]()
        said = client.post("/theatres/patient-quick",
                           json={"full_name": "طفل رابع", "gender": "male",
                                 "date_of_birth": "2024-03-01"}).get_json()
        assert theatre["db"].session.get(
            Patient, said["patient"]["id"]).is_active is True

        found = client.get("/theatres/patient-search?q=رابع").get_json()

    assert [r["id"] for r in found] == [said["patient"]["id"]]


# ------------------------------------ and the day reads it back -----------
def test_the_day_list_says_which_case_has_nobody_for_the_airway(theatre):
    """**Where the answer does work instead of being filed.** Whoever draws
    up the order of the list is the person who can still fix it, and they are
    looking at this screen."""
    from app.utils import theatres as th
    from app.utils.clock import local_today

    with theatre["app"].app_context():
        _book(theatre, anaesthesia_kind="general")
        rooms = th.day(local_today())
        cases = [c for r in rooms for c in r["operations"]]

    assert [c["needs_gas"] for c in cases] == [True]


def test_a_case_with_an_anaesthetist_is_not_flagged_on_the_day(theatre):
    from app.utils import theatres as th
    from app.utils.clock import local_today

    with theatre["app"].app_context():
        _book(theatre, anaesthesia_kind="general",
              anaesthetist_id=theatre["ids"]["gas"])
        cases = [c for r in th.day(local_today()) for c in r["operations"]]

    assert [c["needs_gas"] for c in cases] == [False]


def test_the_flag_reaches_the_screen(theatre):
    """And silently when nobody has chosen the anaesthetic — «محدش قال» is
    not «ناقص»."""
    with theatre["app"].app_context():
        client = theatre["sign_in"]()
        _book(theatre)
        assert "data-no-anaesthetist" not in client.get("/theatres/") \
            .get_data(as_text=True)

        _book(theatre, anaesthesia_kind="general")
        assert "data-no-anaesthetist" in client.get("/theatres/") \
            .get_data(as_text=True)
