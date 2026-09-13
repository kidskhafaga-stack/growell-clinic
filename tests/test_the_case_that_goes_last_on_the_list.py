"""What this case needs beyond what every case gets — and where that does work.

GAHAR SAS.06 (ح), and the whole of what the standard asks is one line:

> **h) Special precautions for infection control preparation.**

**The word is preparation**, and its place on the list is *before the patient is
called for*. An earlier note in this repository had this item as "the
prophylactic antibiotic within sixty minutes of the incision" — which is WHO's
number and general surgical practice. The handbook gives **no number at all**,
and the antibiotic belongs to a different standard (SAS.07, where it reads "the
patient receiving prophylactic antibiotics *if applicable*"). The program does
not invent a clinical number, and it does not invent a requirement it was never
given; the correction is written into docs/gahar/SAS_theatres_matrix.md.

So what is recorded is **which precautions**, quoted from GAHAR IPC.12, which
names all three: *"There are three main categories of Transmission-Based
Precautions: Contact Precautions, Droplet Precautions, and Airborne
Precautions."*

Four things this file pins down:

* **``standard`` is an answer, not the absence of one.** IPC.12 says TBPs are
  used *"in addition to standard precautions"*, so standard is always in force
  and "standard only" is a real thing to have decided — the commonest one. A
  scheme without it makes the honest answer unavailable.
* **``unasked`` and ``standard`` are not one state.** The pair this program
  keeps finding, and here the cost is a theatre list drawn up in the wrong
  order by somebody who thought the question had been answered.
* **It reaches the day screen.** This is the one place the answer does work
  rather than being filed: a contact-precautions case goes last, and the room
  is turned over differently afterwards.
* **No checklist item.** Not one of the three stops has an item this answers,
  and adding one would make every checklist ever signed read as short.
"""
import os
import sys
from datetime import timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def theatre_list():
    """A day with two cases in one room, so list order is a real thing."""
    from app import create_app
    from app.extensions import db

    app = create_app("testing")
    with app.app_context():
        db.create_all()
        from app.models import Patient, Setting, User
        from app.models.theatre import Operation, Theatre
        from app.utils.clock import local_today

        Setting.set("mod_enabled:theatres", "1")
        boss = User(username="boss", full_name="المدير", role="admin",
                    is_active=True)
        boss.set_password("secret")
        room = Theatre(name="غرفة ١", sort_order=1)
        db.session.add_all([boss, room])
        db.session.flush()

        ids = {"boss": boss.id, "room": room.id}
        for key, name, proc in (("first", "طفل أول", "لوز"),
                                ("second", "طفل تاني", "ختان")):
            kid = Patient(patient_number=f"P-{key}", full_name=name,
                          gender="male", is_active=True,
                          date_of_birth=local_today() - timedelta(days=1500))
            db.session.add(kid)
            db.session.flush()
            op = Operation(patient_id=kid.id, theatre_id=room.id,
                           procedure=proc, on_date=local_today(),
                           status="scheduled")
            db.session.add(op)
            db.session.flush()
            ids[key], ids[key + "_kid"] = op.id, kid.id
        db.session.commit()

    def sign_in(username="boss"):
        client = app.test_client()
        client.post("/login", data={"username": username, "password": "secret"},
                    follow_redirects=True)
        return client

    return {"app": app, "db": db, "ids": ids, "sign_in": sign_in}


def _op(ctx, key="first"):
    from app.models.theatre import Operation
    return ctx["db"].session.get(Operation, ctx["ids"][key])


def _boss(ctx):
    from app.models import User
    return ctx["db"].session.get(User, ctx["ids"]["boss"])


# ----------------------------------------------------------- three states --
def test_a_case_nobody_has_asked_about(theatre_list):
    from app.utils import theatres as theatre

    with theatre_list["app"].app_context():
        assert theatre.infection_state(_op(theatre_list)) == "unasked"


def test_standard_only_is_a_recorded_answer(theatre_list):
    """IPC.12: TBPs are used *in addition to* standard precautions. So
    standard is always in force, and "standard only" is a decision somebody
    made — the commonest one, and it has to be sayable."""
    from app.utils import theatres as theatre

    with theatre_list["app"].app_context():
        theatre.note_precautions(_op(theatre_list), ["standard"],
                                 user=_boss(theatre_list))
        theatre_list["db"].session.commit()
        assert theatre.infection_state(_op(theatre_list)) == "standard"


def test_unasked_and_standard_are_not_the_same_state(theatre_list):
    """**The pair this file exists for.** One value for both hides every case
    nobody considered, which is the only number an audit of this item wants."""
    from app.utils import theatres as theatre

    with theatre_list["app"].app_context():
        assert theatre.infection_state(_op(theatre_list)) == "unasked"
        theatre.note_precautions(_op(theatre_list), ["standard"],
                                 user=_boss(theatre_list))
        theatre_list["db"].session.commit()
        assert theatre.infection_state(_op(theatre_list)) == "standard"
        assert theatre.infection_state(_op(theatre_list)) != "unasked"


@pytest.mark.parametrize("kind", ["contact", "droplet", "airborne"])
def test_each_category_the_handbook_names_is_recordable(theatre_list, kind):
    """All three, by name. They are quoted from IPC.12, not chosen here."""
    from app.utils import theatres as theatre

    with theatre_list["app"].app_context():
        theatre.note_precautions(_op(theatre_list), [kind],
                                 user=_boss(theatre_list))
        theatre_list["db"].session.commit()
        assert theatre.infection_state(_op(theatre_list)) == "extra"
        assert theatre.precautions_of(_op(theatre_list)) == [kind]


def test_two_categories_at_once(theatre_list):
    """A case can need more than one — the handbook's own example of a
    suspected respiratory infection is droplet *and* contact."""
    from app.utils import theatres as theatre

    with theatre_list["app"].app_context():
        theatre.note_precautions(_op(theatre_list), ["droplet", "contact"],
                                 user=_boss(theatre_list))
        theatre_list["db"].session.commit()
        assert set(theatre.precautions_of(_op(theatre_list))) == \
            {"droplet", "contact"}


def test_standard_is_dropped_when_a_real_precaution_is_named_beside_it(theatre_list):
    """"Standard **and** contact" says nothing "contact" does not already say —
    standard precautions are in force on every case anyway — and a list
    carrying both reads as a case somebody could not make up their mind
    about."""
    from app.utils import theatres as theatre

    with theatre_list["app"].app_context():
        theatre.note_precautions(_op(theatre_list), ["standard", "contact"],
                                 user=_boss(theatre_list))
        theatre_list["db"].session.commit()
        assert theatre.precautions_of(_op(theatre_list)) == ["contact"]


def test_a_record_with_nobodys_name_against_it_is_not_one(theatre_list):
    """Same rule as the site's marking and the identity check."""
    from app.utils import theatres as theatre

    with theatre_list["app"].app_context():
        op = _op(theatre_list)
        op.infection_precautions = "contact"
        theatre_list["db"].session.commit()
        assert theatre.infection_state(_op(theatre_list)) == "unasked"


# ------------------------------------------------------- empiric, or not --
def test_empiric_is_kept_apart_from_a_confirmed_one(theatre_list):
    """IPC.12 names it: *"isolation precautions while waiting for a clear
    diagnosis"*. It ends differently — released by a result — and somebody has
    to go back and look."""
    from app.utils import theatres as theatre

    with theatre_list["app"].app_context():
        theatre.note_precautions(_op(theatre_list), ["airborne"],
                                 note="درن محتمل", empiric=True,
                                 user=_boss(theatre_list))
        theatre_list["db"].session.commit()
        assert _op(theatre_list).infection_empiric is True
        assert _op(theatre_list).infection_note == "درن محتمل"


def test_standard_only_carries_no_empiric_flag(theatre_list):
    """A case needing nothing extra is not waiting on a diagnosis, and a stale
    yes left behind somebody's changed answer is a record that lies."""
    from app.utils import theatres as theatre

    with theatre_list["app"].app_context():
        theatre.note_precautions(_op(theatre_list), ["contact"], empiric=True,
                                 user=_boss(theatre_list))
        theatre_list["db"].session.commit()
        assert _op(theatre_list).infection_empiric is True

        theatre.note_precautions(_op(theatre_list), ["standard"], empiric=True,
                                 user=_boss(theatre_list))
        theatre_list["db"].session.commit()
        assert _op(theatre_list).infection_empiric is None


# ---------------------------------------------------------- what it refuses --
def test_nothing_chosen_is_refused_not_stored_as_standard(theatre_list):
    from app.utils import theatres as theatre

    with theatre_list["app"].app_context():
        assert theatre.note_precautions(_op(theatre_list), [],
                                        user=_boss(theatre_list)) is None
        theatre_list["db"].session.commit()
        assert theatre.infection_state(_op(theatre_list)) == "unasked"


def test_a_precaution_the_program_does_not_know_is_refused(theatre_list):
    """A free-typed one puts the answer beyond anything the program can read
    — the same rule the site's side follows."""
    from app.utils import theatres as theatre

    with theatre_list["app"].app_context():
        assert theatre.note_precautions(_op(theatre_list), ["احتياطات خاصة"],
                                        user=_boss(theatre_list)) is None
        theatre_list["db"].session.commit()
        assert theatre.infection_state(_op(theatre_list)) == "unasked"


def test_an_unknown_one_beside_a_known_one_is_dropped_not_stored(theatre_list):
    from app.utils import theatres as theatre

    with theatre_list["app"].app_context():
        theatre.note_precautions(_op(theatre_list), ["contact", "nonsense"],
                                 user=_boss(theatre_list))
        theatre_list["db"].session.commit()
        assert theatre.precautions_of(_op(theatre_list)) == ["contact"]


# ------------------------------------------------- no checklist item added --
def test_no_checklist_item_was_added(theatre_list):
    """``missed`` is computed against the **current** item list, so adding one
    would make every checklist ever signed read as short. And unlike the site,
    the consent and the imaging, there is no existing item this answers — so
    it is recorded and shown beside the checklist, the way the blood is."""
    from app.models.theatre import CHECK_ITEMS, SIGN_IN, SIGN_OUT, TIME_OUT
    from app.utils import theatres as theatre

    every = set(CHECK_ITEMS[SIGN_IN]) | set(CHECK_ITEMS[TIME_OUT]) \
        | set(CHECK_ITEMS[SIGN_OUT])
    for invented in ("precautions", "infection", "infection_control",
                     "isolation"):
        assert invented not in every
    # And nothing here joined the derived set.
    assert set(theatre.derived_items()) == {
        "identity", "site_marked", "consent", "anaesthesia_check",
        "imaging_ready"}


# ------------------------------------------ where the answer does its work --
def test_the_day_list_names_the_cases_needing_more(theatre_list):
    """**The one place this is not filing.** Whoever draws up the order of the
    list has to know before they draw it up."""
    from app.utils import theatres as theatre

    with theatre_list["app"].app_context():
        theatre.note_precautions(_op(theatre_list, "second"), ["contact"],
                                 user=_boss(theatre_list))
        theatre.note_precautions(_op(theatre_list, "first"), ["standard"],
                                 user=_boss(theatre_list))
        theatre_list["db"].session.commit()
        flagged = [o.id for o in theatre.precaution_cases()]
        assert flagged == [theatre_list["ids"]["second"]]


def test_a_standard_only_case_is_not_on_that_list(theatre_list):
    """A warning that names every case is a warning nobody reads."""
    from app.utils import theatres as theatre

    with theatre_list["app"].app_context():
        for key in ("first", "second"):
            theatre.note_precautions(_op(theatre_list, key), ["standard"],
                                     user=_boss(theatre_list))
        theatre_list["db"].session.commit()
        assert theatre.precaution_cases() == []


def test_a_cancelled_case_is_not_on_it_either(theatre_list):
    from app.utils import theatres as theatre

    with theatre_list["app"].app_context():
        theatre.note_precautions(_op(theatre_list), ["airborne"],
                                 user=_boss(theatre_list))
        theatre_list["db"].session.commit()
        assert len(theatre.precaution_cases()) == 1

        _op(theatre_list).status = "cancelled"
        theatre_list["db"].session.commit()
        assert theatre.precaution_cases() == []


def test_another_days_case_is_not_on_it(theatre_list):
    from app.utils import theatres as theatre
    from app.utils.clock import local_today

    with theatre_list["app"].app_context():
        op = _op(theatre_list)
        theatre.note_precautions(op, ["contact"], user=_boss(theatre_list))
        op.on_date = local_today() + timedelta(days=3)
        theatre_list["db"].session.commit()
        assert theatre.precaution_cases() == []
        assert len(theatre.precaution_cases(
            local_today() + timedelta(days=3))) == 1


def test_the_day_screen_shows_it(theatre_list):
    from app.i18n import t
    from app.utils import theatres as theatre

    with theatre_list["app"].app_context():
        theatre.note_precautions(_op(theatre_list), ["contact"],
                                 note="MRSA", empiric=True,
                                 user=_boss(theatre_list))
        theatre_list["db"].session.commit()

    html = theatre_list["sign_in"]().get("/theatres/").get_data(as_text=True)
    with theatre_list["app"].test_request_context("/"):
        assert t("theatre.precautions_today") in html
        assert t("theatre.precaution_contact") in html
        assert t("theatre.precaution_empiric") in html
    assert "MRSA" in html
    assert "طفل أول" in html


def test_the_day_screen_stays_quiet_when_there_is_nothing(theatre_list):
    """A banner that is always there is furniture."""
    from app.i18n import t

    html = theatre_list["sign_in"]().get("/theatres/").get_data(as_text=True)
    with theatre_list["app"].test_request_context("/"):
        assert t("theatre.precautions_today") not in html


# --------------------------------------------------------- the case screen --
def test_the_case_screen_records_it(theatre_list):
    from app.utils import theatres as theatre

    theatre_list["sign_in"]().post(
        f"/theatres/operation/{theatre_list['ids']['first']}/precautions",
        data={"precaution": ["droplet"], "infection_note": "أنفلونزا",
              "empiric": "1"}, follow_redirects=True)
    with theatre_list["app"].app_context():
        assert theatre.infection_state(_op(theatre_list)) == "extra"
        assert _op(theatre_list).infection_note == "أنفلونزا"
        assert _op(theatre_list).infection_empiric is True


def test_the_case_screen_refuses_an_empty_answer(theatre_list):
    from app.utils import theatres as theatre

    theatre_list["sign_in"]().post(
        f"/theatres/operation/{theatre_list['ids']['first']}/precautions",
        data={}, follow_redirects=True)
    with theatre_list["app"].app_context():
        assert theatre.infection_state(_op(theatre_list)) == "unasked"


def test_the_case_screen_offers_every_category(theatre_list):
    from app.i18n import t

    html = theatre_list["sign_in"]().get(
        f"/theatres/operation/{theatre_list['ids']['first']}"
    ).get_data(as_text=True)
    with theatre_list["app"].test_request_context("/"):
        for p in ("standard", "contact", "droplet", "airborne"):
            assert t("theatre.precaution_" + p) in html
        assert t("theatre.precautions_unasked") in html


def test_the_columns_are_registered_for_a_clinic_already_running(theatre_list):
    from app.utils.schema import ADDITIONS

    have = {c for tbl, c, _ in ADDITIONS if tbl == "operations"}
    assert {"infection_precautions", "infection_note", "infection_empiric",
            "infection_noted_by", "infection_noted_at"} <= have
