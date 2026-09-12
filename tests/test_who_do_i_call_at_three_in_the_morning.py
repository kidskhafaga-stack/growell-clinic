"""Who is covering the theatre right now — and which of them is in the building.

Asked twice, and the second time to correct my reading of the first:

> «الطوارئ بيبقى فيه ليست مين موجود فى الطوارئ؟»

> «مين موجود فى **العمليات** طوارئ — مش فى قسم الطوارئ. قسم الطوارئ ليه ليست
> بشفتات مختلفة»

and then with the shape:

> «خلى كل لسيت لواحده — لسيت الطبيب الجراح لواحده وليست دكتور التخدير لواحده
> وليست التمريض لواحده. تحت الطلب او اون كول بيتحاسب طريقة مختلفة»

At three in the morning a child needs an emergency operation and somebody is
holding a phone. Three lists, and every name on them saying whether it belongs
to somebody in the building or somebody at home who will take twenty minutes.

**The whole difficulty is midnight**, and it is not an edge case — it is the
hours the question is asked in. A night shift runs 22:00–08:00, so at two on
Wednesday morning the person covering is on *Tuesday's* rota. Every naive
"today's duties" query answers that wrong, and wrong exactly when it matters.

Four more decisions:

**Rostered counts here.** "Rostered is not worked" governs *pay*; applying it
to this screen would empty it at two in the morning, in the middle of the very
shift it is asked about, because nobody confirms a night while working it.

**Present and on-call are kept apart, not mixed and flagged** — they are two
different actions for the reader: fetch, or ring and then wait.

**On call never inherits the presence rate.** A clinic that has not said what
a night at home is worth gets zero and a screen that says so; paying the full
figure would be the program deciding a rate nobody agreed.

**And an empty rota is named.** A screen listing two lists and silently
omitting the third reads as "the anaesthetists are fine".
"""
import os
import sys
from datetime import date, datetime, time, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def rota(clinic):
    """Three shifts — one of them overnight — and people to put on them."""
    from app.models import DutySlot, Setting, User
    from app.utils.on_call import ensure_seeded

    with clinic["app"].app_context():
        Setting.set("mod_enabled:duty", "1")
        Setting.set("mod_enabled:theatres", "1")
        ensure_seeded()

        day = DutySlot(name="صباحي", start_time=time(8, 0),
                       end_time=time(16, 0), rate=300, is_active=True,
                       sort_order=0)
        evening = DutySlot(name="مسائي", start_time=time(16, 0),
                           end_time=time(22, 0), rate=400, is_active=True,
                           sort_order=1)
        night = DutySlot(name="ليلي", start_time=time(22, 0),
                         end_time=time(8, 0), rate=800, on_call_rate=300,
                         is_active=True, sort_order=2)
        clinic["db"].session.add_all([day, evening, night])

        people = {}
        for key, name, phone in (("surg", "د. جرّاح", "01000000001"),
                                 ("gas", "د. مخدّر", "01000000002"),
                                 ("nurse", "تمريض", None),
                                 ("spare", "د. احتياطي", "01000000004")):
            row = User(username=key, full_name=name, role="doctor",
                       is_active=True, phone=phone)
            row.set_password("secret")
            clinic["db"].session.add(row)
            people[key] = row
        clinic["db"].session.commit()
        clinic["ids"] = {"day": day.id, "evening": evening.id,
                         "night": night.id,
                         **{k: v.id for k, v in people.items()}}
    return clinic


def _on(rota_, who, slot, on_date, role="surgeon", cover="present"):
    from app.models import DutySlot, User
    from app.utils import duty as duties

    with rota_["app"].app_context():
        row = duties.assign(
            rota_["db"].session.get(User, rota_["ids"][who]),
            rota_["db"].session.get(DutySlot, rota_["ids"][slot]),
            on_date=on_date, role=role, cover=cover)
        rota_["db"].session.commit()
        return row.id


def _at(rota_, moment, roles_only=True):
    from app.utils import on_call

    with rota_["app"].app_context():
        return on_call.covering(moment, roles_only=roles_only)


def _names(rota_, moment, side="present"):
    """The names on one side of each rota, read inside the session.

    The rows come back attached to a session that closes with the context, so
    the reading happens there rather than in the assertion.
    """
    from app.utils import on_call

    with rota_["app"].app_context():
        return [[d.doctor.full_name for d in row[side]]
                for row in on_call.covering(moment)]


# --------------------------------------------------------------- midnight --
def test_at_two_in_the_morning_the_cover_is_yesterdays_night_shift(rota):
    """**The one that matters.** Not an edge case — it is the hours the
    question is asked in. A naive "today's duties" query answers it wrong
    exactly when somebody needs it."""
    tuesday = date(2026, 3, 3)
    _on(rota, "surg", "night", tuesday)

    # Two in the morning on Wednesday: Tuesday's night shift is running.
    assert _names(rota, datetime(2026, 3, 4, 2, 0)) == [["د. جرّاح"]]


def test_the_night_shift_covers_its_own_evening_too(rota):
    tuesday = date(2026, 3, 3)
    _on(rota, "surg", "night", tuesday)
    assert _at(rota, datetime(2026, 3, 3, 23, 30))[0]["present"]


def test_it_stops_covering_when_the_shift_ends(rota):
    """08:00 is the end, not a grace period: the morning shift's problem."""
    tuesday = date(2026, 3, 3)
    _on(rota, "surg", "night", tuesday)
    assert _at(rota, datetime(2026, 3, 4, 8, 0)) == []
    assert _at(rota, datetime(2026, 3, 4, 7, 59)) != []


def test_a_night_two_days_ago_covers_nothing_now(rota):
    """The window is the shift's own hours, not "recently"."""
    _on(rota, "surg", "night", date(2026, 3, 1))
    assert _at(rota, datetime(2026, 3, 4, 2, 0)) == []


def test_an_ordinary_shift_only_covers_its_own_day(rota):
    tuesday = date(2026, 3, 3)
    _on(rota, "surg", "day", tuesday)
    assert _at(rota, datetime(2026, 3, 3, 10, 0)) != []
    assert _at(rota, datetime(2026, 3, 4, 10, 0)) == []
    assert _at(rota, datetime(2026, 3, 3, 17, 0)) == []


def test_a_shift_that_runs_past_midnight_but_is_not_a_night(rota):
    """14:00–02:00 is a real shape and no rule about "nights" catches it —
    which is why the reach is worked out from the slot's own hours."""
    from app.models import DutySlot

    with rota["app"].app_context():
        late = DutySlot(name="ممتد", start_time=time(14, 0),
                        end_time=time(2, 0), rate=500, is_active=True)
        rota["db"].session.add(late)
        rota["db"].session.commit()
        rota["ids"]["late"] = late.id

    _on(rota, "surg", "late", date(2026, 3, 3))
    assert _at(rota, datetime(2026, 3, 3, 15, 0)) != []
    assert _at(rota, datetime(2026, 3, 4, 1, 0)) != []
    assert _at(rota, datetime(2026, 3, 4, 3, 0)) == []


# ------------------------------------------------------- three lists, apart --
def test_each_rota_is_its_own_list(rota):
    """One list with three kinds of person on it is a list nobody can read at
    speed, and speed is the only reason it exists."""
    tuesday = date(2026, 3, 3)
    _on(rota, "surg", "night", tuesday, role="surgeon")
    _on(rota, "gas", "night", tuesday, role="anaesthesia")
    _on(rota, "nurse", "night", tuesday, role="nursing")

    found = _at(rota, datetime(2026, 3, 4, 2, 0))
    assert [r["role"] for r in found] == ["surgeon", "anaesthesia", "nursing"]
    for row in found:
        assert len(row["present"]) == 1


def test_here_and_reachable_are_two_different_columns(rota):
    """Two different actions for whoever is reading: fetch, or ring and wait."""
    tuesday = date(2026, 3, 3)
    _on(rota, "surg", "night", tuesday, cover="present")
    _on(rota, "spare", "night", tuesday, cover="on_call")

    when = datetime(2026, 3, 4, 2, 0)
    assert _names(rota, when, "present") == [["د. جرّاح"]]
    assert _names(rota, when, "on_call") == [["د. احتياطي"]]


def test_general_cover_is_not_dropped_from_the_data(rota):
    """The resident covering the department belongs to no theatre rota. Kept
    off the theatre screen by default, and never deleted from the answer."""
    tuesday = date(2026, 3, 3)
    _on(rota, "spare", "night", tuesday, role=None)

    assert _at(rota, datetime(2026, 3, 4, 2, 0)) == []
    wider = _at(rota, datetime(2026, 3, 4, 2, 0), roles_only=False)
    assert [r["role"] for r in wider] == [None]


def test_a_clinic_can_add_a_rota_of_its_own(rota):
    """Nothing reads a role by name — the screen groups by whatever exists."""
    from app.models import DutyRole

    with rota["app"].app_context():
        rota["db"].session.add(DutyRole(key="radiology", name_ar="الأشعة",
                                        sort_order=9, is_active=True))
        rota["db"].session.commit()

    _on(rota, "spare", "night", date(2026, 3, 3), role="radiology")
    found = _at(rota, datetime(2026, 3, 4, 2, 0))
    assert [r["role"] for r in found] == ["radiology"]


# ---------------------------------------------------------- rostered counts --
def test_an_unconfirmed_night_still_answers_the_phone(rota):
    """"Rostered is not worked" governs pay. Applying it here would empty the
    screen at two in the morning, in the middle of the shift it is about —
    because nobody confirms a night while working it."""
    from app.models import Duty

    duty = _on(rota, "surg", "night", date(2026, 3, 3))
    with rota["app"].app_context():
        assert rota["db"].session.get(Duty, duty).status == "rostered"
    assert _at(rota, datetime(2026, 3, 4, 2, 0)) != []


def test_somebody_marked_absent_is_not_on_the_list(rota):
    """The one status that does remove them: saying they did not come is a
    fact, and a screen that still names them sends somebody to look."""
    from app.models import Duty
    from app.utils import duty as duties

    row = _on(rota, "surg", "night", date(2026, 3, 3))
    with rota["app"].app_context():
        duties.mark_absent(rota["db"].session.get(Duty, row))
        rota["db"].session.commit()
    assert _at(rota, datetime(2026, 3, 4, 2, 0)) == []


# ----------------------------------------------------------------- the pay --
def test_a_night_at_home_pays_the_on_call_rate(rota):
    from app.models import Duty

    duty = _on(rota, "surg", "night", date(2026, 3, 3), cover="on_call")
    with rota["app"].app_context():
        assert rota["db"].session.get(Duty, duty).amount == 300


def test_a_night_in_the_building_pays_the_presence_rate(rota):
    from app.models import Duty

    duty = _on(rota, "surg", "night", date(2026, 3, 3), cover="present")
    with rota["app"].app_context():
        assert rota["db"].session.get(Duty, duty).amount == 800


def test_on_call_never_falls_back_to_the_presence_rate(rota):
    """**The one that would quietly overpay.** A clinic that has not agreed
    what a night at home is worth must be asked, not have the full figure
    paid for a night somebody spent asleep."""
    from app.models import Duty, DutySlot

    with rota["app"].app_context():
        rota["db"].session.get(DutySlot,
                               rota["ids"]["night"]).on_call_rate = None
        rota["db"].session.commit()

    duty = _on(rota, "surg", "night", date(2026, 3, 3), cover="on_call")
    with rota["app"].app_context():
        assert rota["db"].session.get(Duty, duty).amount is None


def test_a_doctors_own_on_call_figure_wins(rota):
    from app.models import Duty, DutyRate

    with rota["app"].app_context():
        rota["db"].session.add(DutyRate(doctor_id=rota["ids"]["surg"],
                                        slot_id=rota["ids"]["night"],
                                        amount=900, on_call_amount=450))
        rota["db"].session.commit()

    at_home = _on(rota, "surg", "night", date(2026, 3, 3), cover="on_call")
    here = _on(rota, "surg", "day", date(2026, 3, 3), cover="present")
    with rota["app"].app_context():
        assert rota["db"].session.get(Duty, at_home).amount == 450
        # …and their own figure on one slot says nothing about another.
        assert rota["db"].session.get(Duty, here).amount == 300


def test_their_own_presence_figure_does_not_become_their_on_call_one(rota):
    """The two halves of an override fall back separately — a registrar with
    an agreed night rate has not thereby agreed an on-call rate."""
    from app.models import Duty, DutyRate

    with rota["app"].app_context():
        rota["db"].session.add(DutyRate(doctor_id=rota["ids"]["surg"],
                                        slot_id=rota["ids"]["night"],
                                        amount=900, on_call_amount=None))
        rota["db"].session.commit()

    duty = _on(rota, "surg", "night", date(2026, 3, 3), cover="on_call")
    with rota["app"].app_context():
        assert rota["db"].session.get(Duty, duty).amount == 300   # the slot's


# ------------------------------------------------------------- the finding --
def test_a_rota_with_nobody_on_it_is_named(rota):
    """A screen listing two lists and silently omitting the third reads as
    "the anaesthetists are fine"."""
    from app.utils import on_call

    _on(rota, "surg", "night", date(2026, 3, 3), role="surgeon")
    with rota["app"].app_context():
        missing = {r.key for r in on_call.gaps(datetime(2026, 3, 4, 2, 0))}
        assert missing == {"anaesthesia", "nursing"}


def test_somebody_on_call_counts_as_covered(rota):
    """Reachable is cover. Listing the rota as empty because nobody is in the
    building would send somebody hunting for a second anaesthetist."""
    from app.utils import on_call

    for role in ("surgeon", "nursing"):
        _on(rota, "surg" if role == "surgeon" else "nurse", "night",
            date(2026, 3, 3), role=role)
    _on(rota, "gas", "night", date(2026, 3, 3), role="anaesthesia",
        cover="on_call")
    with rota["app"].app_context():
        assert on_call.gaps(datetime(2026, 3, 4, 2, 0)) == []


def test_a_name_with_no_number_is_said_out_loud(rota):
    """A name with no number on an on-call list is the list failing at the one
    moment it is read."""
    from app.models import Duty
    from app.utils import on_call

    duty = _on(rota, "nurse", "night", date(2026, 3, 3), role="nursing")
    with rota["app"].app_context():
        assert on_call.reachable(rota["db"].session.get(Duty, duty)) is None
        surgeon = _on(rota, "surg", "night", date(2026, 3, 3))
        assert on_call.reachable(
            rota["db"].session.get(Duty, surgeon)) == "01000000001"


# ------------------------------------------------------------- the screens --
def test_the_screen_draws(rota):
    _on(rota, "surg", "night", date(2026, 3, 3), role="surgeon")
    client = rota["sign_in"]("boss")
    page = client.get("/duty/now")
    assert page.status_code == 200
    # The rotas nobody is on are named, not omitted.
    body = page.get_data(as_text=True)
    assert "التخدير" in body and "التمريض" in body
    assert client.get("/duty/").status_code == 200
    assert client.get("/duty/slots").status_code == 200


def test_a_rota_key_nothing_recognises_is_not_stored(rota):
    """A key nothing matches would put a name on a list that draws nowhere —
    somebody who looks rostered and cannot be found."""
    from app.blueprints.duty.routes import _a_role

    with rota["app"].app_context():
        assert _a_role("surgeon") == "surgeon"
        assert _a_role("مخترع") is None
        assert _a_role("") is None


def test_the_clinic_clock_decides_which_shift_is_running(rota):
    """«Now» in a Cairo hospital on a UTC server is three hours out — which,
    for a question whose whole answer is which shift is running, is the wrong
    name for a quarter of every day."""
    import inspect

    from app.utils import on_call

    source = inspect.getsource(on_call.covering)
    assert "local_now()" in source
    assert "datetime.now()" not in source and "utcnow()" not in source
