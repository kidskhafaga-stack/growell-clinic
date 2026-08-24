"""A reading is a point in time, and the same reading is one line.

Asked directly: *"موافق بس عايز يبقى في رسم بالزيارات، ايه رايك"* — and the
opinion, argued here in tests rather than in prose:

**The x-axis is the date, not the visit number.** A child seen twice in one week
and then again a year later has three visits. Spacing those evenly draws a fall
over twelve months with the same slope as a fall over four days, and the gap
between two points is half of what a curve says. This was already wrong for the
lab curves; it is fixed for all of them together.

**The same reading is one line, even when it was typed on two screens.** EF
arrives from the echo report and from the cardiology panel. Those are not two
measurements, and drawing them as two curves puts the same child's heart on two
lines that disagree because each is missing half the points. The catalogue says
which device field means the same thing as which panel field, and the join is
data — where nothing says they are the same, they stay apart.

**And the echo is offered, never filled in.** A panel *reads* the vitals because
the nurse took them minutes ago. An echo was taken whenever it was taken, and a
three-month-old EF sitting in today's box is a number nobody measured today.
"""
import os
import sys
from datetime import date, datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def echo(clinic):
    """An echo machine with the seeded template, and a cardiologist."""
    from app.extensions import db
    from app.models import DeviceMeasurement, MedicalDevice, User, Visit

    with clinic["app"].app_context():
        device = MedicalDevice(name="إيكو", device_type="echo",
                               connection_type="manual", import_mode="manual",
                               is_active=True)
        db.session.add(device)
        db.session.flush()
        db.session.add_all([
            DeviceMeasurement(device_id=device.id, name="الكسر القذفي (EF)",
                              name_en="Ejection fraction (EF)", unit="%",
                              normal_low=55, normal_high=70),
            DeviceMeasurement(device_id=device.id, name="الصمامات",
                              name_en="Valves"),
        ])
        visit = db.session.get(Visit, clinic["ids"]["visit"])
        db.session.get(User, visit.doctor_id).specialty_panel = "cardiology"
        db.session.commit()
        clinic["device_id"] = device.id
    return clinic


def _study(app, patient_id, on, readings, device_id, visit_id=None):
    """Record an echo directly, the way the route does."""
    from app.extensions import db
    from app.models import (DeviceMeasurement, DeviceStudy, DeviceStudyValue,
                            MedicalDevice)

    with app.app_context():
        device = db.session.get(MedicalDevice, device_id)
        study = DeviceStudy(patient_id=patient_id, device_id=device.id,
                            visit_id=visit_id, study_date=on)
        for name, raw in readings.items():
            m = (DeviceMeasurement.query
                 .filter_by(device_id=device.id, name=name).one())
            try:
                number = float(raw)
            except ValueError:
                number = None
            study.values.append(DeviceStudyValue(
                measurement_id=m.id, name=m.name, unit=m.unit, value=raw,
                value_num=number, normal_low=m.normal_low,
                normal_high=m.normal_high, flag=m.flag(raw)))
        db.session.add(study)
        db.session.commit()
        return study.id


def _measure(app, patient_id, code, value, unit, when, visit_id=None):
    from app.extensions import db
    from app.models import Measurement

    with app.app_context():
        db.session.add(Measurement(patient_id=patient_id, visit_id=visit_id,
                                   code=code, panel="cardiology",
                                   value_num=value, unit=unit,
                                   recorded_at=when))
        db.session.commit()


def _curves(app, patient_id):
    """Curves keyed by name *and* unit — the same reading in two units is two
    curves, and keying on the name alone would hide exactly that."""
    from app.utils import series

    with app.app_context():
        return {(c["name"], c["unit"]): c for c in series.curves_for(patient_id)}


# ------------------------------------------- a device reading is a number now

def test_an_echo_value_is_kept_as_typed_and_as_a_number(echo):
    """Both, not one. The typed sentence is the record a report reprints; the
    number is what a curve can be drawn from."""
    from app.models import DeviceStudyValue

    sid = _study(echo["app"], echo["ids"]["child"], date(2026, 1, 5),
                 {"الكسر القذفي (EF)": "58"}, echo["device_id"])

    with echo["app"].app_context():
        row = DeviceStudyValue.query.filter_by(study_id=sid).one()
        assert row.value == "58" and row.value_num == 58.0


def test_prose_in_a_device_box_is_not_a_number(echo):
    """Half an echo report is words. "لا يوجد ارتشاح" is a true finding and not
    a value of zero — a chart drawn through it would be a chart of nothing."""
    from app.models import DeviceStudyValue

    sid = _study(echo["app"], echo["ids"]["child"], date(2026, 1, 5),
                 {"الصمامات": "لا يوجد ارتجاع"}, echo["device_id"])

    with echo["app"].app_context():
        row = DeviceStudyValue.query.filter_by(study_id=sid).one()
        assert row.value == "لا يوجد ارتجاع" and row.value_num is None


def test_the_range_it_was_judged_against_is_kept_with_it(echo):
    """Snapshotted like the name and the unit. Without it, a curve drawn next
    year would shade the band the device holds *then* — a chart quietly
    restating history against a rule that did not exist at the time."""
    from app.extensions import db
    from app.models import DeviceMeasurement, DeviceStudyValue

    sid = _study(echo["app"], echo["ids"]["child"], date(2026, 1, 5),
                 {"الكسر القذفي (EF)": "58"}, echo["device_id"])

    with echo["app"].app_context():
        m = DeviceMeasurement.query.filter_by(name="الكسر القذفي (EF)").one()
        m.normal_low, m.normal_high = 40, 80          # the clinic retunes it
        db.session.commit()

        row = DeviceStudyValue.query.filter_by(study_id=sid).one()
        assert (row.normal_low, row.normal_high) == (55.0, 70.0)


def test_no_range_is_its_own_answer_and_not_normal(echo):
    """Three-valued on purpose: most paediatric device fields state no range,
    and reading that silence as "normal" would print a verdict nobody gave."""
    from app.models import DeviceStudyValue

    sid = _study(echo["app"], echo["ids"]["child"], date(2026, 1, 5),
                 {"الكسر القذفي (EF)": "58", "الصمامات": "سليمة"},
                 echo["device_id"])

    with echo["app"].app_context():
        rows = {r.name: r for r in
                DeviceStudyValue.query.filter_by(study_id=sid).all()}
        assert rows["الكسر القذفي (EF)"].out_of_range is False
        assert rows["الصمامات"].out_of_range is None

        rows["الكسر القذفي (EF)"].flag = "low"
        assert rows["الكسر القذفي (EF)"].out_of_range is True


# --------------------------------------------------- one reading, one line

def test_the_echo_and_the_panel_draw_one_curve(echo):
    """The point of the whole change. Two screens, one heart."""
    _study(echo["app"], echo["ids"]["child"], date(2026, 1, 5),
           {"الكسر القذفي (EF)": "58"}, echo["device_id"])
    _measure(echo["app"], echo["ids"]["child"], "ef_pct", 61.0, "%",
             datetime(2026, 4, 5))

    curves = _curves(echo["app"], echo["ids"]["child"])

    assert len(curves) == 1, f"the same reading drew {len(curves)} curves"
    curve = next(iter(curves.values()))
    assert [p["value"] for p in curve["points"]] == [58.0, 61.0]
    assert curve["sources"] == ["panel", "study"], \
        "the curve does not say where its points came from"


def test_a_device_field_nothing_links_stays_its_own_curve(echo):
    """The join is declared, never guessed. A program that decided two readings
    with similar names were the same reading would eventually be wrong about a
    child, and silently."""
    from app.extensions import db
    from app.models import DeviceMeasurement

    with echo["app"].app_context():
        db.session.add(DeviceMeasurement(device_id=echo["device_id"],
                                         name="LVESD", unit="mm"))
        db.session.commit()

    for day, value in ((5, "22"), (9, "24")):
        _study(echo["app"], echo["ids"]["child"], date(2026, 1, day),
               {"LVESD": value}, echo["device_id"])
    _measure(echo["app"], echo["ids"]["child"], "lvedd_mm", 34.0, "mm",
             datetime(2026, 2, 1))
    _measure(echo["app"], echo["ids"]["child"], "lvedd_mm", 35.0, "mm",
             datetime(2026, 3, 1))

    curves = _curves(echo["app"], echo["ids"]["child"])

    assert ("LVESD", "mm") in curves, "an unlinked device field lost its own curve"
    assert len(curves) == 2, "two different readings were drawn as one"


def test_two_units_are_two_curves(echo):
    """It does not convert. An unmarked conversion is how a chart tells a
    confident lie, and the same rule the lab curves already keep."""
    _measure(echo["app"], echo["ids"]["child"], "ef_pct", 58.0, "%",
             datetime(2026, 1, 5))
    _measure(echo["app"], echo["ids"]["child"], "ef_pct", 61.0, "%",
             datetime(2026, 2, 5))
    _study(echo["app"], echo["ids"]["child"], date(2026, 3, 5),
           {"الكسر القذفي (EF)": "0.6"}, echo["device_id"])

    from app.extensions import db
    from app.models import DeviceStudyValue

    with echo["app"].app_context():           # the same field, another unit
        row = DeviceStudyValue.query.one()
        row.unit = "ratio"
        db.session.commit()
    _measure(echo["app"], echo["ids"]["child"], "ef_pct", 0.62, "ratio",
             datetime(2026, 4, 5))

    curves = _curves(echo["app"], echo["ids"]["child"])
    units = sorted(c["unit"] for c in curves.values())

    assert units == ["%", "ratio"], f"units were merged: {units}"


def test_one_reading_is_not_a_curve(echo):
    """A chart of one point is a chart inviting somebody to draw a line
    through it."""
    _measure(echo["app"], echo["ids"]["child"], "ef_pct", 58.0, "%",
             datetime(2026, 1, 5))

    assert _curves(echo["app"], echo["ids"]["child"]) == {}


# ------------------------------------------------------ time on the x-axis

def test_the_gap_between_two_points_is_the_gap_between_two_dates(echo):
    """The argument, as arithmetic.

    Three readings: two four days apart, then one a year later. Spaced by index
    the middle point sits halfway across, saying the second half of the chart
    covers as long as the first. Spaced by date it sits at the very start,
    which is where it happened.
    """
    for day, value in ((1, 58.0), (5, 55.0)):
        _measure(echo["app"], echo["ids"]["child"], "ef_pct", value, "%",
                 datetime(2026, 1, day))
    _measure(echo["app"], echo["ids"]["child"], "ef_pct", 40.0, "%",
             datetime(2027, 1, 1))

    curve = next(iter(_curves(echo["app"], echo["ids"]["child"]).values()))
    offsets = [p["offset"] for p in curve["points"]]

    assert offsets[0] == 0 and offsets[-1] == 1
    assert offsets[1] < 0.02, (
        f"the middle reading was drawn at {offsets[1]:.2f} of the way across; "
        "four days out of a year is 0.011")


def test_two_readings_on_one_day_share_one_place(echo):
    """They were taken on the same day. Nudging them apart would be the chart
    inventing an interval that nobody waited."""
    from app.utils.series import _offsets

    when = datetime(2026, 1, 5)
    points = _offsets([{"date": when}, {"date": when}])

    assert [p["offset"] for p in points] == [0.5, 0.5]


def test_a_reading_with_no_date_still_draws(echo):
    """A curve that raised on a missing timestamp would be a curve that works
    on demo data and not on a register somebody imported."""
    from app.utils.series import _offsets

    points = _offsets([{"date": None}, {"date": datetime(2026, 1, 5)},
                       {"date": None}])

    assert [p["offset"] for p in points] == [0.0, 0.5, 1.0]


def test_a_study_date_and_a_lab_timestamp_sort_together(echo):
    """A study carries a date and a lab result a timestamp. Comparing them raw
    raises, and the child who has both is the ordinary case."""
    from app.utils.series import _moment

    assert _moment(date(2026, 1, 5)) < _moment(datetime(2026, 1, 5, 9, 0))
    assert _moment(None) is None


# -------------------------------------------------- offered, never filled in

def test_the_last_echo_is_shown_beside_the_box_and_not_inside_it(echo):
    """The distinction that matters. The vitals are *read* because the nurse
    took them minutes ago; an echo was taken whenever it was taken."""
    _study(echo["app"], echo["ids"]["child"], date(2026, 1, 5),
           {"الكسر القذفي (EF)": "58"}, echo["device_id"])

    page = (echo["sign_in"]("boss")
            .get(f"/visits/{echo['ids']['visit']}/record").get_data(as_text=True))

    import re

    assert "58" in page, "the last echo reading is nowhere on the screen"

    # The box itself is empty. This is the whole distinction: the reading is
    # beside it, dated, with a button — not sitting in it as today's number.
    box = re.search(r'<input[^>]*name="m_ef_pct"[^>]*>', page)
    assert box, "the EF box is not on the screen"
    assert 'value=""' in box.group(0), \
        f"the box was filled in with an old echo: {box.group(0)}"
    assert "2026-01-05" in page, "the reading is offered without its date"

    from app.models import Measurement

    with echo["app"].app_context():
        assert Measurement.query.filter_by(code="ef_pct").count() == 0, \
            "opening the screen wrote a reading nobody took today"


def test_only_the_last_one_is_offered(echo):
    """Two echoes, and the box is offered the newer. Being offered the first
    one ever taken would be worse than being offered nothing."""
    _study(echo["app"], echo["ids"]["child"], date(2026, 1, 5),
           {"الكسر القذفي (EF)": "58"}, echo["device_id"])
    _study(echo["app"], echo["ids"]["child"], date(2026, 6, 5),
           {"الكسر القذفي (EF)": "62"}, echo["device_id"])

    from app.utils import panels, series

    with echo["app"].app_context():
        last = series.last_study_readings(echo["ids"]["child"],
                                          panels.panel("cardiology"))

    assert last["ef_pct"]["value"] == 62.0
    assert last["ef_pct"]["date"] == date(2026, 6, 5)


def test_a_panel_field_with_no_device_behind_it_is_offered_nothing(echo):
    from app.utils import panels, series

    with echo["app"].app_context():
        last = series.last_study_readings(echo["ids"]["child"],
                                          panels.panel("cardiology"))

    assert last == {}


# --------------------------------------------- the card is not furniture

def test_a_doctor_with_no_specialty_does_not_get_a_panel_card(clinic):
    """It was on every visit screen of every clinic, including the ones with
    one specialty who will never open it. A dropdown nobody uses on a screen
    used forty times a day is not free."""
    page = (clinic["sign_in"]("boss")
            .get(f"/visits/{clinic['ids']['visit']}/record").get_data(as_text=True))

    assert page.count('name="specialty_panel"') == 1, \
        "the panel select is not on the page exactly once"
    # The card's own heading is gone; the label beside the small picker is the
    # one occurrence left, and it only shows once the picker is opened.
    assert page.count("لوح التخصص") == 1
    assert "section-title" not in page.split('name="specialty_panel"')[0][-400:], \
        "the panel is still a card with a heading of its own"


def test_the_picker_is_still_there_for_the_doctor_who_wants_one(clinic):
    """Hidden is not removed. A doctor seeing one cardiac child this month must
    still be able to turn the panel on for that visit."""
    from app.extensions import db
    from app.models import Visit

    page = (clinic["sign_in"]("boss")
            .get(f"/visits/{clinic['ids']['visit']}/record").get_data(as_text=True))
    assert 'value="cardiology"' in page, "there is no way to choose a panel"

    clinic["sign_in"]("boss").post(f"/visits/{clinic['ids']['visit']}/record",
                                   data={"chief_complaint": "متابعة",
                                         "specialty_panel": "cardiology"},
                                   follow_redirects=True)

    with clinic["app"].app_context():
        assert db.session.get(Visit, clinic["ids"]["visit"]).specialty_panel \
            == "cardiology"


def test_saving_without_opening_the_picker_changes_nothing(clinic):
    """The select stays in the form while hidden, so it posts an empty string.
    That must mean "still none", not an error and not a panel."""
    from app.extensions import db
    from app.models import Visit

    clinic["sign_in"]("boss").post(f"/visits/{clinic['ids']['visit']}/record",
                                   data={"chief_complaint": "متابعة",
                                         "specialty_panel": ""},
                                   follow_redirects=True)

    with clinic["app"].app_context():
        assert db.session.get(Visit, clinic["ids"]["visit"]).specialty_panel is None


def test_the_card_comes_back_for_the_doctor_who_has_one(echo):
    page = (echo["sign_in"]("boss")
            .get(f"/visits/{echo['ids']['visit']}/record").get_data(as_text=True))

    assert 'name="m_ef_pct"' in page, "the cardiology fields are not rendered"
