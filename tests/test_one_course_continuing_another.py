"""Doses given as one vaccine that continue another's course.

Reported by a doctor, with a screenshot: a child on the **government
pentavalent** for the primary series and then a **hexavalent booster**, and
the program's banner read *"Next due vaccine — Hexavalent, Dose 1 · Overdue
2024-01-03"*, over a card saying 1/4.

It was right about what it had been told and wrong about the child. The two
are separate rows in the catalogue and nothing said that one continues the
other, so three doses that happened counted for nothing and the course
started again at one — for a child whose only outstanding dose was the
booster they had already had.

**The obvious fix is the wrong one.** Recording the pentavalent doses against
the hexavalent would make the screen right by making the record false: a
child's file saying they were given a product nobody gave them. So the fact
lives where it is true — in the catalogue, once, about the vaccines — and the
child's file keeps saying what actually went into their arm.

``up_to_dose`` is the whole safety of it. Egypt's government pentavalent has
no IPV in it: it continues the hexavalent's primary series and does not
discharge everything the hexavalent covers. A credit that reached the whole
course would tell a child they were finished with something they had never
received.
"""
from datetime import date, timedelta

import pytest


# --------------------------------------------------------------- helpers --
def _series(clinic, code, name, doses):
    """A vaccine with one brand and ``doses`` = [(number, age_months)]."""
    from app.models import Vaccine, VaccineBrand, VaccineBrandDose

    with clinic["app"].app_context():
        db = clinic["db"]
        vaccine = Vaccine(code=code, name_ar=name, is_mandatory=False)
        db.session.add(vaccine)
        db.session.flush()
        brand = VaccineBrand(vaccine_id=vaccine.id, name=f"{code}-brand",
                             price=0, doses_per_vial=1, is_default=True)
        db.session.add(brand)
        db.session.flush()
        for number, months in doses:
            db.session.add(VaccineBrandDose(brand_id=brand.id,
                                            dose_number=number,
                                            age_months=months))
        db.session.commit()
        return vaccine.id, brand.id


@pytest.fixture
def series(clinic):
    """The reported pair: a three-dose pentavalent, a four-dose hexavalent."""
    penta, penta_brand = _series(clinic, "PENTA", "الخماسي",
                                 [(1, 2), (2, 4), (3, 6)])
    hexa, hexa_brand = _series(clinic, "HEXA", "السداسي",
                               [(1, 2), (2, 4), (3, 6), (4, 18)])
    return {"penta": penta, "penta_brand": penta_brand,
            "hexa": hexa, "hexa_brand": hexa_brand}


def _add_dose_row(clinic, brand_id, dose_number, age_months):
    """Give the source vaccine a dose past the cap.

    Without one, every cap mutant survives: a credit that ignored its limit
    had nothing beyond dose 3 to wrongly reach for, so "the cap is obeyed"
    and "the cap is ignored" produced identical cards.
    """
    from app.models import VaccineBrandDose

    with clinic["app"].app_context():
        clinic["db"].session.add(VaccineBrandDose(
            brand_id=brand_id, dose_number=dose_number, age_months=age_months))
        clinic["db"].session.commit()


def _credit(clinic, series, up_to_dose=3):
    from app.models import VaccineCredit

    with clinic["app"].app_context():
        clinic["db"].session.add(VaccineCredit(
            vaccine_id=series["hexa"], from_vaccine_id=series["penta"],
            up_to_dose=up_to_dose))
        clinic["db"].session.commit()


def _give(clinic, vaccine_id, brand_id, dose_number, when, outside=True):
    from app.models import PatientVaccine

    with clinic["app"].app_context():
        clinic["db"].session.add(PatientVaccine(
            patient_id=clinic["ids"]["child"], vaccine_id=vaccine_id,
            brand_id=brand_id, dose_number=dose_number, given_date=when,
            event_type="given", given_outside=outside,
            outside_place="وحدة صحية" if outside else None))
        clinic["db"].session.commit()


def _the_reported_child(clinic, series):
    """Three government pentavalent doses, then a hexavalent booster."""
    start = date(2024, 1, 17)
    for number, day in ((1, 0), (2, 59), (3, 143)):
        _give(clinic, series["penta"], series["penta_brand"], number,
              start + timedelta(days=day))
    _give(clinic, series["hexa"], series["hexa_brand"], 4,
          date(2025, 5, 10), outside=False)


def _plan(clinic, vaccine_id):
    from app.models import Patient
    from app.utils.vaccines import patient_plan

    with clinic["app"].app_context():
        patient = clinic["db"].session.get(Patient, clinic["ids"]["child"])
        plan = patient_plan(patient)
        item = next(v for v in plan if v["vaccine"].id == vaccine_id)
        return [{"n": d["dose_number"], "status": d["status"],
                 "given": d["given_date"], "brand": d.get("brand_name")}
                for d in item["doses"]]


def _next_due(clinic):
    from app.models import Patient
    from app.utils.vaccines import next_due_dose, patient_plan

    with clinic["app"].app_context():
        patient = clinic["db"].session.get(Patient, clinic["ids"]["child"])
        answer = next_due_dose(patient_plan(patient))
        if answer is None:
            return None
        _due, vaccine, _brand, dose = answer
        return {"vaccine": vaccine.name_ar, "dose": dose["dose_number"]}


# --------------------------------------------------- the reported case ----
def test_without_a_credit_the_course_starts_again_at_one(clinic, series):
    """The fault as reported. Kept as a test because it is what every clinic
    sees until somebody states the equivalence — and because it is what makes
    the tests below mean anything."""
    _the_reported_child(clinic, series)
    doses = _plan(clinic, series["hexa"])
    assert [d["status"] for d in doses] == ["overdue", "overdue", "overdue",
                                            "done"]


def test_the_credited_doses_read_as_done(clinic, series):
    """The fix. Three doses that happened stop counting for nothing."""
    _the_reported_child(clinic, series)
    _credit(clinic, series)
    doses = _plan(clinic, series["hexa"])
    assert [d["status"] for d in doses] == ["done"] * 4


def test_the_child_is_no_longer_told_a_dose_is_overdue(clinic, series):
    """The banner the doctor photographed: *"Hexavalent — Dose 1 · Overdue
    2024-01-03"*, for a child who needed nothing."""
    _the_reported_child(clinic, series)
    _credit(clinic, series)
    assert _next_due(clinic) is None


# ------------------------------------------- what the record still says ---
def test_the_credited_dose_keeps_the_date_it_really_happened(clinic, series):
    """A credit stands in for a missing dose with the *real* record of the
    dose that was given — not a blank marked done. A course reading complete
    with nothing behind it is the other kind of lie."""
    _the_reported_child(clinic, series)
    _credit(clinic, series)
    doses = _plan(clinic, series["hexa"])
    assert doses[0]["given"] == "2024-01-17"


def test_the_credited_dose_still_names_the_product_that_was_given(clinic,
                                                                  series):
    """It says pentavalent, because that is what went into the child. The
    file must never claim they were given the hexavalent."""
    _the_reported_child(clinic, series)
    _credit(clinic, series)
    assert _plan(clinic, series["hexa"])[0]["brand"] == "PENTA-brand"


def test_the_pentavalent_course_is_untouched(clinic, series):
    """Crediting is not moving. The doses still belong to the vaccine they
    were given as, and its own card still reads 3/3."""
    _the_reported_child(clinic, series)
    _credit(clinic, series)
    doses = _plan(clinic, series["penta"])
    assert [d["status"] for d in doses] == ["done"] * 3


# ------------------------------------------------------ where it stops ----
def test_a_credit_does_not_reach_past_the_dose_it_names(clinic, series):
    """The safety of the whole thing.

    The government pentavalent has no IPV in it. It continues the primary
    series; it does not discharge the booster. A credit that reached the
    whole course would tell a child they were finished with something they
    never had.
    """
    start = date(2024, 1, 17)
    for number, day in ((1, 0), (2, 59), (3, 143)):
        _give(clinic, series["penta"], series["penta_brand"], number,
              start + timedelta(days=day))
    _credit(clinic, series, up_to_dose=3)          # no hexavalent booster
    doses = _plan(clinic, series["hexa"])
    assert doses[3]["status"] != "done"


def test_a_source_dose_past_the_cap_is_not_credited(clinic, series):
    """The safety property, tested where it can actually fail.

    A pentavalent given four times does not discharge the hexavalent's fourth
    dose, because the clinic said the credit stops at three. This is the case
    that separates "the cap is obeyed" from "the cap is ignored" — and from
    "the cap is off by one", which reaches exactly one dose too far and is the
    likeliest way to write it wrongly.
    """
    _add_dose_row(clinic, series["penta_brand"], 4, 18)
    start = date(2024, 1, 17)
    for number, day in ((1, 0), (2, 59), (3, 143), (4, 480)):
        _give(clinic, series["penta"], series["penta_brand"], number,
              start + timedelta(days=day))
    _credit(clinic, series, up_to_dose=3)

    doses = _plan(clinic, series["hexa"])
    assert [d["status"] for d in doses[:3]] == ["done"] * 3
    assert doses[3]["status"] != "done"


def test_a_credit_with_no_cap_reaches_the_whole_course(clinic, series):
    """Right for a straight rename, and the reason the cap is asked for
    rather than assumed."""
    start = date(2024, 1, 17)
    for number, day in ((1, 0), (2, 59), (3, 143)):
        _give(clinic, series["penta"], series["penta_brand"], number,
              start + timedelta(days=day))
    _credit(clinic, series, up_to_dose=None)
    doses = _plan(clinic, series["hexa"])
    assert [d["status"] for d in doses[:3]] == ["done"] * 3


# --------------------------------------------------- it never overwrites --
def test_a_real_dose_beats_a_credited_one(clinic, series):
    """A credit fills a gap. It must never cover a dose that is actually on
    file, or the card would show the wrong product and the wrong date for
    something this clinic gave itself."""
    _give(clinic, series["penta"], series["penta_brand"], 1,
          date(2024, 1, 17))
    _give(clinic, series["hexa"], series["hexa_brand"], 1,
          date(2024, 3, 1), outside=False)
    _credit(clinic, series)
    first = _plan(clinic, series["hexa"])[0]
    assert first["given"] == "2024-03-01"
    assert first["brand"] == "HEXA-brand"


def test_the_credit_does_not_run_the_other_way(clinic, series):
    """Stated about a direction, and it holds to it. A hexavalent dose does
    not silently complete the pentavalent — that is a separate clinical
    statement, and the clinic makes it separately if they mean it."""
    _give(clinic, series["hexa"], series["hexa_brand"], 1, date(2024, 1, 17))
    _credit(clinic, series)
    assert _plan(clinic, series["penta"])[0]["status"] != "done"


def test_no_credit_changes_nothing_for_anybody_else(clinic, series):
    """Nothing is seeded. Every clinic that has not stated an equivalence
    gets exactly the behaviour it had before."""
    _give(clinic, series["penta"], series["penta_brand"], 1,
          date(2024, 1, 17))
    assert _plan(clinic, series["hexa"])[0]["status"] != "done"


# ------------------------------------------------------- reachable at all --
def test_the_catalogue_screen_offers_the_equivalence(clinic, series):
    """A rule no screen can state is a rule nobody has. This is the one the
    whole change hangs off: until a clinic says which vaccine continues
    which, nothing is credited."""
    boss = clinic["sign_in"]("boss")
    page = boss.get(
        f"/vaccinations/manage/vaccine/{series['hexa']}/schedules"
    ).get_data(as_text=True)
    assert 'name="from_vaccine_id"' in page
    assert 'name="up_to_dose"' in page


def test_stating_it_on_the_screen_credits_the_child(clinic, series):
    """End to end, through the form a doctor actually fills in."""
    _the_reported_child(clinic, series)
    boss = clinic["sign_in"]("boss")
    boss.post(f"/vaccinations/manage/vaccine/{series['hexa']}/credits/new",
              data={"from_vaccine_id": str(series["penta"]), "up_to_dose": "3"},
              follow_redirects=True)

    assert [d["status"] for d in _plan(clinic, series["hexa"])] == ["done"] * 4
    assert _next_due(clinic) is None

    # The cap the doctor typed is the cap that was stored. Read back rather
    # than inferred from the card: with three pentavalent doses on file, a
    # form that dropped the figure entirely produced the same four ticks.
    from app.models import VaccineCredit

    with clinic["app"].app_context():
        assert VaccineCredit.query.one().up_to_dose == 3


def test_a_vaccine_cannot_continue_itself(clinic, series):
    """It would credit every dose with itself and read as complete from the
    moment one dose existed."""
    from app.models import VaccineCredit

    boss = clinic["sign_in"]("boss")
    boss.post(f"/vaccinations/manage/vaccine/{series['hexa']}/credits/new",
              data={"from_vaccine_id": str(series["hexa"]), "up_to_dose": "3"},
              follow_redirects=True)
    with clinic["app"].app_context():
        assert VaccineCredit.query.count() == 0


def test_the_same_pair_is_not_stated_twice(clinic, series):
    """Two rows saying the same thing with different caps is a rule with two
    answers."""
    from app.models import VaccineCredit

    boss = clinic["sign_in"]("boss")
    for cap in ("3", "4"):
        boss.post(f"/vaccinations/manage/vaccine/{series['hexa']}/credits/new",
                  data={"from_vaccine_id": str(series["penta"]),
                        "up_to_dose": cap}, follow_redirects=True)
    with clinic["app"].app_context():
        assert VaccineCredit.query.count() == 1


def test_an_equivalence_can_be_withdrawn(clinic, series):
    """A clinical statement somebody must be able to take back as easily as
    they made it."""
    from app.models import VaccineCredit

    _the_reported_child(clinic, series)
    _credit(clinic, series)
    boss = clinic["sign_in"]("boss")
    with clinic["app"].app_context():
        credit_id = VaccineCredit.query.one().id
    boss.post(f"/vaccinations/manage/credits/{credit_id}/delete",
              follow_redirects=True)

    assert _plan(clinic, series["hexa"])[0]["status"] == "overdue"


def test_the_screen_lists_what_was_already_stated(clinic, series):
    """A rule that cannot be read back is a rule nobody can check or undo.

    Asserted on the note and the withdraw button, not on the vaccine's name:
    the name is in the add form's dropdown too, so looking for it passed
    whether or not anything was listed at all.
    """
    from app.models import VaccineCredit

    with clinic["app"].app_context():
        clinic["db"].session.add(VaccineCredit(
            vaccine_id=series["hexa"], from_vaccine_id=series["penta"],
            up_to_dose=3, note="الخماسي الحكومي — بدون IPV"))
        clinic["db"].session.commit()
        credit_id = VaccineCredit.query.one().id

    boss = clinic["sign_in"]("boss")
    page = boss.get(
        f"/vaccinations/manage/vaccine/{series['hexa']}/schedules"
    ).get_data(as_text=True)
    assert "الخماسي الحكومي — بدون IPV" in page
    assert f"/vaccinations/manage/credits/{credit_id}/delete" in page


# ---------------------------------------- the desk must say the same thing --
def _scan(clinic, vaccine_id):
    """The lean path the work-list and the reminder sweep actually run."""
    from app.models import Patient, PatientVaccine
    from app.utils.clock import local_today
    from app.utils.vaccines import scan_due

    with clinic["app"].app_context():
        patient = clinic["db"].session.get(Patient, clinic["ids"]["child"])
        rows = [(pv.vaccine_id, pv.brand_id, pv.dose_number, pv.given_date,
                 pv.event_type)
                for pv in PatientVaccine.query.filter_by(
                    patient_id=patient.id).all()]
        pending = scan_due(patient.date_of_birth, rows, local_today())
    return [r for r in pending if r["vaccine"].id == vaccine_id]


def test_the_desk_list_credits_the_doses_too(clinic, series):
    """`scan_due` is the lean twin of `patient_plan` and says so in its own
    docstring: *it must answer identically*.

    Crediting in one and not the other is the worst of both — the child's own
    file reads "done" while the desk's work-list and the reminder sweep keep
    calling the same dose overdue, and the two screens argue about one child
    with nobody able to say which is right.
    """
    _the_reported_child(clinic, series)
    _credit(clinic, series)
    assert _scan(clinic, series["hexa"]) == []


def test_the_desk_list_still_chases_an_uncredited_child(clinic, series):
    """And it has not simply gone quiet: without the equivalence stated, the
    same child is still chased for the doses that are genuinely missing."""
    _the_reported_child(clinic, series)
    assert _scan(clinic, series["hexa"]) != []


def test_the_desk_list_obeys_the_cap(clinic, series):
    """The safety property, on the path that generates the reminders a family
    is actually sent."""
    _add_dose_row(clinic, series["penta_brand"], 4, 18)
    start = date(2024, 1, 17)
    for number, day in ((1, 0), (2, 59), (3, 143), (4, 480)):
        _give(clinic, series["penta"], series["penta_brand"], number,
              start + timedelta(days=day))
    _credit(clinic, series, up_to_dose=3)

    still_due = [r["dose_number"] for r in _scan(clinic, series["hexa"])]
    assert still_due == [4]
