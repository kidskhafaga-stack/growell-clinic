"""The vaccine screen opened on forty-seven rows, most of them not the clinic's.

The government (EPI) set is given at the government unit. The clinic does not
buy it, price it or stock it — this screen already declines to print a stock
figure for those rows, because there is none — and it was still the first
thing anybody saw on arrival, with the handful they actually sell mixed in.

Reported as: it scatters the person using it.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def _two_kinds(clinic):
    """One government vaccine and one the clinic sells."""
    from app.extensions import db
    from app.models import Vaccine

    with clinic["app"].app_context():
        db.session.add(Vaccine(code="GOV1", name_ar="شلل الأطفال الحكومي",
                               is_mandatory=True, sort_order=1))
        db.session.add(Vaccine(code="OPT1", name_ar="الروتا",
                               is_mandatory=False, sort_order=2))
        db.session.commit()


def test_it_opens_on_what_the_clinic_dispenses(clinic):
    _two_kinds(clinic)

    page = clinic["sign_in"]("boss").get("/vaccinations/manage").data.decode()

    assert "الروتا" in page, "the clinic's own vaccine is not on its own screen"
    assert "شلل الأطفال الحكومي" not in page, \
        "the government set is still in the way on arrival"


def test_the_government_set_is_one_click_away(clinic):
    """Filtered, never hidden — and the tab carries its count."""
    _two_kinds(clinic)
    client = clinic["sign_in"]("boss")

    page = client.get("/vaccinations/manage?cat=mandatory").data.decode()
    assert "شلل الأطفال الحكومي" in page

    everything = client.get("/vaccinations/manage?cat=all").data.decode()
    assert "شلل الأطفال الحكومي" in everything and "الروتا" in everything


def test_the_screen_says_which_list_this_is(clinic):
    """Otherwise a filtered list reads as a program that lost the data."""
    _two_kinds(clinic)

    page = clinic["sign_in"]("boss").get("/vaccinations/manage").data.decode()

    assert "إجباري" in page or "mandatory" in page.lower(), \
        "nothing on the page points at where the government set went"


def test_nothing_was_removed_from_the_catalogue(clinic):
    """The filter is a view. A vaccine a clinic can record must still exist."""
    from app.models import Vaccine

    _two_kinds(clinic)

    with clinic["app"].app_context():
        assert Vaccine.query.filter_by(code="GOV1").first() is not None
        assert Vaccine.query.count() >= 2
