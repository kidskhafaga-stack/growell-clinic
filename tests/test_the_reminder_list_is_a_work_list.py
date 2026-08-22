"""The reminder screen, made into something a clinic can work from.

Asked directly, looking at it: *"why is the vaccination reminder screen so
big — why isn't it split like the patients screen?"*

Because it was never paged. `app/utils/paging.py` opens by saying that every
long list in this program is paged and that nothing is ever truncated; this
screen is the one that slipped through, and it drew every row it had. On a
real register that is thousands of rows in one page — slow to render, and
impossible to work from.

Paging alone would not have fixed it, because the **order** was wrong for the
job. Rows were sorted by due date ascending, so the screen opened with the
oldest misses: pages of children whose second hepatitis A has been outstanding
since 2012, before anything anybody could act on today.

That is the real finding. "Overdue" was carrying two unlike things:

    a one-year-old three weeks behind on a pneumococcal dose   ← a call today
    a sixteen-year-old outstanding since 2012                  ← a fact on file

Both are true. One of them is work. So a row now carries **how late** it is,
the list is ordered most-actionable-first, and the bands are chips somebody can
filter by rather than a judgement the program makes for them — nothing is
hidden, and the long tail is one click away instead of on top.

None of this invents a clinical number, which is the point: the same fix
improves every vaccine at once, including the ones whose schedules are still
open questions.
"""
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

from app.utils.clock import local_today  # noqa: E402


@pytest.fixture()
def seeded(clinic):
    from app.extensions import db

    from app.utils.vaccines import seed_vaccine_schedules, seed_vaccines

    with clinic["app"].app_context():
        seed_vaccines()
        seed_vaccine_schedules()
        db.session.commit()
    return clinic


def _late_children(clinic, ages):
    """One child per age, each with a first hepatitis A dose at twelve months
    and the second never given — so how late they are is their age."""
    from app.extensions import db
    from app.models import Patient, PatientVaccine, Vaccine

    with clinic["app"].app_context():
        hav = Vaccine.query.filter_by(code="HAV").first()
        for i, years in enumerate(ages):
            dob = local_today() - timedelta(days=int(years * 365.25))
            kid = Patient(patient_number=f"WL{i}", full_name=f"طفل {i}",
                          gender="male", date_of_birth=dob, is_active=True)
            db.session.add(kid)
            db.session.flush()
            db.session.add(PatientVaccine(
                patient_id=kid.id, vaccine_id=hav.id,
                brand_id=hav.default_brand.id, dose_number=1,
                event_type="given", given_date=dob + timedelta(days=365)))
        db.session.commit()


# --------------------------------------------------------- how late it is

@pytest.mark.parametrize("days_late,expected", [
    (-5, "due"), (0, "recent"), (3, "recent"), (30, "recent"),
    (31, "year"), (200, "year"), (365, "year"), (366, "old"), (5000, "old"),
])
def test_the_bands_are_where_a_clinic_would_put_them(days_late, expected):
    from app.utils.vaccine_due import lateness_of

    today = date(2026, 8, 22)
    status = "due" if days_late < 0 else "overdue"

    assert lateness_of(status, today - timedelta(days=days_late),
                       today) == expected


def test_a_seasonal_recall_is_owed_now_not_late(seeded):
    """It has no due date at all — its whole point is that it is due now."""
    from app.utils.vaccine_due import lateness_of

    assert lateness_of("seasonal", None, date(2026, 8, 22)) == "due"


# ------------------------------------------------------------- the order

def test_the_screen_opens_with_what_can_be_acted_on(seeded):
    """The finding this file exists for.

    Sorted by date, the top of the screen was 2012. A calling list that opens
    with the least reachable families is one nobody scrolls.
    """
    from app.utils.vaccine_due import due_list

    _late_children(seeded, [1.6, 3.0, 8.0, 16.0])

    with seeded["app"].app_context():
        rows = due_list()

    bands = [r["lateness"] for r in rows]
    assert bands == sorted(bands, key=["due", "recent", "year", "old"].index), \
        f"the long tail is not at the bottom: {bands}"

    ages = [(local_today() - r["patient"].date_of_birth).days for r in rows]
    assert ages[0] < ages[-1], \
        "the oldest miss is still at the top of the calling list"


def test_within_a_band_the_most_recent_miss_comes_first(seeded):
    from app.utils.vaccine_due import due_list

    _late_children(seeded, [3.0, 8.0, 16.0])

    with seeded["app"].app_context():
        rows = [r for r in due_list() if r["lateness"] == "old"]

    dates = [r["due_date"] for r in rows]
    assert dates == sorted(dates, reverse=True), dates


def test_nothing_is_dropped_by_the_reordering(seeded):
    """Reordering is not filtering. Every row that was on the screen is still
    on it, which is the promise `paging.py` opens with."""
    from app.utils.vaccine_due import due_list

    _late_children(seeded, [1.6, 3.0, 8.0, 16.0])

    with seeded["app"].app_context():
        assert len(due_list()) == 4


# ------------------------------------------------------------ the paging

def test_the_screen_is_paged_like_every_other_long_list(seeded):
    _late_children(seeded, [2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13])

    page = seeded["sign_in"]("doc").get(
        "/vaccinations/reminders?per_page=25", follow_redirects=True)
    body = page.data.decode()

    assert "pager-bar" in body, "the reminder list still has no pager"


def test_a_page_holds_what_was_asked_for(seeded):
    from app.utils.paging import ListPage

    rows = list(range(312))
    page = ListPage(rows, 3, 25)

    assert page.total == 312 and page.pages == 13
    assert page.items == list(range(50, 75))
    assert (page.prev_num, page.next_num) == (2, 4)


def test_asking_past_the_end_is_the_last_page_not_a_blank_screen(seeded):
    """Narrowing a filter while standing on page 7 must not look like lost
    data — the same rule the query pager already follows."""
    from app.utils.paging import ListPage

    page = ListPage(list(range(10)), 99, 25)

    assert page.page == 1 and len(page.items) == 10


def test_an_empty_list_pages_without_falling_over(seeded):
    from app.utils.paging import ListPage

    page = ListPage([], 1, 25)

    assert (page.total, page.pages, page.items, page.has_next) == (0, 0, [], False)


# ------------------------------------------------------- the counts and order

def test_the_purchase_order_still_covers_everybody(seeded):
    """The rule this screen already had: what you take away is what you were
    looking at — the whole filtered set, not the page you happened to be
    standing on. Paging a screen is exactly how that gets broken.
    """
    # More children than fit on a page, and deliberately: with twelve rows on
    # a page of twenty-five the page *is* the whole list, and a mutation that
    # builds the order from `page.items` passes. Measured.
    _late_children(seeded, [2 + i * 0.1 for i in range(30)])

    # Read out of the template's own context, not searched for in the HTML:
    # "30" appears on a page full of ages and counts, so a substring check
    # passed with the order built from a single page. Measured, twice.
    from flask import template_rendered

    seen = {}

    def record(_sender, template, context, **_kw):
        for key in ("order", "counts"):
            if key in context:
                seen[key] = context[key]

    template_rendered.connect(record, seeded["app"])
    try:
        seeded["sign_in"]("doc").get("/vaccinations/reminders?per_page=25",
                                     follow_redirects=True)
    finally:
        template_rendered.disconnect(record, seeded["app"])

    assert seen, "the reminders template did not render"
    assert sum(r["needed"] for r in seen["order"]) == 30, \
        "the purchase order was built from one page instead of the whole list"
    assert seen["counts"]["total"] == 30, \
        "the counts describe one page instead of the whole list"


def test_the_counts_describe_the_whole_list(seeded):
    from app.utils.vaccine_due import due_list, summarise

    _late_children(seeded, [1.6, 3.0, 8.0, 16.0])

    with seeded["app"].app_context():
        counts = summarise(due_list())

    assert counts["total"] == 4
    assert counts["year"] + counts["old"] == 4


# ------------------------------------------------------------- the filter

def test_a_band_can_be_asked_for_on_its_own(seeded):
    _late_children(seeded, [1.6, 3.0, 8.0, 16.0])

    client = seeded["sign_in"]("doc")
    everything = client.get("/vaccinations/reminders",
                            follow_redirects=True).data.decode()
    only_old = client.get("/vaccinations/reminders?late=old",
                          follow_redirects=True).data.decode()

    assert "WL0" in everything, "the sixteen-month-old is missing entirely"
    assert "WL0" not in only_old, "filtering by band did nothing"
    assert "WL3" in only_old


def test_a_band_nobody_offers_is_ignored_rather_than_an_error(seeded):
    """It comes from the URL, so a typo or a stale link must not cost somebody
    their list."""
    _late_children(seeded, [3.0])

    body = seeded["sign_in"]("doc").get(
        "/vaccinations/reminders?late=nonsense",
        follow_redirects=True).data.decode()

    assert "WL0" in body


def test_the_wording_exists_in_both_languages(seeded):
    import json

    here = os.path.dirname(os.path.abspath(__file__))
    for lang in ("ar", "en"):
        with open(os.path.join(here, "..", "app/i18n/locales", f"{lang}.json"),
                  encoding="utf-8") as fh:
            block = json.load(fh)["vlate"]
        for band in ("due", "recent", "year", "old"):
            assert band in block, f"{lang} is missing vlate.{band}"
