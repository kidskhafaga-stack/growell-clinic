"""The cases the clinic agreed something with, on a screen of their own.

Its own screen rather than a filter on the dose reminders, because it answers
a different question. Reminders ask "who is late". This asks "who did we
promise something to, and are we keeping it" — the one somebody works through
with the fridge open, deciding what to buy.

Three things it has to get right.

**The filters every screen here should carry**: a date range, a vaccine, and
nothing else to learn. Asked for exactly that way, for all of them.

**The order is built from what is shown.** The same rule the reminders screen
and the invoice export already follow: what you take away is what you were
looking at. An order that quietly covers more than the filter is one nobody
can check.

**A dose the family is buying is on the list and never in the order.** They
still need the visit arranged and the dose recorded, so leaving them off the
screen would lose them — but putting a vial on the order for a dose nobody is
going to pay the clinic for fills the fridge with stock that does not move.
That distinction is the whole reason `supplied_outside` exists, and it is
invisible on any screen that does not draw it.
"""
import os
import re
import sys
from datetime import timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

from app.utils.clock import local_today  # noqa: E402


@pytest.fixture()
def ward(clinic):
    """Two children on a plan for the same vaccine: one the clinic supplies,
    one the family is bringing. The pair is the point — the screen must treat
    them the same and the order must not."""
    from app.extensions import db
    from app.models import Patient, Vaccine
    from app.models.vaccine_plan import VaccinePlanItem

    from app.utils.vaccines import seed_vaccines

    with clinic["app"].app_context():
        seed_vaccines()
        db.session.commit()
        pcv = Vaccine.query.filter_by(code="PCV").first()
        for tag, outside in (("ours", False), ("theirs", True)):
            kid = Patient(patient_number=f"PL-{tag}", full_name=f"طفل {tag}",
                          gender="male", is_active=True,
                          date_of_birth=local_today() - timedelta(days=800))
            db.session.add(kid)
            db.session.flush()
            db.session.add(VaccinePlanItem(patient_id=kid.id,
                                           vaccine_id=pcv.id,
                                           supplied_outside=outside))
        db.session.commit()
        clinic["pcv_id"] = pcv.id
    return clinic


def _page(ward, query=""):
    return ward["sign_in"]("doc").get(f"/vaccinations/plans{query}",
                                      follow_redirects=True).data.decode()


def _order_needed(page):
    """The 'needed' column of the purchase order, as integers."""
    block = re.search(r"cart-plus.*?</table>", page, re.S)
    if not block:
        return []
    return [int(n) for n in re.findall(r"<td>(\d+)</td>", block.group(0))[::2]]


# ------------------------------------------------------------- the screen

def test_the_screen_opens_and_lists_the_cases(ward):
    page = _page(ward)

    assert "طفل ours" in page and "طفل theirs" in page


def test_it_carries_the_filters_every_screen_should(ward):
    """A range, a vaccine, and nothing else to learn."""
    page = _page(ward)

    assert 'name="from"' in page and 'name="to"' in page
    assert 'name="vaccine_id"' in page


def test_the_date_range_actually_narrows_it(ward):
    """A filter that renders and does nothing is worse than none."""
    long_ago = (local_today() - timedelta(days=3650)).isoformat()
    older_still = (local_today() - timedelta(days=3600)).isoformat()

    page = _page(ward, f"?from={long_ago}&to={older_still}")

    assert "طفل ours" not in page, "the date range is decorative"


def test_the_vaccine_filter_narrows_it_too(ward):
    from app.models import Vaccine

    with ward["app"].app_context():
        other = Vaccine.query.filter_by(code="HAV").first().id

    assert "طفل ours" not in _page(ward, f"?vaccine_id={other}")
    assert "طفل ours" in _page(ward, f"?vaccine_id={ward['pcv_id']}")


def test_a_child_with_no_plan_is_not_on_it(ward):
    """The screen is about promises, not about everybody who is late.

    The child here is deliberately **overdue**: they have a dose on file, so
    the dose-reminder sweep does return them, and only the plan filter keeps
    them off this screen. An unvaccinated child would have proved nothing —
    the sweep never looks at them either way, so removing the filter entirely
    left this test passing. Measured, by removing it.
    """
    from app.extensions import db
    from app.models import Patient, PatientVaccine, Vaccine, VaccineBrand

    with ward["app"].app_context():
        hav = Vaccine.query.filter_by(code="HAV").first()
        brand = VaccineBrand.query.filter_by(vaccine_id=hav.id).first()
        kid = Patient(patient_number="PL-none", full_name="طفل بلا",
                      gender="male", is_active=True,
                      date_of_birth=local_today() - timedelta(days=1400))
        db.session.add(kid)
        db.session.flush()
        db.session.add(PatientVaccine(
            patient_id=kid.id, vaccine_id=hav.id, brand_id=brand.id,
            dose_number=1, event_type="given",
            given_date=kid.date_of_birth + timedelta(days=365)))
        db.session.commit()
        kid_id = kid.id

    # It really is on the reminders sweep — otherwise this proves nothing.
    from app.utils.vaccine_due import due_list
    with ward["app"].app_context():
        assert any(r["patient"].id == kid_id for r in due_list()), \
            "the fixture child is not overdue, so the filter is untested"

    assert "طفل بلا" not in _page(ward)


# ----------------------------------------------------------- the order

def test_the_family_supplied_dose_is_listed_but_not_ordered(ward):
    """Two children need the same vaccine; the clinic buys one vial.

    The assertion this file exists for. Both are on the screen — both need a
    visit — and the order says one.
    """
    page = _page(ward)

    assert "طفل theirs" in page, "the family-supplied case fell off the screen"
    assert _order_needed(page) == [1], \
        f"the order counted a dose the family is buying: {_order_needed(page)}"


def test_the_order_follows_the_filter(ward):
    """What you take away is what you were looking at."""
    from app.models import Vaccine

    with ward["app"].app_context():
        other = Vaccine.query.filter_by(code="HAV").first().id

    assert _order_needed(_page(ward, f"?vaccine_id={other}")) == []


def test_an_empty_result_does_not_read_as_an_empty_clinic(ward):
    """"Nothing due in this range" and "nobody has a plan" are different
    sentences, and a screen that gives the wrong one sends somebody to check
    whether the feature is broken."""
    from app.i18n import t

    long_ago = (local_today() - timedelta(days=3650)).isoformat()
    older_still = (local_today() - timedelta(days=3600)).isoformat()
    page = _page(ward, f"?from={long_ago}&to={older_still}")

    with ward["app"].test_request_context("/"):
        assert t("vplans.none") in page
        assert t("vplans.no_plans") not in page


def test_a_clinic_with_no_plans_at_all_is_told_how_to_make_one(clinic):
    from app.i18n import t

    page = clinic["sign_in"]("doc").get("/vaccinations/plans",
                                        follow_redirects=True).data.decode()

    with clinic["app"].test_request_context("/"):
        assert t("vplans.no_plans") in page
        assert t("vplans.no_plans_hint")[:20] in page


# ------------------------------------------------------------ the way in

def test_the_vaccinations_landing_page_links_to_it(ward):
    page = ward["sign_in"]("doc").get("/vaccinations/",
                                      follow_redirects=True).data.decode()

    assert "/vaccinations/plans" in page


def test_the_wording_exists_in_both_languages(ward):
    import json

    here = os.path.dirname(os.path.abspath(__file__))
    keys = ["title", "sub", "none", "no_plans", "no_plans_hint", "on_plan_n",
            "order", "outside_note", "needed", "in_stock", "to_order"]
    for lang in ("ar", "en"):
        with open(os.path.join(here, "..", "app/i18n/locales", f"{lang}.json"),
                  encoding="utf-8") as fh:
            block = json.load(fh)["vplans"]
        for key in keys:
            assert key in block, f"{lang} is missing vplans.{key}"
