"""The customer-service board: for a period, per unit, and fair to small numbers.

Asked as: *«محتاجين داش بورد للاستبيانات عام ولكل قسم وللشكاوى كل ده في
خدمة العملاء»* — built from the prototype the owner approved, in place of the
old satisfaction page, which counted from the first survey ever sent,
clinic-wide, with no dates, no units, no money question and no complaints.

What is held here:

* a period is two dates, 90 days when none are given, and it is compared with
  the same length just before it;
* a visit survey belongs to the outpatient clinics; a stay's survey to its
  unit; filtering by a unit counts only that unit;
* a unit with too few answers is not coloured and a doctor with too few has
  no average — two families are not a verdict;
* the "what bothered you" taps and the reasons for leaving against advice are
  counted, and a reason nobody wrote down is counted as that, not dropped;
* the complaints tab is for whoever handles complaints; the families behind
  every number can be listed and exported.
"""
import os
import sys
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

from tests.test_a_bed_bill_the_books_never_heard_of import (  # noqa: E402,F401
    _admit, _child, hospital)


def _survey(clinic, days_ago=3, centre_key=None, doctor=None, med=5, svc=5,
            fin=5, nps=9, concerns=None, submitted=True, comment=None,
            patient_id=None):
    from app.models import Feedback
    from app.utils import cost_centres

    with clinic["app"].app_context():
        at = datetime.utcnow() - timedelta(days=days_ago)
        fb = Feedback(patient_id=patient_id or clinic["ids"]["child"],
                      token=Feedback.new_token(), created_at=at,
                      cost_centre_id=(cost_centres.centre_id(centre_key)
                                      if centre_key else None),
                      doctor_id=doctor,
                      status="submitted" if submitted else "sent",
                      submitted_at=at + timedelta(hours=2) if submitted else None,
                      doctor_rating=med if submitted else None,
                      service_rating=svc if submitted else None,
                      finance_rating=fin if submitted else None,
                      nps=nps if submitted else None, concerns=concerns,
                      comment=comment)
        clinic["db"].session.add(fb)
        clinic["db"].session.commit()
        return fb.id


def _period(days=30):
    from app.utils.cs_board import period
    today = date.today()
    return period((today - timedelta(days=days - 1)).isoformat(), today.isoformat())


def test_a_period_is_two_dates_and_the_one_before_it(clinic):
    from app.utils.clock import to_utc
    from app.utils.cs_board import dates, period, previous

    with clinic["app"].app_context():
        start, end = period("2026-03-01", "2026-03-31")
        # The clinic's midnights, stored as UTC like the rows they bound.
        assert (start, end) == (to_utc(datetime(2026, 3, 1)), to_utc(datetime(2026, 4, 1)))
        assert dates(start, end) == (date(2026, 3, 1), date(2026, 3, 31))
        assert dates(*previous(start, end)) == (date(2026, 1, 29), date(2026, 2, 28))
        assert period("2026-03-31", "2026-03-01") == (start, end)      # swapped
        start, end = period("nonsense", None, today=date(2026, 9, 28))
        assert (end - start).days == 90


def test_the_figures_and_how_they_moved(clinic):
    from app.utils import cs_board

    for med, fin in ((5, 2), (4, 3)):
        _survey(clinic, days_ago=3, med=med, fin=fin)
    _survey(clinic, days_ago=4, submitted=False)
    _survey(clinic, days_ago=40, med=3, fin=4)              # the period before
    with clinic["app"].app_context():
        o = cs_board.overview(*_period(30))
    assert (o["sent"], o["answered"], o["rate"]) == (3, 2, 67)
    assert (o["medical"], o["finance"]) == (4.5, 2.5)
    assert o["delta"]["medical"] == 1.5 and o["delta"]["finance"] == -1.5


def test_a_visit_survey_is_the_outpatient_clinics_and_a_unit_filter_counts_only_it(hospital):
    from app.utils import cost_centres, cs_board
    from app.models.place import Unit

    _survey(hospital, days_ago=2)                                   # a visit
    with hospital["app"].app_context():
        unit = Unit.query.one()
        ward = cost_centres.for_unit(unit)
        hospital["db"].session.commit()
        ward_id, key = ward.id, ward.key
    _survey(hospital, days_ago=2, centre_key=key, fin=1)
    with hospital["app"].app_context():
        start, end = _period(30)
        assert cs_board.overview(start, end, ward_id)["answered"] == 1
        out = cost_centres.centre_id("outpatient")
        assert cs_board.overview(start, end, out)["answered"] == 1
        rows = {r["centre"].key: r for r in cs_board.by_centre(start, end)}
    assert rows["outpatient"]["answered"] == 1 and rows[key]["finance"] == 1.0


def test_too_few_answers_are_not_judged(clinic):
    from app.utils import cs_board

    doc = clinic["ids"]["doctor"]
    for _ in range(4):
        _survey(clinic, doctor=doc, med=1)
    with clinic["app"].app_context():
        start, end = _period(30)
        (row,) = [r for r in cs_board.by_centre(start, end)]
        (d,) = cs_board.by_doctor(start, end)
    assert row["judged"] is False and cs_board.colour(row["medical"], row["judged"]) == "none"
    assert d["judged"] is False and d["medical"] is None and d["low"] == 4
    page = clinic["sign_in"]("boss").get("/messages/satisfaction?tab=units").get_data(as_text=True)
    assert 'data-judged="0"' in page
    _survey(clinic, doctor=doc, med=2)
    with clinic["app"].app_context():
        (d,) = cs_board.by_doctor(*_period(30))
    assert d["judged"] is True and d["medical"] == 1.2
    assert d["low"] == 5                           # two stars is low too
    # The colours, on the stars' own scale.
    assert [cs_board.colour(v) for v in (4.3, 4.2, 3.6, 3.5, None)] == [
        "good", "fair", "fair", "poor", "none"]


def test_what_bothered_them_is_counted(clinic):
    from app.utils import cs_board

    _survey(clinic, concerns="finance:price,doctor:explain")
    _survey(clinic, concerns="finance:price")
    with clinic["app"].app_context():
        got = cs_board.concerns(*_period(30))
    assert got[0] == ("finance", "finance", "price", 2)
    assert ("medical", "doctor", "explain", 1) in got


def test_leaving_against_advice_is_counted_with_its_reason_or_its_absence(hospital):
    from app.utils import cs_board

    for name, outcome, reason in (("أ", "self_discharge", "price"),
                                  ("ب", "self_discharge", "made_up"),
                                  ("ج", "home", ""), ("د", "transferred", "")):
        stay = _admit(hospital, _child(hospital, name))
        hospital["sign_in"]("boss").post(
            f"/beds/admission/{stay}/discharge",
            data={"outcome": outcome, "leave_reason": reason})
    with hospital["app"].app_context():
        got = dict(cs_board.leave_reasons(*_period(30)))
    assert got == {"price": 1, None: 1}


def test_the_complaints_tab_is_for_whoever_handles_them(clinic):
    from app.utils import complaint_cases

    with clinic["app"].app_context():
        complaint_cases.open_case("انتظار طويل", notify=False)
        clinic["db"].session.commit()
    desk = clinic["sign_in"]("desk").get(
        "/messages/satisfaction?tab=complaints").get_data(as_text=True)
    assert "data-open-complaints" not in desk and "data-tab-complaints" not in desk
    boss = clinic["sign_in"]("boss").get(
        "/messages/satisfaction?tab=complaints").get_data(as_text=True)
    assert "data-open-complaints" in boss and "C-" in boss


def test_every_tab_draws(clinic):
    _survey(clinic, concerns="service:waiting", comment="استنينا كتير", svc=2)
    boss = clinic["sign_in"]("boss")
    for tab in ("all", "units", "complaints"):
        assert boss.get(f"/messages/satisfaction?tab={tab}").status_code == 200
    page = boss.get("/messages/satisfaction").get_data(as_text=True)
    assert "data-board-kpis" in page and "استنينا كتير" in page and "data-trend" in page


def test_the_families_behind_a_number_and_the_export(clinic):
    _survey(clinic, fin=1, comment="الفاتورة غالية")
    _survey(clinic, fin=5, comment="كله تمام")
    boss = clinic["sign_in"]("boss")
    page = boss.get("/messages/satisfaction/answers?side=finance&low=1").get_data(as_text=True)
    assert "الفاتورة غالية" in page and "كله تمام" not in page
    csv = boss.get("/messages/satisfaction/answers?format=csv").get_data(as_text=True)
    assert csv.startswith("﻿") and "الفاتورة غالية" in csv and "كله تمام" in csv
