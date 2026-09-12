"""After the operation: the recovery room, going home, and what to do there.

Described by the clinic as the ordinary path rather than an edge case:

> «الحالات اللي بتعمل جراحة بمخدر كلي بتقعد في الإفاقة وتخرج على طول لو
> العملية مش كبيرة، والحالات اللي بتاخد مخدر موضعي زي الطهارة بتخرج بعد
> الإفاقة على طول، ويتكتبلها تعليمات بعد الجراحة، ويا بتطلب استشارة بعد
> العملية يا لأ»

A day-case list is mostly made of exactly that, and the program had nothing
for any of it: where the child is after theatre, what the family were told,
and whether anybody expects to see them again.

Four decisions, and each is a way a child goes home badly:

**Stamps, not statuses.** ``status`` keeps the four words it has always had,
because code reads ``done`` by name — the billing query is that filter — and
moving a recovered child to a fifth word would quietly drop their operation
off the bill.

**"Nobody decided" is a state.** ``followup_needed`` is nullable and the
discharge refuses a blank: a surgeon saying *no* and a screen nobody filled in
look identical the moment those two share a column, and the child never seen
again is the second one.

**The instructions are the surgeon's, per procedure.** The template is a
wrapper a clinic writes once; the clinical words are not the wrapper's to
invent, and a procedure with none sends nothing rather than an empty message.

**And the case nobody marked is the case that matters.** A discharge list
built only out of the recovery room would never show the child somebody
wheeled out without pressing anything.
"""
import os
import sys
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def suite(clinic):
    """A theatre, a surgeon, two procedures — one with instructions, one bare."""
    from app.models import Patient, Service, Setting, Theatre, User
    from app.utils.clock import local_today

    with clinic["app"].app_context():
        for module in ("theatres",):
            Setting.set(f"mod_enabled:{module}", "1")

        tonsils = Service(name="استئصال لوز", code="SVC-TONS", price=3000,
                          category="procedure", is_active=True,
                          post_op_instructions="مشروبات باردة، ومسكّن كل ٦ ساعات.",
                          followup_days=7)
        circum = Service(name="طهارة", code="SVC-CIRC", price=900,
                         category="procedure", is_active=True,
                         post_op_instructions="غيار يومي، والحمّام عادي بعد يومين.")
        bare = Service(name="إجراء بدون تعليمات", code="SVC-BARE", price=400,
                       category="procedure", is_active=True)
        clinic["db"].session.add_all([tonsils, circum, bare])

        surgeon = User(username="surg", full_name="د. جرّاح", role="doctor",
                       is_active=True)
        surgeon.set_password("secret")
        clinic["db"].session.add(surgeon)

        room = Theatre(name="غرفة ١", is_active=True)
        clinic["db"].session.add(room)

        kid = Patient(patient_number="R-1", full_name="طفل إفاقة",
                      gender="male", is_active=True,
                      date_of_birth=local_today() - timedelta(days=1500),
                      own_phone="01000000000")
        clinic["db"].session.add(kid)
        clinic["db"].session.commit()
        clinic["ids"] = {"tonsils": tonsils.id, "circum": circum.id,
                         "bare": bare.id, "surgeon": surgeon.id,
                         "room": room.id, "kid": kid.id}
    return clinic


def _op(suite, service="tonsils", status="done", days_ago=0):
    from app.models import Operation
    from app.utils.clock import local_today

    with suite["app"].app_context():
        row = Operation(patient_id=suite["ids"]["kid"],
                        theatre_id=suite["ids"]["room"],
                        procedure="عملية", status=status,
                        on_date=local_today() - timedelta(days=days_ago),
                        service_id=suite["ids"][service],
                        surgeon_id=suite["ids"]["surgeon"])
        suite["db"].session.add(row)
        suite["db"].session.commit()
        return row.id


def _get(suite, operation_id):
    from app.models import Operation

    return suite["db"].session.get(Operation, operation_id)


# ------------------------------------------------------- where the child is --
def test_where_they_are_is_derived_and_the_status_never_moves(suite):
    """``status`` keeps meaning what the billing query reads it to mean. A
    fifth word here would drop a recovered child's operation off the bill."""
    from app.utils import recovery

    operation = _op(suite)
    with suite["app"].app_context():
        row = _get(suite, operation)
        assert row.where is None

        recovery.to_recovery(row, None)
        suite["db"].session.commit()
        assert row.where == "recovery"
        assert row.status == "done"

        recovery.discharge(row, None, followup=False)
        suite["db"].session.commit()
        assert row.where == "home"
        assert row.status == "done"


def test_a_case_that_never_happened_has_no_recovery(suite):
    """Stamping one would put a child in a room they were never taken to."""
    from app.utils import recovery

    for status in ("scheduled", "cancelled", "in_theatre"):
        operation = _op(suite, status=status)
        with suite["app"].app_context():
            row = _get(suite, operation)
            assert recovery.to_recovery(row, None) is None
            assert row.recovery_at is None
            assert recovery.discharge(row, None, followup=False) is None


def test_pressing_it_twice_keeps_the_first_moment(suite):
    """The first is the true one; the second is somebody clicking twice."""
    from app.utils import recovery

    operation = _op(suite)
    with suite["app"].app_context():
        row = _get(suite, operation)
        recovery.to_recovery(row, None, at=datetime(2026, 3, 5, 10, 0))
        recovery.to_recovery(row, None, at=datetime(2026, 3, 5, 14, 0))
        assert row.recovery_at == datetime(2026, 3, 5, 10, 0)


def test_a_child_is_not_sent_home_twice(suite):
    from app.utils import recovery

    operation = _op(suite)
    with suite["app"].app_context():
        row = _get(suite, operation)
        assert recovery.discharge(row, None, followup=False) is not None
        first = row.discharged_at
        assert recovery.discharge(row, None, followup=True) is None
        assert row.discharged_at == first
        assert row.followup_needed is False       # and the answer did not move


# ---------------------------------------------- the question nobody may skip --
def test_a_discharge_with_no_answer_is_refused(suite):
    """**The whole reason the column is nullable.** «مش محتاج» and «محدش سأل»
    stop being the same sentence only if something makes somebody say which."""
    from app.utils import recovery

    operation = _op(suite)
    with suite["app"].app_context():
        row = _get(suite, operation)
        assert recovery.discharge(row, None, followup=None) is None
        assert row.discharged_at is None
        assert row.followup_needed is None


def test_the_screen_refuses_it_too(suite):
    """Not only the helper: the form is where a blank actually arrives."""
    operation = _op(suite)
    client = suite["sign_in"]("boss")
    client.post(f"/theatres/operation/{operation}/discharge",
                data={"discharge_note": "تمام"}, follow_redirects=True)
    with suite["app"].app_context():
        assert _get(suite, operation).discharged_at is None

    client.post(f"/theatres/operation/{operation}/discharge",
                data={"followup": "no"}, follow_redirects=True)
    with suite["app"].app_context():
        row = _get(suite, operation)
        assert row.discharged_at is not None
        assert row.followup_needed is False


def test_no_means_no_date_is_kept(suite):
    """A date against a "no" puts a child on a list nobody meant to."""
    from app.utils import recovery

    operation = _op(suite)
    with suite["app"].app_context():
        row = _get(suite, operation)
        recovery.discharge(row, None, followup=False,
                           followup_on=date(2026, 4, 1))
        assert row.followup_needed is False
        assert row.followup_on is None


def test_yes_with_no_date_falls_back_to_the_procedures_usual_gap(suite):
    """The service carries the usual interval so nobody types it every time —
    and it is a default, never the decision."""
    from app.utils import recovery

    operation = _op(suite, "tonsils")
    with suite["app"].app_context():
        row = _get(suite, operation)
        recovery.discharge(row, None, followup=True)
        assert row.followup_on == row.on_date + timedelta(days=7)


def test_a_procedure_with_no_usual_gap_still_takes_a_typed_date(suite):
    """«الطهارة» does not routinely need one — which is not the same as
    refusing a surgeon who wants to see this particular child."""
    from app.utils import recovery

    operation = _op(suite, "circum")
    with suite["app"].app_context():
        row = _get(suite, operation)
        assert recovery.followup_default(row) is None
        recovery.discharge(row, None, followup=True,
                           followup_on=date(2026, 4, 10))
        assert row.followup_on == date(2026, 4, 10)


# -------------------------------------------------------- the instructions --
def test_the_instructions_are_the_ones_written_for_this_procedure(suite):
    from app.utils import recovery

    with suite["app"].app_context():
        assert "مشروبات باردة" in recovery.instructions_for(
            _get(suite, _op(suite, "tonsils")))
        assert "غيار يومي" in recovery.instructions_for(
            _get(suite, _op(suite, "circum")))


def test_a_procedure_with_nothing_written_sends_nothing(suite):
    """A message that says only «تعليمات بعد الجراحة:» and then stops is
    worse than no message."""
    from app.utils import recovery

    operation = _op(suite, "bare")
    with suite["app"].app_context():
        row = _get(suite, operation)
        assert recovery.instructions_for(row) is None
        assert recovery.send_instructions(row, None) is None
        assert row.instructions_sent_at is None


def test_the_family_is_sent_the_surgeons_own_words(suite):
    """Through the same door every other message goes out of — same opt-out,
    same log — because a clinic that silenced its messages silenced this one."""
    from app.models import MessageLog
    from app.utils import recovery

    operation = _op(suite, "tonsils")
    with suite["app"].app_context():
        row = _get(suite, operation)
        recovery.discharge(row, None, followup=True)
        log = recovery.send_instructions(row, None)
        suite["db"].session.commit()

        assert log is not None
        assert "مشروبات باردة" in log.body
        assert log.template_type == "post_op"
        assert log.patient_id == suite["ids"]["kid"]
        assert row.instructions_sent_at is not None
        assert MessageLog.query.count() == 1


def test_a_family_with_no_phone_is_not_a_crash(suite):
    from app.models import Patient
    from app.utils import recovery

    operation = _op(suite, "tonsils")
    with suite["app"].app_context():
        suite["db"].session.get(
            Patient, suite["ids"]["kid"]).own_phone = None
        suite["db"].session.commit()
        row = _get(suite, operation)
        assert recovery.send_instructions(row, None) is None
        assert row.instructions_sent_at is None


def test_discharging_from_the_screen_sends_them(suite):
    from app.models import MessageLog

    operation = _op(suite, "tonsils")
    suite["sign_in"]("boss").post(
        f"/theatres/operation/{operation}/discharge",
        data={"followup": "yes"}, follow_redirects=True)
    with suite["app"].app_context():
        assert _get(suite, operation).instructions_sent_at is not None
        assert "مشروبات باردة" in MessageLog.query.one().body


# --------------------------------------------------------------- the lists --
def test_the_case_nobody_marked_still_shows_on_the_discharge_list(suite):
    """**The list that matters.** A discharge list built only out of the
    recovery room would never show the child somebody wheeled out without
    pressing anything — and that is exactly the one being forgotten."""
    from app.utils import recovery

    marked = _op(suite, "tonsils")
    unmarked = _op(suite, "circum")
    with suite["app"].app_context():
        recovery.to_recovery(_get(suite, marked), None)
        suite["db"].session.commit()

        assert [o.id for o in recovery.in_recovery()] == [marked]
        assert set(o.id for o in recovery.awaiting_discharge()) == {
            marked, unmarked}


def test_the_room_empties_as_children_go_home(suite):
    from app.utils import recovery

    operation = _op(suite)
    with suite["app"].app_context():
        row = _get(suite, operation)
        recovery.to_recovery(row, None)
        suite["db"].session.commit()
        assert len(recovery.in_recovery()) == 1

        recovery.discharge(row, None, followup=False)
        suite["db"].session.commit()
        assert recovery.in_recovery() == []
        assert recovery.awaiting_discharge() == []


def test_a_child_wheeled_straight_out_still_has_a_recovery_moment(suite):
    """They were plainly in the room; leaving the stamp empty is a hole in the
    record, not an honest blank."""
    from app.utils import recovery

    operation = _op(suite)
    with suite["app"].app_context():
        row = _get(suite, operation)
        assert row.recovery_at is None
        recovery.discharge(row, None, followup=False)
        assert row.recovery_at == row.discharged_at


def test_who_is_expected_back_is_a_list_somebody_can_read(suite):
    """Recording "yes, in ten days" and having no list of who that was is the
    same as not recording it."""
    from app.utils import recovery

    coming = _op(suite, "tonsils")
    not_coming = _op(suite, "circum")
    with suite["app"].app_context():
        recovery.discharge(_get(suite, coming), None, followup=True)
        recovery.discharge(_get(suite, not_coming), None, followup=False)
        suite["db"].session.commit()
        assert [o.id for o in recovery.expecting()] == [coming]


def test_the_undecided_list_is_empty_because_the_discharge_refuses(suite):
    """What lands here are the cases sent home before the question existed —
    which is why the query exists at all."""
    from app.utils import recovery

    operation = _op(suite)
    with suite["app"].app_context():
        row = _get(suite, operation)
        recovery.discharge(row, None, followup=False)
        suite["db"].session.commit()
        assert recovery.undecided() == []

        # …and the old case, discharged before anybody was asked.
        row.followup_needed = None
        suite["db"].session.commit()
        assert [o.id for o in recovery.undecided()] == [operation]


def test_the_screens_draw(suite):
    operation = _op(suite, "tonsils")
    client = suite["sign_in"]("boss")
    assert client.get("/theatres/recovery").status_code == 200
    page = client.get(f"/theatres/operation/{operation}").get_data(as_text=True)
    assert "مشروبات باردة" in page      # said before the discharge is pressed
    assert client.get("/theatres/").status_code == 200
    assert client.get("/finance/services").status_code == 200
