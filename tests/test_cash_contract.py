"""The clinic's own price list must not expire on New Year's Day.

The cash "contract" is not an agreement with anybody — it is the clinic's own
prices for the walk-in patient. But coverage only applies while a contract is
current, so a list that ran to 31 December leaves the clinic with **no prices at
all on 1 January**: every service quietly falls back to its catalogue figure.

The failure has no symptom on any screen. Nobody sees a warning; they see a
bill, and it is wrong, and it looks exactly like a correct one. That is why this
is a batch-1 item and not a convenience.

The renewal **copies** the prices into a new year rather than pushing the old
contract's end date out, for two reasons: what a service cost in 2026 stays
answerable in 2027, and a clinic raising prices in the new year needs somewhere
to do it that does not rewrite what it charged last year.
"""
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def cash(clinic):
    """A cash payer holding a price list that ends today."""
    from app.models import PayerContract, PayerContractRate, PayerEntity
    from app.utils.pricing import set_cash_payer

    with clinic["app"].app_context():
        payer = PayerEntity(name="العقد النقدي", entity_type="cash",
                            is_active=True)
        clinic["db"].session.add(payer)
        clinic["db"].session.flush()

        contract = PayerContract(
            payer_id=payer.id, number="1", is_active=True,
            start_date=date.today() - timedelta(days=364),
            end_date=date.today())
        contract.rates.append(PayerContractRate(
            service_id=clinic["ids"]["exam"], special_price=150))
        clinic["db"].session.add(contract)
        set_cash_payer(payer.id)
        clinic["db"].session.commit()
        clinic["payer"] = payer.id
        clinic["contract"] = contract.id
    return clinic


def _contracts(cash):
    from app.models import PayerContract

    return (PayerContract.query.filter_by(payer_id=cash["payer"])
            .order_by(PayerContract.start_date).all())


def _clear_stamp(cash):
    """The once-a-day guard, reset so a test can ask again."""
    from app.models import Setting

    Setting.set("cash_contract_renewed_on", "")
    cash["db"].session.commit()


# ------------------------------------------------------ the year window ----
def test_a_year_is_a_calendar_year_not_365_days():
    from app.utils.pricing import year_window

    start, end = year_window(date(2026, 7, 30))
    assert (start, end) == (date(2026, 7, 30), date(2027, 7, 29))


def test_a_leap_day_start_does_not_crash_or_drift():
    """29 February has no anniversary. Falling back a day keeps every later
    renewal on the same date instead of walking backwards each leap year."""
    from app.utils.pricing import year_window

    start, end = year_window(date(2028, 2, 29))
    assert start == date(2028, 2, 29) and end == date(2029, 2, 27)


# --------------------------------------------------------- the renewal -----
def test_a_list_about_to_lapse_is_renewed(cash):
    from app.utils.pricing import ensure_cash_contract

    with cash["app"].app_context():
        assert ensure_cash_contract() is not None
        assert len(_contracts(cash)) == 2


def test_the_new_year_starts_the_day_after_the_old_one_ends(cash):
    """No gap and no overlap — a single day of either is a day of wrong
    prices."""
    from app.utils.pricing import ensure_cash_contract

    with cash["app"].app_context():
        renewed = ensure_cash_contract()
        assert renewed.start_date == date.today() + timedelta(days=1)
        assert renewed.end_date == date.today() + timedelta(days=365)


def test_the_prices_come_across(cash):
    """A renewal that arrived empty would be worse than no renewal: the
    contract would be current and every price would fall back anyway."""
    from app.utils.pricing import ensure_cash_contract

    with cash["app"].app_context():
        renewed = ensure_cash_contract()
        assert [(r.service_id, r.special_price) for r in renewed.rates] == [
            (cash["ids"]["exam"], 150)]


def test_the_old_years_prices_are_left_alone(cash):
    """Copied, not extended — what the clinic charged last year stays
    answerable."""
    from app.models import PayerContract
    from app.utils.pricing import ensure_cash_contract

    with cash["app"].app_context():
        ensure_cash_contract()
        old = cash["db"].session.get(PayerContract, cash["contract"])
        assert old.end_date == date.today()
        assert [r.special_price for r in old.rates] == [150]


def test_the_renewed_contract_is_numbered_automatically(cash):
    from app.utils.pricing import ensure_cash_contract

    with cash["app"].app_context():
        assert ensure_cash_contract().number == "2"


# --------------------------------------------------- when it must NOT run --
def test_a_list_with_a_year_left_is_not_renewed_early(cash):
    """Preparing next year in January would leave it sitting there for twelve
    months collecting edits meant for the current one."""
    from app.models import PayerContract
    from app.utils.pricing import ensure_cash_contract

    with cash["app"].app_context():
        contract = cash["db"].session.get(PayerContract, cash["contract"])
        contract.end_date = date.today() + timedelta(days=300)
        cash["db"].session.commit()
        assert ensure_cash_contract() is None
        assert len(_contracts(cash)) == 1


def test_it_does_not_renew_twice(cash):
    """Idempotent, or a clinic that opens the screen twice gets two lists for
    the same year and no way to tell which one bills."""
    from app.utils.pricing import ensure_cash_contract

    with cash["app"].app_context():
        ensure_cash_contract()
        _clear_stamp(cash)
        assert ensure_cash_contract() is None
        assert len(_contracts(cash)) == 2


def test_a_year_prepared_by_hand_is_not_duplicated(cash):
    """Somebody who already made next year's list with their new prices must
    not find a copy of the old prices beside it."""
    from app.models import PayerContract
    from app.utils.pricing import ensure_cash_contract

    with cash["app"].app_context():
        cash["db"].session.add(PayerContract(
            payer_id=cash["payer"], number="99", is_active=True,
            start_date=date.today() + timedelta(days=1),
            end_date=date.today() + timedelta(days=365)))
        cash["db"].session.commit()
        assert ensure_cash_contract() is None
        assert len(_contracts(cash)) == 2


def test_an_open_ended_list_is_left_alone(cash):
    """It never lapses, so there is nothing to prepare."""
    from app.models import PayerContract
    from app.utils.pricing import ensure_cash_contract

    with cash["app"].app_context():
        contract = cash["db"].session.get(PayerContract, cash["contract"])
        contract.end_date = None
        cash["db"].session.commit()
        assert ensure_cash_contract() is None


def test_a_clinic_with_no_cash_list_is_not_given_one(cash):
    """The renewal keeps an existing list alive; it does not invent pricing
    for a clinic that never set any up.

    The entity is deactivated rather than just unsetting the chooser: a clinic
    with exactly one active cash entity gets it without any setting, which is
    deliberate, so clearing the setting alone would not be "no cash list".
    """
    from app.models import PayerEntity
    from app.utils.pricing import ensure_cash_contract, set_cash_payer

    with cash["app"].app_context():
        set_cash_payer(None)
        cash["db"].session.get(PayerEntity, cash["payer"]).is_active = False
        cash["db"].session.commit()
        _clear_stamp(cash)
        assert ensure_cash_contract() is None


def test_it_only_asks_once_a_day(cash):
    """The guard that lets this live on the pricing path: a busy morning must
    not re-run the check on every priced line."""
    from app.models import Setting
    from app.utils.pricing import ensure_cash_contract

    with cash["app"].app_context():
        ensure_cash_contract()
        assert Setting.get("cash_contract_renewed_on") == date.today().isoformat()


# ------------------------------------------------ the prices stay in force -
def test_the_cash_price_survives_the_turn_of_the_year(cash):
    """The failure this exists to prevent, end to end: ask for the price on the
    day the old list dies, and get the list's price rather than the catalogue's.
    """
    from app.models import Service
    from app.utils.pricing import cash_tariff, ensure_cash_contract

    with cash["app"].app_context():
        exam = cash["db"].session.get(Service, cash["ids"]["exam"])
        assert exam.price == 200                     # the catalogue figure
        assert cash_tariff(exam) == 150              # today, from the list

        ensure_cash_contract()
        tomorrow = date.today() + timedelta(days=1)
        assert cash_tariff(exam, tomorrow) == 150    # and after it rolls over


def test_pricing_itself_keeps_the_list_alive(cash):
    """Nobody opens the payers screen on 1 January — reception opens the
    cashier. So the check hangs off the pricing path too."""
    from app.models import Service
    from app.utils.pricing import cash_tariff

    with cash["app"].app_context():
        exam = cash["db"].session.get(Service, cash["ids"]["exam"])
        cash_tariff(exam)
        assert len(_contracts(cash)) == 2


def test_the_screen_says_it_renewed(cash):
    """A renewal nobody is told about is a price change nobody reviewed."""
    client = cash["sign_in"]("boss")
    body = client.get("/finance/payers").get_data(as_text=True)
    assert "اتجدّدت تلقائياً" in body


# ---------------------------------------------------- adding one by hand ---
def test_a_new_contract_needs_nothing_typed(cash):
    """Number generated, dates defaulted to a year — the form the user was
    looking at had an empty number box and no default period."""
    from app.models import PayerContract

    client = cash["sign_in"]("boss")
    client.post(f"/finance/payers/{cash['payer']}/contract/new", data={},
                follow_redirects=True)
    with cash["app"].app_context():
        made = (PayerContract.query.filter_by(payer_id=cash["payer"])
                .order_by(PayerContract.id.desc()).first())
        assert made.number and made.number.isdigit()
        assert made.start_date == date.today()
        assert made.end_date == date.today() + timedelta(days=364)


def test_two_contracts_never_share_a_number(cash):
    """The reason the number is generated at all."""
    from app.models import PayerContract

    client = cash["sign_in"]("boss")
    for _ in range(3):
        client.post(f"/finance/payers/{cash['payer']}/contract/new", data={},
                    follow_redirects=True)
    with cash["app"].app_context():
        numbers = [c.number for c in _contracts(cash)]
        assert len(numbers) == len(set(numbers)) == len(_contracts(cash))
        _ = PayerContract
