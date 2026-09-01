"""Forty-seven rows in the way of the handful a clinic actually gives.

The catalogue loads the national programme and the private market together,
and a practice that does neither half still has both in its list. Reported as
a switch that ought to remove them: *"هو مش المفروض لما معلمش على الحكومي
يشيله؟"* — which the loading checkbox does not do, because it says which sets
to *load* and never deletes.

So: a vaccine can be **put away**. Hidden from the catalogue and from what a
family can be offered, and hidden from nothing else.

**Nothing clinical moves.** The child's card still shows it, what is due still
says so, the reminders still go and the certificate still prints it. Two
reasons, and both of them are somebody's actual afternoon:

* The child's card is where a dose given at the **government unit** gets
  recorded. Hide the national schedule from it and there is nowhere to write
  down the vaccine the child has already had.
* A child **halfway through a course** would lose the rest of it. The clinic
  decided something about its own shelf; the child is still two doses in.

And it is a different fact from `is_discontinued`, which means the
manufacturer stopped making it. A government vaccine is in full production.
Filing "we don't give this" under "this no longer exists" would be telling
every future reader of that file something untrue.
"""
import pytest


@pytest.fixture
def admin(clinic):
    return clinic["sign_in"]("boss")


def _put_away(clinic, admin, code, away=True):
    from app.models import Vaccine

    with clinic["app"].app_context():
        vaccine = Vaccine.query.filter_by(code=code).first()
        assert vaccine is not None, f"no vaccine {code} in the fixture"
        vid = vaccine.id
    data = {"put_away": "1"} if away else {}
    admin.post(f"/vaccinations/manage/vaccine/{vid}/offered", data=data,
               follow_redirects=True)
    return vid


def _codes(clinic):
    from app.models import Vaccine

    with clinic["app"].app_context():
        return {v.code: v for v in Vaccine.query.all()}


# ------------------------------------------------------------ it hides -----
def test_a_vaccine_put_away_leaves_the_catalogue(clinic, admin):
    from app.models import Vaccine

    with clinic["app"].app_context():
        name = Vaccine.query.filter_by(code="OPV").first().name_ar
    assert name in admin.get("/vaccinations/manage?cat=all").get_data(as_text=True)

    _put_away(clinic, admin, "OPV")
    page = admin.get("/vaccinations/manage?cat=all").get_data(as_text=True)
    assert name not in page


def test_it_is_not_deleted(clinic, admin):
    """Put away, not gone. Deleting a vaccine children have doses of would
    take their history with it."""
    _put_away(clinic, admin, "OPV")
    assert "OPV" in _codes(clinic)


def test_the_screen_says_how_many_are_put_away(clinic, admin):
    """A list that silently drops rows is a list somebody re-adds a duplicate
    into."""
    _put_away(clinic, admin, "OPV")
    page = admin.get("/vaccinations/manage").get_data(as_text=True)
    assert "1" in page
    assert "put_away=1" in page, "no way back to what was put away"


def test_they_can_be_looked_at_and_brought_back(clinic, admin):
    from app.models import Vaccine

    with clinic["app"].app_context():
        name = Vaccine.query.filter_by(code="OPV").first().name_ar
    _put_away(clinic, admin, "OPV")

    page = admin.get("/vaccinations/manage?cat=all&put_away=1").get_data(as_text=True)
    assert name in page, "the put-away list does not show them"

    _put_away(clinic, admin, "OPV", away=False)
    assert name in admin.get(
        "/vaccinations/manage?cat=all").get_data(as_text=True)


def test_it_is_not_offered_to_a_family(clinic, admin):
    """The second half of hiding: a plan a receptionist can still add it to
    is a vaccine that was not really put away.

    Checked before as well as after. The offer form disappears altogether
    once nothing is left to offer, so "the option is not on the page" is
    true of a page that never had it — and would pass with the filter
    removed.
    """
    from app.models import Vaccine

    with clinic["app"].app_context():
        pcv = Vaccine.query.filter_by(code="PCV").first()
        assert not pcv.is_mandatory, "the fixture's PCV is not offerable anyway"

    def offered():
        page = admin.get(
            f"/vaccinations/{clinic['ids']['child']}").get_data(as_text=True)
        marker = f"/vaccinations/{clinic['ids']['child']}/plan/add"
        if marker not in page:
            return set()
        form = page.split(marker, 1)[1].split("</form>", 1)[0]
        import re

        return set(re.findall(r'<option value="(\d+)"', form))

    assert str(clinic["ids"]["pcv"]) in offered(), \
        "PCV was not offerable to begin with, so this test proves nothing"
    _put_away(clinic, admin, "PCV")
    assert str(clinic["ids"]["pcv"]) not in offered(), \
        "a put-away vaccine can still be offered to a family"


# ------------------------------------------- and what it must not touch ----
def test_the_childs_card_still_shows_it(clinic, admin):
    """Where a dose given at the government unit gets recorded. Hide the
    national schedule here and there is nowhere to write down the vaccine the
    child has already had."""
    from app.models import Vaccine

    with clinic["app"].app_context():
        name = Vaccine.query.filter_by(code="OPV").first().name_ar
    _put_away(clinic, admin, "OPV")
    page = admin.get(
        f"/vaccinations/{clinic['ids']['child']}").get_data(as_text=True)
    assert name in page, "a put-away vaccine vanished from the child's card"


def test_a_dose_already_given_is_untouched(clinic, admin):
    """It happened. Nothing about the clinic's shelf changes that."""
    from app.models import PatientVaccine

    admin.post(f"/vaccinations/{clinic['ids']['child']}/record",
               data={"vaccine_id": clinic["ids"]["opv"],
                     "brand_id": clinic["ids"]["gov_brand"], "dose_number": "1"},
               follow_redirects=True)
    with clinic["app"].app_context():
        before = PatientVaccine.query.count()
        assert before >= 1, "the dose was not recorded, so this proves nothing"

    _put_away(clinic, admin, "OPV")
    with clinic["app"].app_context():
        assert PatientVaccine.query.count() == before


def test_what_is_due_does_not_change(clinic, admin):
    """A child halfway through a course does not lose the rest of it because
    of a decision about this clinic's shelf."""
    from app.utils.vaccines import patient_plan
    from app.models import Patient

    with clinic["app"].app_context():
        child = clinic["db"].session.get(Patient, clinic["ids"]["child"])
        before = len(patient_plan(child, "ar"))
    _put_away(clinic, admin, "OPV")
    with clinic["app"].app_context():
        child = clinic["db"].session.get(Patient, clinic["ids"]["child"])
        assert len(patient_plan(child, "ar")) == before


def test_it_is_a_different_fact_from_discontinued(clinic, admin):
    """`is_discontinued` means the manufacturer stopped making it. A
    government vaccine is in full production and this clinic simply does not
    give it — filing one under the other tells every future reader of that
    file something untrue."""
    _put_away(clinic, admin, "OPV")
    with clinic["app"].app_context():
        from app.models import Vaccine

        opv = Vaccine.query.filter_by(code="OPV").first()
        assert opv.is_offered is False
        assert opv.is_discontinued is False


def test_everything_is_offered_until_somebody_says_otherwise(clinic):
    """The default every existing clinic wakes up with."""
    with clinic["app"].app_context():
        from app.models import Vaccine

        assert all(v.is_offered for v in Vaccine.query.all())
