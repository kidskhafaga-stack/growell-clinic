"""When the program cannot know the dose count, it says so instead of guessing.

Two trade names in the catalogue do not have a fixed course, and both were
raised by the doctor rather than found by me:

  * **Bexsero** — 2+1 from two months, fewer doses started later.
  * **Vaxneuvance** — 3+1 on the manufacturer's leaflet, 2+1 on the WHO
    schedule. Two authorities, two numbers.

The program computes one standard course for each. That is not yet wrong —
the standard course is the common case — but a number on a screen carries no
doubt with it, and a doctor reading "4 doses" has no way to tell that this is
the one product where the leaflet and the WHO disagree.

`doses_change_by_start_age` has been in the data since the brand facts were
reviewed, and nothing read it. So it is read here: the file shows the warning,
carrying the brand's own note as its tooltip, because the real answer is
written there and not in anything this program computes.

This is deliberately **not** an attempt to encode the rule. Choosing between
2+1 and 3+1 needs age-banded schedules and, more to the point, needs somebody
qualified to decide which authority the clinic follows. Saying "check the
leaflet" is honest; picking one silently is not.
"""
import os
import re
import sys
from datetime import timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

from app.utils.clock import local_today  # noqa: E402


@pytest.fixture()
def seeded(clinic):
    from app.extensions import db

    from app.utils.vaccines import seed_vaccines

    with clinic["app"].app_context():
        seed_vaccines()
        db.session.commit()
    return clinic


def _file_page(seeded, days=200, agree=("MENB",), tag="1"):
    """A child's file. `agree` puts courses on the plan, because the warning
    only shows where the clinic has taken the course on."""
    from app.extensions import db
    from app.models import Patient, Vaccine
    from app.models.vaccine_plan import VaccinePlanItem

    with seeded["app"].app_context():
        kid = Patient(patient_number=f"UN{tag}", full_name="طفل", gender="male",
                      is_active=True,
                      date_of_birth=local_today() - timedelta(days=days))
        db.session.add(kid)
        db.session.flush()
        for code in agree:
            vaccine = Vaccine.query.filter_by(code=code).first()
            db.session.add(VaccinePlanItem(patient_id=kid.id,
                                           vaccine_id=vaccine.id))
        db.session.commit()
        kid_id = kid.id

    return seeded["sign_in"]("doc").get(f"/vaccinations/{kid_id}",
                                        follow_redirects=True).data.decode()


def test_the_brands_that_vary_are_marked_in_the_data(seeded):
    """The flag the doctor asked about, on the two products they named."""
    from app.models import VaccineBrand

    with seeded["app"].app_context():
        for name in ("Bexsero", "Vaxneuvance"):
            brand = VaccineBrand.query.filter_by(name=name).first()
            assert brand is not None, f"{name} is not in the catalogue"
            assert brand.doses_change_by_start_age is True, \
                f"{name} is not marked as varying by starting age"


def test_a_fixed_brand_is_not_marked(seeded):
    """Otherwise the warning is on everything and means nothing."""
    from app.models import VaccineBrand

    with seeded["app"].app_context():
        assert VaccineBrand.query.filter_by(
            name="Varilrix").first().doses_change_by_start_age is False


def test_the_file_says_the_number_is_not_certain(seeded):
    from app.i18n import t

    page = _file_page(seeded)

    with seeded["app"].test_request_context("/"):
        assert t("vaccinations.varies_by_start_age") in page, \
            "the file shows a dose count with no hint that it may be wrong"


def test_the_warning_carries_the_brands_own_note(seeded):
    """Where the real answer is written. A warning with nothing behind it
    sends somebody looking for a document with no idea which."""
    page = _file_page(seeded)

    found = re.search(r'varies|exclamation-triangle', page)
    assert found, "the warning is not rendered at all"
    # Bexsero's note travels with it as the tooltip.
    assert "عدد الجرعات يختلف ببداية السن" in page


def test_it_only_shows_where_somebody_is_acting_on_it(seeded):
    """A badge on every row is wallpaper.

    Measured: on a healthy child's file the catalogue put eleven of these on
    screen at once, because most of the optional schedule varies by starting
    age. At eleven a warning is not read. It shows on the courses this clinic
    started or agreed to, which is where a dose count is acted on.
    """
    page = _file_page(seeded, agree=("MENB",))
    shown = page.count("exclamation-triangle")

    assert shown == 1, \
        f"the warning is on {shown} rows — expected the one agreed course"

    quiet = _file_page(seeded, agree=(), tag="2")
    assert quiet.count("exclamation-triangle") == 0, \
        "the warning shows on courses nobody has taken on"


def test_the_badge_class_is_one_that_exists(seeded):
    """A class nobody styled renders as unformatted text — measured: the first
    version of this used `badge--warn`, which the stylesheet has never had."""
    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, "..", "app/templates/vaccinations/view.html"),
              encoding="utf-8") as fh:
        template = fh.read()

    used = set(re.findall(r"badge--(\w+)", template))
    css = ""
    for name in ("app.css", "content-all.css", "theme.css"):
        path = os.path.join(here, "..", "app/static/css", name)
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                css += fh.read()

    for variant in used:
        assert f"badge--{variant}" in css, \
            f"badge--{variant} is used on the file and styled nowhere"


def test_the_wording_exists_in_both_languages(seeded):
    import json

    here = os.path.dirname(os.path.abspath(__file__))
    for lang in ("ar", "en"):
        with open(os.path.join(here, "..", "app/i18n/locales", f"{lang}.json"),
                  encoding="utf-8") as fh:
            block = json.load(fh)["vaccinations"]
        for key in ("varies_by_start_age", "varies_by_start_age_hint"):
            assert key in block, f"{lang} is missing vaccinations.{key}"
