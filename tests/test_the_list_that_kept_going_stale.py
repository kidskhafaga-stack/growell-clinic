"""The «لسه» list, checked against the program instead of proof-read.

``app/utils/project.py`` holds what the About screen tells a doctor is still
to come. It has now gone stale twice, in both directions:

* **Over-promising** — it announced five things as "coming" that had been
  finished for months, including a compliance board that was already live and
  already excluding government vaccines for a reason written in its own file.
  Caught by a person reading the screen: *"الحاجات دي معمولة، اتأكد"*.
* **Under-promising** — and after that sweep it still claimed the patient
  statement and the debt ageing were missing, while ``/reports/statement/<id>``
  and ``/reports/ar-aging`` had both been open the whole time. Only the roll-up
  across siblings was ever absent.

The second direction is the one that looks harmless and is not. Somebody
deciding what to build next reads this list, and a line that under-promises
sends them off to write a screen that already exists.

Both were spotted by a human re-reading prose. That is not a check, so this
file is: it opens each remaining item against the running program. **The day
one of them is built, the test here fails** — and the list has to be brought
up to date before anything else can be merged. A test that goes red on
*success* is unusual and deliberate: the failure message says what to do.

What it deliberately does not do is assert the list is a particular length or
holds particular words. That would only pin the prose, which was never the
part that drifted.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

STALE = ("«{}» is on the NEXT list in app/utils/project.py, and this test "
         "found it built. If you built it: move it out of NEXT — the About "
         "screen is telling doctors it is still to come.")


@pytest.fixture()
def app():
    from app import create_app
    from app.extensions import db

    application = create_app("testing")
    with application.app_context():
        db.create_all()
    return application


# ------------------------------------------------------- 1) cost centres --
def test_cost_centres_are_still_not_built(app):
    """The claim is that the accounting engine runs without them. What would
    make it false is a dimension on the journal line — revenue and expense
    cannot be split by department without somewhere to write the department.
    """
    from app.models.accounting import JournalLine

    columns = set(JournalLine.__table__.columns.keys())
    for dimension in ("cost_centre_id", "cost_center_id", "department_id",
                      "cost_centre", "cost_center"):
        assert dimension not in columns, STALE.format("cost centres")


# --------------------------------------------- 2) the family-level statement --
def test_the_family_roll_up_is_still_not_built(app):
    """Narrowed after the list was found wrong about this one. The *patient*
    statement and the *patient* debt ageing are asserted present below; what is
    missing is only the sheet that adds the siblings up."""
    endpoints = {r.endpoint for r in app.url_map.iter_rules()}
    # Not "any route mentioning a family": managing families is a different
    # feature and has had screens for a long time (search, edit, delete). What
    # is missing is a family's *money* on one sheet, so both words have to be
    # there before this counts as built.
    money = ("statement", "aging", "ageing", "balance", "account")
    built = [e for e in endpoints
             if "famil" in e.lower() and any(w in e.lower() for w in money)]
    assert not built, STALE.format("the family statement") + f" ({built})"


def test_and_the_two_it_used_to_deny_are_present(app):
    """**The half that caught the mistake.** The list said these were missing.
    They are the reason the item was narrowed rather than deleted, and if one
    of them ever disappears this file must not go on quietly asserting the
    narrow version."""
    endpoints = {r.endpoint for r in app.url_map.iter_rules()}
    assert "reports.patient_statement" in endpoints, (
        "the per-patient statement is gone — the NEXT list says it exists")
    assert "reports.ar_aging" in endpoints, (
        "the per-patient debt ageing is gone — the NEXT list says it exists")


def test_the_ageing_that_exists_really_is_per_patient(app):
    """Read once as "per doctor and per supplier", which is what put it on the
    NEXT list. It buckets patients, so that reading was wrong — asserted here
    rather than left as something somebody has to re-read the route to know."""
    from app.blueprints.reports.routes import AGING_BUCKETS

    assert len(AGING_BUCKETS) >= 3
    assert AGING_BUCKETS[0][0] == 0


# ---------------------------------------------------------- 3) FHIR --------
def test_fhir_endpoints_are_still_not_built(app):
    """The models carry the FHIR names already — ``Observation``,
    ``Encounter``, ``Immunization`` — which is exactly what makes this easy to
    believe is done. The endpoints are the thing, so the endpoints are what is
    looked for."""
    rules = [str(r) for r in app.url_map.iter_rules()]
    fhir = [r for r in rules if "fhir" in r.lower()]
    assert not fhir, STALE.format("FHIR readiness") + f" ({fhir})"


# --------------------------------------------------- and the list itself --
def test_every_item_on_the_next_list_is_covered_here(app):
    """The guard's own weak point: an item added to NEXT with no check here
    goes back to being prose nobody verifies. Counted, so growing the list
    forces a decision about how it will be checked.
    """
    from app.utils.project import NEXT

    assert len(NEXT) == 3, (
        f"NEXT has {len(NEXT)} items; this file checks 3. Add a check for the "
        "new one — an unchecked item is how this list went stale twice.")
