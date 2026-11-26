"""حسبة جرعات Bexsero (السحائي B) من نشرة هيئة الدواء المصرية.

The clinic's owner wrote the rule out on 26 Nov 2026 — Bexsero's leaflet
approved by the Egyptian Drug Authority (10/1/2024), table 1 and its notes —
with ten worked cases, computed as if today were 26/11/2026. They are the
cases below, word for word. Before this, eight of the ten came out wrong:
every interval was 28 days, there was no 2+1 at two to five months, the 6–11
booster was at 13 months, the 12–23 booster came nine months after the last
dose, and a booster past its last day went on being chased.

* the band is the age at the **first** dose, for the whole series;
* intervals are calendar months (31/1 + a month = 28/2), not days;
* at two to five months the gap given between the first two doses tells 3+1
  from 2+1, and with one dose only it is 2+1 (the owner's choice);
* the booster has a last day; past it the dose is expired, not chased;
* a dose given sooner than its interval, and a first dose before two months,
  go to the doctor;
* the reminder list says what the child's file says.
"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

TODAY = date(2026, 11, 26)

# (case, birth, doses given, {dose: (due, status)} expected for what is left)
CASES = [
    ("بدأ في سن شهرين، تلت جرعات", date(2026, 1, 10),
     [date(2026, 3, 15), date(2026, 4, 20), date(2026, 5, 25)],
     {4: (date(2027, 1, 10), "upcoming")}),
    ("جرعتين بينهم أقل من شهرين", date(2026, 1, 10),
     [date(2026, 3, 15), date(2026, 4, 20)],
     {3: (date(2026, 5, 20), "overdue"), 4: (date(2027, 1, 10), "upcoming")}),
    ("جرعتين بينهم شهرين", date(2026, 1, 10),
     [date(2026, 3, 15), date(2026, 5, 20)],
     {3: (date(2027, 1, 10), "upcoming")}),
    ("منشطة متأخرة بس لسه مسموحة", date(2025, 1, 1),
     [date(2025, 3, 5), date(2025, 6, 1)],
     {3: (date(2026, 1, 1), "overdue")}),
    ("المنشطة فاتت", date(2024, 6, 1),
     [date(2024, 8, 5), date(2024, 10, 7)],
     {3: (date(2025, 6, 1), "expired")}),
    ("بدأ في سن 7 شهور، جرعة واحدة", date(2025, 10, 1),
     [date(2026, 5, 1)],
     # The booster after it: in the second year and two months after the
     # second dose — from today's projection of the second.
     {2: (date(2026, 7, 1), "overdue"), 3: (date(2026, 10, 1), "overdue")}),
    ("بدأ في سن 7 شهور، جرعتين", date(2025, 10, 1),
     [date(2026, 5, 1), date(2026, 7, 5)],
     {3: (date(2026, 10, 1), "overdue")}),
    ("بدأ في سن 15 شهر", date(2025, 3, 1),
     [date(2026, 6, 1), date(2026, 8, 10)],
     {3: (date(2027, 8, 10), "upcoming")}),
    ("طفل عنده 6 سنين", date(2020, 5, 1),
     [date(2026, 11, 1)],
     {2: (date(2026, 12, 1), "due")}),
]


@pytest.fixture()
def menb(clinic, monkeypatch):
    from app.extensions import db
    from app.models import Vaccine, VaccineBrand
    from app.utils import vaccines
    from app.utils.vaccines import seed_vaccine_schedules, seed_vaccines

    monkeypatch.setattr(vaccines, "local_today", lambda: TODAY)
    with clinic["app"].app_context():
        seed_vaccines()
        seed_vaccine_schedules()
        db.session.commit()
        m = Vaccine.query.filter_by(code="MENB").first()
        brand = VaccineBrand.query.filter_by(vaccine_id=m.id, name="Bexsero").first()
        clinic["menb"], clinic["bexsero"] = m.id, brand.id
    return clinic


_N = [0]


def _child(fx, dob, given):
    from app.extensions import db
    from app.models import Patient, PatientVaccine

    _N[0] += 1
    kid = Patient(patient_number=f"BX{_N[0]}", full_name="طفل", gender="male",
                  date_of_birth=dob, is_active=True)
    db.session.add(kid)
    db.session.flush()
    for n, when in enumerate(given, 1):
        db.session.add(PatientVaccine(patient_id=kid.id, vaccine_id=fx["menb"],
                                      brand_id=fx["bexsero"], dose_number=n,
                                      event_type="given", given_date=when))
    db.session.commit()
    return kid


def _row(fx, kid):
    from app.utils.vaccines import patient_plan

    plan = patient_plan(kid, agreed={fx["menb"]})
    return next(v for v in plan if v["vaccine"].id == fx["menb"])


@pytest.mark.parametrize("case,dob,given,left", CASES, ids=[c[0] for c in CASES])
def test_the_owners_worked_cases(menb, case, dob, given, left):
    with menb["app"].app_context():
        row = _row(menb, _child(menb, dob, given))
        got = {d["dose_number"]: (str(d["due_date"]), d["status"])
               for d in row["doses"] if d["status"] != "done"}
        assert got == {n: (when.isoformat(), status) for n, (when, status) in left.items()}, case
        assert len(row["doses"]) == len(given) + len(left), "no dose more, no dose less"
        assert not row.get("review")


def test_a_baby_with_nothing_yet_starts_at_two_months(menb):
    with menb["app"].app_context():
        row = _row(menb, _child(menb, date(2026, 10, 26), []))
        assert str(row["doses"][0]["due_date"]) == "2026-12-26"


def test_one_dose_at_two_to_five_months_is_2_plus_1(menb):
    """The leaflet allows either; with one dose only the owner chose 2+1. The
    second dose then decides for good."""
    with menb["app"].app_context():
        row = _row(menb, _child(menb, date(2026, 6, 1), [date(2026, 8, 3)]))
        assert [(d["dose_number"], str(d["due_date"])) for d in row["doses"][1:]] == \
            [(2, "2026-10-03"), (3, "2027-06-01")]


def test_a_dose_sooner_than_its_interval_goes_to_the_doctor(menb):
    with menb["app"].app_context():
        # Started at seven months: the second is due two months later and came
        # after five weeks.
        row = _row(menb, _child(menb, date(2025, 10, 1), [date(2026, 5, 1), date(2026, 6, 5)]))
        assert row["review"] == "short_interval"


def test_a_first_dose_before_two_months_goes_to_the_doctor(menb):
    with menb["app"].app_context():
        row = _row(menb, _child(menb, date(2026, 9, 1), [date(2026, 10, 1)]))
        assert row["review"] == "guideline_unsettled"


def test_the_reminder_list_says_what_the_file_says(menb):
    """The sweep is another path through the same rule; a booster that
    expired is not chased there either."""
    from app.utils.vaccines import scan_due

    with menb["app"].app_context():
        def due(dob, given):
            doses = [(menb["menb"], menb["bexsero"], n, d, "given")
                     for n, d in enumerate(given, 1)]
            return {(r["dose_number"], r["due_date"], r["status"])
                    for r in scan_due(dob, doses, TODAY, agreed={menb["menb"]})
                    if r["vaccine"].id == menb["menb"]}

        assert due(date(2025, 10, 1), [date(2026, 5, 1)]) == {(2, "2026-07-01", "overdue")}
        assert due(date(2024, 6, 1), [date(2024, 8, 5), date(2024, 10, 7)]) == set(), \
            "past its last day: expired, no reminder"
        assert due(date(2025, 10, 1), [date(2026, 5, 1), date(2026, 6, 5)]) == set(), \
            "a dose the doctor must judge sends no message meanwhile"


def test_the_old_bands_are_retired_unless_a_doctor_edited_them(menb):
    from app.extensions import db
    from app.models import VaccineScheduleDose, VaccineScheduleTemplate
    from app.utils.vaccines import retag_moved_bands

    with menb["app"].app_context():
        def old(code, doses):
            t = VaccineScheduleTemplate(vaccine_id=menb["menb"], code=code, source="manufacturer",
                                        label=code, is_seeded=True, is_active=True,
                                        start_age_min_months=2, start_age_max_months=5,
                                        brand_id=menb["bexsero"])
            db.session.add(t)
            db.session.flush()
            for i, (age, iv) in enumerate(doses, 1):
                db.session.add(VaccineScheduleDose(template_id=t.id, dose_number=i,
                                                   recommended_age_months=age,
                                                   min_interval_days=iv))
            return t

        as_seeded = old("MENB-2-5", [(2, None), (3, 28), (4, 28), (12, 180)])
        edited = old("MENB-6-11", [(6, None), (8, 60), (12, 60)])
        db.session.commit()
        retag_moved_bands()
        db.session.commit()
        assert not as_seeded.is_active
        assert edited.is_active, "a doctor's edit is theirs"


def test_the_months_and_last_day_are_edited_on_the_screen(menb):
    """The clinic's standing rule: the calculation is configurable, not
    re-programmed. The new boxes are on the schedule screen's dose rows."""
    from app.extensions import db
    from app.models import VaccineScheduleDose, VaccineScheduleTemplate

    with menb["app"].app_context():
        tpl = VaccineScheduleTemplate.query.filter_by(code="MENB-EG-6-11").one()
        booster = next(d for d in tpl.doses if d.dose_number == 3)
        dose_id, vaccine_id = booster.id, tpl.vaccine_id
    boss = menb["sign_in"]("boss")
    page = boss.get(f"/vaccinations/manage/vaccine/{vaccine_id}/schedules").get_data(as_text=True)
    assert 'name="min_interval_months"' in page and 'name="latest_age_months"' in page
    boss.post(f"/vaccinations/manage/schedules/dose/{dose_id}/edit", data={
        "dose_number": "3", "recommended_age_months": "12", "min_interval_months": "3",
        "latest_age_months": "23", "latest_after_months": ""})
    with menb["app"].app_context():
        d = db.session.get(VaccineScheduleDose, dose_id)
        assert (d.min_interval_months, d.latest_age_months, d.latest_after_months) == (3, 23, None)
