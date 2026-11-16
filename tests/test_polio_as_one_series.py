"""Polio as one series — OPV and IPV read together, by WHO's own numbers.

IMPROVEMENTS_BACKLOG ٠.٢ left OPV and IPV with no ceiling on purpose, until
an engine read them as the one series they are. This is that engine, as an
advice card beside the schedule, and every number in it is quoted from
«Polio vaccines: WHO position paper – June 2022» (WER 97(25):277–300), read
from WHO's repository — the first test pins them to it.

What is held:

* the birth dose is said and not counted toward the primary series;
* a dose too young or too soon after the last is shown, and not counted;
* IPV given inside a hexavalent counts as IPV;
* a late starter's first IPV is at the first contact;
* no upper age: a six-year-old missing polio is missing it;
* where the clinic's schedule asks for fewer IPV doses than the paper, it is
  said — and no date on the schedule is changed.
"""
import os
import sys
from datetime import timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

from app.utils.clock import local_today  # noqa: E402


def test_the_numbers_are_the_papers():
    from app.utils import polio_series as ps

    assert ps.SOURCE["url"] == "https://iris.who.int/handle/10665/357168"
    assert "97(25):277" in ps.SOURCE["citation"]
    # «3 doses of bOPV and 2 doses of IPV»
    assert (ps.OPV_PRIMARY, ps.IPV_DOSES) == (3, 2)
    # «at birth, or within the first week of life»
    assert ps.ZERO_DOSE_DAYS == 7
    # «minimum age of 6 weeks, with at least a 4 week interval»
    assert (ps.OPV_MIN_AGE_DAYS, ps.OPV_MIN_GAP_DAYS) == (42, 28)
    # «from a minimum of 14 weeks … the second … at least 4 months later»
    assert (ps.IPV1_PREFERRED_AGE_DAYS, ps.IPV2_PREFERRED_GAP_MONTHS) == (98, 4)
    # «age >3 months»
    assert ps.LATE_START_MONTHS == 3


@pytest.fixture()
def seeded(clinic):
    from app.extensions import db
    from app.utils.vaccines import seed_vaccine_schedules, seed_vaccines

    with clinic["app"].app_context():
        seed_vaccines()
        seed_vaccine_schedules()
        db.session.commit()
    return clinic


def _child(c, days_old):
    from app.extensions import db
    from app.models import Patient

    with c["app"].app_context():
        row = Patient(patient_number=f"PS{days_old}", full_name="طفل",
                      gender="male", is_active=True,
                      date_of_birth=local_today() - timedelta(days=days_old))
        db.session.add(row)
        db.session.commit()
        return row.id


def _give(c, patient_id, code, days_after_birth, number, brand_name=None):
    from app.extensions import db
    from app.models import Patient, PatientVaccine, Vaccine

    with c["app"].app_context():
        kid = db.session.get(Patient, patient_id)
        vaccine = Vaccine.query.filter_by(code=code).first()
        brand = next((b for b in vaccine.brands
                      if brand_name is None or brand_name in (b.name_en or b.name)),
                     vaccine.brands[0])
        db.session.add(PatientVaccine(
            patient_id=kid.id, vaccine_id=vaccine.id, brand_id=brand.id,
            dose_number=number, event_type="given",
            given_date=kid.date_of_birth + timedelta(days=days_after_birth)))
        db.session.commit()


def _status(c, patient_id):
    from app.extensions import db
    from app.models import Patient
    from app.utils import polio_series

    with c["app"].app_context():
        got = polio_series.status(db.session.get(Patient, patient_id))
        return {"zero": len(got["zero"]), "opv": len(got["opv"]),
                "ipv": len(got["ipv"]), "complete": got["complete"],
                "missing": got["missing"],
                "next": [(n["kind"], n["earliest"], n.get("why"))
                         for n in got["next"]],
                "skipped": [(why, kind) for _r, why, kind in got["not_counted"]],
                "fewer_ipv": got["fewer_ipv"], "clinic_ipv": got["clinic_ipv"]}


def test_the_egyptian_infant_doses_read_as_one_series(seeded):
    kid = _child(seeded, 2 * 365)
    for n, day in enumerate((2, 61, 122, 183), start=1):
        _give(seeded, kid, "OPV", day, n)
    _give(seeded, kid, "IPV", 122, 1)
    got = _status(seeded, kid)
    # The birth dose is said, and not counted toward the three.
    assert (got["zero"], got["opv"], got["ipv"]) == (1, 3, 1)
    assert got["complete"] is False and got["missing"] == {"opv": 0, "ipv": 1}
    [(kind, earliest, why)] = got["next"]
    assert (kind, why) == ("ipv", "preferred_second")
    assert earliest == local_today()      # four months have long passed
    # The clinic's schedule asks for one IPV; the paper for two.
    assert (got["clinic_ipv"], got["fewer_ipv"]) == (1, True)


def test_ipv_inside_a_hexavalent_counts_as_ipv(seeded):
    kid = _child(seeded, 2 * 365)
    for n, day in enumerate((2, 61, 122, 183), start=1):
        _give(seeded, kid, "OPV", day, n)
    for n, day in enumerate((61, 122, 183), start=1):
        _give(seeded, kid, "HEXA", day, n, brand_name="Hexaxim")
    got = _status(seeded, kid)
    assert (got["opv"], got["ipv"], got["complete"]) == (3, 3, True)
    assert got["next"] == []


def test_a_dose_too_soon_is_shown_and_not_counted(seeded):
    kid = _child(seeded, 300)
    _give(seeded, kid, "OPV", 61, 1)
    _give(seeded, kid, "OPV", 71, 2)          # ten days later
    _give(seeded, kid, "OPV", 20, 3)          # before six weeks, after the first week
    got = _status(seeded, kid)
    assert got["opv"] == 1
    assert sorted(got["skipped"]) == [("too_soon", "opv"),
                                      ("too_young", "opv")]


def test_a_late_starter_gets_ipv_at_the_first_contact(seeded):
    kid = _child(seeded, 8 * 30)
    got = _status(seeded, kid)
    nxt = {kind: (earliest, why) for kind, earliest, why in got["next"]}
    assert nxt["ipv"] == (local_today(), "late_start")
    assert nxt["opv"][0] == local_today()


def test_no_upper_age_a_six_year_old_is_still_missing_it(seeded):
    kid = _child(seeded, 6 * 365)
    got = _status(seeded, kid)
    assert got["complete"] is False
    assert got["missing"] == {"opv": 3, "ipv": 2}
    assert {kind for kind, _e, _w in got["next"]} == {"opv", "ipv"}


def test_the_card_is_on_the_vaccination_screen_and_changes_no_date(seeded):
    from app.extensions import db
    from app.models import Patient
    from app.utils.vaccines import patient_plan

    kid = _child(seeded, 2 * 365)
    _give(seeded, kid, "OPV", 2, 1)

    def opv_dates():
        with seeded["app"].app_context():
            plan = patient_plan(db.session.get(Patient, kid))
            item = next(i for i in plan if i["vaccine"].code == "OPV")
            return [(d["dose_number"], d["due_date"], d["status"])
                    for d in item["doses"]]

    before = opv_dates()
    page = seeded["sign_in"]("boss").get(f"/vaccinations/{kid}") \
        .get_data(as_text=True)
    assert 'data-polio-series="open"' in page
    assert "https://iris.who.int/handle/10665/357168" in page
    assert "data-polio-fewer-ipv" in page
    assert opv_dates() == before
