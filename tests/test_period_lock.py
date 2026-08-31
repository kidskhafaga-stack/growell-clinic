"""A closed month is closed for the store too.

Closing the books means a report printed in February still says the same
thing in June. That only holds if *nothing of value* can be written into
January afterwards — and stock is value. A box received into a signed month
changes that month's closing stock, which changes cost of sales, which
changes the profit somebody already signed for.

So the store obeys the same lock the till does, through the same helper.
"""
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# The clinic's today, not the server's — the same clock the screens filter by.
#
# These built their world with `local_today()` while the report they check
# filters on `local_today()`, and the two disagree for the three hours a day
# when it is already tomorrow in Cairo and still today in UTC. The suite went
# green at 23:28 Cairo and red at 00:20, on the same commit, with nothing
# changed in between. conftest.py warns about exactly this at the top of the
# file.
from app.utils.clock import local_today  # noqa: E402


import pytest  # noqa: E402


@pytest.fixture()
def clinic():
    """A logged-in admin, one store item, and this month as a period.

    The ``testing`` config is in-memory, so each test starts on an empty
    database and nothing here can reach the developer's real one. Nothing is
    written back onto the config class either: that leaks into every test
    that builds an app afterwards.
    """
    from app import create_app
    from app.extensions import db

    app = create_app("testing")

    with app.app_context():
        db.create_all()
        from app.models import StoreItem, User
        from app.utils.periods import ensure_month

        user = User(username="boss", full_name="مدير", role="admin",
                    is_active=True)
        user.set_password("secret")
        db.session.add(user)
        item = StoreItem(name="قفازات", unit="علبة", is_active=True,
                         purchase_price=50, sell_price=70)
        db.session.add(item)
        today = local_today()
        period = ensure_month(today.year, today.month)
        db.session.commit()
        ids = {"item": item.id, "period": period.id}

    client = app.test_client()
    client.post("/login", data={"username": "boss", "password": "secret"},
                follow_redirects=True)
    yield {"app": app, "db": db, "client": client, "ids": ids}


def _close(clinic, closed=True):
    from app.models import AccountingPeriod
    from app.utils.periods import close_period, reopen_period

    with clinic["app"].app_context():
        period = clinic["db"].session.get(AccountingPeriod,
                                          clinic["ids"]["period"])
        (close_period if closed else reopen_period)(period)
        clinic["db"].session.commit()


def _movements(clinic):
    from app.models import StockMovement

    with clinic["app"].app_context():
        return StockMovement.query.count()


def _receive(clinic, qty=5):
    return clinic["client"].post(
        f"/inventory/store/{clinic['ids']['item']}/move",
        data={"kind": "in", "qty": str(qty), "unit_cost": "50"},
        follow_redirects=True)


# ------------------------------------------------------------- the helper --
def test_an_open_month_blocks_nothing(clinic):
    from app.utils.periods import period_blocked

    with clinic["app"].app_context():
        assert period_blocked(local_today(), flash_it=False) is False


def test_a_closed_month_is_blocked(clinic):
    from app.utils.periods import period_blocked

    _close(clinic)
    with clinic["app"].app_context():
        assert period_blocked(local_today(), flash_it=False) is True


def test_a_date_no_period_covers_is_not_blocked(clinic):
    """A clinic that never defined periods must not find the store frozen."""
    from app.utils.periods import period_blocked

    _close(clinic)
    with clinic["app"].app_context():
        far_off = local_today() + timedelta(days=400)
        assert period_blocked(far_off, flash_it=False) is False


def test_no_date_is_not_blocked(clinic):
    from app.utils.periods import period_blocked

    _close(clinic)
    with clinic["app"].app_context():
        assert period_blocked(None, flash_it=False) is False


def test_reopening_lifts_the_block(clinic):
    """Reopening is deliberate and logged — and it has to actually work."""
    from app.utils.periods import period_blocked

    _close(clinic)
    _close(clinic, closed=False)
    with clinic["app"].app_context():
        assert period_blocked(local_today(), flash_it=False) is False


# -------------------------------------------------------------- the store --
def test_stock_can_be_received_while_the_month_is_open(clinic):
    before = _movements(clinic)
    assert _receive(clinic).status_code == 200
    assert _movements(clinic) == before + 1


def test_a_closed_month_refuses_a_receipt(clinic):
    """The refusal is the point: nothing written, and a reason on screen."""
    _close(clinic)
    before = _movements(clinic)
    resp = _receive(clinic)
    assert resp.status_code == 200
    assert _movements(clinic) == before


def test_the_refusal_says_which_month(clinic):
    """A silent no-op reads as a bug. Name the period that refused."""
    from app.models import AccountingPeriod

    _close(clinic)
    with clinic["app"].app_context():
        name = clinic["db"].session.get(AccountingPeriod,
                                        clinic["ids"]["period"]).name
    body = _receive(clinic).get_data(as_text=True)
    assert name in body


def test_reopening_lets_the_receipt_through(clinic):
    _close(clinic)
    _receive(clinic)
    _close(clinic, closed=False)
    before = _movements(clinic)
    _receive(clinic)
    assert _movements(clinic) == before + 1


def _stocktake(clinic, counted=99):
    return clinic["client"].post(
        "/inventory/store/stocktake",
        data={f"count_{clinic['ids']['item']}": str(counted)},
        follow_redirects=True)


def test_a_closed_month_refuses_a_stocktake(clinic):
    """Counting the shelf and writing the difference is an adjustment — it
    moves value exactly like a receipt does. The open month proves the count
    would otherwise have been posted, so the refusal is the lock and not an
    empty form."""
    assert _stocktake(clinic).status_code == 200
    posted = _movements(clinic)
    assert posted > 0, "the count should have adjusted the shelf"

    _close(clinic)
    assert _stocktake(clinic, counted=7).status_code == 200
    assert _movements(clinic) == posted


# --------------------------------------------- every writing route is held --
def test_no_stock_writing_route_was_left_unguarded():
    """A route added later that posts stock and forgets the guard is a hole
    that only shows up in a signed month. Name them here so it can't happen
    quietly."""
    import inspect

    from app.blueprints.inventory import routes

    guarded = ("batch_new", "receipt_new", "store_move", "stocktake",
               "vaccine_stocktake", "batch_delete", "transfer_new",
               "return_new", "purchase_receive")
    for name in guarded:
        source = inspect.getsource(getattr(routes, name))
        assert "period_blocked(" in source, f"{name} writes stock unguarded"
