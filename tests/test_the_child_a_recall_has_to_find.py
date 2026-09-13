"""What was left inside a child — and whether a recall can find them.

Two standards meet on one row.

**SAS.06 (ز)** asks the pre-operative half: *"Implantable devices and special
prostheses"* — is what this case needs **in the operating location before the
patient is called for**.

**SAS.11** asks the half with the weight, and names what it wants in evidence:

> The procedure report includes the details of any used implantable device,
> **including the batch number**.

> Every patient with an implantable device should be easily identified and
> **reachable within a defined time frame** to be ready for any device recall.

A recall that cannot find the children is the failure the standard exists to
prevent, and it is the one thing here software is actually good at.

Four decisions this file pins down:

* **Two moments, kept apart.** Confirmed present, and actually implanted. They
  disagree in the room — a surgeon opens a size and uses another — and one
  "used" flag loses exactly the difference a recall reads.
* **A recall lists only what went in.** A plate that was fetched and not used
  is not in a child, and putting it on the list sends somebody to telephone a
  family about a device nobody implanted.
* **An implant in a child needs a batch or a serial.** Without one the row is
  a child a recall cannot find, so recording it as implanted is refused — and
  the batch is asked for *at the moment it is known*, with the wrapper open,
  not at planning time when a placeholder gets typed.
* **A row in a child cannot be deleted from the case screen.** That row is
  what a recall reads.

**And what this is not.** SAS.11 is a whole system — selection, procurement,
technical staff competency, adverse-event reporting, reporting malfunctions to
authorities. This covers the two halves the pre-operative list and the recall
turn on. Nothing here should be read as covering the rest.
"""
import os
import sys
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def ortho():
    """Two children, each with a case that could implant something."""
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
        for key, name in (("first", "طفل أول"), ("second", "طفل تاني")):
            kid = Patient(patient_number=f"P-{key}", full_name=name,
                          gender="male", is_active=True, own_phone="01000000000",
                          date_of_birth=local_today() - timedelta(days=2500))
            db.session.add(kid)
            db.session.flush()
            op = Operation(patient_id=kid.id, theatre_id=room.id,
                           procedure="تثبيت كسر", on_date=local_today(),
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


def _plate(ctx, key="first", name="شريحة", lot="L-1", **kw):
    from app.utils import theatres as theatre
    return theatre.add_implant(_op(ctx, key), name, lot=lot, **kw)


# --------------------------------------------------- the pre-operative half --
def test_a_case_nobody_has_asked_about(ortho):
    from app.utils import theatres as theatre

    with ortho["app"].app_context():
        assert theatre.implant_state(_op(ortho)) == "unasked"
        assert theatre.implants_ready(_op(ortho)) is False


def test_implanting_nothing_is_a_recorded_answer(ortho):
    """Nearly every case on a children's list, which is exactly why it has to
    be an answer and not the absence of one."""
    from app.utils import theatres as theatre

    with ortho["app"].app_context():
        theatre.set_implants_needed(_op(ortho), False, user=_boss(ortho))
        ortho["db"].session.commit()
        assert theatre.implant_state(_op(ortho)) == "not_needed"
        assert theatre.implants_ready(_op(ortho)) is True


def test_unasked_and_not_needed_are_not_the_same_state(ortho):
    from app.utils import theatres as theatre

    with ortho["app"].app_context():
        assert theatre.implant_state(_op(ortho)) == "unasked"
        theatre.set_implants_needed(_op(ortho), False, user=_boss(ortho))
        ortho["db"].session.commit()
        assert theatre.implant_state(_op(ortho)) == "not_needed"


def test_a_planned_implant_is_not_ready_until_somebody_confirms_it(ortho):
    from app.utils import theatres as theatre

    with ortho["app"].app_context():
        _plate(ortho)
        ortho["db"].session.commit()
        assert theatre.implant_state(_op(ortho)) == "waiting"

        row = theatre.implants_for(_op(ortho))[0]
        theatre.confirm_implant(row, user=_boss(ortho))
        ortho["db"].session.commit()
        assert theatre.implant_state(_op(ortho)) == "ready"
        assert theatre.implants_for(_op(ortho))[0].state == "available"


def test_one_unconfirmed_holds_the_whole_case(ortho):
    from app.utils import theatres as theatre

    with ortho["app"].app_context():
        _plate(ortho, name="شريحة")
        _plate(ortho, name="مسامير", lot="L-2")
        ortho["db"].session.commit()
        rows = theatre.implants_for(_op(ortho))
        theatre.confirm_implant(rows[0], user=_boss(ortho))
        ortho["db"].session.commit()
        assert theatre.implant_state(_op(ortho)) == "waiting"


def test_saying_yes_and_naming_nothing_is_half_an_answer(ortho):
    from app.utils import theatres as theatre

    with ortho["app"].app_context():
        theatre.set_implants_needed(_op(ortho), True, user=_boss(ortho))
        ortho["db"].session.commit()
        assert theatre.implant_state(_op(ortho)) == "none_named"


def test_naming_one_answers_the_question_too(ortho):
    from app.utils import theatres as theatre

    with ortho["app"].app_context():
        assert _op(ortho).implants_needed is None
        _plate(ortho)
        ortho["db"].session.commit()
        assert _op(ortho).implants_needed is True


def test_a_blank_name_is_refused(ortho):
    from app.utils import theatres as theatre

    with ortho["app"].app_context():
        assert theatre.add_implant(_op(ortho), "  ") is None
        assert theatre.add_implant(_op(ortho), None) is None
        ortho["db"].session.commit()
        assert theatre.implants_for(_op(ortho)) == []


def test_a_missing_answer_is_refused(ortho):
    from app.utils import theatres as theatre

    with ortho["app"].app_context():
        assert theatre.set_implants_needed(_op(ortho), None) is None
        ortho["db"].session.commit()
        assert theatre.implant_state(_op(ortho)) == "unasked"


# ------------------------------------------------ two moments, kept apart --
def test_confirmed_present_is_not_the_same_as_in_the_child(ortho):
    """**The pair this file exists for.** They disagree in the room, and one
    "used" flag loses exactly the difference a recall reads."""
    from app.utils import theatres as theatre

    with ortho["app"].app_context():
        _plate(ortho)
        ortho["db"].session.commit()
        row = theatre.implants_for(_op(ortho))[0]
        theatre.confirm_implant(row, user=_boss(ortho))
        ortho["db"].session.commit()

        row = theatre.implants_for(_op(ortho))[0]
        assert row.available_at is not None
        assert row.implanted_at is None
        assert row.state == "available"
        assert theatre.implanted_in(ortho["ids"]["first_kid"]) == []


def test_one_that_was_fetched_and_not_used_reads_as_unused(ortho):
    """Derived from the case being finished — nobody ticks "we did not use
    this", they just close the case."""
    from app.utils import theatres as theatre

    with ortho["app"].app_context():
        _plate(ortho)
        ortho["db"].session.commit()
        row = theatre.implants_for(_op(ortho))[0]
        theatre.confirm_implant(row, user=_boss(ortho))
        ortho["db"].session.commit()
        assert theatre.implants_for(_op(ortho))[0].state == "available"

        _op(ortho).finished_at = datetime.utcnow()
        ortho["db"].session.commit()
        assert theatre.implants_for(_op(ortho))[0].state == "unused"


def test_an_implanted_one_stays_implanted_after_the_case_closes(ortho):
    from app.utils import theatres as theatre

    with ortho["app"].app_context():
        _plate(ortho)
        ortho["db"].session.commit()
        theatre.record_implanted(theatre.implants_for(_op(ortho))[0],
                                 user=_boss(ortho))
        _op(ortho).finished_at = datetime.utcnow()
        ortho["db"].session.commit()
        assert theatre.implants_for(_op(ortho))[0].state == "implanted"


# ------------------------------------- an implant in a child needs a number --
def test_recording_it_without_a_batch_or_serial_is_refused(ortho):
    """*"including the batch number"* is what the standard asks for by name,
    and an implant in a child with neither is a child a recall cannot find."""
    from app.utils import theatres as theatre

    with ortho["app"].app_context():
        theatre.add_implant(_op(ortho), "شريحة")      # no lot, no serial
        ortho["db"].session.commit()
        row = theatre.implants_for(_op(ortho))[0]
        assert theatre.record_implanted(row, user=_boss(ortho)) is None
        ortho["db"].session.commit()
        assert theatre.implants_for(_op(ortho))[0].implanted_at is None


def test_a_serial_alone_is_enough(ortho):
    """Some implants carry a serial and no batch. Either answers "which child
    has this one"."""
    from app.utils import theatres as theatre

    with ortho["app"].app_context():
        theatre.add_implant(_op(ortho), "شريحة", serial="SN-9")
        ortho["db"].session.commit()
        row = theatre.implants_for(_op(ortho))[0]
        assert theatre.record_implanted(row, user=_boss(ortho)) is not None
        ortho["db"].session.commit()
        assert theatre.implants_for(_op(ortho))[0].state == "implanted"


def test_the_batch_can_be_filled_in_at_the_moment_it_is_known(ortho):
    """The wrapper is open and in somebody's hand. Demanding it at planning
    time gets a placeholder typed — and a recall would then search it."""
    from app.utils import theatres as theatre

    with ortho["app"].app_context():
        theatre.add_implant(_op(ortho), "شريحة")
        ortho["db"].session.commit()
        row = theatre.implants_for(_op(ortho))[0]
        theatre.record_implanted(row, lot="BATCH-77", user=_boss(ortho))
        ortho["db"].session.commit()
        row = theatre.implants_for(_op(ortho))[0]
        assert row.lot == "BATCH-77"
        assert row.implanted_by == ortho["ids"]["boss"]
        assert row.implanted_at is not None


def test_one_in_a_child_cannot_be_taken_off_the_list(ortho):
    """That row is what a recall reads, and a screen that can quietly drop it
    is a screen that can lose a child."""
    from app.utils import theatres as theatre

    with ortho["app"].app_context():
        _plate(ortho)
        ortho["db"].session.commit()
        row = theatre.implants_for(_op(ortho))[0]
        theatre.record_implanted(row, user=_boss(ortho))
        ortho["db"].session.commit()

        assert theatre.remove_implant(theatre.implants_for(_op(ortho))[0]) is None
        ortho["db"].session.commit()
        assert len(theatre.implants_for(_op(ortho))) == 1


def test_a_planned_one_can_be(ortho):
    from app.utils import theatres as theatre

    with ortho["app"].app_context():
        _plate(ortho)
        ortho["db"].session.commit()
        theatre.remove_implant(theatre.implants_for(_op(ortho))[0])
        ortho["db"].session.commit()
        assert theatre.implants_for(_op(ortho)) == []


# ----------------------------------------------------------- the recall ----
def test_the_recall_finds_the_children_by_batch(ortho):
    """The whole point. A recall names a batch, and the answer has to be the
    children, complete and quickly."""
    from app.utils import theatres as theatre

    with ortho["app"].app_context():
        for key in ("first", "second"):
            theatre.add_implant(_op(ortho, key), "شريحة", lot="BAD-1")
        ortho["db"].session.commit()
        for key in ("first", "second"):
            theatre.record_implanted(theatre.implants_for(_op(ortho, key))[0],
                                     user=_boss(ortho))
        ortho["db"].session.commit()

        hits = theatre.recall(lot="BAD-1")
        assert {h.operation.patient_id for h in hits} == \
            {ortho["ids"]["first_kid"], ortho["ids"]["second_kid"]}


def test_a_different_batch_is_not_on_the_list(ortho):
    from app.utils import theatres as theatre

    with ortho["app"].app_context():
        theatre.add_implant(_op(ortho, "first"), "شريحة", lot="BAD-1")
        theatre.add_implant(_op(ortho, "second"), "شريحة", lot="FINE-2")
        ortho["db"].session.commit()
        for key in ("first", "second"):
            theatre.record_implanted(theatre.implants_for(_op(ortho, key))[0],
                                     user=_boss(ortho))
        ortho["db"].session.commit()

        hits = theatre.recall(lot="BAD-1")
        assert [h.operation.patient_id for h in hits] == \
            [ortho["ids"]["first_kid"]]


def test_one_that_was_never_used_is_not_on_the_recall(ortho):
    """**The one that would send somebody to telephone a family about a
    device nobody implanted.** It was fetched and confirmed; it is not in a
    child."""
    from app.utils import theatres as theatre

    with ortho["app"].app_context():
        theatre.add_implant(_op(ortho, "first"), "شريحة", lot="BAD-1")
        theatre.add_implant(_op(ortho, "second"), "شريحة", lot="BAD-1")
        ortho["db"].session.commit()
        # The first went in; the second was only confirmed present.
        theatre.record_implanted(theatre.implants_for(_op(ortho, "first"))[0],
                                 user=_boss(ortho))
        theatre.confirm_implant(theatre.implants_for(_op(ortho, "second"))[0],
                                user=_boss(ortho))
        ortho["db"].session.commit()

        hits = theatre.recall(lot="BAD-1")
        assert [h.operation.patient_id for h in hits] == \
            [ortho["ids"]["first_kid"]]


def test_a_partial_name_finds_it(ortho):
    """A recall notice names a product the way the manufacturer writes it; the
    theatre wrote it the way it was on the box."""
    from app.utils import theatres as theatre

    with ortho["app"].app_context():
        theatre.add_implant(_op(ortho), "شريحة تثبيت فخذ", lot="X",
                            manufacturer="Synthes")
        ortho["db"].session.commit()
        theatre.record_implanted(theatre.implants_for(_op(ortho))[0],
                                 user=_boss(ortho))
        ortho["db"].session.commit()

        assert len(theatre.recall(name="تثبيت")) == 1
        assert len(theatre.recall(manufacturer="synthes")) == 1, \
            "the match is case-sensitive"
        assert theatre.recall(name="ركبة") == []


def test_two_terms_narrow_rather_than_widen(ortho):
    from app.utils import theatres as theatre

    with ortho["app"].app_context():
        theatre.add_implant(_op(ortho, "first"), "شريحة", lot="BAD-1")
        theatre.add_implant(_op(ortho, "second"), "مسمار", lot="BAD-1")
        ortho["db"].session.commit()
        for key in ("first", "second"):
            theatre.record_implanted(theatre.implants_for(_op(ortho, key))[0],
                                     user=_boss(ortho))
        ortho["db"].session.commit()

        assert len(theatre.recall(lot="BAD-1")) == 2
        assert len(theatre.recall(lot="BAD-1", name="مسمار")) == 1


def test_asking_nothing_lists_nothing_rather_than_everything(ortho):
    """A recall question is always narrow, and a screen that opens with every
    implant the clinic ever used is a list nobody reads."""
    from app.utils import theatres as theatre

    with ortho["app"].app_context():
        theatre.add_implant(_op(ortho), "شريحة", lot="X")
        ortho["db"].session.commit()
        theatre.record_implanted(theatre.implants_for(_op(ortho))[0],
                                 user=_boss(ortho))
        ortho["db"].session.commit()

    html = ortho["sign_in"]().get("/theatres/implants/recall").get_data(as_text=True)
    assert "طفل أول" not in html


def test_the_childs_own_side_of_it(ortho):
    """*"Every patient with an implantable device should be easily
    identified"* — read from the patient, because that is the side somebody is
    standing on when a family telephones."""
    from app.utils import theatres as theatre

    with ortho["app"].app_context():
        theatre.add_implant(_op(ortho), "شريحة", lot="X")
        ortho["db"].session.commit()
        theatre.record_implanted(theatre.implants_for(_op(ortho))[0],
                                 user=_boss(ortho))
        ortho["db"].session.commit()

        mine = theatre.implanted_in(ortho["ids"]["first_kid"])
        assert [r.lot for r in mine] == ["X"]
        assert theatre.implanted_in(ortho["ids"]["second_kid"]) == []


# --------------------------------------------------------- on the screen --
def test_the_recall_screen_lists_the_children_and_their_number(ortho):
    """The reason this screen exists is somebody telephoning a family, so the
    number is on it rather than one click away."""
    from app.utils import theatres as theatre

    with ortho["app"].app_context():
        theatre.add_implant(_op(ortho), "شريحة", lot="BAD-1")
        ortho["db"].session.commit()
        theatre.record_implanted(theatre.implants_for(_op(ortho))[0],
                                 user=_boss(ortho))
        ortho["db"].session.commit()

    html = ortho["sign_in"]().get(
        "/theatres/implants/recall?lot=BAD-1").get_data(as_text=True)
    assert "طفل أول" in html
    assert "BAD-1" in html
    assert "01000000000" in html
    assert "P-first" in html


def test_the_case_screen_records_one_going_in(ortho):
    from app.utils import theatres as theatre

    with ortho["app"].app_context():
        theatre.add_implant(_op(ortho), "شريحة")
        ortho["db"].session.commit()
        item = theatre.implants_for(_op(ortho))[0].id

    ortho["sign_in"]().post(
        f"/theatres/operation/{ortho['ids']['first']}/implants",
        data={"needed": "yes", f"do_{item}": "in", f"lot_{item}": "B-9"},
        follow_redirects=True)
    with ortho["app"].app_context():
        row = theatre.implants_for(_op(ortho))[0]
        assert row.state == "implanted"
        assert row.lot == "B-9"


def test_the_case_screen_says_why_it_refused(ortho):
    """A refusal nobody can read is a screen that just did not work."""
    from app.i18n import t
    from app.utils import theatres as theatre

    with ortho["app"].app_context():
        theatre.add_implant(_op(ortho), "شريحة")
        ortho["db"].session.commit()
        item = theatre.implants_for(_op(ortho))[0].id

    html = ortho["sign_in"]().post(
        f"/theatres/operation/{ortho['ids']['first']}/implants",
        data={"needed": "yes", f"do_{item}": "in"},
        follow_redirects=True).get_data(as_text=True)
    with ortho["app"].app_context():
        assert theatre.implants_for(_op(ortho))[0].implanted_at is None
    with ortho["app"].test_request_context("/"):
        assert t("theatre.implant_needs_lot") in html
    # Pinned to real words: `t(key) in html` cannot fail on a missing phrase,
    # because `t` hands back the key and the template prints the same string.
    assert "رقم تشغيلة أو رقم تسلسلي" in html


def test_the_case_screen_shows_the_card(ortho):
    from app.i18n import t

    html = ortho["sign_in"]().get(
        f"/theatres/operation/{ortho['ids']['first']}").get_data(as_text=True)
    with ortho["app"].test_request_context("/"):
        assert t("theatre.implants_unasked") in html
    assert "الأجهزة المزروعة" in html
    assert "الحالة هتزرع حاجة؟" in html


def test_the_column_is_registered_for_a_clinic_already_running(ortho):
    from app.utils.schema import ADDITIONS

    assert ("operations", "implants_needed") in {(t, c) for t, c, _ in ADDITIONS}
