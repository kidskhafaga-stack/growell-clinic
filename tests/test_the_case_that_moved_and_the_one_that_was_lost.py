"""Postponed is not cancelled — and how long it was meant to take.

The rest of GAHAR SAS.02, which is two things.

**(ب) — the time on the booking.** The standard asks that a booking *"specify
the start time and end time for surgery based on the international surgery
times"*, and its third item of evidence asks for a process for booking elective
procedures *"and determining the needed time for each procedure"*.

The program **holds no table of surgery times and will not invent one** — the
same rule that keeps invented vaccine thresholds out of the code. So the clinic
writes the number it works to, once, on the procedure; the booking offers it;
the end time is derived; and the case screen shows planned beside actual. It
measures. It does not judge: no target, no "ran late", and the difference is
**signed**, because a case that finished twenty minutes early is as much a
booking worth looking at as one that ran twenty minutes over.

And it is written on **the column that was already there**. ``Service.
duration_minutes`` has had an edit box on the price list for a long time and
nothing read it. A second "how long does this take" column beside it would have
made the answer depend on which of two screens somebody happened to fill in.

**Evidence 4 — two numbers, not one.** *"There is a process for analyzing
**postponed and canceled** procedures, and action is taken to improve them."* A
theatre with thirty postponements and two cancellations is booking badly; one
with two postponements and thirty cancellations is losing its cases, and a
single "called off" count answers neither.

A postponement is **a cancellation that has a successor** — not a fifth
``status``. That word is read by name elsewhere in this codebase (``is_open``,
the billing query), and a new one would quietly change what every one of those
places means. So the case is cancelled exactly as it always was, the
replacement is an ordinary booking, and ``postponed_to_id`` joins them.

And the reasons are grouped **as written**: the program ships no list of
cancellation reasons and invents none. A call-off with nothing written gets its
own row, named for what it is — not "other".
"""
import os
import sys
from datetime import date, datetime, time, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def theatre_day():
    from app import create_app
    from app.extensions import db

    app = create_app("testing")
    with app.app_context():
        db.create_all()
        from app.models import Patient, Service, Setting, User
        from app.models.theatre import Operation, Theatre
        from app.utils.clock import local_today

        Setting.set("mod_enabled:theatres", "1")
        Setting.set("mod_enabled:finance", "1")
        boss = User(username="boss", full_name="المدير", role="admin",
                    is_active=True)
        boss.set_password("secret")
        # Two rooms, and the case is in the second one — a fixture with a
        # single room cannot tell "kept its own room" from "took whichever
        # room came first", which is a real way for a replacement booking to
        # end up somewhere nobody chose.
        first = Theatre(name="غرفة ١", sort_order=1)
        room = Theatre(name="غرفة ٢", sort_order=2)
        # Ninety minutes, written once by the clinic on the procedure itself.
        tonsils = Service(name="استئصال لوز", code="SVC-T", price=1000,
                          category="procedure", duration_minutes=90)
        # And one nobody has timed, which stays an honest blank.
        untimed = Service(name="ختان", code="SVC-C", price=500,
                          category="procedure")
        db.session.add_all([boss, first, room, tonsils, untimed])
        db.session.flush()
        kid = Patient(patient_number="P1", full_name="طفل", gender="male",
                      is_active=True,
                      date_of_birth=local_today() - timedelta(days=1500))
        db.session.add(kid)
        db.session.flush()
        case = Operation(patient_id=kid.id, theatre_id=room.id,
                         procedure="لوز", on_date=local_today(),
                         service_id=tonsils.id, surgeon_id=boss.id,
                         start_time=time(9, 0), minutes=90,
                         team="فريق أ", status="scheduled")
        db.session.add(case)
        db.session.commit()
        ids = {"boss": boss.id, "case": case.id, "room": room.id,
               "first_room": first.id, "kid": kid.id,
               "timed": tonsils.id, "untimed": untimed.id}

    def sign_in(username="boss"):
        client = app.test_client()
        client.post("/login", data={"username": username, "password": "secret"},
                    follow_redirects=True)
        return client

    return {"app": app, "db": db, "ids": ids, "sign_in": sign_in}


def _case(ctx, which="case"):
    from app.models.theatre import Operation
    return ctx["db"].session.get(Operation, ctx["ids"][which])


def _boss(ctx):
    from app.models import User
    return ctx["db"].session.get(User, ctx["ids"]["boss"])


def _service(ctx, which="timed"):
    from app.models import Service
    return ctx["db"].session.get(Service, ctx["ids"][which])


def _another(ctx, **fields):
    """One more case on the list, so a period has something in it."""
    from app.models.theatre import Operation

    row = Operation(patient_id=ctx["ids"]["kid"], theatre_id=ctx["ids"]["room"],
                    procedure=fields.pop("procedure", "حالة"),
                    on_date=fields.pop("on_date", None) or _case(ctx).on_date,
                    status=fields.pop("status", "scheduled"), **fields)
    ctx["db"].session.add(row)
    ctx["db"].session.commit()
    return row


# ------------------------------------- how long it was meant to take ------
def test_the_usual_time_is_read_off_the_column_that_already_existed(theatre_day):
    """``Service.duration_minutes``, not a second column beside it.

    It had an edit box on the price list and no reader. Adding
    ``expected_minutes`` next to it would have been one fact in two places,
    with the answer depending on which screen somebody had filled in.
    """
    from app.models import Service
    from app.utils import theatres as theatre

    with theatre_day["app"].app_context():
        assert theatre.expected_minutes(_service(theatre_day)) == 90
        # And nothing else on the model claims to hold the same answer.
        assert not hasattr(Service, "expected_minutes")


def test_a_procedure_nobody_timed_offers_nothing(theatre_day):
    """Blank stays blank. A guessed number here would be the program inventing
    the "international surgery times" it does not hold."""
    from app.utils import theatres as theatre

    with theatre_day["app"].app_context():
        assert theatre.expected_minutes(_service(theatre_day, "untimed")) is None
        assert theatre.expected_minutes(None) is None


def test_zero_minutes_is_nobody_answered_not_no_time(theatre_day):
    """A procedure that takes no time is not something anybody meant — and
    letting a zero through would prefill every booking of it with nothing and
    call that an answer."""
    from app.utils import theatres as theatre

    with theatre_day["app"].app_context():
        row = _service(theatre_day)
        row.duration_minutes = 0
        theatre_day["db"].session.commit()
        assert theatre.expected_minutes(row) is None


def test_the_end_time_is_derived_from_the_start_and_the_length(theatre_day):
    """SAS.02 (ب) asks a booking to carry a start **and** an end. Derived,
    never stored: a case moved half an hour later must not keep an end time
    that belongs to where it used to be."""
    from app.utils import theatres as theatre

    with theatre_day["app"].app_context():
        assert theatre.planned_end(_case(theatre_day)) == time(10, 30)

        # Moved, and the end moves with it — with nothing else touched.
        row = _case(theatre_day)
        row.start_time = time(11, 15)
        theatre_day["db"].session.commit()
        assert theatre.planned_end(_case(theatre_day)) == time(12, 45)


def test_an_end_time_needs_both_halves(theatre_day):
    """One half of an answer is not half an end time — it is none."""
    from app.utils import theatres as theatre

    with theatre_day["app"].app_context():
        row = _case(theatre_day)
        row.minutes = None
        theatre_day["db"].session.commit()
        assert theatre.planned_end(_case(theatre_day)) is None

        row = _case(theatre_day)
        row.minutes, row.start_time = 60, None
        theatre_day["db"].session.commit()
        assert theatre.planned_end(_case(theatre_day)) is None
        assert theatre.planned_end(None) is None


def test_a_case_running_past_midnight_gives_the_wall_clock(theatre_day):
    """What prints on a theatre list is a time; the list carries its own date
    at the top."""
    from app.utils import theatres as theatre

    with theatre_day["app"].app_context():
        row = _case(theatre_day)
        row.start_time, row.minutes = time(23, 30), 120
        theatre_day["db"].session.commit()
        assert theatre.planned_end(_case(theatre_day)) == time(1, 30)


def test_the_actual_length_comes_from_the_stamps_already_made(theatre_day):
    """Knife to close, off the two moments the theatre already records — so
    the measurement costs nobody a keystroke."""
    from app.utils import theatres as theatre

    with theatre_day["app"].app_context():
        row = _case(theatre_day)
        row.started_at = datetime(2026, 3, 1, 9, 5)
        row.finished_at = datetime(2026, 3, 1, 10, 50)
        theatre_day["db"].session.commit()
        assert theatre.actual_minutes(_case(theatre_day)) == 105


def test_a_case_with_one_stamp_has_an_unknown_length_not_a_short_one(theatre_day):
    from app.utils import theatres as theatre

    with theatre_day["app"].app_context():
        row = _case(theatre_day)
        row.started_at = datetime(2026, 3, 1, 9, 5)
        theatre_day["db"].session.commit()
        assert theatre.actual_minutes(_case(theatre_day)) is None
        assert theatre.actual_minutes(None) is None


def test_the_difference_is_signed_in_both_directions(theatre_day):
    """**Measured, not judged.** A case that finished twenty minutes early is
    as much a booking worth looking at as one that ran twenty over — and an
    unsigned "overrun" would hide half of them."""
    from app.utils import theatres as theatre

    with theatre_day["app"].app_context():
        row = _case(theatre_day)
        row.started_at = datetime(2026, 3, 1, 9, 0)
        row.finished_at = datetime(2026, 3, 1, 11, 0)   # 120 against 90
        theatre_day["db"].session.commit()
        assert theatre.time_plan(_case(theatre_day))["difference"] == 30

        row = _case(theatre_day)
        row.finished_at = datetime(2026, 3, 1, 10, 0)   # 60 against 90
        theatre_day["db"].session.commit()
        assert theatre.time_plan(_case(theatre_day))["difference"] == -30


def test_no_difference_where_one_of_the_numbers_was_never_written(theatre_day):
    """A difference measured from a number nobody wrote is not a small
    difference — it is no difference at all."""
    from app.utils import theatres as theatre

    with theatre_day["app"].app_context():
        row = _case(theatre_day)
        row.minutes = None
        row.started_at = datetime(2026, 3, 1, 9, 0)
        row.finished_at = datetime(2026, 3, 1, 11, 0)
        theatre_day["db"].session.commit()
        plan = theatre.time_plan(_case(theatre_day))
        assert plan["actual"] == 120
        assert plan["planned"] is None
        assert plan["difference"] is None


def test_what_this_booking_got_and_what_the_procedure_usually_gets_stay_apart(
        theatre_day):
    """Two numbers, kept apart on purpose: a case booked at half the clinic's
    own usual length is visible **before** the morning it overruns, and only
    two separate numbers can show that."""
    from app.utils import theatres as theatre

    with theatre_day["app"].app_context():
        row = _case(theatre_day)
        row.minutes = 45
        theatre_day["db"].session.commit()
        plan = theatre.time_plan(_case(theatre_day))
        assert plan["planned"] == 45
        assert plan["usual"] == 90


def test_a_zero_on_the_booking_is_nobody_answered_too(theatre_day):
    """The same rule as the procedure's usual time, one field along: a case
    booked for no minutes was not booked for none, it was booked by somebody
    who never filled the box in — and measuring an overrun against zero would
    make every such case look catastrophic."""
    from app.utils import theatres as theatre

    with theatre_day["app"].app_context():
        row = _case(theatre_day)
        row.minutes = 0
        row.started_at = datetime(2026, 3, 1, 9, 0)
        row.finished_at = datetime(2026, 3, 1, 10, 0)
        theatre_day["db"].session.commit()
        plan = theatre.time_plan(_case(theatre_day))
        assert plan["planned"] is None
        assert plan["difference"] is None
        assert theatre.planned_end(_case(theatre_day)) is None


def test_no_case_is_an_empty_plan_not_a_crash(theatre_day):
    from app.utils import theatres as theatre

    with theatre_day["app"].app_context():
        assert theatre.time_plan(None) == {
            "start": None, "end": None, "planned": None, "usual": None,
            "actual": None, "difference": None}


def test_the_booking_form_offers_the_clinics_own_number(theatre_day):
    """It offers, it does not decide: the box is filled only while it is
    empty, so a number somebody typed is never overwritten by one the program
    guessed."""
    with theatre_day["app"].app_context():
        html = theatre_day["sign_in"]().get("/theatres/").get_data(as_text=True)
    assert 'data-minutes="90"' in html
    # A procedure nobody timed offers nothing rather than a zero.
    assert 'data-minutes=""' in html
    assert 'x-ref="minutes"' in html
    # And the emptiness guard is the whole point of the prefill.
    assert "!this.$refs.minutes.value" in html


def test_the_case_screen_shows_planned_beside_actual(theatre_day):
    from app.i18n import translate as t

    with theatre_day["app"].app_context():
        row = _case(theatre_day)
        row.started_at = datetime(2026, 3, 1, 9, 0)
        row.finished_at = datetime(2026, 3, 1, 11, 0)
        theatre_day["db"].session.commit()
        client = theatre_day["sign_in"]()
        html = client.get("/theatres/operation/%s" % theatre_day["ids"]["case"]
                          ).get_data(as_text=True)
        assert t("theatre.planned_minutes", n=90) in html
        assert t("theatre.actual_minutes", n=120) in html
        assert t("theatre.usual_minutes", n=90) in html
        # The start and the derived end, both on the page.
        assert "09:00" in html and "10:30" in html


# --------------------------------------- postponed is not cancelled -------
def test_an_open_case_was_not_called_off_at_all(theatre_day):
    with theatre_day["app"].app_context():
        assert _case(theatre_day).called_off_as is None


def test_a_cancelled_case_with_no_successor_reads_as_cancelled(theatre_day):
    """The reading nothing already written changes: a plain cancel is still a
    cancel, exactly as it was before any of this existed."""
    from app.utils import theatres as theatre

    with theatre_day["app"].app_context():
        theatre.cancel(_case(theatre_day), reason="الأهل ما جوش",
                       user=_boss(theatre_day))
        theatre_day["db"].session.commit()
        row = _case(theatre_day)
        assert row.status == "cancelled"
        assert row.called_off_as == "cancelled"
        assert row.postponed_to_id is None


def test_postponing_closes_this_case_and_books_the_next_one(theatre_day):
    from app.utils import theatres as theatre

    with theatre_day["app"].app_context():
        moved = theatre.postpone(_case(theatre_day),
                                 _case(theatre_day).on_date + timedelta(days=7),
                                 reason="الأوضة مش فاضية",
                                 user=_boss(theatre_day))
        theatre_day["db"].session.commit()
        old = _case(theatre_day)
        assert old.status == "cancelled"
        assert old.cancel_reason == "الأوضة مش فاضية"
        assert old.called_off_as == "postponed"
        assert old.postponed_to_id == moved.id
        assert moved.status == "scheduled"
        assert moved.on_date == old.on_date + timedelta(days=7)


def test_the_moved_case_is_the_same_case_on_another_day(theatre_day):
    """Retyping it is how the second booking quietly ends up different from
    the first."""
    from app.utils import theatres as theatre

    with theatre_day["app"].app_context():
        old_room = _case(theatre_day).theatre_id
        moved = theatre.postpone(_case(theatre_day), date(2026, 5, 1),
                                 user=_boss(theatre_day))
        theatre_day["db"].session.commit()
        # Its own room, and provably not just the first room in the building.
        assert moved.theatre_id == old_room
        assert moved.theatre_id != theatre_day["ids"]["first_room"]
        assert moved.patient_id == theatre_day["ids"]["kid"]
        assert moved.procedure == "لوز"
        assert moved.service_id == theatre_day["ids"]["timed"]
        assert moved.surgeon_id == theatre_day["ids"]["boss"]
        assert moved.start_time == time(9, 0)
        assert moved.minutes == 90
        assert moved.team == "فريق أ"


def test_a_case_moved_to_a_later_slot_the_same_day_is_still_a_move(theatre_day):
    """A case bumped to the afternoon is a real postponement, and refusing it
    would push somebody into the cancel box."""
    from app.utils import theatres as theatre

    with theatre_day["app"].app_context():
        same_day = _case(theatre_day).on_date
        moved = theatre.postpone(_case(theatre_day), same_day,
                                 user=_boss(theatre_day))
        theatre_day["db"].session.commit()
        assert moved is not None
        assert _case(theatre_day).called_off_as == "postponed"


def test_postponing_with_no_day_is_refused_and_changes_nothing(theatre_day):
    """A postponement to nowhere is a cancellation, and the two must not be
    the same button."""
    from app.models.theatre import Operation
    from app.utils import theatres as theatre

    with theatre_day["app"].app_context():
        before = Operation.query.count()
        with pytest.raises(ValueError):
            theatre.postpone(_case(theatre_day), None, user=_boss(theatre_day))
        theatre_day["db"].session.rollback()
        assert Operation.query.count() == before
        assert _case(theatre_day).status == "scheduled"


def test_a_case_already_called_off_cannot_be_moved_again(theatre_day):
    """Nothing open to move — and the link already written is not overwritten
    by a second attempt."""
    from app.utils import theatres as theatre

    with theatre_day["app"].app_context():
        moved = theatre.postpone(_case(theatre_day), date(2026, 5, 1),
                                 user=_boss(theatre_day))
        theatre_day["db"].session.commit()
        assert theatre.postpone(_case(theatre_day), date(2026, 6, 1),
                                user=_boss(theatre_day)) is None
        theatre_day["db"].session.commit()
        assert _case(theatre_day).postponed_to_id == moved.id


def test_a_finished_case_cannot_be_moved(theatre_day):
    from app.utils import theatres as theatre

    with theatre_day["app"].app_context():
        row = _case(theatre_day)
        row.status = "done"
        theatre_day["db"].session.commit()
        assert theatre.postpone(_case(theatre_day), date(2026, 5, 1),
                                user=_boss(theatre_day)) is None
        assert _case(theatre_day).called_off_as is None
        assert theatre.postpone(None, date(2026, 5, 1)) is None


# ------------------------------------------ what the theatre lost ---------
def test_the_two_numbers_are_counted_apart(theatre_day):
    """SAS.02's fourth item of evidence names **two** things, and a theatre
    can only ever have two numbers if the two were told apart on the day."""
    from app.utils import theatres as theatre

    with theatre_day["app"].app_context():
        day = _case(theatre_day).on_date
        lost = _another(theatre_day, procedure="فتق")
        theatre.cancel(lost, reason="الطفل بيكح", user=_boss(theatre_day))
        theatre.postpone(_case(theatre_day), day + timedelta(days=3),
                         reason="الأوضة مش فاضية", user=_boss(theatre_day))
        theatre_day["db"].session.commit()

        summary = theatre.calloff_analysis(day, day)
        assert summary["postponed"] == 1
        assert summary["cancelled"] == 1


def test_a_call_off_counts_on_the_day_the_list_had_the_hole(theatre_day):
    """Not the day somebody pressed cancel: a case cancelled in March off an
    April list is April's hole."""
    from app.utils import theatres as theatre

    with theatre_day["app"].app_context():
        day = _case(theatre_day).on_date
        theatre.cancel(_case(theatre_day), reason="سبب", user=_boss(theatre_day))
        theatre_day["db"].session.commit()
        assert theatre.calloff_analysis(day, day)["cancelled"] == 1
        # The same call-off, read over a period the *case* was never on.
        gone = day + timedelta(days=30)
        assert theatre.calloff_analysis(gone, gone)["cancelled"] == 0


def test_the_reasons_are_grouped_exactly_as_they_were_written(theatre_day):
    """Deciding that two spellings mean the same thing is a judgement about
    this clinic's own words, and only this clinic can make it."""
    from app.utils import theatres as theatre

    with theatre_day["app"].app_context():
        day = _case(theatre_day).on_date
        for text in ("عدوى صدر", "عدوى صدر", "الطفل بيكح"):
            theatre.cancel(_another(theatre_day), reason=text,
                           user=_boss(theatre_day))
        theatre_day["db"].session.commit()

        # Two that start the same way, so the grouping is proved to be on the
        # whole sentence rather than on however much of it fits somewhere.
        theatre.cancel(_another(theatre_day), reason="عدوى بولية",
                       user=_boss(theatre_day))
        theatre_day["db"].session.commit()

        rows = theatre.calloff_analysis(day, day)["reasons"]
        assert [(r["reason"], r["total"]) for r in rows] == [
            ("عدوى صدر", 2), ("الطفل بيكح", 1), ("عدوى بولية", 1)]


def test_a_call_off_with_nothing_written_gets_its_own_row(theatre_day):
    """**Not "other".** A theatre where half the call-offs carry no reason
    cannot improve anything, and that is the first finding this has to be able
    to show."""
    from app.utils import theatres as theatre

    with theatre_day["app"].app_context():
        day = _case(theatre_day).on_date
        theatre.cancel(_another(theatre_day), reason="عدوى صدر",
                       user=_boss(theatre_day))
        theatre.cancel(_another(theatre_day), reason="   ",
                       user=_boss(theatre_day))
        theatre_day["db"].session.commit()

        rows = theatre.calloff_analysis(day, day)["reasons"]
        keyed = {r["reason"]: r["total"] for r in rows}
        assert keyed == {"عدوى صدر": 1, None: 1}


def test_each_reason_row_splits_the_two_kinds_as_well(theatre_day):
    """The same reason can be behind both a move and a loss, and one column
    would hide which."""
    from app.utils import theatres as theatre

    with theatre_day["app"].app_context():
        day = _case(theatre_day).on_date
        theatre.cancel(_another(theatre_day), reason="الأوضة مش فاضية",
                       user=_boss(theatre_day))
        theatre.postpone(_case(theatre_day), day + timedelta(days=2),
                         reason="الأوضة مش فاضية", user=_boss(theatre_day))
        theatre_day["db"].session.commit()

        rows = theatre.calloff_analysis(day, day)["reasons"]
        assert len(rows) == 1
        assert rows[0] == {"reason": "الأوضة مش فاضية", "postponed": 1,
                           "cancelled": 1, "total": 2}


def test_the_reasons_come_back_commonest_first(theatre_day):
    from app.utils import theatres as theatre

    with theatre_day["app"].app_context():
        day = _case(theatre_day).on_date
        for text in ("واحد", "تلاتة", "تلاتة", "تلاتة", "اتنين", "اتنين"):
            theatre.cancel(_another(theatre_day), reason=text,
                           user=_boss(theatre_day))
        theatre_day["db"].session.commit()
        rows = theatre.calloff_analysis(day, day)["reasons"]
        assert [r["total"] for r in rows] == [3, 2, 1]


def test_the_call_offs_are_counted_against_everything_booked(theatre_day):
    """A count of call-offs with no denominator is a number that grows with
    the theatre and means nothing on its own — and the called-off cases are in
    the denominator, because they were booked."""
    from app.utils import theatres as theatre

    with theatre_day["app"].app_context():
        day = _case(theatre_day).on_date
        _another(theatre_day)
        _another(theatre_day)
        theatre.cancel(_case(theatre_day), reason="سبب", user=_boss(theatre_day))
        theatre_day["db"].session.commit()
        summary = theatre.calloff_analysis(day, day)
        assert summary["booked"] == 3
        assert summary["cancelled"] == 1


def test_a_period_with_one_open_end_still_narrows(theatre_day):
    """«من أول الشهر» and «لحد النهاردة» are both real questions."""
    from app.utils import theatres as theatre

    with theatre_day["app"].app_context():
        day = _case(theatre_day).on_date
        old = _another(theatre_day, on_date=day - timedelta(days=40))
        theatre.cancel(old, reason="قديمة", user=_boss(theatre_day))
        theatre.cancel(_case(theatre_day), reason="جديدة",
                       user=_boss(theatre_day))
        theatre_day["db"].session.commit()

        # And one the other side of the period, so each end is doing work:
        # a report for last month must not pick up this month's losses.
        later = _another(theatre_day, on_date=day + timedelta(days=40))
        theatre.cancel(later, reason="بعدين", user=_boss(theatre_day))
        theatre_day["db"].session.commit()

        assert theatre.calloff_analysis(start=day)["cancelled"] == 2
        assert theatre.calloff_analysis(end=day)["cancelled"] == 2
        assert theatre.calloff_analysis(day, day)["cancelled"] == 1
        assert theatre.calloff_analysis()["cancelled"] == 3


def test_the_list_of_call_offs_carries_the_cases_themselves(theatre_day):
    """Counting is the first half; the second is being able to look at the
    cases the counts came from."""
    from app.utils import theatres as theatre

    with theatre_day["app"].app_context():
        day = _case(theatre_day).on_date
        theatre.cancel(_case(theatre_day), reason="سبب", user=_boss(theatre_day))
        theatre_day["db"].session.commit()
        rows = theatre.call_offs(day, day)
        assert [r.id for r in rows] == [theatre_day["ids"]["case"]]
        # And an open case is not on it.
        _another(theatre_day)
        assert len(theatre.call_offs(day, day)) == 1


# ---------------------------------------------------- through the screen --
def test_the_postpone_button_moves_the_case_and_lands_on_the_new_one(theatre_day):
    """The new case is where the work now is."""
    from app.models.theatre import Operation

    with theatre_day["app"].app_context():
        day = _case(theatre_day).on_date
        client = theatre_day["sign_in"]()
        reply = client.post(
            "/theatres/operation/%s/postpone" % theatre_day["ids"]["case"],
            data={"date": (day + timedelta(days=5)).isoformat(),
                  "reason": "الجرّاح مسافر"}, follow_redirects=False)
        assert reply.status_code in (301, 302)
        old = _case(theatre_day)
        assert old.called_off_as == "postponed"
        moved = theatre_day["db"].session.get(Operation, old.postponed_to_id)
        assert reply.headers["Location"].endswith("/operation/%s" % moved.id)


def test_the_postpone_button_with_no_day_says_so_and_books_nothing(theatre_day):
    from app.i18n import translate as t
    from app.models.theatre import Operation

    with theatre_day["app"].app_context():
        before = Operation.query.count()
        client = theatre_day["sign_in"]()
        html = client.post(
            "/theatres/operation/%s/postpone" % theatre_day["ids"]["case"],
            data={"reason": "كده"}, follow_redirects=True).get_data(as_text=True)
        assert t("theatre.postpone_needs_date") in html
        assert Operation.query.count() == before
        assert _case(theatre_day).status == "scheduled"


def test_a_case_that_was_moved_links_to_the_one_it_became(theatre_day):
    """One click, rather than somebody searching the child's name for it."""
    from app.i18n import translate as t
    from app.utils import theatres as theatre

    with theatre_day["app"].app_context():
        moved = theatre.postpone(_case(theatre_day), date(2026, 5, 1),
                                 user=_boss(theatre_day))
        theatre_day["db"].session.commit()
        html = theatre_day["sign_in"]().get(
            "/theatres/operation/%s" % theatre_day["ids"]["case"]
        ).get_data(as_text=True)
        assert t("theatre.moved_to_case") in html
        assert "/theatres/operation/%s" % moved.id in html


def test_the_analysis_screen_shows_both_numbers_and_the_reasons(theatre_day):
    from app.i18n import translate as t
    from app.utils import theatres as theatre

    with theatre_day["app"].app_context():
        day = _case(theatre_day).on_date
        theatre.cancel(_another(theatre_day), reason="عدوى صدر",
                       user=_boss(theatre_day))
        theatre.postpone(_case(theatre_day), day + timedelta(days=2),
                         reason="الأوضة مش فاضية", user=_boss(theatre_day))
        theatre_day["db"].session.commit()

        html = theatre_day["sign_in"]().get(
            "/theatres/call-offs?start=%s&end=%s" % (day, day)
        ).get_data(as_text=True)
        # The numbers themselves, not the words beside them: both labels are
        # also column headings in the table below, so a page that had lost the
        # summary entirely would still carry them.
        assert 'data-postponed="1"' in html
        assert 'data-cancelled="1"' in html
        assert 'data-booked="2"' in html
        # And the by-reason table, named so that a page showing the reasons
        # only in the list of cases underneath cannot stand in for it.
        assert html.count("data-reason-row") == 2
        assert "عدوى صدر" in html
        assert "الأوضة مش فاضية" in html


def test_the_analysis_screen_names_the_call_offs_nobody_explained(theatre_day):
    """The blank is shown as a finding, not as a blank cell."""
    from app.i18n import translate as t
    from app.utils import theatres as theatre

    with theatre_day["app"].app_context():
        day = _case(theatre_day).on_date
        theatre.cancel(_case(theatre_day), user=_boss(theatre_day))
        theatre_day["db"].session.commit()
        html = theatre_day["sign_in"]().get(
            "/theatres/call-offs?start=%s&end=%s" % (day, day)
        ).get_data(as_text=True)
        # Twice: once in the by-reason table and once against the case itself.
        # One of the two alone would let the other go blank unnoticed.
        assert html.count(t("theatre.no_reason_written")) == 2


def test_a_quiet_period_says_so_rather_than_showing_an_empty_table(theatre_day):
    from app.i18n import translate as t

    with theatre_day["app"].app_context():
        day = _case(theatre_day).on_date
        html = theatre_day["sign_in"]().get(
            "/theatres/call-offs?start=%s&end=%s" % (day, day)
        ).get_data(as_text=True)
        assert t("theatre.no_calloffs") in html


def test_the_day_screen_reaches_the_analysis(theatre_day):
    """Beside the privileges screen, because the people who read it are the
    people who draw up the list."""
    with theatre_day["app"].app_context():
        html = theatre_day["sign_in"]().get("/theatres/").get_data(as_text=True)
        assert "/theatres/call-offs" in html


def test_the_day_list_says_a_moved_case_was_moved(theatre_day):
    """Without this the row reads «cancelled», which is the exact confusion
    the fourth item of evidence exists to remove — and the day it went to is
    what whoever is reading the list actually wants."""
    from app.i18n import translate as t
    from app.utils import theatres as theatre

    with theatre_day["app"].app_context():
        day = _case(theatre_day).on_date
        theatre.postpone(_case(theatre_day), day + timedelta(days=4),
                         user=_boss(theatre_day))
        theatre_day["db"].session.commit()
        html = theatre_day["sign_in"]().get(
            "/theatres/?date=%s" % day).get_data(as_text=True)
        assert "data-moved" in html
        assert t("theatre.postponed_to_day") in html
        assert str(day + timedelta(days=4)) in html
