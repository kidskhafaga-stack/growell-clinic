"""Long lists: search on top, pages below, and you choose how many rows.

The thing worth testing hardest is not the arithmetic — it's that nothing is
silently cut off any more. The drug catalogue used to stop at 500 rows and the
drug reference at 300, with no pager and no message. With 25,000 medicines on
file that means the 501st is simply absent from a screen that claims to list
them, and the only person who finds out is a doctor who concludes the drug
isn't in the system.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def app():
    from app import create_app

    return create_app("testing")


# --------------------------------------------------------- the page size --
def test_the_offered_sizes_are_taken(app):
    from app.utils.paging import per_page

    for size in (25, 50, 100, 200):
        with app.test_request_context(f"/x?per_page={size}"):
            assert per_page() == size


def test_a_size_nobody_offered_is_ignored_not_an_error(app):
    """``?per_page=`` comes from a URL. A typo, a stale link or somebody
    probing must cost a fallback, never the list."""
    from app.utils.paging import per_page

    for junk in ("0", "-5", "999999", "abc", ""):
        with app.test_request_context(f"/x?per_page={junk}"):
            assert per_page() == 25


def test_the_choice_is_remembered_across_screens(app):
    """It's a preference about screens, not about one table: someone who
    picked 100 on the drug list shouldn't be asked again on the patient list."""
    from flask import session

    from app.utils.paging import per_page

    with app.test_request_context("/drugs?per_page=100"):
        assert per_page() == 100
        remembered = dict(session)

    with app.test_request_context("/patients"):
        session.update(remembered)
        assert per_page() == 100


def test_a_screen_can_ask_for_its_own_default(app):
    """The audit log showed 50 rows before this and still should."""
    from app.utils.paging import per_page

    with app.test_request_context("/audit"):
        assert per_page(default=50) == 50


def test_the_page_number_never_goes_below_one(app):
    from app.utils.paging import page_number

    for bad in ("0", "-4", "junk"):
        with app.test_request_context(f"/x?page={bad}"):
            assert page_number() == 1


def test_the_row_window_counts_from_one(app):
    """"Showing 51–75 of 312" — a page number alone says nothing about where
    you are in 25,000 rows."""
    from app.utils.paging import page_window

    class Page:
        def __init__(self, page, per_page, total, items):
            self.page, self.per_page = page, per_page
            self.total, self.items = total, items

    assert page_window(Page(1, 25, 312, [None] * 25)) == (1, 25)
    assert page_window(Page(3, 25, 312, [None] * 25)) == (51, 75)
    # The last page is short, and the window has to end at the real last row.
    assert page_window(Page(13, 25, 312, [None] * 12)) == (301, 312)
    assert page_window(Page(1, 25, 0, [])) == (0, 0)


# ------------------------------------------------------- the real screens --
@pytest.fixture()
def clinic():
    """A logged-in admin and 60 medicines to page through."""
    from app import create_app
    from app.extensions import db

    app = create_app("testing")
    with app.app_context():
        db.create_all()
        from app.models import Drug, User

        boss = User(username="boss", full_name="مدير", role="admin",
                    is_active=True)
        boss.set_password("secret")
        db.session.add(boss)
        for i in range(60):
            db.session.add(Drug(trade_name=f"Drug {i:03d}",
                                generic_name="paracetamol" if i < 10 else "x",
                                is_active=True))
        db.session.commit()

    client = app.test_client()
    client.post("/login", data={"username": "boss", "password": "secret"},
                follow_redirects=True)
    yield {"app": app, "db": db, "client": client}


def _names(body):
    import re

    return re.findall(r"Drug \d{3}", body)


def test_the_catalogue_pages_instead_of_ending(clinic):
    page1 = clinic["client"].get("/prescriptions/drugs")
    assert page1.status_code == 200
    first = _names(page1.get_data(as_text=True))
    assert len(set(first)) == 25

    page2 = clinic["client"].get("/prescriptions/drugs?page=2")
    second = _names(page2.get_data(as_text=True))
    assert len(set(second)) == 25
    assert not set(first) & set(second), "page 2 repeated page 1"


def test_the_last_page_holds_the_remainder(clinic):
    body = clinic["client"].get("/prescriptions/drugs?page=3").get_data(as_text=True)
    assert len(set(_names(body))) == 10
    assert "Drug 059" in body


def test_asking_for_more_rows_gets_more_rows(clinic):
    body = clinic["client"].get(
        "/prescriptions/drugs?per_page=100").get_data(as_text=True)
    assert len(set(_names(body))) == 60


def test_a_page_past_the_end_is_empty_not_a_404(clinic):
    """Narrowing a search while standing on page 9 is ordinary, not an error."""
    resp = clinic["client"].get("/prescriptions/drugs?page=900")
    assert resp.status_code == 200


def test_searching_and_paging_do_not_cancel_each_other(clinic):
    """The pager's links have to carry the search, or page 2 of a search is
    page 2 of everything."""
    body = clinic["client"].get(
        "/prescriptions/drugs?q=paracetamol&per_page=25").get_data(as_text=True)
    assert len(set(_names(body))) == 10          # only the matching ten
    assert "q=paracetamol" in body or "paracetamol" in body


def test_nothing_is_capped_at_five_hundred(clinic):
    """The old cap was a limit clause with no pager: row 501 existed in the
    database and nowhere on the screen."""
    from app.models import Drug

    with clinic["app"].app_context():
        for i in range(60, 520):
            clinic["db"].session.add(Drug(trade_name=f"Drug {i:03d}",
                                          is_active=True))
        clinic["db"].session.commit()

    body = clinic["client"].get(
        "/prescriptions/drugs?q=Drug+519").get_data(as_text=True)
    assert "Drug 519" in body, "the 520th medicine is unreachable"


def test_the_pager_offers_the_page_sizes(clinic):
    body = clinic["client"].get("/prescriptions/drugs").get_data(as_text=True)
    assert 'name="per_page"' in body
    for size in (25, 50, 100, 200):
        assert f'value="{size}"' in body


@pytest.mark.parametrize("path", [
    "/prescriptions/",
    "/prescriptions/drugs",
    "/prescriptions/drugbook",
    "/patients/",
    "/visits/",
    "/vaccinations/",
    "/growth/",
    "/finance/invoices",
    "/finance/shifts",
    "/inventory/documents",
    "/messages/",
    "/users/audit",
])
def test_every_list_screen_still_renders(clinic, path):
    """One macro sits under all of them, so a typo in it is twelve broken
    pages. An empty list is a real state and has to render too — that is what
    this covers; the pager itself is checked below on screens with rows."""
    resp = clinic["client"].get(path, follow_redirects=True)
    assert resp.status_code == 200, f"{path} → {resp.status_code}"


@pytest.mark.parametrize("path", ["/finance/shifts", "/inventory/documents",
                                  "/users/audit", "/prescriptions/drugs"])
def test_the_screens_that_lost_their_own_pager_show_the_shared_one(clinic, path):
    """These three had hand-written pagers — one of them drew a button for
    every page, which is a wall of buttons once a till has run for a year.
    They now share the macro, so they must actually show it once they have
    rows to page."""
    from datetime import date, datetime

    from app.models import CashierShift, StoreDocument, User

    with clinic["app"].app_context():
        boss = User.query.filter_by(username="boss").one()
        for i in range(30):
            clinic["db"].session.add(CashierShift(
                shift_number=f"SHIFT-2026-{i:06d}", opened_by=boss.id,
                status="closed", opening_float=0,
                opened_at=datetime(2026, 1, 1, 8, i)))
            clinic["db"].session.add(StoreDocument(
                doc_number=f"GRN-{i:04d}", kind="grn", doc_date=date(2026, 1, 1)))
        clinic["db"].session.commit()

    body = clinic["client"].get(path).get_data(as_text=True)
    assert 'name="per_page"' in body, f"{path} has no page-size picker"


def test_the_drug_reference_pages_too(clinic):
    """The reference is the other screen that used to stop mid-list."""
    from app.models import GenericDrug

    with clinic["app"].app_context():
        for i in range(40):
            clinic["db"].session.add(GenericDrug(name_en=f"Ingredient {i:03d}",
                                                 name_ar=f"مادة {i}",
                                                 is_active=True))
        clinic["db"].session.commit()

    body = clinic["client"].get("/prescriptions/drugbook").get_data(as_text=True)
    assert "Ingredient 000" in body and "Ingredient 039" not in body
    later = clinic["client"].get(
        "/prescriptions/drugbook?page=2").get_data(as_text=True)
    assert "Ingredient 039" in later
