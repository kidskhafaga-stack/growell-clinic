"""The clock a theatre day is actually run on.

GAHAR SAS.02 (هـ) asks for *"a clear and safe mechanism to call patients for
surgeries or invasive procedures"*, and the standard's fifth item of evidence
says how far the clock has to reach:

> Punctuality (timekeeping) of procedures in the operating room is maintained
> and recorded, **starting with the patient's call** and ending with **the room
> being cleaned** after the procedure.

The middle of that chain was already here — started, finished, moved to
recovery. **Both ends were missing**, and they are the two the standard names
by name. They are also the two that matter most to the people in the corridor:
the gap between the call and the knife is the wait a family actually feels, and
the gap between finishing and the room being ready is what the next case waits
on.

Four decisions:

* **The call is recorded once.** A second call is somebody chasing, not a new
  beginning — and moving the stamp would quietly shorten every wait this exists
  to measure.
* **A moment that never happened stays in the chain as ``None``.** A timeline
  that drops what nobody recorded always looks complete, which is the opposite
  of what a punctuality record is for.
* **The gap is measured to the previous *recorded* moment**, not the previous
  one in the list, so an unstamped recovery does not make the turnover read as
  instant.
* **A room cannot be cleaned before the case finishes.** A stamp that can land
  out of order makes every figure computed from it wrong.
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def theatre_day():
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
        kid = Patient(patient_number="P1", full_name="طفل", gender="male",
                      is_active=True,
                      date_of_birth=local_today() - timedelta(days=1500))
        db.session.add(kid)
        db.session.flush()
        case = Operation(patient_id=kid.id, theatre_id=room.id,
                         procedure="لوز", on_date=local_today(),
                         status="scheduled")
        db.session.add(case)
        db.session.commit()
        ids = {"boss": boss.id, "case": case.id, "room": room.id}

    def sign_in(username="boss"):
        client = app.test_client()
        client.post("/login", data={"username": username, "password": "secret"},
                    follow_redirects=True)
        return client

    return {"app": app, "db": db, "ids": ids, "sign_in": sign_in}


def _case(ctx):
    from app.models.theatre import Operation
    return ctx["db"].session.get(Operation, ctx["ids"]["case"])


def _boss(ctx):
    from app.models import User
    return ctx["db"].session.get(User, ctx["ids"]["boss"])


# ------------------------------------------------------------ the call ----
def test_a_case_nobody_called_has_no_call(theatre_day):
    from app.utils import theatres as theatre

    with theatre_day["app"].app_context():
        assert _case(theatre_day).called_at is None
        assert theatre.waited_minutes(_case(theatre_day)) is None


def test_calling_records_who_and_where_to(theatre_day):
    """*"A clear and safe mechanism to call patients"* — and where the call
    went is free text, because the standard asks for *a* mechanism and does not
    name the channels. A list invented here would be the program telling a
    clinic how to call its patients."""
    from app.utils import theatres as theatre

    with theatre_day["app"].app_context():
        theatre.call_patient(_case(theatre_day), to="الداخلي — عنبر ٢",
                             user=_boss(theatre_day))
        theatre_day["db"].session.commit()
        row = _case(theatre_day)
        assert row.called_at is not None
        assert row.called_by == theatre_day["ids"]["boss"]
        assert row.called_to == "الداخلي — عنبر ٢"


def test_calling_twice_does_not_move_the_moment(theatre_day):
    """**A second call is somebody chasing, not a new beginning.** Moving the
    stamp would quietly shorten every wait this exists to measure."""
    from app.utils import theatres as theatre

    with theatre_day["app"].app_context():
        theatre.call_patient(_case(theatre_day), to="الأولى",
                             user=_boss(theatre_day))
        theatre_day["db"].session.commit()
        first = _case(theatre_day).called_at

        assert theatre.call_patient(_case(theatre_day), to="التانية",
                                    user=_boss(theatre_day)) is None
        theatre_day["db"].session.commit()
        assert _case(theatre_day).called_at == first
        assert _case(theatre_day).called_to == "الأولى"


def test_the_wait_is_from_the_call_to_the_knife(theatre_day):
    """The number a theatre list is run on, and no stamp in this program could
    measure it before."""
    from app.utils import theatres as theatre

    with theatre_day["app"].app_context():
        row = _case(theatre_day)
        row.called_at = datetime(2026, 5, 1, 8, 0)
        row.started_at = datetime(2026, 5, 1, 9, 35)
        theatre_day["db"].session.commit()
        assert theatre.waited_minutes(_case(theatre_day)) == 95


def test_a_wait_with_one_end_missing_is_unknown_not_short(theatre_day):
    from app.utils import theatres as theatre

    with theatre_day["app"].app_context():
        row = _case(theatre_day)
        row.started_at = datetime(2026, 5, 1, 9, 35)
        theatre_day["db"].session.commit()
        assert theatre.waited_minutes(_case(theatre_day)) is None

    with theatre_day["app"].app_context():
        row = _case(theatre_day)
        row.started_at = None
        row.called_at = datetime(2026, 5, 1, 8, 0)
        theatre_day["db"].session.commit()
        assert theatre.waited_minutes(_case(theatre_day)) is None


# --------------------------------------------------------- the turnover ----
def test_the_room_cannot_be_cleaned_before_the_case_finishes(theatre_day):
    """A stamp that can land out of order makes every figure computed from it
    wrong."""
    from app.utils import theatres as theatre

    with theatre_day["app"].app_context():
        assert theatre.mark_cleaned(_case(theatre_day),
                                    user=_boss(theatre_day)) is None
        theatre_day["db"].session.commit()
        assert _case(theatre_day).cleaned_at is None


def test_cleaning_after_it_finishes_is_recorded(theatre_day):
    from app.utils import theatres as theatre

    with theatre_day["app"].app_context():
        _case(theatre_day).finished_at = datetime.utcnow()
        theatre_day["db"].session.commit()
        theatre.mark_cleaned(_case(theatre_day), user=_boss(theatre_day))
        theatre_day["db"].session.commit()
        row = _case(theatre_day)
        assert row.cleaned_at is not None
        assert row.cleaned_by == theatre_day["ids"]["boss"]


def test_cleaning_twice_does_not_move_it_either(theatre_day):
    from app.utils import theatres as theatre

    with theatre_day["app"].app_context():
        _case(theatre_day).finished_at = datetime.utcnow()
        theatre_day["db"].session.commit()
        theatre.mark_cleaned(_case(theatre_day), user=_boss(theatre_day))
        theatre_day["db"].session.commit()
        first = _case(theatre_day).cleaned_at

        assert theatre.mark_cleaned(_case(theatre_day),
                                    user=_boss(theatre_day)) is None
        theatre_day["db"].session.commit()
        assert _case(theatre_day).cleaned_at == first


def test_the_turnover_is_from_finishing_to_ready(theatre_day):
    """What the next case waits on — and the one moment nobody records,
    because it happens after everybody has moved on."""
    from app.utils import theatres as theatre

    with theatre_day["app"].app_context():
        row = _case(theatre_day)
        row.finished_at = datetime(2026, 5, 1, 11, 0)
        row.cleaned_at = datetime(2026, 5, 1, 11, 25)
        theatre_day["db"].session.commit()
        assert theatre.turnover_minutes(_case(theatre_day)) == 25


def test_a_turnover_with_one_end_missing_is_unknown(theatre_day):
    from app.utils import theatres as theatre

    with theatre_day["app"].app_context():
        _case(theatre_day).finished_at = datetime(2026, 5, 1, 11, 0)
        theatre_day["db"].session.commit()
        assert theatre.turnover_minutes(_case(theatre_day)) is None


# ---------------------------------------------------------- the chain ------
def test_the_chain_is_the_one_the_standard_names(theatre_day):
    """Both ends quoted: *"starting with the patient's call and ending with the
    room being cleaned"*."""
    from app.utils import theatres as theatre

    steps = [step for step, _ in theatre.TIMELINE]
    assert steps[0] == "called"
    assert steps[-1] == "cleaned"
    assert steps == ["called", "started", "finished", "recovery", "cleaned"]


def test_a_moment_nobody_recorded_stays_in_the_chain(theatre_day):
    """**A timeline that drops what nobody recorded always looks complete**,
    which is the opposite of what a punctuality record is for."""
    from app.utils import theatres as theatre

    with theatre_day["app"].app_context():
        _case(theatre_day).called_at = datetime(2026, 5, 1, 8, 0)
        theatre_day["db"].session.commit()
        rows = theatre.timeline(_case(theatre_day))
        assert len(rows) == 5
        assert rows[0]["at"] is not None
        assert all(r["at"] is None for r in rows[1:])


def test_each_gap_is_measured_to_the_previous_recorded_moment(theatre_day):
    """**The one this had to get right.** A case whose recovery was never
    stamped must still show an honest gap between finishing and the room being
    cleaned — not a blank that reads as instant."""
    from app.utils import theatres as theatre

    with theatre_day["app"].app_context():
        row = _case(theatre_day)
        row.called_at = datetime(2026, 5, 1, 8, 0)
        row.started_at = datetime(2026, 5, 1, 9, 0)
        row.finished_at = datetime(2026, 5, 1, 10, 0)
        row.recovery_at = None                      # nobody stamped it
        row.cleaned_at = datetime(2026, 5, 1, 10, 30)
        theatre_day["db"].session.commit()

        rows = {r["step"]: r for r in theatre.timeline(_case(theatre_day))}
        assert rows["called"]["minutes"] is None     # nothing before it
        assert rows["started"]["minutes"] == 60
        assert rows["finished"]["minutes"] == 60
        assert rows["recovery"]["minutes"] is None
        # …measured from *finished*, not from the empty recovery.
        assert rows["cleaned"]["minutes"] == 30


def test_an_empty_case_has_a_chain_of_nothing_rather_than_no_chain(theatre_day):
    from app.utils import theatres as theatre

    with theatre_day["app"].app_context():
        rows = theatre.timeline(_case(theatre_day))
        assert len(rows) == 5
        assert all(r["at"] is None and r["minutes"] is None for r in rows)


def test_no_operation_is_an_empty_list_not_a_crash(theatre_day):
    from app.utils import theatres as theatre

    with theatre_day["app"].app_context():
        assert theatre.timeline(None) == []
        assert theatre.waited_minutes(None) is None
        assert theatre.turnover_minutes(None) is None
        assert theatre.call_patient(None) is None
        assert theatre.mark_cleaned(None) is None


# --------------------------------------------------------- on the screen --
def test_the_screen_shows_the_whole_chain_including_the_gaps(theatre_day):
    from datetime import datetime as dt

    with theatre_day["app"].app_context():
        row = _case(theatre_day)
        row.called_at = dt(2026, 5, 1, 8, 0)
        row.started_at = dt(2026, 5, 1, 9, 0)
        theatre_day["db"].session.commit()

    html = theatre_day["sign_in"]().get(
        f"/theatres/operation/{theatre_day['ids']['case']}").get_data(as_text=True)
    # Pinned to real words: `t(key) in html` cannot fail on a missing phrase.
    assert "توقيتات الحالة" in html
    assert "النداء على الطفل" in html
    # A moment nobody recorded is still on the list.
    assert "الأوضة اتنضّفت" in html
    assert "استنى 60 دقيقة" in html


def test_the_screen_records_the_call(theatre_day):
    from app.utils import theatres as theatre

    theatre_day["sign_in"]().post(
        f"/theatres/operation/{theatre_day['ids']['case']}/call",
        data={"called_to": "عنبر ٢"}, follow_redirects=True)
    with theatre_day["app"].app_context():
        assert _case(theatre_day).called_at is not None
        assert _case(theatre_day).called_to == "عنبر ٢"


def test_the_screen_says_why_a_second_call_changed_nothing(theatre_day):
    """A refusal nobody can read is a screen that just did not work."""
    from app.i18n import t
    from app.utils import theatres as theatre

    client = theatre_day["sign_in"]()
    client.post(f"/theatres/operation/{theatre_day['ids']['case']}/call",
                data={"called_to": "الأولى"}, follow_redirects=True)
    with theatre_day["app"].app_context():
        first = _case(theatre_day).called_at

    html = client.post(
        f"/theatres/operation/{theatre_day['ids']['case']}/call",
        data={"called_to": "التانية"},
        follow_redirects=True).get_data(as_text=True)
    with theatre_day["app"].app_context():
        assert _case(theatre_day).called_at == first
    with theatre_day["app"].test_request_context("/"):
        assert t("theatre.call_already") in html
    assert "متابعة مش بداية جديدة" in html


def test_the_screen_refuses_cleaning_before_the_case_finishes(theatre_day):
    from app.i18n import t

    html = theatre_day["sign_in"]().post(
        f"/theatres/operation/{theatre_day['ids']['case']}/cleaned",
        data={}, follow_redirects=True).get_data(as_text=True)
    with theatre_day["app"].app_context():
        assert _case(theatre_day).cleaned_at is None
    with theatre_day["app"].test_request_context("/"):
        assert t("theatre.cleaned_not_yet") in html


def test_the_screen_records_the_turnover(theatre_day):
    from datetime import datetime as dt

    with theatre_day["app"].app_context():
        _case(theatre_day).finished_at = dt.utcnow()
        theatre_day["db"].session.commit()

    theatre_day["sign_in"]().post(
        f"/theatres/operation/{theatre_day['ids']['case']}/cleaned",
        data={}, follow_redirects=True)
    with theatre_day["app"].app_context():
        assert _case(theatre_day).cleaned_at is not None


def test_the_columns_are_registered_for_a_clinic_already_running(theatre_day):
    from app.utils.schema import ADDITIONS

    pairs = {(t, c) for t, c, _ in ADDITIONS}
    for column in ("called_at", "called_by", "called_to", "cleaned_at",
                   "cleaned_by"):
        assert ("operations", column) in pairs
