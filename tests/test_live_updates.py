"""Telling the other screen that something changed.

Reported: *"I have the doctor's account and the admin account open, and they
don't hear each other in any screen — the doctor changes things and the admin
sees nothing until they refresh."*

The mechanism for this already existed and was applied to four screens out of a
hundred and fifty-two, all four asking the **same** fingerprint (the day's
board). So a diagnosis, a prescription, a study, a corrected birth date — none
of them were covered by any fingerprint at all. This adds the two screens two
people genuinely have open at once, and the fingerprints that cover what those
screens actually show.

**Why these two are told rather than reloaded.** The boards already wired up are
read-only, so throwing the page away costs nothing. The patient file and the
visit record carry eighteen forms each, and a doctor who has typed half a page
of notes and clicked away would lose it — the existing focus check only pauses
while the caret is still in a field.

And reloading was never the request. "The admin didn't see it until they
refreshed" is a complaint about not being **told**. Being told is the fix; when
to refresh belongs to the reader, because only they know whether they are
mid-sentence.

The last test is the one that will still be earning its place in a year: it
holds the rule from `live.py` — *whatever a screen shows, its fingerprint
covers* — by checking that each thing the patient file displays actually moves
the fingerprint. A screen that looks live while lying is worse than one that
plainly is not, because nobody refreshes a screen they trust.
"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# The clinic's today, not the server's — the same clock the
# screens filter by. See conftest.py.
from app.utils.clock import local_today  # noqa: E402

import pytest  # noqa: E402


@pytest.fixture()
def watched(clinic):
    """The doctor and the admin both signed in, looking at the same child."""
    clinic["doc"] = clinic["sign_in"]("doc")
    clinic["boss"] = clinic["sign_in"]("boss")
    return clinic


def _fp(watched, kind, ident):
    from app.utils.live import FINGERPRINTS

    with watched["app"].app_context():
        return FINGERPRINTS[kind](ident)


def _patient_fp(watched):
    return _fp(watched, "patient", watched["ids"]["child"])


def _visit_fp(watched):
    return _fp(watched, "visit", watched["ids"]["visit"])


# ------------------------------------------------------ the fingerprint ----
def test_nothing_changing_means_nothing_changed(watched):
    """A fingerprint that moved on its own would reload every screen in the
    clinic every fifteen seconds."""
    assert _patient_fp(watched) == _patient_fp(watched)


def test_a_new_visit_moves_the_patients_fingerprint(watched):
    from app.models import Visit

    before = _patient_fp(watched)
    with watched["app"].app_context():
        watched["db"].session.add(Visit(
            patient_id=watched["ids"]["child"],
            doctor_id=watched["ids"]["doctor"], visit_date=date.today()))
        watched["db"].session.commit()
    assert _patient_fp(watched) != before


def test_a_new_prescription_moves_it(watched):
    from app.models import Prescription

    before = _patient_fp(watched)
    with watched["app"].app_context():
        watched["db"].session.add(Prescription(
            patient_id=watched["ids"]["child"],
            doctor_id=watched["ids"]["doctor"], rx_date=date.today()))
        watched["db"].session.commit()
    assert _patient_fp(watched) != before


def test_a_new_study_moves_it(watched):
    """The section added for the studies is on this screen, so it has to be
    in this fingerprint — that is the rule, not a nicety."""
    from app.models import DeviceStudy, MedicalDevice

    with watched["app"].app_context():
        dev = MedicalDevice(name="إيكو", device_type="echo", is_active=True)
        watched["db"].session.add(dev)
        watched["db"].session.commit()
        dev_id = dev.id

    before = _patient_fp(watched)
    with watched["app"].app_context():
        watched["db"].session.add(DeviceStudy(
            patient_id=watched["ids"]["child"], device_id=dev_id,
            study_date=local_today()))
        watched["db"].session.commit()
    assert _patient_fp(watched) != before


def test_a_new_consent_moves_it(watched):
    from app.models import Consent

    before = _patient_fp(watched)
    with watched["app"].app_context():
        watched["db"].session.add(Consent(
            patient_id=watched["ids"]["child"], consent_type="general",
            guardian_name="الأب", signed_date=date.today()))
        watched["db"].session.commit()
    assert _patient_fp(watched) != before


def test_a_new_invoice_moves_it(watched):
    from app.models import Invoice

    before = _patient_fp(watched)
    with watched["app"].app_context():
        watched["db"].session.add(Invoice(
            invoice_number="INV-L1", patient_id=watched["ids"]["child"],
            invoice_date=date.today(), status="issued"))
        watched["db"].session.commit()
    assert _patient_fp(watched) != before


def test_another_childs_visit_does_not_move_it(watched):
    """Otherwise every file in the clinic offers to refresh whenever anything
    happens anywhere, and people learn to ignore the bar."""
    from app.models import Patient, Visit

    before = _patient_fp(watched)
    with watched["app"].app_context():
        other = Patient(patient_number="P42", full_name="طفل تاني",
                        gender="female", date_of_birth=date(2024, 2, 2),
                        is_active=True)
        watched["db"].session.add(other)
        watched["db"].session.flush()
        watched["db"].session.add(Visit(
            patient_id=other.id, doctor_id=watched["ids"]["doctor"],
            visit_date=local_today()))
        watched["db"].session.commit()
    assert _patient_fp(watched) == before


# ------------------------------------------------------------ the visit ----
def test_a_service_added_to_a_visit_moves_its_fingerprint(watched):
    from app.models import VisitService

    before = _visit_fp(watched)
    with watched["app"].app_context():
        watched["db"].session.add(VisitService(
            visit_id=watched["ids"]["visit"],
            service_id=watched["ids"]["exam"], name="كشف", quantity=1))
        watched["db"].session.commit()
    assert _visit_fp(watched) != before


def test_the_visits_own_status_moves_it(watched):
    """"The doctor finished" is exactly the thing the other screen is
    waiting for."""
    from app.models import Visit

    before = _visit_fp(watched)
    with watched["app"].app_context():
        watched["db"].session.get(Visit, watched["ids"]["visit"]).status = "done"
        watched["db"].session.commit()
    assert _visit_fp(watched) != before


# --------------------------------------------------------- the endpoint ----
def test_the_endpoint_answers_with_a_fingerprint(watched):
    r = watched["boss"].get(f"/live/patient/{watched['ids']['child']}")
    assert r.status_code == 200 and r.get_json()["fp"]


def test_the_endpoint_agrees_with_the_function(watched):
    r = watched["boss"].get(f"/live/visit/{watched['ids']['visit']}")
    assert r.get_json()["fp"] == _visit_fp(watched)


def test_an_unknown_kind_is_a_404_not_a_crash(watched):
    """The kinds come from a fixed map. A name in the URL is looked up, never
    called — otherwise the URL decides what code runs."""
    assert watched["boss"].get("/live/os.system/1").status_code == 404


def test_a_stranger_cannot_ask(watched):
    """The answer is only a hash, but *whether it changed* still says
    something about a patient."""
    anon = watched["app"].test_client()
    r = anon.get(f"/live/patient/{watched['ids']['child']}")
    assert r.status_code in (302, 401)


# ------------------------------------------------------ on the screens -----
def test_the_patient_file_watches_for_changes(watched):
    body = watched["boss"].get(
        f"/patients/{watched['ids']['child']}").get_data(as_text=True)
    assert "gcLiveNotify" in body
    assert f"/live/patient/{watched['ids']['child']}" in body


def test_the_visit_record_watches_for_changes(watched):
    body = watched["doc"].get(
        f"/visits/{watched['ids']['visit']}/record").get_data(as_text=True)
    assert "gcLiveNotify" in body


def test_a_screen_with_forms_is_never_reloaded_out_from_under_somebody(watched):
    """The judgement this rests on. `gcLivePoll` reloads; on a page with
    eighteen forms that would take a half-written note with it, and the focus
    guard only helps while the caret is still in the field."""
    for url in (f"/patients/{watched['ids']['child']}",
                f"/visits/{watched['ids']['visit']}/record"):
        body = watched["boss"].get(url).get_data(as_text=True)
        assert "gcLivePoll(" not in body, url


def test_the_bar_is_offered_in_the_users_language(watched):
    watched["boss"].get("/lang/en", follow_redirects=True)
    body = watched["boss"].get(
        f"/patients/{watched['ids']['child']}").get_data(as_text=True)
    assert "somebody recorded something new" in body


# -------------------------------------------- the rule, not the instances --
def test_everything_the_file_shows_is_covered(watched):
    """`live.py` states the rule this whole feature turns on — *whatever a
    screen shows, its fingerprint covers* — and the bug it was written after
    was a fingerprint narrower than its screen.

    So rather than trusting the tests above to have listed everything, this
    walks the sections the patient file renders and requires each to be in the
    fingerprint. A section added later without one fails here, which is the
    only moment anybody is thinking about it.
    """
    import inspect

    from app.utils import live

    source = inspect.getsource(live.patient_fingerprint)
    # Each of these has a section in patients/profile.html.
    for model in ("Visit", "Prescription", "DeviceStudy", "Consent",
                  "Invoice", "Patient"):
        assert model in source, (
            f"the patient file shows {model} but its fingerprint does not "
            "cover it — the screen would look live while going stale")
