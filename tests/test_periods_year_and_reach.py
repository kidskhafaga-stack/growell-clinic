"""Three things found by opening the screens rather than the code.

**The year was a closed list.** It offered 2021–2028 and nothing else, so a
clinic entering 2019's books, or opening 2030, was told no by a dropdown with
nothing on the screen explaining why. The suggestions were never meant to be
the boundary — they are the years wanted nine times out of ten. It is typed
now, with those years suggested.

**"Created 0" was reported as success.** Creating periods is idempotent, so
pressing the button twice is harmless — but a green "0 created" reads as a
failure nobody can explain. It says which year already has them.

**And the history import screen had no link anywhere at all.** Reachable only
by typing the URL: nine thousand rows of work behind a door with no handle.
That is exactly how the contracts screen was lost, and it is worth a test of
its own, because a feature nobody can reach is indistinguishable from one that
was never built.
"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def boss(clinic):
    return clinic["sign_in"]("boss")


# ============================================================== any year ====
def test_a_year_outside_the_suggestions_is_accepted(boss, clinic):
    """2019 was unreachable. A clinic entering last decade's books is a normal
    reason to open this screen."""
    from app.models import AccountingPeriod

    boss.post("/finance/periods", data={
        "action": "generate", "year": "2019", "kind": "month"},
        follow_redirects=True)
    with clinic["app"].app_context():
        made = AccountingPeriod.query.filter(
            AccountingPeriod.start_date >= date(2019, 1, 1),
            AccountingPeriod.start_date <= date(2019, 12, 31)).count()
    assert made == 12


def test_a_year_far_ahead_is_accepted_too(boss, clinic):
    from app.models import AccountingPeriod

    boss.post("/finance/periods", data={
        "action": "generate", "year": "2035", "kind": "year"},
        follow_redirects=True)
    with clinic["app"].app_context():
        assert AccountingPeriod.query.filter(
            AccountingPeriod.start_date == date(2035, 1, 1)).count() == 1


def test_the_year_is_typed_not_only_picked(boss, clinic):
    body = boss.get("/finance/periods").get_data(as_text=True)
    assert 'name="year" type="number"' in body
    # …and the usual years are still offered, because typing 2026 every time
    # would be a worse screen than the one this replaces.
    assert "<datalist" in body


def test_a_nonsense_year_falls_back_rather_than_creating_anything(clinic):
    """A stray keystroke turning 2026 into 22026 would otherwise create twelve
    periods twenty thousand years out, and somebody would go looking."""
    from app.utils.periods import valid_year

    with clinic["app"].app_context():
        assert valid_year("22026") == date.today().year
        assert valid_year("") == date.today().year
        assert valid_year(None) == date.today().year
        assert valid_year("abc") == date.today().year
        assert valid_year("2019") == 2019


def test_the_suggestions_still_cover_the_usual_span(clinic):
    from app.utils.periods import selectable_years

    with clinic["app"].app_context():
        years = selectable_years()
    assert date.today().year in years
    assert date.today().year + 1 in years


# ================================================ pressing it twice =========
def test_making_the_same_periods_again_says_they_are_already_there(boss, clinic):
    """Idempotent is right; reporting it as "0 created, success" is not."""
    data = {"action": "generate", "year": "2026", "kind": "month"}
    boss.post("/finance/periods", data=data, follow_redirects=True)
    body = boss.post("/finance/periods", data=data,
                     follow_redirects=True).get_data(as_text=True)

    with clinic["app"].test_request_context("/"):
        from app.i18n import t
        assert t("periods.already_there").split("{")[0].strip() in body


def test_it_says_how_many_are_already_there(boss, clinic):
    data = {"action": "generate", "year": "2026", "kind": "month"}
    boss.post("/finance/periods", data=data, follow_redirects=True)
    body = boss.post("/finance/periods", data=data,
                     follow_redirects=True).get_data(as_text=True)
    assert "12" in body


def test_a_second_kind_in_the_same_year_is_not_a_duplicate(boss, clinic):
    """Months and quarters coexist on purpose — a clinic that reviews
    quarterly closes the quarter. Adding quarters after months must not be
    reported as "already there"."""
    from app.models import AccountingPeriod

    boss.post("/finance/periods", data={
        "action": "generate", "year": "2026", "kind": "month"},
        follow_redirects=True)
    boss.post("/finance/periods", data={
        "action": "generate", "year": "2026", "kind": "quarter"},
        follow_redirects=True)

    with clinic["app"].app_context():
        assert AccountingPeriod.query.filter_by(kind="quarter").count() == 4
        assert AccountingPeriod.query.filter_by(kind="month").count() == 12


def test_the_count_is_per_kind(clinic):
    from app.utils.periods import count_periods, generate_periods

    with clinic["app"].app_context():
        generate_periods(2026, "month")
        clinic["db"].session.commit()
        assert count_periods(2026, "month") == 12
        assert count_periods(2026, "quarter") == 0
        assert count_periods(2026) == 12


# ======================================= and the screen you could not reach ==
def test_the_history_import_has_a_way_in_from_the_patients_screen(boss, clinic):
    """It had none at all. A feature reachable only by typing its URL is
    indistinguishable from one that was never built."""
    body = boss.get("/patients/").get_data(as_text=True)
    assert "/patients/import/history" in body


def test_the_data_tools_screen_offers_the_way_in_too(boss, clinic):
    """The screen is called "data tools" and carried only the ways *out*. A
    clinic moving off another program looks here first."""
    body = boss.get("/settings/data").get_data(as_text=True)
    assert "/patients/import/history" in body
    assert "/patients/import/patients" in body or "/patients/import" in body


def test_the_past_imports_are_reachable_as_well(boss, clinic):
    """Undo lives on that screen, and undo you cannot find is not undo."""
    body = boss.get("/settings/data").get_data(as_text=True)
    assert "/patients/import/history/batches" in body


def test_both_languages_carry_the_new_words(clinic):
    import json

    root = os.path.join(os.path.dirname(__file__), "..")
    for lang in ("ar", "en"):
        with open(os.path.join(root, "app", "i18n", "locales", f"{lang}.json"),
                  encoding="utf-8") as fh:
            data = json.load(fh)
        assert data["periods"].get("already_there"), lang
        assert data["data_tools"].get("import_title"), lang
        assert data["data_tools"].get("import_hint"), lang
