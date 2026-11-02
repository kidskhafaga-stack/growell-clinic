"""Rabies is a course the doctor opens on a protocol, dated from day 0.

Asked: *«تطعيم داء الكلب ده مش المفروض بيتاخد لو حالة طلبته بجدول معين مش
جرعة واحدة»* — and decided: *«اكتب الاثنين والطبيب يحدد»*. It was one dose at
birth: the first needle "finished" the course and nothing was ever reminded.

* not suggested by age, and nothing owed until a course is opened;
* the protocols side by side (WHO 4, Egyptian 5, vaccinated before 2,
  pre-exposure 2) — the doctor chooses, the count never comes from the age;
* every dose dated from day 0, and day 0 is the first dose's real date;
* the child's file, the reminder, the clinic-wide sweep and the message
  after a dose all give the same next date;
* the immunoglobulin question stays on the card until a person answers it;
* a second bite years later is a new course, numbered after the first.
"""
from datetime import timedelta

import pytest

from app.utils.clock import local_today


@pytest.fixture()
def rabies(clinic):
    from app.models import Vaccine
    from app.utils import vaccines as V

    with clinic["app"].app_context():
        V.seed_vaccines()
        V.seed_vaccine_schedules()
        v = Vaccine.query.filter_by(code="RABIES").one()
        clinic["ids"]["rabies"] = v.id
        clinic["ids"]["verorab"] = next(b.id for b in v.brands if b.name == "Verorab")
        clinic["db"].session.commit()
    return clinic


def _plan_row(fx):
    from app.models import Patient
    from app.utils import vaccines as V

    kid = fx["db"].session.get(Patient, fx["ids"]["child"])
    return next(p for p in V.patient_plan(kid) if p["vaccine"].code == "RABIES")


def _start(fx, protocol, days_ago=0, **extra):
    from app.models import Patient, Vaccine
    from app.utils import vaccine_protocols as VP

    with fx["app"].app_context():
        kid = fx["db"].session.get(Patient, fx["ids"]["child"])
        v = fx["db"].session.get(Vaccine, fx["ids"]["rabies"])
        c = VP.start(kid, v, {"protocol": protocol,
                              "start_date": (local_today() - timedelta(days=days_ago)).isoformat(),
                              **extra}, None)
        fx["db"].session.commit()
        return c.id


def test_not_by_age_and_nothing_owed_without_a_course(rabies):
    from app.models import Patient
    from app.utils import vaccines as V

    with rabies["app"].app_context():
        row = _plan_row(rabies)
        assert not row["committed"] and row["day_course"] is None
        kid = rabies["db"].session.get(Patient, rabies["ids"]["child"])
        assert not any(r["vaccine"].code == "RABIES" for r in V.patient_due_reminders(kid))


@pytest.mark.parametrize("key,days", [("pep_who4", [0, 3, 7, 14]),
                                      ("pep_eg5", [0, 3, 7, 14, 28]),
                                      ("pep_previous", [0, 3]),
                                      ("prep_who", [0, 7])])
def test_each_protocol_dates_its_doses_from_day_0(rabies, key, days):
    _start(rabies, key, days_ago=0)
    with rabies["app"].app_context():
        row = _plan_row(rabies)
        assert row["committed"] and row["day_protocol"]["key"] == key
        today = local_today()
        assert [d["due_date"] for d in row["doses"]] == \
            [(today + timedelta(days=n)).isoformat() for n in days]
        assert [d["course_day"] for d in row["doses"]] == days
        # Due on its day (and the day before), not thirty days ahead.
        assert [d["status"] for d in row["doses"]] == ["due"] + ["upcoming"] * (len(days) - 1) \
            if days[1] > 1 else True


def test_day_0_moves_to_the_real_first_dose_and_everything_agrees(rabies):
    from app.models import Patient, Vaccine, VaccineBrand
    from app.utils import vaccines as V
    from app.utils.dose_labels import next_dose
    from app.utils.vaccine_due import due_list

    _start(rabies, "pep_eg5", days_ago=6, previously_vaccinated="0", exposure_category="III")
    with rabies["app"].app_context():
        db = rabies["db"]
        kid = db.session.get(Patient, rabies["ids"]["child"])
        v = db.session.get(Vaccine, rabies["ids"]["rabies"])
        br = db.session.get(VaccineBrand, rabies["ids"]["verorab"])
        # Opened six days ago; nothing given yet — day 0 is owed, overdue.
        assert V.patient_due_reminders(kid)[0]["dose_number"] == 1
        # The first dose was really given five days ago: day 0 moves with it.
        first_day = local_today() - timedelta(days=5)
        pv, _ = V.administer_dose(kid, v, brand=br, given_date=first_day)
        assert pv.dose_number == 1
        db.session.commit()
        due = (first_day + timedelta(days=3)).isoformat()
        row = _plan_row(rabies)
        assert row["doses"][1]["due_date"] == due and row["doses"][1]["status"] == "overdue"
        mine = [r for r in V.patient_due_reminders(kid) if r["vaccine"].code == "RABIES"]
        swept = [r for r in due_list() if r["vaccine"].code == "RABIES"]
        assert [(r["dose_number"], r["due_date"]) for r in mine] == [(2, due)]
        assert [(r["dose_number"], r["due_date"]) for r in swept] == [(2, due)], \
            "the sweep and the file give the same date"
        nxt = next_dose(kid, v, br, 1, first_day)
        assert nxt["kind"] == "date" and nxt["number"] == 2 and nxt["date"].isoformat() == due
        # The next dose given from the vaccinations screen is the course's.
        pv2, _ = V.administer_dose(kid, v, brand=br, given_date=local_today())
        assert pv2.dose_number == 2


def test_the_immunoglobulin_question_and_the_protocol_check(rabies):
    from app.models import Vaccine
    from app.models.vaccine_course import VaccineCourse
    from app.utils import vaccine_protocols as VP

    cid = _start(rabies, "pep_previous", previously_vaccinated="0")
    with rabies["app"].app_context():
        c = rabies["db"].session.get(VaccineCourse, cid)
        v = rabies["db"].session.get(Vaccine, rabies["ids"]["rabies"])
        w = VP.warnings(c, v)
        assert "rig_assess" in w, "never vaccinated after an exposure: RIG is asked"
        assert "mismatch_previous" in w, "a 2-dose course for a child never vaccinated"
        VP.set_rig(c, "given", local_today())
        assert "rig_assess" not in VP.warnings(c, v)


def test_the_screen_starts_gives_and_stops_a_course(rabies):
    boss = rabies["sign_in"]("boss")
    pid, vid = rabies["ids"]["child"], rabies["ids"]["rabies"]
    page = boss.get(f"/vaccinations/{pid}").get_data(as_text=True)
    assert 'data-course-start' in page and 'data-protocol="pep_eg5"' in page \
        and 'data-protocol="pep_who4"' in page
    boss.post(f"/vaccinations/{pid}/course/start", data={
        "vaccine_id": vid, "protocol": "pep_who4", "previously_vaccinated": "0",
        "exposure_category": "III", "start_date": local_today().isoformat()})
    page = boss.get(f"/vaccinations/{pid}").get_data(as_text=True)
    assert 'data-course-protocol="pep_who4"' in page and 'data-course-warning="rig_assess"' in page
    assert page.count("data-course-dose=") == 4 and "data-course-give" in page
    # A second course while this one owes doses is refused.
    boss.post(f"/vaccinations/{pid}/course/start", data={"vaccine_id": vid, "protocol": "prep_who"})
    from app.models.vaccine_course import VaccineCourse

    with rabies["app"].app_context():
        assert VaccineCourse.query.count() == 1
        cid = VaccineCourse.query.one().id
    boss.post(f"/vaccinations/course/{cid}/close", data={"reason": ""})
    with rabies["app"].app_context():
        assert rabies["db"].session.get(VaccineCourse, cid).is_open, "a reason is required"
    boss.post(f"/vaccinations/course/{cid}/close", data={"reason": "الكلب فضل سليم ١٠ أيام"})
    with rabies["app"].app_context():
        c = rabies["db"].session.get(VaccineCourse, cid)
        assert not c.is_open and c.close_reason
        row = _plan_row(rabies)
        assert not row["committed"], "a stopped course is nothing owed"


def test_a_second_bite_years_later_is_a_new_course_after_the_first(rabies):
    from app.models import Patient, Vaccine, VaccineBrand
    from app.models.vaccine_course import VaccineCourse
    from app.utils import vaccines as V

    _start(rabies, "pep_previous", days_ago=800, previously_vaccinated="1")
    with rabies["app"].app_context():
        db = rabies["db"]
        kid = db.session.get(Patient, rabies["ids"]["child"])
        v = db.session.get(Vaccine, rabies["ids"]["rabies"])
        br = db.session.get(VaccineBrand, rabies["ids"]["verorab"])
        for ago in (800, 797):
            V.administer_dose(kid, v, brand=br, given_date=local_today() - timedelta(days=ago))
        db.session.commit()
    second = _start(rabies, "pep_previous", previously_vaccinated="1")
    with rabies["app"].app_context():
        assert VaccineCourse.query.filter(VaccineCourse.closed_at.isnot(None)).count() == 1, \
            "the finished course closed itself"
        assert rabies["db"].session.get(VaccineCourse, second).first_dose_number == 3
        row = _plan_row(rabies)
        assert [d["dose_number"] for d in row["doses"]] == [1, 2, 3, 4]
        assert [d.get("earlier_course", False) for d in row["doses"]] == [True, True, False, False]


def test_opened_and_given_from_the_visit_with_the_volume_said(rabies):
    """The bite is seen in the visit: the course opens there, its next dose
    is given there, and each product's dose volume is said where it is given."""
    from app.models import PatientVaccine
    from app.models.vaccine_course import VaccineCourse

    doc = rabies["sign_in"]("doc")
    vid, rid = rabies["ids"]["visit"], rabies["ids"]["rabies"]
    page = doc.get(f"/visits/{vid}/record").get_data(as_text=True)
    assert 'data-visit-course="RABIES"' in page and "data-visit-course-start" in page
    doc.post(f"/visits/{vid}/vaccine-course", data={
        "vaccine_id": rid, "protocol": "pep_who4", "previously_vaccinated": "0",
        "exposure_category": "III"})
    with rabies["app"].app_context():
        assert VaccineCourse.query.one().protocol == "pep_who4"
    page = doc.get(f"/visits/{vid}/record").get_data(as_text=True)
    assert "data-visit-course-give" in page and 'data-visit-course-warning="rig_assess"' in page
    assert "0.5 mL" in page and "1.0 mL" in page, "each product's volume"
    doc.post(f"/visits/{vid}/give-vaccine", data={
        "vaccine_id": rid, "dose_number": 1, "brand_id": rabies["ids"]["verorab"]})
    with rabies["app"].app_context():
        assert PatientVaccine.query.filter_by(vaccine_id=rid, event_type="given").count() == 1
    page = doc.get(f"/visits/{vid}/record").get_data(as_text=True)
    assert "الجرعة 2 (اليوم 3)" in page or "Dose 2 (day 3)" in page
    # And on the vaccinations page.
    boss = rabies["sign_in"]("boss")
    page = boss.get(f"/vaccinations/{rabies['ids']['child']}").get_data(as_text=True)
    assert "data-course-volumes" in page and "0.5 mL" in page
