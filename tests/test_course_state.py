"""Saying whether a course is finished, instead of leaving it to be counted.

The program already knew every product's dose count — Rotarix two, RotaTeq
three, Prevenar three primary and a booster. What no screen did was say so. A
card reading "3/4" makes the reader do the arithmetic and still does not answer
the question that decides what happens next: is the missing dose a primary one
the child is behind on, or the booster due next year? One is a phone call and
the other is a diary note.

The second half is the honesty. The old export has no dose column, so imported
numbers were worked out from the order of the dates. Three doses of a four-dose
course may be the first three, or a child who started elsewhere and had the
second, third and fourth. Nothing in the data separates those, and the clinic
said plainly that this one is the doctor's — so the state carries what it was
inferred from rather than being asserted as fact.
"""
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def boss(clinic):
    return clinic["sign_in"]("boss")


def _doses(*specs):
    """``(status, booster, imported)`` triples as plan dose rows."""
    return [{"dose_number": i, "status": s, "booster": b, "imported": im}
            for i, (s, b, im) in enumerate(specs, start=1)]


def _state(*specs):
    from app.utils.course_state import course_state

    return course_state(_doses(*specs))


D = ("done", False, False)          # a primary dose given here
P = ("due", False, False)           # a primary dose still pending
B_DONE = ("done", True, False)      # the booster, given
B_DUE = ("due", True, False)        # the booster, pending
D_IMPORTED = ("done", False, True)  # given, but its number was inferred


# ================================================== what "finished" means ===
def test_two_doses_of_a_two_dose_course_is_complete(clinic):
    """Rotarix. Two is the whole course, and a screen that keeps showing it as
    outstanding is one people stop reading."""
    assert _state(D, D)["state"] == "complete"


def test_three_doses_of_a_three_dose_course_is_complete(clinic):
    """RotaTeq. Same rule, different product — which is the point of reading
    the dose count off the brand rather than hardcoding a number."""
    assert _state(D, D, D)["state"] == "complete"


def test_the_primary_series_done_with_the_booster_left_says_so(clinic):
    """Prevenar: three primary and a booster. "3/4" and "فاضل المنشطة" are the
    same arithmetic and different instructions."""
    out = _state(D, D, D, B_DUE)
    assert out["state"] == "booster_left"
    assert out["primary_given"] == out["primary_total"] == 3
    assert out["boosters_total"] == 1


def test_a_missing_primary_dose_is_not_a_missing_booster(clinic):
    """The child is behind, not merely due a top-up."""
    out = _state(D, D, P, B_DUE)
    assert out["state"] == "in_progress"
    assert out["left"] == 2


def test_the_booster_given_too_is_complete(clinic):
    assert _state(D, D, D, B_DONE)["state"] == "complete"


def test_nothing_given_is_not_started(clinic):
    """Kept apart from "in progress" because the screen groups them
    differently — a course nobody began is not a course somebody stalled."""
    assert _state(P, P)["state"] == "not_started"


def test_a_course_with_no_booster_never_claims_one_is_left(clinic):
    """Two of three doses of Rotateq is in progress, not "booster
    outstanding" — the product has no booster to be outstanding."""
    assert _state(D, D, P)["state"] == "in_progress"


# ========================================== and what it was worked out from ==
def test_an_imported_course_is_marked_as_inferred(clinic):
    """Its numbers came from the order of the dates in a file, not from
    anything this clinic watched happen."""
    assert _state(D_IMPORTED, D_IMPORTED, D_IMPORTED, B_DUE)["inferred"] is True


def test_a_course_recorded_here_is_not(clinic):
    """Marking everything "inferred" would make the mark mean nothing."""
    assert _state(D, D, D, B_DUE)["inferred"] is False


def test_a_course_nobody_has_started_is_not_inferred(clinic):
    """There is nothing to have inferred."""
    assert _state(P, P)["inferred"] is False


def test_the_three_dose_ambiguity_is_flagged_rather_than_resolved(clinic):
    """The case the clinic described: three imported doses of a four-dose
    course. It may be the first three with the booster left, or a child who
    started elsewhere. The program states what it worked out and says it worked
    it out — deciding would be inventing a fact about a child."""
    out = _state(D_IMPORTED, D_IMPORTED, D_IMPORTED, B_DUE)
    assert out["state"] == "booster_left"
    assert out["inferred"] is True


# ================================================== read off the catalogue ==
def test_the_pneumococcal_booster_is_the_fourth_dose(clinic):
    """3+1 — three primary at 2/4/6 months and a booster at 12. Stated in the
    catalogue rather than guessed: the "a year later, so it is a booster" rule
    is right for the 18-month OPV and misses this one by three months."""
    from app.models import Vaccine
    from app.utils.vaccines import seed_vaccines

    with clinic["app"].app_context():
        seed_vaccines()
        pcv = Vaccine.query.filter_by(code="PCV").first()
        brand = next(b for b in pcv.brands if b.name == "Prevenar 13")
        flags = {d.dose_number: d.is_booster for d in brand.doses}
    assert flags == {1: False, 2: False, 3: False, 4: True}


def test_a_rotavirus_course_has_no_booster_at_all(clinic):
    """Two doses and finished. Marking one of them a booster would put
    "outstanding" on a child who has had everything."""
    from app.models import Vaccine
    from app.utils.vaccines import seed_vaccines

    with clinic["app"].app_context():
        seed_vaccines()
        rota = Vaccine.query.filter_by(code="ROTA").first()
        brand = next(b for b in rota.brands if b.name == "RotaRix")
        assert not any(d.is_booster for d in brand.doses)


def test_the_plan_carries_the_booster_flag(clinic):
    """Computed once where the plan is built, so the sentence at the top of a
    card can never disagree with the pills underneath it."""
    from app.models import Patient
    from app.utils.vaccines import patient_plan

    with clinic["app"].app_context():
        patient = Patient.query.filter_by(id=clinic["ids"]["child"]).first()
        plan = patient_plan(patient)
        assert plan
        assert all("booster" in d for item in plan for d in item["doses"])


# ================================================================ the screen ==
def _given(clinic, *dose_numbers, imported=False):
    from app.models import ImportBatch, PatientVaccine

    with clinic["app"].app_context():
        batch_id = None
        if imported:
            batch = ImportBatch(kind="history", rows_total=len(dose_numbers))
            clinic["db"].session.add(batch)
            clinic["db"].session.flush()
            batch_id = batch.id
        for number in dose_numbers:
            clinic["db"].session.add(PatientVaccine(
                patient_id=clinic["ids"]["child"], vaccine_id=clinic["ids"]["pcv"],
                brand_id=clinic["ids"]["brand"], dose_number=number,
                event_type="given", import_batch_id=batch_id,
                given_date=date.today() - timedelta(days=400 - 30 * number)))
        clinic["db"].session.commit()


def test_the_screen_says_a_finished_course_is_finished(boss, clinic):
    """The shared fixture's PCV brand has three doses and no booster."""
    _given(clinic, 1, 2, 3)
    body = boss.get(f"/vaccinations/{clinic['ids']['child']}").get_data(as_text=True)
    with clinic["app"].test_request_context("/"):
        from app.i18n import t
        assert t("vaccinations.course_complete") in body


def test_the_screen_says_how_many_are_left(boss, clinic):
    _given(clinic, 1)
    body = boss.get(f"/vaccinations/{clinic['ids']['child']}").get_data(as_text=True)
    with clinic["app"].test_request_context("/"):
        from app.i18n import t
        assert t("vaccinations.course_left").replace("{n}", "2") in body


def test_the_screen_marks_an_imported_course_as_inferred(boss, clinic):
    _given(clinic, 1, 2, imported=True)
    body = boss.get(f"/vaccinations/{clinic['ids']['child']}").get_data(as_text=True)
    with clinic["app"].test_request_context("/"):
        from app.i18n import t
        assert t("vaccinations.course_inferred") in body


def test_a_course_recorded_here_carries_no_such_mark(boss, clinic):
    _given(clinic, 1, 2)
    body = boss.get(f"/vaccinations/{clinic['ids']['child']}").get_data(as_text=True)
    with clinic["app"].test_request_context("/"):
        from app.i18n import t
        assert t("vaccinations.course_inferred") not in body


def test_both_languages_carry_the_words(clinic):
    import json

    root = os.path.join(os.path.dirname(__file__), "..")
    for lang in ("ar", "en"):
        with open(os.path.join(root, "app", "i18n", "locales", f"{lang}.json"),
                  encoding="utf-8") as fh:
            data = json.load(fh)
        for key in ("course_complete", "course_booster_left", "course_left",
                    "course_inferred", "course_inferred_hint"):
            assert data["vaccinations"].get(key), f"{lang}.{key}"
