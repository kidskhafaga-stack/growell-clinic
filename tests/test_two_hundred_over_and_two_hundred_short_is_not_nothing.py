"""Shifts added up per person and per till.

Asked for while the design of the safe was still open: a clinic deciding how
the drawer should work is better off looking at what its own shifts actually
did than at a diagram. The history screen lists sessions one at a time and the
end-of-day screen covers a day; neither answers *"is this person short every
week"* or *"does this desk only balance when one particular person is on it"*.

**The rule the file is named after.** Somebody 200 over on Monday and 200 short
on Tuesday nets to zero, and a net of zero reads as "this desk is fine". It is
not fine. It is two differences nobody explained, and quite possibly one being
used to cover the other. Short and over are totalled apart and the count of
shifts that came out wrong is carried beside them.

**An open shift has no verdict.** `variance` is None until somebody counts, and
None is not zero — treating an uncounted shift as balanced would let anybody
improve their record by leaving shifts open.

And every number is the shift's own. A summary that disagreed with the shift
reports it totals would be worse than no summary at all.
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


def _shift(db, *, who, till, opened, float_=200, counted=None, when=None):
    from app.models import CashierShift

    shift = CashierShift(shift_number=f"S{opened}", opening_float=float_,
                         account_id=till, opened_by=who,
                         opened_at=when or datetime.utcnow(),
                         counted_cash=counted,
                         status="closed" if counted is not None else "open")
    db.session.add(shift)
    db.session.flush()
    return shift


@pytest.fixture()
def desks(clinic):
    """Two people, one drawer, and a week of shifts."""
    from app.extensions import db
    from app.models import CashAccount, User

    with clinic["app"].app_context():
        till = CashAccount(name="استقبال ١", code="1010", kind="cash")
        other = CashAccount(name="استقبال ٢", code="1011", kind="cash")
        db.session.add_all([till, other])
        db.session.flush()
        desk = User.query.filter_by(username="desk").first()
        acct = User.query.filter_by(username="acct").first()
        db.session.commit()
        clinic["till"], clinic["other_till"] = till.id, other.id
        clinic["desk_id"], clinic["acct_id"] = desk.id, acct.id
    return clinic


def _summary(clinic, days=30):
    from app.utils import shift_rollup
    from app.utils.clock import local_today

    today = local_today()
    with clinic["app"].app_context():
        return shift_rollup.summary(today - timedelta(days=days), today)


# ------------------------------------------- the rule this file is named for

def test_over_and_short_do_not_cancel_each_other_out(desks):
    """The whole point. Two unexplained differences that happen to be equal
    and opposite are two problems, not none."""
    from app.extensions import db

    with desks["app"].app_context():
        # Expected is the float alone (no payments), so counted tells the tale.
        _shift(db, who=desks["desk_id"], till=desks["till"], opened=1,
               counted=400)                                    # 200 over
        _shift(db, who=desks["desk_id"], till=desks["till"], opened=2,
               counted=0)                                      # 200 short
        db.session.commit()

    totals = _summary(desks)["totals"]

    assert totals["over"] == 200
    assert totals["short"] == 200
    assert totals["off"] == 2, "two shifts came out wrong and the count says so"
    # The net is still reported — it is a real fact — but it is not the
    # headline, and it is not what "off" counts.
    assert totals["net"] == 0


def test_a_run_of_shortages_shows_as_a_run(desks):
    """The pattern somebody is scanning for: short every time, not once."""
    from app.extensions import db

    with desks["app"].app_context():
        for n in range(4):
            _shift(db, who=desks["desk_id"], till=desks["till"], opened=n,
                   counted=150)                                 # 50 short each
        db.session.commit()

    person = _summary(desks)["people"][0]

    assert person["short"] == 200 and person["over"] == 0
    assert person["off"] == 4


def test_a_shift_that_balances_is_not_a_shift_that_came_out_wrong(desks):
    """Found by mutation testing, and it is the test that gives "shifts out"
    its meaning: if a difference of zero counted, every shift would be out and
    the number would say nothing about anybody."""
    from app.extensions import db

    with desks["app"].app_context():
        _shift(db, who=desks["desk_id"], till=desks["till"], opened=1,
               counted=200)                                    # exactly right
        _shift(db, who=desks["desk_id"], till=desks["till"], opened=2,
               counted=190)                                    # 10 short
        db.session.commit()

    totals = _summary(desks)["totals"]

    assert totals["shifts"] == 2
    assert totals["off"] == 1, "a shift that balanced was counted as out"
    assert totals["short"] == 10 and totals["over"] == 0


# --------------------------------------------- an open shift has no verdict

def test_an_uncounted_shift_is_not_a_balanced_one(desks):
    """None is not zero. Otherwise the way to a clean record is to stop
    counting."""
    from app.extensions import db

    with desks["app"].app_context():
        _shift(db, who=desks["desk_id"], till=desks["till"], opened=1)
        db.session.commit()

    totals = _summary(desks)["totals"]

    assert totals["shifts"] == 1
    assert totals["open"] == 1
    assert totals["off"] == 0
    assert totals["short"] == 0 and totals["over"] == 0
    assert totals["expected"] == 0, \
        "an uncounted shift contributed to the reconciliation"


def test_the_screen_says_how_many_are_uncounted(desks):
    from app.extensions import db

    with desks["app"].app_context():
        _shift(db, who=desks["desk_id"], till=desks["till"], opened=1)
        _shift(db, who=desks["desk_id"], till=desks["till"], opened=2,
               counted=200)
        db.session.commit()

    person = _summary(desks)["people"][0]

    assert person["shifts"] == 2 and person["open"] == 1


# --------------------------------------- the two questions are two questions

def test_the_same_shifts_are_folded_by_person_and_by_till(desks):
    """"Is this person short" and "is this desk short" have different answers
    the moment two people work one desk — which is the case the report exists
    to make visible."""
    from app.extensions import db

    with desks["app"].app_context():
        _shift(db, who=desks["desk_id"], till=desks["till"], opened=1,
               counted=100)                                    # desk: 100 short
        _shift(db, who=desks["acct_id"], till=desks["till"], opened=2,
               counted=300)                                    # acct: 100 over
        db.session.commit()

    seen = _summary(desks)

    assert len(seen["people"]) == 2, "the two people were merged"
    assert len(seen["tills"]) == 1, "the one drawer was split"

    till = seen["tills"][0]
    assert till["short"] == 100 and till["over"] == 100, \
        "the drawer's own figures lost the two differences"


def test_a_till_two_people_worked_is_reported_as_such(desks):
    """The finding the report was asked for, said plainly rather than left for
    somebody to spot by reading two tables against each other."""
    from app.extensions import db
    from app.utils import shift_rollup

    with desks["app"].app_context():
        _shift(db, who=desks["desk_id"], till=desks["till"], opened=1, counted=200)
        _shift(db, who=desks["acct_id"], till=desks["till"], opened=2, counted=200)
        _shift(db, who=desks["desk_id"], till=desks["other_till"], opened=3,
               counted=200)
        db.session.commit()

    seen = _summary(desks)
    with desks["app"].app_context():
        shared = shift_rollup.shared_tills(seen)

    assert list(shared) == [desks["till"]], \
        "the drawer two people worked was not identified"


# ------------------------------------------------- it reads, never computes

def test_every_figure_is_the_shift_s_own(desks):
    """A summary that disagreed with the shift reports it totals would be
    worse than no summary. It reads `collected`, `expected_cash` and
    `variance` off the shift rather than recomputing them."""
    import inspect

    from app.utils import shift_rollup

    source = inspect.getsource(shift_rollup)

    for computed in ("counted_cash -", "opening_float +", "signed_amount"):
        assert computed not in source, \
            f"the rollup is doing its own arithmetic: {computed}"


def test_cash_out_is_one_definition_batched(desks):
    """The shift's own `cash_paid_out` used to run two queries per shift, which
    is sixty shifts × two on a month. Batched — but through the same code, so a
    fast copy cannot drift from the slow one."""
    from app.models import CashierShift

    assert hasattr(CashierShift, "paid_out_for")
    source = __import__("inspect").getsource(CashierShift.cash_paid_out.fget)
    assert "paid_out_for" in source, \
        "the per-shift property has its own copy of the query again"


# --------------------------------------------------------------- the screen

def test_the_screen_opens_and_says_both_halves(desks):
    from app.extensions import db

    with desks["app"].app_context():
        _shift(db, who=desks["desk_id"], till=desks["till"], opened=1, counted=100)
        db.session.commit()

    page = desks["sign_in"]("boss").get("/finance/shifts/summary").get_data(as_text=True)

    assert "shiftsum.title" not in page, "the strings are keys, not translations"
    assert "استقبال ١" in page or "Reception" in page


def test_it_writes_nothing(desks):
    """Read-only by design: a summary that could close a shift or write a
    difference off is a summary somebody uses to make a shortage disappear."""
    import inspect

    from app.blueprints.finance.routes import shift_summary

    source = inspect.getsource(shift_summary)

    for verb in ("db.session.add", "db.session.commit", "status =", "methods="):
        assert verb not in source, f"the summary route reaches for {verb}"


def test_a_range_typed_backwards_still_answers(desks):
    from app.utils.clock import local_today

    today = local_today()
    answer = desks["sign_in"]("boss").get(
        f"/finance/shifts/summary?date_from={today.isoformat()}"
        f"&date_to={(today - timedelta(days=7)).isoformat()}")

    assert answer.status_code == 200


def test_reception_without_the_till_cannot_open_it(desks):
    """It carries every desk's figures, so it is behind the same door as the
    cashier itself rather than open to anyone who can take a payment."""
    answer = desks["sign_in"]("doc").get("/finance/shifts/summary")

    assert answer.status_code in (302, 403)
