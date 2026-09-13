"""Who is allowed to do this here — and the booking that has to match.

GAHAR SAS.02 (أ): *"Surgeries and invasive procedures are booked **according to
granted clinical privileges**."* WFM.12 defines what those are, and the
definition is the whole reason this is a record and not a rule:

> Clinical privilege refers to the **specific authorization or permission
> granted** to a healthcare provider ... **by a healthcare institution**.

> Clinical privileges are **specific to the healthcare institution** where they
> are granted and **may vary from one institution to another**.

So the program holds no opinion about who may do what. It does not know that a
paediatric surgeon may do a herniotomy; it knows **this hospital wrote it
down**, when, until when, and who signed. Any other reading would be the
program inventing a credentialing decision.

And WFM.12's fourth item of evidence is what makes it more than a filing
cabinet: *"Clinical privileges are **accessible to and used by staff involved
in booking**."*

Four decisions:

* **It warns; it does not refuse.** There is one hard refusal in this module —
  a case cannot start without its sign-in — and this is not it. At three in the
  morning the only surgeon in the building may be the one without the
  privilege, and a program that blocks the booking does not make the child
  safer; it moves the booking somewhere the program cannot see.
* **Going ahead records who accepted it and why.** That recorded exception
  *is* the standard's "ongoing process to ensure that booked procedures match"
  — a process, not a wall — and an acknowledged gap never reads as no gap.
* **Judged against the day of the operation.** A case booked in March under a
  privilege that stood in March goes on reading as correct after it lapses; one
  granted in April does not retroactively make March's booking fine.
* **Supervised is not the same as granted.** WFM.12 (g) keeps them apart and
  names the accountable supervisor; a screen showing both as green loses the
  one fact somebody rostering the day needs.
"""
import os
import sys
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def hospital():
    """Two surgeons, two procedures of the same type, and one of another."""
    from app import create_app
    from app.extensions import db

    app = create_app("testing")
    with app.app_context():
        db.create_all()
        from app.models import Patient, Service, Setting, User
        from app.models.theatre import Operation, Theatre
        from app.utils.clock import local_today

        Setting.set("mod_enabled:theatres", "1")
        ids = {}
        for username, name, role in (("cutter", "د. الجرّاح", "doctor"),
                                     ("junior", "د. مقيم", "doctor"),
                                     ("boss", "المدير", "admin")):
            u = User(username=username, full_name=name, role=role,
                     is_active=True)
            u.set_password("secret")
            db.session.add(u)
            db.session.flush()
            ids[username] = u.id

        # Two of one type, one of another — so a type-wide grant can be told
        # apart from a grant that happens to cover everything.
        hernia = Service(name="فتق", category="procedure", price=4000,
                         service_type="surgery", is_active=True)
        tonsils = Service(name="لوز", category="procedure", price=3000,
                          service_type="surgery", is_active=True)
        scope = Service(name="منظار", category="procedure", price=5000,
                        service_type="endoscopy", is_active=True)
        db.session.add_all([hernia, tonsils, scope])
        db.session.flush()
        ids.update({"hernia": hernia.id, "tonsils": tonsils.id,
                    "scope": scope.id})

        room = Theatre(name="غرفة ١", sort_order=1)
        db.session.add(room)
        db.session.flush()
        kid = Patient(patient_number="P1", full_name="طفل", gender="male",
                      is_active=True,
                      date_of_birth=local_today() - timedelta(days=1500))
        db.session.add(kid)
        db.session.flush()
        case = Operation(patient_id=kid.id, theatre_id=room.id,
                         procedure="فتق", on_date=local_today(),
                         status="scheduled", surgeon_id=ids["cutter"],
                         service_id=hernia.id)
        db.session.add(case)
        db.session.commit()
        ids.update({"room": room.id, "kid": kid.id, "case": case.id})

    def sign_in(username="boss"):
        client = app.test_client()
        client.post("/login", data={"username": username, "password": "secret"},
                    follow_redirects=True)
        return client

    return {"app": app, "db": db, "ids": ids, "sign_in": sign_in}


def _svc(ctx, key):
    from app.models import Service
    return ctx["db"].session.get(Service, ctx["ids"][key])


def _case(ctx):
    from app.models.theatre import Operation
    return ctx["db"].session.get(Operation, ctx["ids"]["case"])


def _user(ctx, key="boss"):
    from app.models import User
    return ctx["db"].session.get(User, ctx["ids"][key])


# ------------------------------------------------- the program has no opinion --
def test_a_doctor_with_nothing_written_down_is_privileged_for_nothing(hospital):
    """**The program knows no medicine here.** It does not know that a surgeon
    may do a hernia; it knows whether this hospital wrote it down."""
    from app.utils import privileges

    with hospital["app"].app_context():
        assert privileges.state(hospital["ids"]["cutter"],
                                _svc(hospital, "hernia")) == "outside"
        assert privileges.allowed(hospital["ids"]["cutter"],
                                  _svc(hospital, "hernia")) is False


def test_a_grant_for_one_procedure_covers_that_one(hospital):
    from app.utils import privileges

    with hospital["app"].app_context():
        privileges.grant(hospital["ids"]["cutter"],
                         service_id=hospital["ids"]["hernia"],
                         user=_user(hospital))
        hospital["db"].session.commit()
        assert privileges.state(hospital["ids"]["cutter"],
                                _svc(hospital, "hernia")) == "ok"
        assert privileges.state(hospital["ids"]["cutter"],
                                _svc(hospital, "tonsils")) == "outside"


def test_a_grant_for_a_type_covers_every_procedure_of_it(hospital):
    """A delineation form reads "general surgery: all of it". Making this
    services-only would have somebody tick forty boxes per surgeon, which is
    how a privileges list stops being maintained."""
    from app.utils import privileges

    with hospital["app"].app_context():
        privileges.grant(hospital["ids"]["cutter"], service_type="surgery",
                         user=_user(hospital))
        hospital["db"].session.commit()
        for key in ("hernia", "tonsils"):
            assert privileges.state(hospital["ids"]["cutter"],
                                    _svc(hospital, key)) == "ok"
        # …and not the one of another type.
        assert privileges.state(hospital["ids"]["cutter"],
                                _svc(hospital, "scope")) == "outside"


def test_a_service_from_before_the_service_engine_still_matches(hospital):
    """``service_type`` is empty on rows created before it existed, and the
    type is derived from the category. A privileges list that missed those
    would read "unprivileged" for every procedure the clinic has had longest.
    """
    from app.utils import privileges

    with hospital["app"].app_context():
        old = _svc(hospital, "hernia")
        old.service_type = None          # as an old row has it
        hospital["db"].session.commit()
        privileges.grant(hospital["ids"]["cutter"],
                         service_type=_svc(hospital, "hernia").kind,
                         user=_user(hospital))
        hospital["db"].session.commit()
        assert privileges.state(hospital["ids"]["cutter"],
                                _svc(hospital, "hernia")) == "ok"


def test_a_privilege_scoped_to_nothing_authorises_nothing(hospital):
    """The widest possible failure from the narrowest possible bug: a row with
    no scope read as "everything"."""
    from app.models import ClinicalPrivilege
    from app.utils import privileges

    with hospital["app"].app_context():
        # Built directly, because `grant` refuses to make one.
        hospital["db"].session.add(ClinicalPrivilege(
            doctor_id=hospital["ids"]["cutter"], kind="standard"))
        hospital["db"].session.commit()
        assert privileges.state(hospital["ids"]["cutter"],
                                _svc(hospital, "hernia")) == "outside"


def test_granting_refuses_a_row_with_no_scope_or_two(hospital):
    """Both scopes at once has two different answers to "what does this
    authorise", and whichever the code picked would be a coin toss nobody
    recorded."""
    from app.utils import privileges

    with hospital["app"].app_context():
        assert privileges.grant(hospital["ids"]["cutter"],
                                user=_user(hospital)) is None
        assert privileges.grant(hospital["ids"]["cutter"],
                                service_id=hospital["ids"]["hernia"],
                                service_type="surgery",
                                user=_user(hospital)) is None
        hospital["db"].session.commit()
        assert privileges.all_for(hospital["ids"]["cutter"]) == []


def test_an_unknown_kind_is_refused(hospital):
    from app.utils import privileges

    with hospital["app"].app_context():
        assert privileges.grant(hospital["ids"]["cutter"],
                                service_type="surgery", kind="whatever",
                                user=_user(hospital)) is None


# ----------------------------------------------- supervised is its own word --
def test_a_supervised_privilege_is_not_the_same_as_a_full_one(hospital):
    """WFM.12 (g) keeps them apart and names the accountable supervisor. A
    screen showing both as green loses the fact somebody rostering the day
    needs."""
    from app.utils import privileges

    with hospital["app"].app_context():
        privileges.grant(hospital["ids"]["junior"], service_type="surgery",
                         supervisor_id=hospital["ids"]["cutter"],
                         supervision="حاضر في الأوضة", user=_user(hospital))
        hospital["db"].session.commit()
        assert privileges.state(hospital["ids"]["junior"],
                                _svc(hospital, "hernia")) == "supervised"
        # It is still allowed — supervised is a way of being privileged.
        assert privileges.allowed(hospital["ids"]["junior"],
                                  _svc(hospital, "hernia")) is True


def test_supervised_with_nobody_named_is_not_supervision(hospital):
    """"Supervised" without a supervisor is exactly the empty tick this module
    replaces, so it reads as an ordinary privilege and the gap shows."""
    from app.utils import privileges

    with hospital["app"].app_context():
        privileges.grant(hospital["ids"]["junior"], service_type="surgery",
                         supervision="تحت إشراف", user=_user(hospital))
        hospital["db"].session.commit()
        assert privileges.state(hospital["ids"]["junior"],
                                _svc(hospital, "hernia")) == "ok"


def test_a_full_grant_beside_a_supervised_one_wins(hospital):
    """A doctor holding both is not supervised for this case."""
    from app.utils import privileges

    with hospital["app"].app_context():
        privileges.grant(hospital["ids"]["junior"], service_type="surgery",
                         supervisor_id=hospital["ids"]["cutter"],
                         user=_user(hospital))
        privileges.grant(hospital["ids"]["junior"],
                         service_id=hospital["ids"]["hernia"],
                         user=_user(hospital))
        hospital["db"].session.commit()
        assert privileges.state(hospital["ids"]["junior"],
                                _svc(hospital, "hernia")) == "ok"


# ----------------------------------------------- the day it is judged against --
def test_a_privilege_that_has_not_started_does_not_count(hospital):
    from app.utils import privileges
    from app.utils.clock import local_today

    with hospital["app"].app_context():
        privileges.grant(hospital["ids"]["cutter"], service_type="surgery",
                         valid_from=local_today() + timedelta(days=7),
                         user=_user(hospital))
        hospital["db"].session.commit()
        assert privileges.state(hospital["ids"]["cutter"],
                                _svc(hospital, "hernia")) == "outside"
        assert privileges.state(
            hospital["ids"]["cutter"], _svc(hospital, "hernia"),
            local_today() + timedelta(days=8)) == "ok"


def test_a_lapsed_privilege_does_not_count_today(hospital):
    from app.utils import privileges
    from app.utils.clock import local_today

    with hospital["app"].app_context():
        privileges.grant(hospital["ids"]["cutter"], service_type="surgery",
                         valid_until=local_today() - timedelta(days=1),
                         user=_user(hospital))
        hospital["db"].session.commit()
        assert privileges.state(hospital["ids"]["cutter"],
                                _svc(hospital, "hernia")) == "outside"


def test_but_a_case_booked_while_it_stood_still_reads_as_correct(hospital):
    """**The rule this file turns on.** A case booked in March under a
    privilege that stood in March must go on reading as correct after it
    lapses — otherwise every audit of last year's list invents findings."""
    from app.utils import privileges
    from app.utils.clock import local_today

    with hospital["app"].app_context():
        privileges.grant(hospital["ids"]["cutter"], service_type="surgery",
                         valid_until=local_today() - timedelta(days=1),
                         user=_user(hospital))
        hospital["db"].session.commit()
        assert privileges.state(
            hospital["ids"]["cutter"], _svc(hospital, "hernia"),
            local_today() - timedelta(days=30)) == "ok"


def test_a_privilege_granted_later_does_not_fix_an_earlier_booking(hospital):
    """The other direction, and the one that would quietly launder a finding."""
    from app.utils import privileges
    from app.utils.clock import local_today

    with hospital["app"].app_context():
        privileges.grant(hospital["ids"]["cutter"], service_type="surgery",
                         valid_from=local_today(), user=_user(hospital))
        hospital["db"].session.commit()
        assert privileges.state(
            hospital["ids"]["cutter"], _svc(hospital, "hernia"),
            local_today() - timedelta(days=30)) == "outside"


def test_withdrawing_keeps_the_row_and_the_history(hospital):
    """Withdrawn, never deleted — the same rule the consent follows."""
    from app.utils import privileges
    from app.utils.clock import local_today

    with hospital["app"].app_context():
        row = privileges.grant(hospital["ids"]["cutter"],
                               service_type="surgery", user=_user(hospital))
        hospital["db"].session.commit()
        privileges.withdraw(row, reason="شكوى قيد الفحص")
        hospital["db"].session.commit()

        assert privileges.state(hospital["ids"]["cutter"],
                                _svc(hospital, "hernia")) == "outside"
        # The row is still there, with its reason…
        every = privileges.all_for(hospital["ids"]["cutter"])
        assert len(every) == 1
        assert every[0].withdrawn_reason == "شكوى قيد الفحص"
        # …and yesterday's booking still reads as it read yesterday.
        assert privileges.state(
            hospital["ids"]["cutter"], _svc(hospital, "hernia"),
            local_today() - timedelta(days=1)) == "ok"


def test_withdrawing_twice_does_not_move_the_moment(hospital):
    """A second click on a slow screen must not rewrite when it stopped
    standing."""
    from app.utils import privileges

    with hospital["app"].app_context():
        row = privileges.grant(hospital["ids"]["cutter"],
                               service_type="surgery", user=_user(hospital))
        hospital["db"].session.commit()
        privileges.withdraw(row, reason="الأولى")
        hospital["db"].session.commit()
        first = row.withdrawn_at

        assert privileges.withdraw(row, reason="التانية") is None
        hospital["db"].session.commit()
        assert row.withdrawn_at == first
        assert row.withdrawn_reason == "الأولى"


# ------------------------------------------------ the booking side of it ----
def test_a_booking_with_no_service_cannot_be_judged(hospital):
    """**``unknown`` has to exist.** A case booked as free text has nothing to
    check against, and calling that ``ok`` would report a verification the
    program never did."""
    from app.utils import theatres as theatre

    with hospital["app"].app_context():
        _case(hospital).service_id = None
        hospital["db"].session.commit()
        assert theatre.privilege_state(_case(hospital)) == "unknown"
        assert theatre.privilege_ok(_case(hospital)) is False


def test_a_booking_with_no_surgeon_cannot_be_judged_either(hospital):
    from app.utils import theatres as theatre

    with hospital["app"].app_context():
        _case(hospital).surgeon_id = None
        hospital["db"].session.commit()
        assert theatre.privilege_state(_case(hospital)) == "unknown"


def test_a_booking_outside_the_privileges_says_so(hospital):
    from app.utils import theatres as theatre

    with hospital["app"].app_context():
        assert theatre.privilege_state(_case(hospital)) == "outside"
        assert theatre.privilege_ok(_case(hospital)) is False


def test_a_booking_inside_them_is_clean(hospital):
    from app.utils import privileges
    from app.utils import theatres as theatre

    with hospital["app"].app_context():
        privileges.grant(hospital["ids"]["cutter"], service_type="surgery",
                         user=_user(hospital))
        hospital["db"].session.commit()
        assert theatre.privilege_state(_case(hospital)) == "ok"
        assert theatre.privilege_ok(_case(hospital)) is True


def test_it_refuses_nothing(hospital):
    """**The decision this file argues for.** At three in the morning the only
    surgeon in the building may be the one without the privilege, and blocking
    the booking moves it somewhere the program cannot see."""
    from app.models.theatre import Theatre
    from app.models import Patient
    from app.utils import theatres as theatre

    with hospital["app"].app_context():
        kid = hospital["db"].session.get(Patient, hospital["ids"]["kid"])
        room = hospital["db"].session.get(Theatre, hospital["ids"]["room"])
        row = theatre.book(kid, room, "منظار",
                           surgeon_id=hospital["ids"]["cutter"],
                           service_id=hospital["ids"]["scope"])
        hospital["db"].session.commit()
        assert row.id is not None, "the booking was refused"
        assert theatre.privilege_state(row) == "outside"


def test_accepting_the_gap_records_who_and_why(hospital):
    """The recorded exception **is** the standard's "ongoing process to ensure
    that booked procedures match" — a process, not a wall."""
    from app.utils import theatres as theatre

    with hospital["app"].app_context():
        theatre.acknowledge_privilege(_case(hospital), "طوارئ ٣ص، مفيش غيره",
                                      user=_user(hospital))
        hospital["db"].session.commit()
        row = _case(hospital)
        assert theatre.privilege_state(row) == "acknowledged"
        assert row.privilege_ack_by == hospital["ids"]["boss"]
        assert row.privilege_ack_reason == "طوارئ ٣ص، مفيش غيره"
        assert row.privilege_ack_at is not None


def test_an_acknowledged_gap_never_reads_as_no_gap(hospital):
    """Recording it does not clear it. That is the difference between a record
    and a dismissal."""
    from app.utils import theatres as theatre

    with hospital["app"].app_context():
        theatre.acknowledge_privilege(_case(hospital), "طوارئ",
                                      user=_user(hospital))
        hospital["db"].session.commit()
        assert theatre.privilege_state(_case(hospital)) != "ok"
        assert theatre.privilege_state(_case(hospital)) == "acknowledged"


def test_accepting_without_a_reason_is_refused(hospital):
    """"Somebody clicked accept" is the tick this module keeps replacing. The
    sentence they typed is the only part a review afterwards can use."""
    from app.utils import theatres as theatre

    with hospital["app"].app_context():
        assert theatre.acknowledge_privilege(_case(hospital), "   ",
                                             user=_user(hospital)) is None
        assert theatre.acknowledge_privilege(_case(hospital), None,
                                             user=_user(hospital)) is None
        hospital["db"].session.commit()
        assert theatre.privilege_state(_case(hospital)) == "outside"


def test_an_acknowledgement_on_a_clean_booking_changes_nothing(hospital):
    """A privilege granted after the fact makes the case clean, and the old
    acknowledgement must not keep flagging it."""
    from app.utils import privileges
    from app.utils import theatres as theatre

    with hospital["app"].app_context():
        theatre.acknowledge_privilege(_case(hospital), "طوارئ",
                                      user=_user(hospital))
        privileges.grant(hospital["ids"]["cutter"], service_type="surgery",
                         user=_user(hospital))
        hospital["db"].session.commit()
        assert theatre.privilege_state(_case(hospital)) == "ok"


# ------------------------------------------- used by whoever is booking ----
def test_the_booking_side_can_ask_who_may_do_this(hospital):
    """*"Clinical privileges are accessible to and used by staff involved in
    booking"* — WFM.12's fourth item of evidence."""
    from app.utils import privileges

    with hospital["app"].app_context():
        privileges.grant(hospital["ids"]["cutter"], service_type="surgery",
                         user=_user(hospital))
        privileges.grant(hospital["ids"]["junior"],
                         service_id=hospital["ids"]["scope"],
                         user=_user(hospital))
        hospital["db"].session.commit()

        assert privileges.doctors_for(_svc(hospital, "hernia")) == \
            {hospital["ids"]["cutter"]}
        assert privileges.doctors_for(_svc(hospital, "scope")) == \
            {hospital["ids"]["junior"]}
        assert privileges.doctors_for(None) == set()


def test_the_list_of_who_may_respects_the_day_too(hospital):
    from app.utils import privileges
    from app.utils.clock import local_today

    with hospital["app"].app_context():
        privileges.grant(hospital["ids"]["cutter"], service_type="surgery",
                         valid_from=local_today() + timedelta(days=3),
                         user=_user(hospital))
        hospital["db"].session.commit()
        assert privileges.doctors_for(_svc(hospital, "hernia")) == set()
        assert privileges.doctors_for(
            _svc(hospital, "hernia"),
            local_today() + timedelta(days=4)) == {hospital["ids"]["cutter"]}


def test_the_file_shows_the_withdrawn_ones_too(hospital):
    """A list of only the live ones answers "what can he do" and never "what
    happened to the other one"."""
    from app.utils import privileges

    with hospital["app"].app_context():
        gone = privileges.grant(hospital["ids"]["cutter"],
                                service_type="surgery", user=_user(hospital))
        privileges.grant(hospital["ids"]["cutter"],
                         service_id=hospital["ids"]["scope"],
                         user=_user(hospital))
        hospital["db"].session.commit()
        privileges.withdraw(gone, reason="انتهت")
        hospital["db"].session.commit()

        assert len(privileges.all_for(hospital["ids"]["cutter"])) == 2
        assert len(privileges.live(hospital["ids"]["cutter"])) == 1


# ------------------------------------------------- the kinds are quoted ----
def test_the_kinds_are_the_ones_the_standard_names(hospital):
    """Quoted from WFM.12, and each ends differently — which is why they are
    not one word with a date on it."""
    from app.models import PRIVILEGE_KINDS

    assert PRIVILEGE_KINDS == ("standard", "temporary", "emergency",
                               "disaster")


def test_the_review_interval_is_the_handbooks_and_computes_nothing(hospital):
    """*"reviewed and renewed at least every three years"* is the handbook's
    own number, quoted so a screen can say it. **Nothing derives from it** — a
    renewal date the program guessed is a renewal nobody scheduled."""
    from app.models import MAX_REVIEW_YEARS
    from app.utils import privileges

    assert MAX_REVIEW_YEARS == 3
    with hospital["app"].app_context():
        row = privileges.grant(hospital["ids"]["cutter"],
                               service_type="surgery", user=_user(hospital))
        hospital["db"].session.commit()
        assert row.valid_until is None, "the program invented a renewal date"


# --------------------------------------------------------- on the screens --
def test_the_privileges_screen_lists_what_is_on_file(hospital):
    from app.utils import privileges

    with hospital["app"].app_context():
        privileges.grant(hospital["ids"]["cutter"], service_type="surgery",
                         note="بعد لجنة ٢٠٢٥", user=_user(hospital))
        hospital["db"].session.commit()

    html = hospital["sign_in"]().get(
        f"/theatres/privileges?doctor={hospital['ids']['cutter']}"
    ).get_data(as_text=True)
    assert "بعد لجنة ٢٠٢٥" in html
    # Pinned to real words: `t(key) in html` cannot fail on a missing phrase.
    assert "الصلاحيات الإكلينيكية" in html
    assert "سارية" in html


def test_the_screen_grants_and_withdraws(hospital):
    from app.utils import privileges

    client = hospital["sign_in"]()
    client.post("/theatres/privileges",
                data={"doctor_id": hospital["ids"]["cutter"], "scope": "type",
                      "service_type": "surgery", "kind": "standard"},
                follow_redirects=True)
    with hospital["app"].app_context():
        rows = privileges.all_for(hospital["ids"]["cutter"])
        assert len(rows) == 1
        assert privileges.state(hospital["ids"]["cutter"],
                                _svc(hospital, "hernia")) == "ok"
        row_id = rows[0].id

    client.post("/theatres/privileges",
                data={"action": "withdraw", "privilege_id": row_id,
                      "reason": "انتهت المدة"}, follow_redirects=True)
    with hospital["app"].app_context():
        assert privileges.state(hospital["ids"]["cutter"],
                                _svc(hospital, "hernia")) == "outside"
        assert privileges.all_for(hospital["ids"]["cutter"])[0].withdrawn_reason \
            == "انتهت المدة"


def test_the_screen_refuses_a_row_with_no_scope(hospital):
    from app.i18n import t
    from app.utils import privileges

    html = hospital["sign_in"]().post(
        "/theatres/privileges",
        data={"doctor_id": hospital["ids"]["cutter"], "scope": "type",
              "service_type": "", "kind": "standard"},
        follow_redirects=True).get_data(as_text=True)
    with hospital["app"].app_context():
        assert privileges.all_for(hospital["ids"]["cutter"]) == []
    with hospital["app"].test_request_context("/"):
        assert t("privileges.needs_one_scope") in html
    assert "اختار نطاق واحد" in html


def test_only_an_admin_may_grant(hospital):
    """*"approved by the medical staff committee"* — granting a privilege is a
    credentialing decision, not something the surgeon does for himself."""
    from app.utils import privileges

    hospital["sign_in"]("cutter").post(
        "/theatres/privileges",
        data={"doctor_id": hospital["ids"]["cutter"], "scope": "type",
              "service_type": "surgery", "kind": "standard"},
        follow_redirects=True)
    with hospital["app"].app_context():
        assert privileges.all_for(hospital["ids"]["cutter"]) == []


def test_the_case_screen_names_the_gap_and_takes_a_reason(hospital):
    from app.utils import theatres as theatre

    html = hospital["sign_in"]().get(
        f"/theatres/operation/{hospital['ids']['case']}").get_data(as_text=True)
    assert "بره صلاحياته" in html
    assert "ليه اتحجزت كده؟" in html

    hospital["sign_in"]().post(
        f"/theatres/operation/{hospital['ids']['case']}/privilege",
        data={"reason": "طوارئ، مفيش غيره"}, follow_redirects=True)
    with hospital["app"].app_context():
        assert theatre.privilege_state(_case(hospital)) == "acknowledged"


def test_the_case_screen_refuses_an_empty_reason(hospital):
    from app.i18n import t
    from app.utils import theatres as theatre

    html = hospital["sign_in"]().post(
        f"/theatres/operation/{hospital['ids']['case']}/privilege",
        data={"reason": "   "}, follow_redirects=True).get_data(as_text=True)
    with hospital["app"].app_context():
        assert theatre.privilege_state(_case(hospital)) == "outside"
    with hospital["app"].test_request_context("/"):
        assert t("theatre.privilege_needs_reason") in html


def test_a_case_that_cannot_be_judged_shows_no_card(hospital):
    """A card saying nothing is furniture. With no service behind the booking
    there is nothing to check against, and the screen stays quiet."""
    from app.i18n import t

    with hospital["app"].app_context():
        _case(hospital).service_id = None
        hospital["db"].session.commit()

    html = hospital["sign_in"]().get(
        f"/theatres/operation/{hospital['ids']['case']}").get_data(as_text=True)
    with hospital["app"].test_request_context("/"):
        assert t("theatre.privilege_outside") not in html
    assert "صلاحية الجرّاح" not in html


def test_the_columns_are_registered_for_a_clinic_already_running(hospital):
    from app.utils.schema import ADDITIONS

    pairs = {(t, c) for t, c, _ in ADDITIONS}
    for column in ("privilege_ack_by", "privilege_ack_at",
                   "privilege_ack_reason"):
        assert ("operations", column) in pairs
