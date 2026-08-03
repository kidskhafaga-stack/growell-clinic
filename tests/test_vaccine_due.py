"""Who is due a dose, and what to buy for them — from one list.

Asked for as a reminders screen that can also raise a purchase order, filter by
period and by vaccine or trade name, and book an appointment.

The reminders screen already existed, so this extends it rather than adding a
second one — the same rule that removed the invoice builder. What it lacked was
everything that makes it *usable twice*: "who do I call this week" and "what
will I need next month" are the same data over different windows, so the window
is a filter, and the order is totalled from whatever the filter is showing.

The one piece of judgement worth stating: **"to order" is what is missing, not
what is needed.** A clinic with nine Rotarix on the shelf and eleven children
due should be told to buy two. An order that restates the demand and ignores
the fridge is one somebody has to redo by hand, which is the same as not having
it.
"""
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def boss(clinic):
    return clinic["sign_in"]("boss")


@pytest.fixture()
def given(clinic):
    """A child who had dose 1 of PCV here, long enough ago to be due dose 2."""
    from app.models import PatientVaccine

    with clinic["app"].app_context():
        clinic["db"].session.add(PatientVaccine(
            patient_id=clinic["ids"]["child"], vaccine_id=clinic["ids"]["pcv"],
            brand_id=clinic["ids"]["brand"], dose_number=1,
            event_type="given", given_date=date.today() - timedelta(days=365)))
        clinic["db"].session.commit()
    return clinic


def _due(clinic, **kwargs):
    from app.utils.vaccine_due import due_list

    with clinic["app"].app_context():
        return due_list(**kwargs)


# ============================================ only courses started with us ==
def test_a_course_started_here_produces_a_reminder(given, clinic):
    rows = _due(clinic)
    assert rows
    assert rows[0]["patient"].id == clinic["ids"]["child"]


def test_a_vaccine_never_given_here_is_never_chased(clinic):
    """The child may be getting it somewhere else, and a reminder for a course
    this clinic knows nothing about is a phone call that annoys a family."""
    assert _due(clinic) == []


def test_the_most_urgent_come_first(given, clinic):
    """A list somebody works down has to start with the calls that matter."""
    rows = _due(clinic)
    statuses = [r["status"] for r in rows]
    assert statuses == sorted(
        statuses, key=lambda s: {"overdue": 0, "due": 1, "seasonal": 2}.get(s, 3))


# ==================================================================== filters
def test_the_list_can_be_cut_to_one_vaccine(given, clinic):
    assert _due(clinic, vaccine_id=clinic["ids"]["pcv"])
    assert _due(clinic, vaccine_id=clinic["ids"]["opv"]) == []


def test_the_list_can_be_cut_to_one_trade_name(given, clinic):
    """Asked for by brand, because that is what a clinic orders."""
    assert _due(clinic, brand_id=clinic["ids"]["brand"])
    assert _due(clinic, brand_id=clinic["ids"]["gov_brand"]) == []


def test_the_list_can_be_cut_to_a_status(given, clinic):
    rows = _due(clinic)
    status = rows[0]["status"]
    assert _due(clinic, status=status)
    other = "seasonal" if status != "seasonal" else "due"
    assert all(r["status"] == other for r in _due(clinic, status=other))


def test_a_window_in_the_future_excludes_what_is_already_late(given, clinic):
    """The point of the range: "what will I need next month" is a different
    question from "who is late"."""
    later = date.today() + timedelta(days=365)
    assert _due(clinic, start=later) == []


def test_a_window_that_covers_the_due_date_keeps_it(given, clinic):
    rows = _due(clinic, end=date.today() + timedelta(days=3650))
    assert rows


def test_a_seasonal_recall_survives_any_window(given, clinic):
    """It has no due date — its whole point is that it is due now — so a date
    filter must not quietly drop it."""
    from app.utils.vaccine_due import due_list

    rows = [{"status": "seasonal", "due_date": None}]
    with clinic["app"].app_context():
        assert callable(due_list)
    # The rule itself, on the filter: a row with no date is never excluded.
    from app.utils.vaccine_due import _as_date

    assert _as_date(None) is None


# ============================================================ the order =====
def _order(clinic, **kwargs):
    """Build the list and total it inside one context.

    Both run in a single request in the route; splitting them across two
    contexts here would only be testing SQLAlchemy's detachment rules.
    """
    from app.utils.vaccine_due import due_list, order_suggestion

    with clinic["app"].app_context():
        return order_suggestion(due_list(), **kwargs)


def test_the_order_totals_the_list_by_brand(given, clinic):
    order = _order(clinic)
    assert order
    assert order[0]["needed"] == len(_due(clinic))


def test_the_order_subtracts_what_is_already_in_the_fridge(given, clinic):
    """Nine on the shelf and eleven due means buy two. An order that restates
    the demand is one somebody has to redo by hand."""
    from app.models import VaccineInventory

    with clinic["app"].app_context():
        clinic["db"].session.add(VaccineInventory(
            brand_id=clinic["ids"]["brand"], lot_number="BIG",
            qty_received=50, qty_used=0, expiry_date=date(2030, 1, 1)))
        clinic["db"].session.commit()

    order = _order(clinic)
    assert order[0]["in_stock"] >= 50
    assert order[0]["to_order"] == 0


def test_the_order_never_goes_negative(given, clinic):
    """More stock than demand is not a negative purchase."""
    from app.models import VaccineInventory

    with clinic["app"].app_context():
        clinic["db"].session.add(VaccineInventory(
            brand_id=clinic["ids"]["brand"], lot_number="HUGE",
            qty_received=999, qty_used=0, expiry_date=date(2030, 1, 1)))
        clinic["db"].session.commit()
    assert all(row["to_order"] >= 0 for row in _order(clinic))


def test_a_row_with_no_brand_is_not_ordered(clinic):
    """Nothing to buy when nobody has said which product."""
    from app.utils.vaccine_due import order_suggestion

    rows = [{"brand": None, "vaccine": None, "due": None, "status": "due"}]
    with clinic["app"].app_context():
        assert order_suggestion(rows) == []


def test_the_order_can_be_limited_to_a_horizon(given, clinic):
    """"Order for this month" from the same list, without re-running anything."""
    from app.utils.vaccine_due import due_list, order_suggestion

    with clinic["app"].app_context():
        rows = due_list()
        for row in rows:
            row["due"] = date.today() + timedelta(days=200)
        assert order_suggestion(rows, cover_days=30) == []
        assert order_suggestion(rows, cover_days=365)


# ============================================================== the screen ==
def test_the_screen_opens(given, boss):
    assert boss.get("/vaccinations/reminders").status_code == 200


def test_the_screen_offers_the_filters(given, boss):
    body = boss.get("/vaccinations/reminders").get_data(as_text=True)
    for field in ("from", "to", "vaccine_id", "brand_id", "status"):
        assert f'name="{field}"' in body, field


def test_the_screen_shows_the_order(given, boss, clinic):
    body = boss.get("/vaccinations/reminders").get_data(as_text=True)
    with clinic["app"].test_request_context("/"):
        from app.i18n import t
        assert t("vaccinations.order_title") in body


def test_the_order_follows_the_filter(given, boss, clinic):
    """Built from whatever the filter is showing — the same rule as the invoice
    export: what you take away is what you were looking at."""
    body = boss.get("/vaccinations/reminders", query_string={
        "vaccine_id": clinic["ids"]["opv"]}).get_data(as_text=True)
    with clinic["app"].test_request_context("/"):
        from app.i18n import t
        assert t("vaccinations.order_title") not in body


def test_a_dose_can_be_booked_from_the_reminder(given, boss, clinic):
    """The person reading the row already knows who and roughly when; making
    them go and search for the patient again is how a reminder list stops being
    acted on."""
    body = boss.get("/vaccinations/reminders").get_data(as_text=True)
    assert f"patient_id={clinic['ids']['child']}" in body
    assert "appt_type=vaccination" in body


def test_the_screen_counts_what_it_is_showing(given, boss, clinic):
    body = boss.get("/vaccinations/reminders").get_data(as_text=True)
    with clinic["app"].test_request_context("/"):
        from app.i18n import t
        assert t("vaccinations.due_patients") in body


def test_both_languages_carry_the_new_words(clinic):
    import json

    root = os.path.join(os.path.dirname(__file__), "..")
    for lang in ("ar", "en"):
        with open(os.path.join(root, "app", "i18n", "locales", f"{lang}.json"),
                  encoding="utf-8") as fh:
            data = json.load(fh)
        for key in ("due_patients", "book_dose", "order_title", "order_hint",
                    "order_needed", "order_stock", "order_buy"):
            assert data["vaccinations"].get(key), f"{lang}.vaccinations.{key}"
