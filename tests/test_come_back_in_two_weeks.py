"""«تعالى بعد أسبوعين» — وهل جه؟ GAHAR ICD.05 evidence 5.

> *"The plans of care and **follow-up instructions** are recorded in the
> patient's medical records."*

The instruction was nowhere in this program. `Visit.plan` is what the doctor
decided; it is not what the family was told on the way out, and the two are
read by different people months apart.

What is tested here, in the order it matters:

1. **The instruction alone is half the fact.** A file that says «ارجع بعد
   أسبوعين» and cannot say whether they did is the half that was never worth
   writing down. Every row needed to answer it was already in the database, in
   two tables nothing joined.
2. **The state is derived, never stored.** It is right the moment reception
   books an appointment, without anybody telling the visit anything — and
   every visit recorded before this existed reads `none`, which is true,
   because nobody was ever asked.
3. **Two instructions, not one.** «تعالى بعد أسبوعين» has a date; «تعالى فوراً
   لو سخن» is the safety net that brings a child back *before* it. One box
   holding both would let a booked appointment stand in for having given one.
4. **«جه» beats everything**, and a rebooking beats a missed one — the same
   rule `no_show` follows before it sends anything.
5. **It tells, it never blocks**, and nothing here books or sends anything.
"""
import os
import sys
from datetime import date, time, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

from app.utils.clock import local_today  # noqa: E402

# **The clinic's today, never the machine's.**
#
# This file first wrote its dates with `date.today()`, and CI went red at
# 22:41 UTC — when it is already tomorrow in Cairo. `followup.state` asks
# `local_today()`, correctly, so a due date of "the machine's today" was in the
# clinic's *past* and a child due back today read as overdue.
#
# Production was right and the test was wrong, which is the exact shape the
# conftest's docstring was written about: the suite has gone red in that window
# three separate times before this. `pytest --tz=Pacific/Midway` forces the two
# clocks eleven hours apart all day and is how this fix was checked.


@pytest.fixture()
def seen(clinic):
    """The clinic's child, with a second one so a missing filter cannot pass."""
    from app.models import Patient
    from app.utils.clock import local_today

    with clinic["app"].app_context():
        other = Patient(patient_number="FU-OTHER", full_name="طفل تاني",
                        gender="female", is_active=True,
                        date_of_birth=local_today() - timedelta(days=900))
        clinic["db"].session.add(other)
        clinic["db"].session.commit()
        clinic["ids"]["other_child"] = other.id
    return clinic


def _visit(clinic, patient_id=None, days_ago=0):
    from app.models import Visit
    from app.utils.clock import local_today

    with clinic["app"].app_context():
        visit = Visit(patient_id=patient_id or clinic["ids"]["child"],
                      doctor_id=clinic["ids"]["doctor"],
                      visit_date=local_today() - timedelta(days=days_ago))
        clinic["db"].session.add(visit)
        clinic["db"].session.commit()
        return visit.id


def _tell(clinic, visit_id, due=None, instructions=None):
    """Record the instruction the way the consultation screen does."""
    form = {}
    if due is not None:
        form["followup_due"] = due
    if instructions is not None:
        form["followup_instructions"] = instructions
    return clinic["sign_in"]("doc").post(f"/visits/{visit_id}/followup",
                                         data=form, follow_redirects=True)


def _book(clinic, patient_id, days_ahead=14, status="scheduled"):
    from app.models import Appointment
    from app.utils.clock import local_today

    with clinic["app"].app_context():
        row = Appointment(patient_id=patient_id,
                          doctor_id=clinic["ids"]["doctor"],
                          appt_date=local_today() + timedelta(days=days_ahead),
                          appt_time=time(10, 0), status=status)
        clinic["db"].session.add(row)
        clinic["db"].session.commit()
        return row.id


def _state(clinic, visit_id):
    from app.models import Visit
    from app.utils import followup

    with clinic["app"].app_context():
        return followup.state(Visit.query.get(visit_id))


# ------------------------------------------------ the instruction itself ----
def test_the_instruction_is_written_into_the_record(seen):
    """ICD.05 evidence 5 in one line. `Visit.plan` is what the doctor decided;
    this is what the family was told."""
    from app.models import Visit

    visit = _visit(seen)
    _tell(seen, visit, due="2027-01-20",
          instructions="ارجع فوراً لو سخن فوق ٣٩")

    with seen["app"].app_context():
        row = Visit.query.get(visit)
        assert row.followup_due == date(2027, 1, 20)
        assert row.followup_instructions == "ارجع فوراً لو سخن فوق ٣٩"


def test_a_safety_net_with_no_date_is_still_an_instruction(seen):
    """«تعالى فوراً لو سخن» has no date and is the instruction that matters
    most. Reading only the date would record that visit as having said
    nothing."""
    from app.models import Visit
    from app.utils import followup

    visit = _visit(seen)
    _tell(seen, visit, instructions="ارجع لو النَفَس اتضايق")

    with seen["app"].app_context():
        row = Visit.query.get(visit)
        assert row.followup_due is None
        assert followup.told(row) is True
    assert _state(seen, visit) == "told"


def test_a_date_with_no_words_is_also_an_instruction(seen):
    visit = _visit(seen)
    _tell(seen, visit, due=(local_today() + timedelta(days=30)).isoformat())

    assert _state(seen, visit) == "told"


def test_a_visit_nobody_asked_anything_of_says_so(seen):
    """Every visit recorded before this existed reads `none` — and that is
    true, because nobody was ever asked."""
    assert _state(seen, _visit(seen)) == "none"


def test_a_blank_date_clears_it_and_a_missing_one_does_not(seen):
    """A person emptying the box is a different act from a form that did not
    carry it — and the consultation screen has more than one form on it."""
    from app.models import Visit

    visit = _visit(seen)
    _tell(seen, visit, due="2027-01-20", instructions="لو سخن")

    # The safety net saved on its own, with no date field on that form.
    _tell(seen, visit, instructions="لو سخن أو قلّ أكله")
    with seen["app"].app_context():
        assert Visit.query.get(visit).followup_due == date(2027, 1, 20)

    # And the date emptied on purpose.
    _tell(seen, visit, due="")
    with seen["app"].app_context():
        row = Visit.query.get(visit)
        assert row.followup_due is None
        assert row.followup_instructions == "لو سخن أو قلّ أكله"


# ----------------------------------------------- and whether they came ----
def test_a_booking_answers_it_without_anybody_telling_the_visit(seen):
    """Derived, never stored: right the moment reception books."""
    visit = _visit(seen)
    _tell(seen, visit, due=(local_today() + timedelta(days=14)).isoformat())
    assert _state(seen, visit) == "told"

    _book(seen, seen["ids"]["child"], days_ahead=14)
    assert _state(seen, visit) == "booked"


def test_coming_back_beats_everything(seen):
    """A child who attended is not also missed, whatever was booked and broken
    along the way: the point of the instruction was that they come back."""
    visit = _visit(seen, days_ago=30)
    _tell(seen, visit, due=(local_today() - timedelta(days=5)).isoformat())
    _book(seen, seen["ids"]["child"], days_ahead=-3, status="no_show")
    _book(seen, seen["ids"]["child"], days_ahead=-1, status="completed")

    assert _state(seen, visit) == "came"


def test_a_rebooking_beats_a_missed_one_behind_it(seen):
    """The family that missed Tuesday and rebooked for Thursday is booked, not
    missed — the same rule `no_show` follows before it sends anything."""
    visit = _visit(seen, days_ago=30)
    _tell(seen, visit, due=(local_today() - timedelta(days=5)).isoformat())
    _book(seen, seen["ids"]["child"], days_ahead=-3, status="no_show")
    _book(seen, seen["ids"]["child"], days_ahead=4, status="scheduled")

    assert _state(seen, visit) == "booked"


def test_booked_and_never_came_is_its_own_state(seen):
    visit = _visit(seen, days_ago=30)
    _tell(seen, visit, due=(local_today() - timedelta(days=5)).isoformat())
    _book(seen, seen["ids"]["child"], days_ahead=-3, status="no_show")

    assert _state(seen, visit) == "missed"


def test_the_number_of_missed_bookings_is_the_errand(seen):
    """«اتحجزله ٣ مواعيد وما جاش في ولا واحد». One missed appointment is a
    family stuck in traffic; three is a child nobody has seen since a doctor
    said they needed to be seen."""
    from app.models import Visit
    from app.utils import followup

    visit = _visit(seen, days_ago=40)
    _tell(seen, visit, due=(local_today() - timedelta(days=20)).isoformat())
    for ago in (15, 10, 4):
        _book(seen, seen["ids"]["child"], days_ahead=-ago, status="no_show")

    with seen["app"].app_context():
        assert followup.missed_count(Visit.query.get(visit)) == 3
    assert _state(seen, visit) == "missed"


def test_a_date_that_passed_with_nothing_booked_is_overdue(seen):
    visit = _visit(seen)
    _tell(seen, visit, due=(local_today() - timedelta(days=2)).isoformat())

    assert _state(seen, visit) == "overdue"


def test_a_safety_net_alone_never_goes_overdue(seen):
    """«ارجع لو سخن» is a condition, not an appointment. Calling it overdue
    would put every visit in the clinic on a chasing list."""
    visit = _visit(seen, days_ago=400)
    _tell(seen, visit, instructions="ارجع لو سخن")

    assert _state(seen, visit) == "told"


def test_a_whitespace_instruction_is_not_an_instruction(seen):
    """Two guards, and both stay. The route strips on the way in so a row of
    spaces is never stored — and `told` strips on the way out so a row that
    got one anyway (an import, a script, a hand-edited database) does not read
    as a follow-up nobody gave. A guard from one side is half a rule.
    """
    from app.models import Visit
    from app.utils import followup

    visit = _visit(seen)
    _tell(seen, visit, instructions="   ")
    with seen["app"].app_context():
        row = Visit.query.get(visit)
        # the way in
        assert row.followup_instructions is None
        # and the way out, for a row that never came through the route
        row.followup_instructions = "   "
        seen["db"].session.commit()
        assert followup.told(row) is False


def test_the_day_itself_is_not_late(seen):
    """A child due back today has all day to come. Calling them overdue at
    midnight puts them on a chasing list the morning they were asked for."""
    visit = _visit(seen, days_ago=14)
    _tell(seen, visit, due=local_today().isoformat())

    assert _state(seen, visit) == "told"


def test_only_the_missed_bookings_are_counted(seen):
    """The number is «كام مرة غاب», not «كام ميعاد اتحجزله». A child booked
    four times who missed two has missed two."""
    from app.models import Visit
    from app.utils import followup

    visit = _visit(seen, days_ago=40)
    _tell(seen, visit, due=(local_today() - timedelta(days=20)).isoformat())
    _book(seen, seen["ids"]["child"], days_ahead=-15, status="no_show")
    _book(seen, seen["ids"]["child"], days_ahead=-10, status="no_show")
    _book(seen, seen["ids"]["child"], days_ahead=-5, status="cancelled")

    with seen["app"].app_context():
        assert followup.missed_count(Visit.query.get(visit)) == 2


def test_the_file_reads_the_same_rule_as_the_visit_does(seen):
    """`by_visit` draws the whole file in one query and once had its **own
    copy** of «does this booking belong to that consultation». A sweep showed
    the copy could be deleted with the suite still green — every test went
    through the other reader — so the two now share one definition, and this
    asserts the batched path gives the same answer.
    """
    from app.models import Visit
    from app.utils import followup

    visit = _visit(seen, days_ago=1)
    _tell(seen, visit, due=(local_today() + timedelta(days=10)).isoformat())
    _book(seen, seen["ids"]["child"], days_ahead=-30, status="completed")
    _book(seen, seen["ids"]["other_child"], days_ahead=2, status="completed")

    with seen["app"].app_context():
        row = Visit.query.get(visit)
        batched = followup.by_visit([row])[row.id]
        assert batched["state"] == followup.state(row) == "told"
        assert batched["missed"] == 0


def test_one_file_two_visits_and_the_booking_belongs_to_only_one(seen):
    """**The case the batched reader alone can get wrong.**

    `by_visit` fetches one page of appointments for the whole file, narrowed
    only to the *earliest* visit on it — so every later visit has to re-test
    the date itself. With one visit in the fixture the SQL narrowing already
    did that job and a sweep could delete the per-visit rule unnoticed. Two
    visits with a booking between them is the shape that separates them.
    """
    from app.models import Visit
    from app.utils import followup

    older = _visit(seen, days_ago=60)
    newer = _visit(seen, days_ago=2)
    _tell(seen, older, due=(local_today() - timedelta(days=40)).isoformat())
    _tell(seen, newer, due=(local_today() + timedelta(days=10)).isoformat())
    # Missed a month ago: after the older consultation, before the newer one.
    _book(seen, seen["ids"]["child"], days_ahead=-30, status="no_show")

    with seen["app"].app_context():
        rows = Visit.query.filter(Visit.id.in_([older, newer])).all()
        states = followup.by_visit(rows)
    assert states[older]["state"] == "missed"
    assert states[older]["missed"] == 1
    # The newer consultation was after that booking, so it is not its answer.
    assert states[newer]["state"] == "told"
    assert states[newer]["missed"] == 0


def test_a_booking_before_the_visit_is_not_this_visits_follow_up(seen):
    """The question is what was arranged **as a result of** this consultation.
    An appointment already on the books last month answers a different one."""
    visit = _visit(seen, days_ago=1)
    _tell(seen, visit, due=(local_today() + timedelta(days=10)).isoformat())
    _book(seen, seen["ids"]["child"], days_ahead=-30, status="completed")

    assert _state(seen, visit) == "told"


def test_another_childs_appointment_never_answers_this_visit(seen):
    visit = _visit(seen)
    _tell(seen, visit, due=(local_today() + timedelta(days=7)).isoformat())
    _book(seen, seen["ids"]["other_child"], days_ahead=3)

    assert _state(seen, visit) == "told"


def test_a_cancelled_booking_is_not_a_booking(seen):
    """A cancelled appointment is nobody coming back, and reading it as one
    would take the child off the chasing list for the exact reason they
    belong on it."""
    visit = _visit(seen, days_ago=30)
    _tell(seen, visit, due=(local_today() - timedelta(days=3)).isoformat())
    _book(seen, seen["ids"]["child"], days_ahead=-1, status="cancelled")

    assert _state(seen, visit) == "overdue"


# -------------------------------------------------- the list, and the file ----
def test_the_outstanding_list_is_the_two_errands_and_nothing_else(seen):
    """`told` and `booked` are not errands: one is not due and the other is
    handled. A list that carried them would be every visit in the clinic."""
    from app.utils import followup

    came = _visit(seen, days_ago=30)
    _tell(seen, came, due=(local_today() - timedelta(days=20)).isoformat())
    _book(seen, seen["ids"]["child"], days_ahead=-18, status="completed")

    waiting = _visit(seen, patient_id=seen["ids"]["other_child"], days_ago=20)
    _tell(seen, waiting, due=(local_today() - timedelta(days=6)).isoformat())

    with seen["app"].app_context():
        rows = [v.id for v in followup.outstanding()]
    assert rows == [waiting]


def test_the_list_puts_the_oldest_first(seen):
    """A list that puts this morning's on top is a list where last month's is
    still there at the end of the year."""
    from app.utils import followup

    older = _visit(seen, days_ago=60)
    _tell(seen, older, due=(local_today() - timedelta(days=50)).isoformat())
    newer = _visit(seen, patient_id=seen["ids"]["other_child"], days_ago=10)
    _tell(seen, newer, due=(local_today() - timedelta(days=3)).isoformat())

    with seen["app"].app_context():
        assert [v.id for v in followup.outstanding()] == [older, newer]


def test_the_screen_shows_them_and_says_how_many_were_missed(seen):
    visit = _visit(seen, days_ago=30)
    _tell(seen, visit, due=(local_today() - timedelta(days=20)).isoformat(),
          instructions="ارجع لو سخن")
    for ago in (15, 5):
        _book(seen, seen["ids"]["child"], days_ahead=-ago, status="no_show")

    page = seen["sign_in"]("doc").get("/visits/followups")
    body = page.get_data(as_text=True)
    assert page.status_code == 200
    assert f'data-followup-row="{visit}"' in body
    assert 'data-followup-state="missed"' in body
    assert 'data-followup-missed="2"' in body


def test_an_empty_list_says_so_rather_than_drawing_nothing(seen):
    page = seen["sign_in"]("doc").get("/visits/followups")
    assert page.status_code == 200
    assert "data-followup-row" not in page.get_data(as_text=True)


def test_the_file_shows_the_state_against_each_visit(seen):
    visit = _visit(seen, days_ago=30)
    _tell(seen, visit, due=(local_today() - timedelta(days=20)).isoformat())
    _book(seen, seen["ids"]["child"], days_ahead=-10, status="no_show")

    page = seen["sign_in"]("doc").get(f"/patients/{seen['ids']['child']}")
    body = page.get_data(as_text=True)
    assert page.status_code == 200
    assert 'data-followup="missed"' in body


def test_a_visit_with_no_instruction_carries_no_badge(seen):
    """«مفيش متابعة مطلوبة» is not a thing to print on every visit in a
    three-year file."""
    _visit(seen)

    body = seen["sign_in"]("doc").get(
        f"/patients/{seen['ids']['child']}").get_data(as_text=True)
    assert 'data-followup="none"' not in body


def test_the_file_costs_one_query_however_many_visits(seen):
    """A child with three years on the books is a hundred encounters, and a
    state asked per row is a hundred queries on one page."""
    from sqlalchemy import event
    from sqlalchemy.engine import Engine

    for ago in range(8):
        visit = _visit(seen, days_ago=ago + 1)
        _tell(seen, visit, due=(local_today() + timedelta(days=ago)).isoformat())

    seen_sql = []

    def record(conn, cursor, statement, params, context, many):
        if "appointments" in statement:
            seen_sql.append(statement)

    client = seen["sign_in"]("doc")
    event.listen(Engine, "before_cursor_execute", record)
    try:
        client.get(f"/patients/{seen['ids']['child']}")
    finally:
        event.remove(Engine, "before_cursor_execute", record)
    assert len(seen_sql) <= 3, f"{len(seen_sql)} appointment queries for 8 visits"


def test_the_door_is_on_the_visits_list(seen):
    """Six times in this project something was built and nothing led to it."""
    body = seen["sign_in"]("doc").get("/visits/").get_data(as_text=True)
    assert "/visits/followups" in body


# --------------------------------------------------------------- it tells ----
def test_nothing_here_books_or_sends_anything(seen):
    """The date is what the doctor asked for. Whether an appointment exists is
    reception's answer, read back from the appointment book rather than
    written down twice — and what the clinic *says* to a family is
    `utils/no_show` and `utils/recall`, both pressed by a person."""
    from app.models import Appointment, MessageLog

    visit = _visit(seen)
    _tell(seen, visit, due=(local_today() + timedelta(days=14)).isoformat(),
          instructions="ارجع لو سخن")

    with seen["app"].app_context():
        assert Appointment.query.count() == 0
        assert MessageLog.query.count() == 0


def test_every_follow_up_word_is_written_in_both_languages(seen):
    from app.i18n import _load_translations, _lookup

    tables = _load_translations()
    keys = ["title", "hint", "instructions_ph", "saved", "due", "instructions",
            "state", "child", "seen_on", "n_missed", "outstanding_title",
            "outstanding_sub", "nobody_waiting"]
    keys += [f"state_{s}" for s in ("none", "told", "booked", "came", "missed",
                                    "overdue")]
    for key in keys:
        for lang in ("ar", "en"):
            assert _lookup(tables, lang, f"followup.{key}"), f"{lang}:{key}"


def test_the_six_states_are_the_ones_the_screen_can_draw(seen):
    from app.utils.followup import OUTSTANDING, STATES

    assert STATES == ("none", "told", "booked", "came", "missed", "overdue")
    assert OUTSTANDING == ("missed", "overdue")
