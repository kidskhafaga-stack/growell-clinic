"""Rabies, made to match what the owner saw done in the other program.

Shown a report of the same feature built elsewhere (*«بص انت عاملتها فى
برنامج تانى»*), with these points this program did not have yet:

* the day-3 dose warned "too soon — the minimum interval is 28 days";
  between the doses of a course only a second dose on the same day is;
* a rabies dose could be recorded with no course and no protocol, and then
  nothing was ever reminded — the record form now asks for the protocol and
  opens the course from that dose (a dose typed in from an old card, "given
  elsewhere", may stay without one);
* the card says how far the course is ("2/4") and when it is complete, and
  a child with rabies doses on file from before is said to be most likely
  vaccinated before;
* the clinic edits its protocols (names, days, the RIG question) and adds
  its own, and a course already open keeps the days it was opened with.
"""
from datetime import timedelta

import pytest

from app.utils.clock import local_today

from tests.test_a_rabies_course_by_protocol import _start, rabies  # noqa: F401


def _record(fx, days_ago=0, user="doc", **extra):
    data = {"vaccine_id": fx["ids"]["rabies"], "brand_id": fx["ids"]["verorab"],
            "given_date": (local_today() - timedelta(days=days_ago)).isoformat()}
    data.update(extra)
    return fx["sign_in"](user).post(f"/vaccinations/{fx['ids']['child']}/record",
                                    data=data, follow_redirects=True).get_data(as_text=True)


def _given(fx):
    from app.models import PatientVaccine

    with fx["app"].app_context():
        return sorted((pv.dose_number, pv.given_date) for pv in PatientVaccine.query.filter_by(
            vaccine_id=fx["ids"]["rabies"], event_type="given").all())


def _view(fx):
    return fx["sign_in"]("doc").get(f"/vaccinations/{fx['ids']['child']}").get_data(as_text=True)


def test_day_3_is_not_too_soon_but_the_same_day_twice_is(rabies):
    _start(rabies, "pep_who4", days_ago=3)
    _record(rabies, days_ago=3)
    page = _record(rabies, days_ago=0)
    assert "28" not in page.split("flash__msg")[1][:300], "day 3 of a course is on time"
    assert [n for n, _ in _given(rabies)] == [1, 2]

    from app.models import Vaccine
    from app.utils.vaccines import interval_warning

    with rabies["app"].app_context():
        v = rabies["db"].session.get(Vaccine, rabies["ids"]["rabies"])
        assert interval_warning(rabies["ids"]["child"], v, local_today()) is not None, \
            "a second dose on the same day still warns"


def test_no_dose_without_a_protocol(rabies):
    page = _record(rabies)
    assert _given(rabies) == [], "a rabies dose is not recorded with no course"
    assert "اختار البروتوكول" in page or "choose the protocol" in page.lower()


def test_the_record_form_opens_the_course_from_its_dose(rabies):
    from app.models.vaccine_course import VaccineCourse

    page = _view(rabies)
    assert f'data-record-protocol="{rabies["ids"]["rabies"]}"' in page
    _record(rabies, days_ago=2, protocol="pep_who4", previously_vaccinated="0",
            exposure_category="III")
    with rabies["app"].app_context():
        c = VaccineCourse.query.one()
        assert c.protocol == "pep_who4" and c.exposure_category == "III"
        assert c.start_date == local_today() - timedelta(days=2), "day 0 is the dose's day"
        assert c.rig == "assess"
    assert [n for n, _ in _given(rabies)] == [1]
    page = _view(rabies)
    assert "data-course-count" in page and "1/4" in page
    assert 'data-course-warning="rig_assess"' in page


def test_history_from_an_old_card_stays_without_a_protocol(rabies):
    from app.models.vaccine_course import VaccineCourse

    _record(rabies, days_ago=4000, given_outside="1", dose_number="1")
    with rabies["app"].app_context():
        assert VaccineCourse.query.count() == 0
    assert len(_given(rabies)) == 1
    page = _view(rabies)
    assert "data-course-before" in page, "the card says the child had rabies doses before"
    # The next bite: numbered after the old dose, and "vaccinated before"
    # is offered already chosen in the record form.
    assert '<option value="1" selected>' in page
    _record(rabies, protocol="pep_previous", previously_vaccinated="1")
    with rabies["app"].app_context():
        c = VaccineCourse.query.one()
        assert c.first_dose_number == 2 and c.previously_vaccinated is True
    page = _view(rabies)
    assert "1/2" in page


def test_the_card_says_complete(rabies):
    _start(rabies, "prep_who", days_ago=7)
    _record(rabies, days_ago=7)
    page = _view(rabies)
    assert "1/2" in page
    _record(rabies, days_ago=0)
    page = _view(rabies)
    assert "الكورس اكتمل" in page or "Course complete" in page


def test_the_visit_does_not_give_it_without_a_course(rabies):
    doc = rabies["sign_in"]("doc")
    doc.post(f"/visits/{rabies['ids']['visit']}/give-vaccine", data={
        "vaccine_id": rabies["ids"]["rabies"], "dose_number": 1,
        "brand_id": rabies["ids"]["verorab"]})
    assert _given(rabies) == []


def _rows(fx):
    from app.models import Vaccine
    from app.utils import vaccine_protocols as VP

    with fx["app"].app_context():
        return VP.protocols_for(fx["db"].session.get(Vaccine, fx["ids"]["rabies"]))


def _save(fx, rows, user="boss"):
    data = {"rows": len(rows)}
    for i, r in enumerate(rows):
        for k, v in r.items():
            if v is True:
                data[f"{k}_{i}"] = "1"
            elif v not in (None, False):
                data[f"{k}_{i}"] = v if not isinstance(v, (list, tuple)) else ", ".join(map(str, v))
    return fx["sign_in"](user).post(
        f"/vaccinations/manage/vaccine/{fx['ids']['rabies']}/protocols",
        data=data, follow_redirects=True).get_data(as_text=True)


def _as_form(p):
    return {"key": p["key"], "ar": p["ar"], "en": p["en"], "kind": p["kind"],
            "previously": {True: "1", False: "0"}.get(p["previously"], ""),
            "days": p["days"], "source": p["source"], "note_ar": p["note_ar"],
            "note_en": p["note_en"], "rig": p["rig"]}


def test_the_clinic_edits_its_protocols_and_an_open_course_keeps_its_days(rabies):
    from app.models.vaccine_course import VaccineCourse

    page = rabies["sign_in"]("boss").get(
        f"/vaccinations/manage/vaccine/{rabies['ids']['rabies']}/schedules").get_data(as_text=True)
    assert "data-protocol-editor" in page and 'data-protocol-row="pep_who4"' in page

    cid = _start(rabies, "pep_who4", days_ago=0)
    rows = [_as_form(p) for p in _rows(rabies)]
    rows[0]["days"] = "0, 3, 7, 21"
    rows.append({"ar": "بروتوكول العيادة", "en": "Clinic's own", "kind": "pep",
                 "days": "0, 3, 7", "rig": False})
    _save(rabies, rows)
    protos = _rows(rabies)
    assert protos[0]["days"] == (0, 3, 7, 21)
    assert protos[-1]["ar"] == "بروتوكول العيادة" and protos[-1]["days"] == (0, 3, 7)

    from app.models import Patient
    from app.utils import vaccines as V

    with rabies["app"].app_context():
        kid = rabies["db"].session.get(Patient, rabies["ids"]["child"])
        row = next(p for p in V.patient_plan(kid) if p["vaccine"].code == "RABIES")
        assert row["day_protocol"]["days"] == (0, 3, 7, 14), \
            "the child already on the course keeps the dates the doctor gave"
        rabies["db"].session.get(VaccineCourse, cid).closed_at = local_today()
        rabies["db"].session.commit()

    _start(rabies, protos[-1]["key"], days_ago=0)
    with rabies["app"].app_context():
        kid = rabies["db"].session.get(Patient, rabies["ids"]["child"])
        row = next(p for p in V.patient_plan(kid) if p["vaccine"].code == "RABIES")
        assert row["day_protocol"]["days"] == (0, 3, 7)
        c = VaccineCourse.query.order_by(VaccineCourse.id.desc()).first()
        assert c.rig is None, "this protocol does not ask about RIG"


@pytest.mark.parametrize("days", ["3, 7", "0, 7, 3", "0, 0, 3", "0, x", "", "0, 400"])
def test_days_that_cannot_be_a_course_are_refused(rabies, days):
    rows = [_as_form(p) for p in _rows(rabies)]
    rows[0]["days"] = days
    _save(rabies, rows)
    assert _rows(rabies)[0]["days"] == (0, 3, 7, 14)


def test_reset_and_the_egyptian_source_note(rabies):
    from app.models import Vaccine
    from app.models.vaccine_course import VaccineCourse
    from app.utils import vaccine_protocols as VP

    cid = _start(rabies, "pep_eg5")
    with rabies["app"].app_context():
        c = rabies["db"].session.get(VaccineCourse, cid)
        v = rabies["db"].session.get(Vaccine, rabies["ids"]["rabies"])
        assert "confirm_source" in VP.warnings(c, v)
        c.closed_at = local_today()
        rabies["db"].session.commit()
    rows = [_as_form(p) for p in _rows(rabies)]
    rows[1]["note_ar"] = "حسب منشور الوزارة رقم ١٢ لسنة ٢٠٢٦"
    _save(rabies, rows)
    cid = _start(rabies, "pep_eg5")
    with rabies["app"].app_context():
        c = rabies["db"].session.get(VaccineCourse, cid)
        v = rabies["db"].session.get(Vaccine, rabies["ids"]["rabies"])
        assert "confirm_source" not in VP.warnings(c, v), \
            "the clinic wrote the circular it follows"
    rabies["sign_in"]("boss").post(
        f"/vaccinations/manage/vaccine/{rabies['ids']['rabies']}/protocols/reset")
    assert _rows(rabies)[1]["note_ar"].startswith("منشور عند المجلس الصحي")


def test_the_last_protocol_cannot_be_deleted(rabies):
    rows = [dict(_as_form(p), delete=True) for p in _rows(rabies)]
    _save(rabies, rows)
    assert len(_rows(rabies)) == 4
