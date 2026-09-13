"""Right patient, right procedure — the half the site marking does not cover.

GAHAR SAS.06 (أ) asks for the child's identity **and the planned procedure**,
confirmed *with the family taking part*. The program had a checklist box called
``identity`` that anybody could tick on the way past, and in paediatrics that
is the box with the most behind it: a child cannot confirm their own name, two
siblings are booked the same morning under the same surname, and the family is
the only witness in the room who knows which one this is.

**What the program can honestly hold.** The act happens in a room and no
software sees it. So it does not claim to verify anything — it records that a
named person did, when, who from the family stood there, and what it was
matched against. A witnessed event instead of a tick, and the checklist box is
then *read* from it, exactly as the consent and the site are.

Four mistakes this file exists to stop, each of them a way the same shortcut
comes back:

* **one empty value for two facts** — *nobody asked* and *nobody from the
  family could come* are two different mornings, and a single blank column
  would make them one
* **refusing the honest answer** — if "nobody was there" could not be
  recorded, somebody names a mother who was in the car park, and the record is
  worse than the box it replaced
* **storing a contradiction** — "nobody from the family was present, and her
  name is Fatma"
* **offering an identifier the program has no value for** — a ticked "national
  id matched" on a child with no national id on file is a confirmation of an
  empty column
"""
import os
import sys
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def theatre_day():
    """One child with a mother and a father on file, and one case booked."""
    from app import create_app
    from app.extensions import db

    app = create_app("testing")
    with app.app_context():
        db.create_all()
        from app.models import Patient, Setting, User
        from app.models.family import Family
        from app.models.parent import Parent
        from app.models.theatre import Operation, Theatre
        from app.utils.clock import local_today

        Setting.set("mod_enabled:theatres", "1")
        ids = {}
        for username, name, role in (("cutter", "د. الجرّاح", "doctor"),
                                     ("nurse", "التمريض", "nurse")):
            u = User(username=username, full_name=name, role=role,
                     is_active=True)
            u.set_password("secret")
            db.session.add(u)
            db.session.flush()
            ids[username] = u.id

        family = Family(family_name="خفاجة")
        db.session.add(family)
        db.session.flush()
        for relation, name in (("father", "محمد خفاجة"),
                              ("mother", "فاطمة السيد")):
            db.session.add(Parent(family_id=family.id, relation=relation,
                                  full_name=name))

        room = Theatre(name="غرفة ١", sort_order=1)
        db.session.add(room)
        db.session.flush()

        child = Patient(patient_number="P1", full_name="طفل خفاجة",
                        date_of_birth=date(2022, 3, 1), gender="male",
                        family_id=family.id)
        db.session.add(child)
        db.session.flush()
        op = Operation(patient_id=child.id, theatre_id=room.id,
                       procedure="لوز", on_date=local_today(),
                       status="scheduled", surgeon_id=ids["cutter"])
        db.session.add(op)
        db.session.commit()
        ids.update({"child": child.id, "op": op.id, "room": room.id,
                    "family": family.id})

    def sign_in(username="cutter"):
        client = app.test_client()
        client.post("/login", data={"username": username, "password": "secret"},
                    follow_redirects=True)
        return client

    return {"app": app, "db": db, "ids": ids, "sign_in": sign_in}


def _op(ctx):
    from app.models.theatre import Operation
    return ctx["db"].session.get(Operation, ctx["ids"]["op"])


def _user(ctx, key="cutter"):
    from app.models import User
    return ctx["db"].session.get(User, ctx["ids"][key])


# ------------------------------------------------------ nothing recorded --
def test_a_case_nobody_has_checked_reads_as_nobody_has_checked(theatre_day):
    from app.utils import theatres as theatre

    with theatre_day["app"].app_context():
        assert theatre.identity_state(_op(theatre_day)) == "none"
        assert theatre.identity_ok(_op(theatre_day)) is False


def test_the_checklist_box_is_unticked_however_firmly_somebody_ticks_it(theatre_day):
    """**The bug, stated as a test.** Posting the item with nothing recorded
    used to store a confirmation that the child had been identified."""
    from app.utils import theatres as theatre

    with theatre_day["app"].app_context():
        row = theatre.sign(_op(theatre_day), "sign_in",
                           items=["identity", "allergy"],
                           user=_user(theatre_day))
        theatre_day["db"].session.commit()
        assert row.has("allergy"), "an ordinary item stopped being recordable"
        assert not row.has("identity"), \
            "the identity box was ticked with no record behind it"
        assert "identity" in row.missed


# ------------------------------------------------------ somebody checked --
def test_a_check_with_the_mother_present_is_recorded_and_read(theatre_day):
    from app.utils import theatres as theatre

    with theatre_day["app"].app_context():
        theatre.verify_identity(_op(theatre_day), "mother",
                                name="فاطمة السيد",
                                matched=["name", "birth_date", "procedure"],
                                user=_user(theatre_day))
        theatre_day["db"].session.commit()
        op = _op(theatre_day)
        assert theatre.identity_state(op) == "with_family"
        assert theatre.identity_ok(op) is True
        assert op.identity_with_name == "فاطمة السيد"
        assert theatre.identity_matched_keys(op) == \
            ["name", "birth_date", "procedure"]
        assert op.identity_checked_by == theatre_day["ids"]["cutter"]
        assert op.identity_checked_at is not None


def test_the_box_then_ticks_itself_without_anybody_posting_it(theatre_day):
    """Read in both directions, like the consent: a record nobody thought to
    tick still answers the item."""
    from app.utils import theatres as theatre

    with theatre_day["app"].app_context():
        theatre.verify_identity(_op(theatre_day), "father", name="محمد خفاجة",
                                user=_user(theatre_day))
        row = theatre.sign(_op(theatre_day), "sign_in", items=[],
                           user=_user(theatre_day))
        theatre_day["db"].session.commit()
        assert row.has("identity")
        assert "identity" not in row.missed


# ------------------------- nobody came is an answer, not a missing answer --
def test_nobody_from_the_family_is_a_recorded_answer(theatre_day):
    """A child brought by a school, or arriving in an emergency with nobody.
    The identity was still confirmed by a named person at a recorded moment."""
    from app.utils import theatres as theatre

    with theatre_day["app"].app_context():
        theatre.verify_identity(_op(theatre_day), "none_present",
                                user=_user(theatre_day))
        theatre_day["db"].session.commit()
        assert theatre.identity_state(_op(theatre_day)) == "alone"
        assert theatre.identity_ok(_op(theatre_day)) is True


def test_alone_and_not_asked_are_not_the_same_state(theatre_day):
    """**The one this file was written for.** One column standing for both
    would hide every case where the family could not come, which is the only
    number an audit of this item would actually want."""
    from app.utils import theatres as theatre

    with theatre_day["app"].app_context():
        assert theatre.identity_state(_op(theatre_day)) == "none"
        theatre.verify_identity(_op(theatre_day), "none_present",
                                user=_user(theatre_day))
        theatre_day["db"].session.commit()
        assert theatre.identity_state(_op(theatre_day)) == "alone"
        assert theatre.identity_state(_op(theatre_day)) != "with_family"


def test_nobody_present_cannot_also_have_a_name(theatre_day):
    """"Nobody from the family was there, and her name is Fatma" is a
    contradiction, and storing both halves leaves whoever reads it later
    choosing which to believe."""
    from app.utils import theatres as theatre

    with theatre_day["app"].app_context():
        theatre.verify_identity(_op(theatre_day), "none_present",
                                name="فاطمة السيد", user=_user(theatre_day))
        theatre_day["db"].session.commit()
        assert _op(theatre_day).identity_with_name is None


def test_a_role_with_nobodys_name_against_it_is_not_a_check(theatre_day):
    """**Caught by measurement.** Every other test here goes through
    ``verify_identity``, which always stamps who and when — so the guard
    against a half-written row could have been dropped and nothing failed. A
    row carrying "mother" with nobody's signature is a note, not a
    verification: the same rule the site's marking follows."""
    from app.utils import theatres as theatre

    with theatre_day["app"].app_context():
        op = _op(theatre_day)
        op.identity_with = "mother"
        op.identity_with_name = "فاطمة السيد"
        theatre_day["db"].session.commit()
        assert theatre.identity_state(_op(theatre_day)) == "none"
        assert theatre.identity_ok(_op(theatre_day)) is False


@pytest.mark.parametrize("half", ["who", "when"])
def test_half_a_record_is_not_a_record(theatre_day, half):
    """Both halves are required, and **each one had to be asserted
    separately** — a test that supplied neither killed a mutant dropping the
    pair and left either one alone standing.

    The claim this makes is "a named person did this at a known moment". A
    name with no time is not a moment, and a time with no name is not a
    witness; each on its own is exactly the tick this replaced.
    """
    from app.utils import theatres as theatre

    with theatre_day["app"].app_context():
        op = _op(theatre_day)
        op.identity_with = "mother"
        if half == "who":
            op.identity_checked_by = theatre_day["ids"]["cutter"]
        else:
            op.identity_checked_at = datetime.utcnow()
        theatre_day["db"].session.commit()
        assert theatre.identity_state(_op(theatre_day)) == "none"


# ----------------------------------------------------- what it refuses ----
def test_an_answer_the_program_cannot_read_is_refused(theatre_day):
    """Same rule as the site's side: a free-typed answer puts the checklist
    beyond anything the program can derive — the tick again, in a hat."""
    from app.utils import theatres as theatre

    with theatre_day["app"].app_context():
        assert theatre.verify_identity(_op(theatre_day), "الجدة",
                                       user=_user(theatre_day)) is None
        assert theatre.verify_identity(_op(theatre_day), "",
                                       user=_user(theatre_day)) is None
        theatre_day["db"].session.commit()
        assert theatre.identity_state(_op(theatre_day)) == "none"


def test_a_relative_who_is_nobodys_row_on_file_still_fits(theatre_day):
    """The person who brings a child to theatre is very often the grandmother
    or an aunt, who is in no ``parents`` row."""
    from app.utils import theatres as theatre

    with theatre_day["app"].app_context():
        theatre.verify_identity(_op(theatre_day), "other", name="جدة الطفل",
                                user=_user(theatre_day))
        theatre_day["db"].session.commit()
        assert theatre.identity_state(_op(theatre_day)) == "with_family"
        assert _op(theatre_day).identity_with_name == "جدة الطفل"


def test_a_matched_key_the_program_does_not_know_is_dropped(theatre_day):
    from app.utils import theatres as theatre

    with theatre_day["app"].app_context():
        theatre.verify_identity(_op(theatre_day), "mother", name="فاطمة",
                                matched=["name", "horoscope"],
                                user=_user(theatre_day))
        theatre_day["db"].session.commit()
        assert theatre.identity_matched_keys(_op(theatre_day)) == ["name"]


# ------------------------------------------------- what the screen offers --
def test_the_guardians_on_file_are_offered_so_nobody_retypes_a_name(theatre_day):
    from app.utils import theatres as theatre

    with theatre_day["app"].app_context():
        people = theatre.identity_options(_op(theatre_day))["people"]
        assert {(p["relation"], p["name"]) for p in people} == \
            {("father", "محمد خفاجة"), ("mother", "فاطمة السيد")}


def test_an_identifier_with_no_value_on_file_is_not_offered(theatre_day):
    """**The other one this file was written for.** A ticked "national id
    matched" on a child with no national id is a confirmation of the
    program's own empty column."""
    from app.utils import theatres as theatre

    with theatre_day["app"].app_context():
        keys = theatre.identity_options(_op(theatre_day))["identifiers"]
        assert "national_id" not in keys
        assert "name" in keys and "birth_date" in keys and "procedure" in keys


def test_it_is_offered_once_the_child_has_one(theatre_day):
    from app.models import Patient
    from app.utils import theatres as theatre

    with theatre_day["app"].app_context():
        child = theatre_day["db"].session.get(Patient, theatre_day["ids"]["child"])
        child.national_id = "30001010100011"
        theatre_day["db"].session.commit()
        assert "national_id" in \
            theatre.identity_options(_op(theatre_day))["identifiers"]


def test_a_clinic_that_does_not_band_children_is_not_asked_about_wristbands(theatre_day):
    """An identifier nobody wears is one more box people learn to tick
    without reading."""
    from app.models import Setting
    from app.utils import theatres as theatre

    with theatre_day["app"].app_context():
        assert "wristband" not in \
            theatre.identity_options(_op(theatre_day))["identifiers"]

    with theatre_day["app"].app_context():
        Setting.set("theatre_wristbands", "1")
        theatre_day["db"].session.commit()
        assert "wristband" in \
            theatre.identity_options(_op(theatre_day))["identifiers"]


def test_a_child_with_no_family_on_file_does_not_break_the_screen(theatre_day):
    from app.models import Patient
    from app.utils import theatres as theatre

    with theatre_day["app"].app_context():
        child = theatre_day["db"].session.get(Patient, theatre_day["ids"]["child"])
        child.family_id = None
        theatre_day["db"].session.commit()
        assert theatre.identity_options(_op(theatre_day))["people"] == []


# --------------------------------------------------------- on the screen --
def test_the_case_screen_shows_the_state_and_the_people(theatre_day):
    client = theatre_day["sign_in"]()
    html = client.get(
        f"/theatres/operation/{theatre_day['ids']['op']}").get_data(as_text=True)
    from app.i18n import t

    with theatre_day["app"].test_request_context("/"):
        assert t("theatre.identity_none") in html
        assert t("theatre.identity_role_none_present") in html
    assert "فاطمة السيد" in html, "the mother on file is not offered"
    # And the identifier the child has no value for is not on the screen.
    with theatre_day["app"].test_request_context("/"):
        assert t("theatre.identity_key_national_id") not in html


def test_the_checklist_row_is_not_offered_as_something_to_tick(theatre_day):
    """**Caught by measurement.** ``sign`` drops a posted ``identity`` either
    way, so leaving the row tickable changed no stored data and every test
    stayed green — it only made the *screen* lie, showing an empty box that
    invites the exact habit this replaced. The other three read-only items are
    drawn disabled; this one has to be too."""
    from app.i18n import t

    html = theatre_day["sign_in"]().get(
        f"/theatres/operation/{theatre_day['ids']['op']}").get_data(as_text=True)
    assert 'name="item" value="identity"' not in html,         "the identity box is posted like an ordinary tick"
    with theatre_day["app"].test_request_context("/"):
        assert t("theatre.identity_read_only") in html


def test_the_screen_records_a_check_and_says_so(theatre_day):
    from app.i18n import t
    from app.utils import theatres as theatre

    client = theatre_day["sign_in"]()
    client.post(f"/theatres/operation/{theatre_day['ids']['op']}/identity",
                data={"with_whom": "mother", "with_name": "فاطمة السيد",
                      "matched": ["name", "procedure"]},
                follow_redirects=True)
    with theatre_day["app"].app_context():
        assert theatre.identity_state(_op(theatre_day)) == "with_family"

    html = client.get(
        f"/theatres/operation/{theatre_day['ids']['op']}").get_data(as_text=True)
    with theatre_day["app"].test_request_context("/"):
        assert t("theatre.identity_with_family") in html


def test_a_blank_answer_from_the_screen_is_refused_not_read_as_nobody(theatre_day):
    """The screen's half of the two-facts rule: leaving the box empty must not
    be stored as "nobody from the family was there"."""
    from app.utils import theatres as theatre

    client = theatre_day["sign_in"]()
    client.post(f"/theatres/operation/{theatre_day['ids']['op']}/identity",
                data={"with_whom": "", "with_name": ""}, follow_redirects=True)
    with theatre_day["app"].app_context():
        assert theatre.identity_state(_op(theatre_day)) == "none"


# ----------------------------------------------- the record does not move --
def test_a_case_reviewed_later_reads_as_it_read_on_the_day(theatre_day):
    """The check is a moment that happened, not a state recomputed against
    today — the same reason the consent is judged against ``on_date``."""
    from app.utils import theatres as theatre

    long_ago = datetime.utcnow() - timedelta(days=400)
    with theatre_day["app"].app_context():
        theatre.verify_identity(_op(theatre_day), "father", name="محمد خفاجة",
                                user=_user(theatre_day), at=long_ago)
        theatre_day["db"].session.commit()
        assert theatre.identity_state(_op(theatre_day)) == "with_family"
        assert _op(theatre_day).identity_checked_at == long_ago


def test_the_column_is_registered_for_a_clinic_already_running(theatre_day):
    """A clinic upgrading into this gets the columns added, and every case
    booked before it reads as "nobody recorded it" — which is true."""
    from app.utils.schema import ADDITIONS

    wanted = {"identity_checked_by", "identity_checked_at", "identity_with",
              "identity_with_name", "identity_matched"}
    have = {col for table, col, _ in ADDITIONS if table == "operations"}
    assert wanted <= have, f"not registered: {wanted - have}"
