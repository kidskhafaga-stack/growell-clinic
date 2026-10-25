"""The hospital's indicators (HOSPITAL_PLAN.md ٥‑د, REPORTS_PLAN.md ت-٦).

*«زود ده فى البلان بتاع المستشفى علشان ما يخشش على الى عنده البرنامج شغال على
مستوى العيادة بس»*: every section here exists only with its department switched
on, and a clinic that runs none of them has no page, no tab and no card.
"""
import os
import sys
from datetime import datetime, time, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

from app.utils.clock import local_today  # noqa: E402

NOW = datetime.utcnow


def _modules(fx, **on):
    from app.models import Setting

    with fx["app"].app_context():
        for name, value in on.items():
            Setting.set(f"mod_enabled:{name}", "1" if value else "0")
        fx["db"].session.commit()


@pytest.fixture()
def hospital(clinic):
    """A ward and an intensive care unit with two beds each, and a theatre."""
    from app.models.place import Bed, Space, Unit
    from app.models.theatre import Theatre

    _modules(clinic, beds=True, ward=True, icu=True, emergency=True, theatres=True)
    db = clinic["db"]
    with clinic["app"].app_context():
        beds = {}
        for kind, name in (("ward", "الداخلي"), ("icu", "العناية")):
            unit = Unit(name=name, kind=kind)
            db.session.add(unit)
            db.session.flush()
            space = Space(unit_id=unit.id, name=f"غرفة {kind}", kind="room")
            db.session.add(space)
            db.session.flush()
            for n in range(2):
                bed = Bed(space_id=space.id, name=f"{kind}{n}", sort_order=n)
                db.session.add(bed)
                db.session.flush()
                beds[f"{kind}{n}"] = bed.id
        theatre = Theatre(name="عمليات ١")
        db.session.add(theatre)
        db.session.commit()
        clinic["beds"] = beds
        clinic["theatre"] = theatre.id
    return clinic


def _kid(fx, name):
    from app.models import Patient

    with fx["app"].app_context():
        kid = Patient(patient_number=f"H{name}", full_name=name, gender="male",
                      is_active=True, date_of_birth=local_today() - timedelta(days=800))
        fx["db"].session.add(kid)
        fx["db"].session.commit()
        return kid.id


def _stay(fx, patient_id, beds):
    """One admission through ``beds``: ``[(bed, hours_ago_from, hours_ago_to|None)]``."""
    from app.models import Admission, BedStay

    db = fx["db"]
    with fx["app"].app_context():
        adm = Admission(patient_id=patient_id, admitted_at=NOW() - timedelta(hours=beds[0][1]))
        db.session.add(adm)
        db.session.flush()
        for bed, since, until in beds:
            db.session.add(BedStay(admission_id=adm.id, bed_id=fx["beds"][bed],
                                   since=NOW() - timedelta(hours=since),
                                   until=NOW() - timedelta(hours=until) if until is not None else None))
        db.session.commit()
        return adm.id


def _board(fx, days=30):
    from app.utils import hospital_kpis

    with fx["app"].app_context():
        today = local_today()
        return hospital_kpis.board(today - timedelta(days=days - 1), today)


# --------------------------------------------------- a clinic sees nothing --
def test_a_clinic_with_no_hospital_department_has_no_page_tab_or_card(clinic):
    boss = clinic["sign_in"]()
    assert boss.get("/reports/hospital").status_code == 404
    assert 'data-rep="reports.hospital_board"' not in boss.get("/reports/").get_data(as_text=True)
    assert "/reports/hospital" not in boss.get("/reports/medical").get_data(as_text=True)


def test_each_section_comes_with_its_department(hospital):
    boss = hospital["sign_in"]()
    page = boss.get("/reports/hospital?preset=30").get_data(as_text=True)
    for section in ("emergency", "theatres", "critical", "safety"):
        assert f'data-kpi-section="{section}"' in page, section
    assert 'data-rep="reports.hospital_board"' in boss.get("/reports/").get_data(as_text=True)
    assert "/reports/hospital" in boss.get("/reports/medical").get_data(as_text=True)
    _modules(hospital, theatres=False, emergency=False)
    page = boss.get("/reports/hospital?preset=30").get_data(as_text=True)
    assert 'data-kpi-section="theatres"' not in page
    assert 'data-kpi-section="emergency"' not in page
    assert 'data-kpi-section="safety"' in page


# -------------------------------------------------------------- emergency --
def test_the_emergencys_times_and_who_came_back(hospital):
    from app.models.emergency_visit import EmergencyVisit

    a, b = _kid(hospital, "أ"), _kid(hospital, "ب")
    db = hospital["db"]
    with hospital["app"].app_context():
        t0 = NOW() - timedelta(days=3)
        rows = [
            # a: triaged after 10, seen after 30, out after 60.
            EmergencyVisit(patient_id=a, arrived_at=t0, triaged_at=t0 + timedelta(minutes=10),
                           seen_at=t0 + timedelta(minutes=30), departed_at=t0 + timedelta(minutes=60),
                           disposition="home"),
            # a again, 24 hours after leaving: back within 72 hours.
            EmergencyVisit(patient_id=a, arrived_at=t0 + timedelta(hours=25),
                           triaged_at=t0 + timedelta(hours=25, minutes=20),
                           departed_at=t0 + timedelta(hours=27), disposition="home"),
            # b: never triaged, left unseen.
            EmergencyVisit(patient_id=b, arrived_at=t0, disposition="left_unseen",
                           departed_at=t0 + timedelta(minutes=45)),
        ]
        db.session.add_all(rows)
        db.session.commit()
    e = _board(hospital)["emergency"]
    assert e["total"] == 3
    assert (e["triage_median"], e["triaged"]) == (15.0, 2)
    assert (e["doctor_median"], e["seen"]) == (30.0, 1)
    assert e["stay_median"] == 60.0 and e["left"] == 3
    assert (e["unseen"], e["unseen_pct"]) == (1, 33.3)
    assert (e["back"], e["back_pct"]) == (1, 33.3)


def test_the_doctor_saw_the_child_once_by_button_or_first_order(hospital):
    from app.models.emergency_visit import EmergencyVisit

    kid = _kid(hospital, "ج")
    with hospital["app"].app_context():
        row = EmergencyVisit(patient_id=kid, arrived_at=NOW() - timedelta(minutes=40))
        hospital["db"].session.add(row)
        hospital["db"].session.commit()
        rid = row.id
    boss = hospital["sign_in"]()
    page = boss.get(f"/emergency/attendance/{rid}").get_data(as_text=True)
    assert "data-seen-form" in page
    boss.post(f"/emergency/attendance/{rid}/seen")
    with hospital["app"].app_context():
        first = hospital["db"].session.get(EmergencyVisit, rid).seen_at
    assert first is not None
    boss.post(f"/emergency/attendance/{rid}/seen")
    with hospital["app"].app_context():
        row = hospital["db"].session.get(EmergencyVisit, rid)
        assert row.seen_at == first and 39 <= row.wait_to_doctor <= 41
    page = boss.get(f"/emergency/attendance/{rid}").get_data(as_text=True)
    assert "data-seen" in page and "data-seen-form" not in page


# --------------------------------------------------------------- theatres --
def test_the_theatres_list_used_on_time_changeover_and_cancelled(hospital):
    from app.models.theatre import Operation
    from app.utils.clock import to_utc

    kid = _kid(hospital, "د")
    day = local_today() - timedelta(days=1)

    def at(hh, mm):
        return to_utc(datetime.combine(day, time(hh, mm)))

    with hospital["app"].app_context():
        db = hospital["db"]
        common = {"patient_id": kid, "theatre_id": hospital["theatre"], "on_date": day}
        db.session.add_all([
            Operation(procedure="فتق", start_time=time(9, 0), minutes=60, status="done",
                      started_at=at(9, 10), finished_at=at(10, 0), **common),
            Operation(procedure="لوز", start_time=time(10, 30), minutes=60, status="done",
                      started_at=at(10, 20), finished_at=at(11, 30), **common),
            Operation(procedure="ختان", start_time=time(12, 0), minutes=30, status="cancelled",
                      cancel_reason="الطفل عنده سخونية", **common),
        ])
        later = Operation(procedure="زايدة", on_date=day + timedelta(days=3), minutes=60,
                          patient_id=kid, theatre_id=hospital["theatre"])
        db.session.add(later)
        db.session.flush()
        db.session.add(Operation(procedure="زايدة", start_time=time(13, 0), minutes=60,
                                 status="cancelled", postponed_to_id=later.id,
                                 cancel_reason="مفيش سرير عناية", **common))
        db.session.commit()
    o = _board(hospital)["theatres"]
    assert (o["total"], o["done"], o["cancelled"], o["postponed"]) == (4, 2, 1, 1)
    assert o["used_pct"] == 100.0 and (o["used_hours"], o["booked_hours"]) == (2.0, 2.0)
    assert (o["first_cases"], o["on_time"]) == (1, 1)
    assert o["turnover_median"] == 20.0
    assert ("الطفل عنده سخونية", 1) in o["reasons"] and ("مفيش سرير عناية", 1) in o["reasons"]


# ------------------------------------------------- back in intensive care --
def test_back_in_intensive_care_within_48_hours(hospital):
    a, b = _kid(hospital, "هـ"), _kid(hospital, "و")
    # a: ICU, out to the ward, back in ICU twelve hours later.
    _stay(hospital, a, [("icu0", 120, 72), ("ward0", 72, 60), ("icu1", 60, None)])
    # b: ICU, out to the ward, stays there.
    _stay(hospital, b, [("icu0", 200, 100), ("ward1", 100, None)])
    c = _board(hospital)["critical"]["units"]["icu"]
    assert (c["left"], c["back"], c["back_pct"]) == (2, 1, 50.0)


# ------------------------------------------------- safety per 1000 days ---
def test_falls_pressure_injuries_and_medication_errors_per_1000_bed_days(hospital):
    from app.models import Incident
    from app.models.med_error import MedicationError
    from app.models.place import Unit

    kid = _kid(hospital, "ز")
    adm = _stay(hospital, kid, [("ward0", 24 * 10, None)])     # ten days in the ward
    with hospital["app"].app_context():
        db = hospital["db"]
        ward = Unit.query.filter_by(kind="ward").one().id
        when = NOW() - timedelta(days=2)
        for n, category in enumerate(("fall", "pressure_injury", "fall")):
            db.session.add(Incident(number=f"INC-{n}", occurred_at=when, unit_id=ward,
                                    category=category, affected="patient", patient_id=kid,
                                    what_happened="—"))
        # A staff member's fall is not a child's.
        db.session.add(Incident(number="INC-9", occurred_at=when, unit_id=ward, category="fall",
                                affected="staff", what_happened="—"))
        db.session.add(MedicationError(patient_id=kid, admission_id=adm, stage="administration",
                                       outcome="C", reached_patient=True, what_happened="—",
                                       happened_at=when))
        db.session.add(MedicationError(patient_id=kid, admission_id=adm, stage="prescribing",
                                       outcome="B", reached_patient=False, what_happened="—",
                                       happened_at=when))
        db.session.commit()
    s = _board(hospital)["safety"]
    (row,) = s["rows"]
    assert row["kind"] == "ward" and 9.9 <= row["days"] <= 10.1
    assert row["fall"]["n"] == 2 and 198 <= row["fall"]["rate"] <= 202
    assert row["pressure_injury"]["n"] == 1 and row["med_error"]["n"] == 1
    assert s["whole"]["fall"]["n"] == 2
    page = hospital["sign_in"]().get("/reports/hospital?preset=30").get_data(as_text=True)
    assert 'data-safety-row="ward"' in page and "data-safety-total" in page
