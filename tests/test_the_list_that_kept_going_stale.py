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
def test_cost_centres_have_been_built_and_are_off_the_list(app):
    """This one has flipped too, as written: it asserted the journal line had
    no department, and went red the day ``JournalLine.cost_centre_id`` landed
    — the list was brought up to date before the merge.

    Kept as the mirror, both halves: the dimension and the report exist, and
    NEXT no longer calls them to come. Cost centres quietly removed while the
    About screen lists them as built is the same failure pointing the other
    way.
    """
    from app.models.accounting import JournalLine
    from app.utils.project import DONE, NEXT

    assert "cost_centre_id" in JournalLine.__table__.columns.keys()
    endpoints = {r.endpoint for r in app.url_map.iter_rules()}
    assert "reports.cost_centres" in endpoints
    for arabic, english in NEXT:
        assert "تكلفة" not in arabic and "cost centre" not in english.lower(), (
            "cost centres are built; NEXT still lists them")
    assert any("cost centre" in english.lower() for _a, english in DONE)


# --------------------------------------------- 2) the family-level statement --
def test_the_family_roll_up_has_been_built_and_is_off_the_list(app):
    """This one has flipped, which is the guard doing its job.

    It went red the day ``reports.family_statement`` landed — exactly as
    written — and the list was brought up to date before the merge. Kept as
    the mirror of what it used to assert: the sheet exists, and NEXT no longer
    claims otherwise. A feature quietly deleted while the roadmap still calls
    it done is the same failure pointing the other way.
    """
    from app.utils.project import NEXT

    endpoints = {r.endpoint for r in app.url_map.iter_rules()}
    assert "reports.family_statement" in endpoints
    for arabic, english in NEXT:
        assert "أسرة" not in arabic and "family" not in english.lower(), (
            "the family statement is built; NEXT still lists it")


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
    looked for.

    **The file is not the door.** The child's record downloads as a FHIR
    file from their page (``/patients/<id>/fhir``) — stage one, built and on
    this list's own line as built. What is still to come is an API another
    system asks, and that is what is looked for: any FHIR route but that one.
    """
    rules = [str(r) for r in app.url_map.iter_rules()]
    fhir = [r for r in rules if "fhir" in r.lower()
            and r != "/patients/<int:patient_id>/fhir"]
    assert not fhir, STALE.format("FHIR for other systems") + f" ({fhir})"


def test_the_fhir_file_the_list_says_is_built_is_built(app):
    """The other direction: the line says the file exists, so it had better."""
    rules = {str(r) for r in app.url_map.iter_rules()}
    assert "/patients/<int:patient_id>/fhir" in rules


# --------------------------------------------------- and the list itself --
def test_every_item_on_the_next_list_is_covered_here(app):
    """The guard's own weak point: an item added to NEXT with no check here
    goes back to being prose nobody verifies. Counted, so growing the list
    forces a decision about how it will be checked.
    """
    from app.utils.project import NEXT

    assert len(NEXT) == 1, (
        f"NEXT has {len(NEXT)} items; this file checks 1 (the FHIR API — cost "
        "centres were built and left it). Add a check for the new one — an "
        "unchecked item is how this list went stale twice.")
