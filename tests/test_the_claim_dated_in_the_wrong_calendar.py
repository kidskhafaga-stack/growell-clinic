"""A claim's clock, read in the clinic's calendar rather than the server's.

Caught by CI: ``assert 16 == 15`` on a run that started at 22:19 UTC, and
reproduced in one command —

    utcnow().date() = 2026-09-08
    local_today()   = 2026-09-09     ← the clinic's clock is ahead

Two calendars in one sum. ``payment_due`` derived its date from
``claim.submitted_at.date()``, which is a **UTC** date, and ``days_overdue``
compared it against ``local_today()``, which is the **clinic's**. They agree
for most of the day and part company for the hours after the clinic's clock
has crossed midnight and UTC has not.

**And it is not only a test that suffers.** A claim submitted at half past
eleven at night in Cairo is stamped with the previous UTC day, so its money
falls due a day early and the screen calls it overdue while it is still inside
its terms — a desk ringing a payer who is not late yet. The same fault the
consent row already had, on the one field where the date is the point.

Every test here **pins the zone and the timestamp**. The one it replaces was
true in the morning and false at night, which is the property that let this
sit in the code until a merge happened to run late enough to find it.
"""
import os
import sys
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

#: 22:30 UTC. In Cairo that is already half past midnight the next day, which
#: is the window the whole bug lives in.
LATE = datetime(2026, 3, 10, 22, 30)
IN_UTC = date(2026, 3, 10)
IN_CAIRO = date(2026, 3, 11)


@pytest.fixture()
def clinic():
    from app import create_app
    from app.extensions import db

    app = create_app("testing")
    with app.app_context():
        db.create_all()
        from app.models import Setting

        Setting.set("clinic_timezone", "Africa/Cairo")
        db.session.commit()
    return {"app": app, "db": db}


def _claim(clinic, submitted_at=LATE, payer_terms=30):
    """A payer on contract, and one claim sent to them.

    The terms live on the **contract**, not on the payer — a renewal may
    change them, and a claim raised in March is judged by March's agreement.
    ``payer_terms=0`` is the "nothing typed" case, which is a different thing
    from "no time left" and must never be shown as a deadline.
    """
    from app.models import PayerContract, PayerEntity
    from app.models.payer import Claim

    with clinic["app"].app_context():
        payer = PayerEntity(name="شركة تأمين", entity_type="insurance",
                            is_active=True)
        clinic["db"].session.add(payer)
        clinic["db"].session.flush()
        clinic["db"].session.add(PayerContract(
            payer_id=payer.id, number="C-1",
            start_date=date(2026, 1, 1), end_date=date(2026, 12, 31),
            is_active=True, filing_days=90,
            payment_days=payer_terms or None))
        row = Claim(claim_number="CLM-1", payer_id=payer.id,
                    date_from=date(2026, 3, 1), date_to=date(2026, 3, 1),
                    status="submitted", total_amount=100,
                    submitted_at=submitted_at)
        clinic["db"].session.add(row)
        clinic["db"].session.commit()
        return row.id


def _get(clinic, claim_id):
    from app.models.payer import Claim

    return clinic["db"].session.get(Claim, claim_id)


# ------------------------------------------------------------- the fault --
def test_a_claim_sent_after_midnight_here_is_dated_here(clinic):
    """**The bug, stated as the rule.** 22:30 UTC is already the 11th in
    Cairo, and the 11th is the day the clinic will tell the payer."""
    from app.utils import claim_clock

    cid = _claim(clinic)
    with clinic["app"].app_context():
        assert claim_clock.sent_on(_get(clinic, cid)) == IN_CAIRO


def test_the_money_falls_due_from_that_day_too(clinic):
    """Which is the consequence that costs something: a due date a day early
    makes a payer look late before they are."""
    from app.utils import claim_clock

    cid = _claim(clinic, payer_terms=30)
    with clinic["app"].app_context():
        due = claim_clock.payment_due(_get(clinic, cid))
        assert due == IN_CAIRO + timedelta(days=30)
        assert due != IN_UTC + timedelta(days=30)


def test_and_the_overdue_count_agrees_with_it(clinic):
    """The number a desk acts on. ``today`` is passed in, so this asserts the
    arithmetic rather than what time it happens to be."""
    from app.utils import claim_clock

    cid = _claim(clinic, payer_terms=30)
    with clinic["app"].app_context():
        claim = _get(clinic, cid)
        due = IN_CAIRO + timedelta(days=30)
        assert claim_clock.days_overdue(claim, today=due) == 0
        assert claim_clock.days_overdue(claim, today=due + timedelta(days=5)) == 5


def test_a_claim_sent_at_midday_is_the_same_day_either_way(clinic):
    """Most of the day the two calendars agree — which is exactly why this
    went unnoticed. Asserted so the fix is not read as a blanket day shift."""
    from app.utils import claim_clock

    cid = _claim(clinic, submitted_at=datetime(2026, 3, 10, 9, 0))
    with clinic["app"].app_context():
        assert claim_clock.sent_on(_get(clinic, cid)) == IN_UTC


# ------------------------------------------------- the two calendars agree --
def test_the_age_and_the_due_date_are_counted_from_one_day(clinic):
    """They are two numbers on the same row of the same screen. Read from two
    calendars they can disagree by a day, and a reader has no way to tell
    which one to believe."""
    from app.utils import claim_clock

    _claim(clinic, payer_terms=30)
    with clinic["app"].app_context():
        row = claim_clock.outstanding(today=IN_CAIRO + timedelta(days=40))[0]
        assert row["age"] == 40
        assert row["due"] == IN_CAIRO + timedelta(days=30)
        assert row["overdue"] == 10


# ----------------------------------------------------------- the limit --
def test_an_unknown_zone_falls_back_rather_than_guessing(clinic):
    """``to_local`` answers ``None`` when the zone cannot be resolved — on
    Windows without ``tzdata`` that is every zone. An unknown zone is a
    question nobody answered, and answering it with a guess is how this
    program would start inventing dates."""
    from app.utils import claim_clock

    cid = _claim(clinic)
    with clinic["app"].app_context():
        import app.utils.clock as clock

        real = clock.to_local
        clock.to_local = lambda *a, **k: None
        try:
            assert claim_clock.sent_on(_get(clinic, cid)) == IN_UTC
        finally:
            clock.to_local = real


def test_a_claim_that_was_never_sent_has_no_date(clinic):
    from app.utils import claim_clock

    cid = _claim(clinic, submitted_at=None)
    with clinic["app"].app_context():
        claim = _get(clinic, cid)
        assert claim_clock.sent_on(claim) is None
        assert claim_clock.payment_due(claim) is None
        assert claim_clock.days_overdue(claim) == 0


def test_nothing_is_due_when_the_payer_has_no_terms(clinic):
    """The switch this module already had: no term typed, no deadline shown.
    The calendar fix must not have quietly invented one."""
    from app.utils import claim_clock

    cid = _claim(clinic, payer_terms=0)
    with clinic["app"].app_context():
        assert claim_clock.payment_due(_get(clinic, cid)) is None
