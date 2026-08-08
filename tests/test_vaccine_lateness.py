""""Late" is a broken promise, and only this clinic's promises can break.

Reported from a real screen: *the system says this patient is late for 41
vaccines*. He was not late for anything. The catalogue holds every vaccine the
program knows, a due date can be projected from any birthday, and so every
dose of every course a healthy two-year-old had not received here counted as
overdue — including the entire national schedule, which is given at the
government unit and was never this clinic's to give.

The number is worse than useless. It frightens a parent who reads it, it says
nothing clinically, and it buries the one or two doses that genuinely *are*
owed among forty that are not.

So the rule this file pins is: a course becomes ours the moment one dose is
given here. Before that, everything the child is old enough for is a
**suggestion by age** — true, sayable, and a different sentence.

The certificate follows from the same idea. It carries what the child had and
what this clinic still owes; suggestions print only if the doctor asks; and a
refused dose appears in neither, because reprinting it as outstanding is
asking the family again, on paper, every time the certificate is issued.
"""
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def _toddler(clinic, days=730):
    """A child old enough that every projected due date is in the past."""
    from app.models import Patient

    db = clinic["db"]
    patient = db.session.get(Patient, clinic["ids"]["child"])
    patient.date_of_birth = date.today() - timedelta(days=days)
    db.session.commit()
    return patient


def _give(clinic, patient, vaccine_id, brand_id, dose=1, days_ago=400, **kw):
    from app.models import PatientVaccine

    db = clinic["db"]
    row = PatientVaccine(patient_id=patient.id, vaccine_id=vaccine_id,
                         brand_id=brand_id, dose_number=dose,
                         given_date=date.today() - timedelta(days=days_ago),
                         event_type=kw.pop("event_type", "given"), **kw)
    db.session.add(row)
    db.session.commit()
    return row


# ================================================== the 41 that were not ====
def test_a_child_who_started_nothing_here_is_late_for_nothing(clinic):
    """The bug itself. Nobody at this clinic promised those doses."""
    from app.utils.vaccines import patient_plan, plan_summary

    with clinic["app"].app_context():
        patient = _toddler(clinic)
        summary = plan_summary(patient_plan(patient))

        assert summary["overdue"] == 0, (
            "a child who was never given anything here cannot be late for "
            "anything here")
        # And they are not simply hidden — they are counted honestly.
        assert summary["suggested"] > 0


def test_starting_a_course_here_is_what_makes_the_next_dose_late(clinic):
    """The other half. Once a dose is given, the course is this clinic's and
    the one after it really can be owed — otherwise the fix would have turned
    a loud wrong number into a silent missing one."""
    from app.utils.vaccines import patient_plan, plan_summary

    db = clinic["db"]
    with clinic["app"].app_context():
        patient = _toddler(clinic)
        _give(clinic, patient, clinic["ids"]["pcv"], clinic["ids"]["brand"])

        summary = plan_summary(patient_plan(patient))
        assert summary["done"] == 1
        assert summary["overdue"] >= 1, "the started course stopped being tracked"


def test_lateness_is_confined_to_the_course_that_was_started(clinic):
    """One started course must not make the rest of the catalogue late."""
    from app.utils.vaccines import patient_plan

    db = clinic["db"]
    with clinic["app"].app_context():
        patient = _toddler(clinic)
        _give(clinic, patient, clinic["ids"]["pcv"], clinic["ids"]["brand"])

        for item in patient_plan(patient):
            overdue = [d for d in item["doses"] if d["status"] == "overdue"]
            if item["vaccine"].id != clinic["ids"]["pcv"]:
                assert not overdue, (
                    f"{item['vaccine'].code} is late and nobody ever started it")


def test_the_plan_says_which_courses_are_ours(clinic):
    """Every screen that has to make this distinction reads one flag rather
    than re-deriving it — which is how the derivation drifts."""
    from app.utils.vaccines import patient_plan

    with clinic["app"].app_context():
        patient = _toddler(clinic)
        _give(clinic, patient, clinic["ids"]["pcv"], clinic["ids"]["brand"])

        by_id = {v["vaccine"].id: v for v in patient_plan(patient)}
        assert by_id[clinic["ids"]["pcv"]]["started"] is True
        assert by_id[clinic["ids"]["opv"]]["started"] is False


def test_the_screen_shows_suggestions_as_their_own_thing(clinic):
    """Counted on the page, in their own card, so nothing about them reads as
    a debt — and so the honest number is not simply hidden."""
    from app.i18n import t

    with clinic["app"].app_context():
        patient = _toddler(clinic)
        pid = patient.id

    page = clinic["sign_in"]("doc").get(f"/vaccinations/{pid}").data.decode()
    with clinic["app"].test_request_context():
        assert t("vstatus.suggested") in page


# ================================================== what the paper says =====
def test_the_certificate_lists_only_what_this_clinic_still_owes(clinic):
    """Asked for directly: only what is left *for him*.

    The schedule table used to carry every not-yet-given dose in the
    catalogue, so a certificate handed to a family implied this clinic owed
    them the whole national schedule.
    """
    from app.i18n import t

    with clinic["app"].app_context():
        patient = _toddler(clinic)
        _give(clinic, patient, clinic["ids"]["pcv"], clinic["ids"]["brand"])
        pid = patient.id
        started = "PCV"

    page = clinic["sign_in"]("doc").get(
        f"/vaccinations/{pid}/certificate?schedule=1").data.decode()

    with clinic["app"].test_request_context():
        table = page.split(t("vaccinations.cert_upcoming_hint"))[0]
    # The started course is what is owed; the untouched one is not.
    assert started in table or "المكورات" in table
    assert "شلل الأطفال" not in table, (
        "a course nobody started was printed as outstanding")


def test_age_suggestions_are_the_doctors_choice_and_off_by_default(clinic):
    """"لأن الحكومي لا" — the national schedule is given at the government
    unit, so printing it on this clinic's certificate by default misleads the
    family holding the paper."""
    from app.i18n import t

    with clinic["app"].app_context():
        patient = _toddler(clinic)
        _give(clinic, patient, clinic["ids"]["pcv"], clinic["ids"]["brand"])
        pid = patient.id

    client = clinic["sign_in"]("doc")
    with clinic["app"].test_request_context():
        marker = t("vaccinations.cert_suggested_hint")

    default = client.get(f"/vaccinations/{pid}/certificate?schedule=1").data.decode()
    assert marker not in default

    asked = client.get(
        f"/vaccinations/{pid}/certificate?schedule=1&suggest=1").data.decode()
    assert marker in asked


def test_the_two_tables_are_never_merged(clinic):
    """They make different claims — one is a commitment, the other an idea —
    and a reader cannot tell them apart once they share a heading."""
    from app.i18n import t

    with clinic["app"].app_context():
        patient = _toddler(clinic)
        _give(clinic, patient, clinic["ids"]["pcv"], clinic["ids"]["brand"])
        pid = patient.id

    page = clinic["sign_in"]("doc").get(
        f"/vaccinations/{pid}/certificate?suggest=1").data.decode()

    with clinic["app"].test_request_context():
        # Suggestions asked for, the clinic's own table not — so the page must
        # carry one and not the other.
        assert t("vaccinations.cert_suggested_hint") in page
        assert t("vaccinations.cert_upcoming_hint") not in page


def test_a_refused_dose_is_not_reprinted_as_outstanding(clinic):
    """The family said no. Listing it again on every certificate is asking
    them again, on paper, for as long as the child is a patient."""
    from app.i18n import t
    from app.models import Vaccine

    db = clinic["db"]
    with clinic["app"].app_context():
        patient = _toddler(clinic)
        _give(clinic, patient, clinic["ids"]["pcv"], clinic["ids"]["brand"])
        # Refuse the second dose of the very course that is ours.
        _give(clinic, patient, clinic["ids"]["pcv"], clinic["ids"]["brand"],
              dose=2, event_type="refused")
        db.session.commit()
        pid = patient.id
        name = db.session.get(Vaccine, clinic["ids"]["pcv"]).display_name("ar")

    page = clinic["sign_in"]("doc").get(
        f"/vaccinations/{pid}/certificate?schedule=1").data.decode()
    with clinic["app"].test_request_context():
        table = page.split(t("vaccinations.cert_upcoming_hint"))[0]
        table = table.split(t("vaccinations.cert_upcoming_title"))[-1]

    # Dose 3 may still be owed; dose 2 was refused and must not be listed.
    rows = [line for line in table.splitlines() if name in line]
    assert not any(">2<" in line for line in rows), (
        "the refused dose was printed as still outstanding")


def test_the_certificate_still_lists_what_the_child_actually_had(clinic):
    """Guarding the guard: none of this may quietly shrink the record itself,
    which is the entire purpose of the document."""
    from app.utils.vaccines import certificate_cards, patient_plan

    with clinic["app"].app_context():
        patient = _toddler(clinic)
        _give(clinic, patient, clinic["ids"]["pcv"], clinic["ids"]["brand"])

        cards = certificate_cards(patient_plan(patient))
        assert len(cards) == 1
        assert cards[0]["given"] == 1
