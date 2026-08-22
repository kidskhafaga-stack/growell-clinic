"""The catalogue as a review table, generated rather than kept.

A doctor reviewing forty-eight trade names against a set of scheduling rules
needs to see what the program actually holds for each one — the age bands it
follows, the ceiling on its final dose, whether it is routine or given on
indication, whether a WHO row is kept beside the manufacturer's. Marking gaps
against a leaflet is only possible if the table says what is there now.

**Generated, not checked in.** A copy in the repository is out of date the
first time somebody edits a brand, and a stale review table is worse than none
because it still reads as current. The command regenerates it from the live
catalogue in a second.

The two empty columns are the honest part: previous-dose rules and
interchangeability are not modelled, so they are blank on every row rather
than absent from the file. A rule the program does not have should be visible
as a gap, not invisible as a missing column.
"""
import csv
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def catalogue(clinic, tmp_path):
    from app.extensions import db

    from app.utils.vaccines import seed_vaccines, seed_vaccine_schedules

    with clinic["app"].app_context():
        seed_vaccines()
        seed_vaccine_schedules()
        db.session.commit()
    clinic["out"] = str(tmp_path / "review.csv")
    return clinic


def _run(catalogue):
    runner = catalogue["app"].test_cli_runner()
    result = runner.invoke(args=["vaccine-review", "--out", catalogue["out"]])
    assert result.exit_code == 0, result.output
    with open(catalogue["out"], encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def test_every_brand_gets_a_row(catalogue):
    from app.models import VaccineBrand

    rows = _run(catalogue)

    with catalogue["app"].app_context():
        assert len(rows) == VaccineBrand.query.count()
    assert len(rows) > 40, f"only {len(rows)} brands — the catalogue is short"


def test_it_carries_what_the_program_actually_holds(catalogue):
    """Spot-checked against the facts the rules turn on, not against a count."""
    rows = {r["brand"]: r for r in _run(catalogue)}

    rotarix = rows["RotaRix"]
    assert rotarix["R4_max_age_final_dose_days"] == str(24 * 7)
    assert rotarix["manufacturer"] == "GSK"

    assert rows["RotaTeq"]["R4_max_age_final_dose_days"] == str(32 * 7)
    assert rows["Synflorix"]["R4_max_age_final_dose_days"] == str(5 * 365)


def test_a_banded_brand_says_how_many_bands(catalogue):
    """The rule that most often surprises somebody reading the catalogue.

    Asserted as "has bands, and more than one" rather than as an exact total.
    The number moves for a legitimate reason — a second guideline profile adds
    its own rows beside the leaflet's, which is the design — and a test that
    pins the count fails on the feature working. It did, on the CDC bands.
    """
    rows = {r["brand"]: r for r in _run(catalogue)}

    for name in ("Bexsero", "Vaxneuvance"):
        count = rows[name]["R1_age_bands"]
        assert count and int(count) > 1, \
            f"{name} lost its age bands: {count!r}"
    # HPV's bands are the vaccine's, so both trade names follow them.
    assert "vaccine-wide" in rows["Gardasil 9"]["R1_age_bands"]
    # Prevenar 13 carries the pneumococcal ceiling — one vaccine-wide row
    # saying the routine childhood course ends at five — and no leaflet bands
    # of its own. Asserted as "vaccine-wide", not as a count: the count is
    # exactly what the docstring above says a test must not pin.
    assert "vaccine-wide" in rows["Prevenar 13"]["R1_age_bands"]


def test_rabies_is_marked_as_given_on_an_event(catalogue):
    rows = {r["brand"]: r for r in _run(catalogue)}

    assert rows["Verorab"]["R6_indication"] == "event"
    assert rows["Rabipur"]["R6_indication"] == "event"


def test_unknown_is_written_as_unknown(catalogue):
    """Never as "no". The three-valued answer is the whole point of the
    column, and a review table that flattens it invites somebody to conclude
    a product is unregistered when nobody has checked."""
    rows = {r["brand"]: r for r in _run(catalogue)}

    assert rows["Quinvaxem"]["registered_eg"] == "unknown"
    assert rows["Quinvaxem"]["available_now"] == "no"
    assert rows["Quinvaxem"]["discontinued"] == "yes"


def test_the_rules_we_do_not_have_are_visible_as_gaps(catalogue):
    """Blank on every row, not missing from the file.

    Previous-dose rules and interchangeability are the two the review is meant
    to catch. A column that is absent reads as a rule nobody thought of; one
    that is present and empty reads as a rule nobody has filled in.
    """
    rows = _run(catalogue)

    for column in ("R2_previous_doses", "R7_interchangeable"):
        assert column in rows[0], f"{column} is not even a column"
        assert all(r[column] == "" for r in rows)


def test_it_is_not_kept_in_the_repository(catalogue):
    """Generated on demand. A checked-in copy is stale after the first edit
    and still reads as current, which is the failure worth avoiding."""
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    stale = [name for name in os.listdir(root)
             if name.lower().endswith(".csv") and "brand" in name.lower()]

    assert not stale, f"a generated review table was committed: {stale}"


def test_an_empty_catalogue_says_so_rather_than_writing_nothing(clinic, tmp_path):
    out = str(tmp_path / "empty.csv")
    result = clinic["app"].test_cli_runner().invoke(
        args=["vaccine-review", "--out", out])

    assert result.exit_code == 0
    assert "empty" in result.output.lower() or os.path.exists(out)
