"""A lab result that is a number, so it can be a point on a curve.

Every specialty in the specialties survey asks for the same thing in its own
words — *"تحاليل تريد رؤيتها كمنحنى"*. HbA1c for the endocrinologist, ferritin
for the haematologist, eGFR for the nephrologist, INR for the cardiologist,
drug levels for the neurologist. Twelve lists, one feature underneath them, and
not one of them was buildable: `VisitInvestigation.result_text` is Text, and
prose does not plot.

Four optional columns fix it, and the drawing half has existed for years in
the growth charts.

**Added beside the text, not instead of it.** A culture result and a radiology
report are not numbers and never will be. The value is filled where a value
exists, and a curve is drawn from the visits that have one — so this file
spends as much effort on what stays out of a chart as on what goes in.

**And nothing about a reference range is assumed.** The band comes from what
the report itself said, per result. A paediatric range moves with age and with
the assay a particular lab runs; one range held centrally and shaded on every
child's chart would be the program stating a clinical fact nobody told it,
which is the failure the vaccine tables exist to avoid.
"""
import os
import sys
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def chart(clinic):
    """A child with three HbA1c readings and one chest film."""
    from app.extensions import db
    from app.models import Patient, Visit, VisitInvestigation

    with clinic["app"].app_context():
        kid = Patient(patient_number="LAB-1", full_name="طفل التحاليل",
                      gender="male", date_of_birth=date(2018, 4, 1),
                      is_active=True)
        db.session.add(kid)
        db.session.flush()
        visit = Visit(patient_id=kid.id, doctor_id=1, visit_date=date(2026, 1, 1))
        db.session.add(visit)
        db.session.flush()

        for index, value in enumerate((8.4, 7.9, 7.1)):
            db.session.add(VisitInvestigation(
                visit_id=visit.id, patient_id=kid.id, kind="lab", name="HbA1c",
                status="resulted", result_value=value, result_unit="%",
                result_low=4.0, result_high=5.6,
                resulted_at=datetime(2026, 1, 1) + timedelta(days=90 * index)))

        # A result that is not a number and must never become a point.
        db.session.add(VisitInvestigation(
            visit_id=visit.id, patient_id=kid.id, kind="imaging",
            name="أشعة صدر", status="resulted",
            result_text="طبيعية، لا ارتشاح",
            resulted_at=datetime(2026, 2, 1)))
        db.session.commit()
        clinic["kid_id"] = kid.id
        clinic["visit_id"] = visit.id
    return clinic


def _series(chart):
    from app.utils import lab_series

    with chart["app"].app_context():
        return lab_series.series_for(chart["kid_id"])


# ------------------------------------------------------------- it draws a line

def test_three_readings_of_one_test_are_one_curve(chart):
    series = _series(chart)

    assert len(series) == 1, f"not one curve: {[s['name'] for s in series]}"
    assert series[0]["name"] == "HbA1c"
    assert series[0]["unit"] == "%"
    assert [p["value"] for p in series[0]["points"]] == [8.4, 7.9, 7.1], \
        "the points are not in the order they were taken"


def test_the_chest_film_is_not_a_point_on_anything(chart):
    """The reason the number sits beside the text instead of replacing it.

    A radiology report is a result and is not a measurement. A design that
    made every result numeric would either lose the report or invent a number
    for it.
    """
    series = _series(chart)

    assert not [s for s in series if "أشعة" in s["name"]], \
        "an imaging report was put on a chart"


def test_one_reading_is_not_a_trend(chart):
    """A chart of a single point invites a line to be drawn through it, and
    there is nothing there to draw. It still counts as a *value*, which is the
    next test."""
    from app.extensions import db
    from app.models import VisitInvestigation
    from app.utils import lab_series

    with chart["app"].app_context():
        db.session.add(VisitInvestigation(
            visit_id=chart["visit_id"], patient_id=chart["kid_id"], kind="lab",
            name="فيريتين", status="resulted", result_value=44.0,
            result_unit="ng/mL", resulted_at=datetime(2026, 3, 1)))
        db.session.commit()

        curves = {s["name"] for s in lab_series.series_for(chart["kid_id"])}
        latest = {row["name"] for row in
                  lab_series.latest_values(chart["kid_id"])}

    assert "فيريتين" not in curves, "one reading was drawn as a curve"
    assert "فيريتين" in latest, \
        "one reading is still the answer to \"what is his ferritin?\""


def test_two_units_are_two_curves_and_not_one_line_with_a_jump(chart):
    """No silent conversion. Ferritin in ng/mL and in µg/L happen to be the
    same number, and plenty of pairs are not — an unmarked conversion is how a
    chart tells a confident lie, so the unit is part of what makes two results
    the same test."""
    from app.extensions import db
    from app.models import VisitInvestigation
    from app.utils import lab_series

    with chart["app"].app_context():
        for unit, value in (("mg/L", 30.0), ("mg/L", 34.0),
                            ("mg/dL", 3.0), ("mg/dL", 3.4)):
            db.session.add(VisitInvestigation(
                visit_id=chart["visit_id"], patient_id=chart["kid_id"],
                kind="lab", name="CRP", status="resulted",
                result_value=value, result_unit=unit,
                resulted_at=datetime(2026, 4, 1)))
        db.session.commit()
        crp = [s for s in lab_series.series_for(chart["kid_id"])
               if s["name"] == "CRP"]

    assert len(crp) == 2, f"units were merged into one line: {crp}"
    assert {s["unit"] for s in crp} == {"mg/L", "mg/dL"}


# --------------------------------------------------- the range is the report's

def test_a_result_with_no_stated_range_is_not_called_normal(chart):
    """Three answers, not two. "The report gave no range" is a different
    thing from "in range", and a screen that showed the second for the first
    would be reassuring on no evidence."""
    from app.extensions import db
    from app.models import VisitInvestigation

    with chart["app"].app_context():
        row = VisitInvestigation(
            visit_id=chart["visit_id"], patient_id=chart["kid_id"], kind="lab",
            name="IgE", status="resulted", result_value=180.0)
        db.session.add(row)
        db.session.commit()

        assert row.out_of_range is None, \
            "a value with no reference range was judged anyway"


def test_out_of_range_reads_the_range_the_report_gave(chart):
    series = _series(chart)

    assert all(p["out_of_range"] for p in series[0]["points"]), \
        "an HbA1c of 8.4 against a range of 4.0–5.6 is not inside it"


def test_nothing_defaults_a_reference_range(chart):
    """The guard on the one decision that could quietly become a clinical
    claim. The catalogue may hold a *unit* — that is a fact about the
    measurement — and must not hold a range, which moves with age and lab."""
    from app.models import Investigation

    columns = set(Investigation.__table__.columns.keys())

    assert "unit" in columns
    for forbidden in ("ref_low", "ref_high", "normal_low", "normal_high"):
        assert forbidden not in columns, \
            (f"the catalogue grew {forbidden} — one range shown for every "
             f"child is the program inventing a clinical number")


# ------------------------------------------------------------- entering it

def test_the_form_saves_the_number(chart):
    from app.extensions import db
    from app.models import VisitInvestigation

    with chart["app"].app_context():
        row = VisitInvestigation(
            visit_id=chart["visit_id"], patient_id=chart["kid_id"], kind="lab",
            name="TSH", status="requested")
        db.session.add(row)
        db.session.commit()
        row_id = row.id

    chart["sign_in"]("boss").post(
        f"/visits/investigations/{row_id}/result",
        data={"result_value": "3.4", "result_unit": "mIU/L",
              "result_low": "0.5", "result_high": "4.2",
              "result_comment": "ضمن المدى"})

    with chart["app"].app_context():
        row = db.session.get(VisitInvestigation, row_id)
        assert row.result_value == 3.4
        assert row.result_unit == "mIU/L"
        assert (row.result_low, row.result_high) == (0.5, 4.2)
        assert row.out_of_range is False
        assert row.status == "resulted", \
            "a number alone did not count as having a result"


def test_a_value_that_is_not_a_number_is_not_stored_as_zero(chart):
    """A doctor who types "7.2 %" into the value box has said something true,
    and the program does not have to guess which half is the number — the text
    box beside it holds exactly that sentence. What it must not do is store
    zero, which is a reading, and a wrong one."""
    from app.extensions import db
    from app.models import VisitInvestigation

    with chart["app"].app_context():
        row = VisitInvestigation(
            visit_id=chart["visit_id"], patient_id=chart["kid_id"], kind="lab",
            name="Culture", status="requested")
        db.session.add(row)
        db.session.commit()
        row_id = row.id

    chart["sign_in"]("boss").post(
        f"/visits/investigations/{row_id}/result",
        data={"result_value": "no growth", "result_text": "لا يوجد نمو"})

    with chart["app"].app_context():
        row = db.session.get(VisitInvestigation, row_id)
        assert row.result_value is None, \
            f"prose was stored as the number {row.result_value}"
        assert row.result_text == "لا يوجد نمو", "the result itself was lost"


def test_clearing_the_value_clears_the_range_with_it(chart):
    """A band with nothing to compare it to is shading on an empty chart, and
    a range left behind from a previous report is worse: it would be applied
    to whatever number is entered next."""
    from app.extensions import db
    from app.models import VisitInvestigation

    with chart["app"].app_context():
        row = VisitInvestigation(
            visit_id=chart["visit_id"], patient_id=chart["kid_id"], kind="lab",
            name="Na", status="resulted", result_value=138.0,
            result_low=135.0, result_high=145.0)
        db.session.add(row)
        db.session.commit()
        row_id = row.id

    chart["sign_in"]("boss").post(
        f"/visits/investigations/{row_id}/result",
        data={"result_value": "", "result_low": "135", "result_high": "145",
              "result_text": "العينة اتكسرت"})

    with chart["app"].app_context():
        row = db.session.get(VisitInvestigation, row_id)
        assert row.result_value is None
        assert (row.result_low, row.result_high) == (None, None), \
            "a reference range outlived the value it belonged to"


# --------------------------------------------------------------- on the screen

def test_the_curve_reaches_the_patients_file(chart):
    body = (chart["sign_in"]("boss").get(f"/patients/{chart['kid_id']}")
            .get_data(as_text=True))

    assert "HbA1c" in body, "the test is not named on the file"
    assert "<polyline" in body, "there are three readings and no line drawn"


def test_the_chart_is_drawn_without_reaching_the_internet(chart):
    """Inline SVG rather than a charting library. This runs on a clinic PC
    that is often offline, and the growth charts made the same choice for the
    same reason."""
    with open("app/templates/patients/_lab_curves.html", encoding="utf-8") as fh:
        template = fh.read()

    for offsite in ("https://", "http://", "cdn.", "unpkg", "jsdelivr"):
        assert offsite not in template, \
            f"the chart reaches {offsite} — it will be blank in a clinic offline"


# ------------------------------------------------------- and it reaches clinics

def test_a_clinic_that_upgrades_gets_the_columns(chart):
    """Four columns added by a migration, and a migration that adds a column
    should be the thing that adds it everywhere — `max_age_final_dose_days`
    once shipped empty and rotavirus went a release with no ceiling."""
    from sqlalchemy import text

    from app.extensions import db
    from app.utils.schema import ADDITIONS, apply_schema

    listed = {(t, c) for t, c, _d in ADDITIONS}
    for column in ("result_value", "result_unit", "result_low", "result_high"):
        assert ("visit_investigations", column) in listed, \
            f"visit_investigations.{column} is not on the upgrade list"
    assert ("investigations", "unit") in listed

    with chart["app"].app_context():
        db.session.execute(text(
            "ALTER TABLE visit_investigations DROP COLUMN result_value"))
        db.session.commit()
        apply_schema(report=None)
        db.session.commit()
        columns = [row[1] for row in db.session.execute(
            text("PRAGMA table_info(visit_investigations)"))]

    assert "result_value" in columns, "upgrade-db does not restore the column"
