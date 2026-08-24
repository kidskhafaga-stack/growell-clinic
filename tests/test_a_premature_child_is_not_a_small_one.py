"""What the child arrived with, and what the growth chart does with it.

Asked directly: *"غالباً سن الحمل عند الولادة والوزن عند الولادة تقريباً
بيعوزوها"* — and the second half of that sentence is the design.

**"تقريباً" is the point, not a caveat.** Both numbers are usually the mother's
memory rather than a discharge summary. So neither is required, neither is ever
inferred, and a blank one means nobody said — which is a different fact from a
normal one, and the screen keeps them different.

**A premature child scored at their birthday age reads as small.** A baby born
at 32 weeks and weighed at six months has been outside for six months and alive
for eight; the growth standard's zero is birth *at term*. Scoring them against a
six-month reference puts a child who is exactly on course below the third
centile — and "below the third centile" is what starts a workup. Correcting is
arithmetic on days, and the only hard part is saying so on the screen.

**And the correction has to end somewhere.** There is no single universal rule,
which is why the window is a setting: two years by default, three for the very
preterm, and a clinic that follows its own protocol changes a number rather than
the program.
"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


class _Child:
    """Just the four attributes the growth engine reads."""

    def __init__(self, dob, weeks=None, days=0, gender="male"):
        self.date_of_birth = dob
        self.gender = gender
        self.gestation_weeks = weeks
        self.gestation_days = days

    @property
    def gestation_total_days(self):
        if self.gestation_weeks is None:
            return None
        return self.gestation_weeks * 7 + (self.gestation_days or 0)


# ------------------------------------------------- what the file remembers

def test_a_gestation_is_written_the_way_it_is_said(clinic):
    """36+4, not 36.57. A decimal week is a number no discharge summary ever
    printed, and the whole reason the field exists is to match a document
    somebody is reading off."""
    from app.extensions import db
    from app.models import Patient

    with clinic["app"].app_context():
        child = db.session.get(Patient, clinic["ids"]["child"])
        child.gestation_weeks, child.gestation_days = 36, 4
        db.session.commit()

        assert child.gestation == "36+4"
        assert child.gestation_total_days == 256


def test_nobody_said_is_not_the_same_as_born_at_term(clinic):
    """Three-valued on purpose. "We do not know" and "no, they were term" lead
    to different conversations, and a screen showing the second when it means
    the first is the program answering a question nobody asked it."""
    from app.extensions import db
    from app.models import Patient

    with clinic["app"].app_context():
        child = db.session.get(Patient, clinic["ids"]["child"])
        assert child.is_preterm is None and child.gestation is None

        child.gestation_weeks, child.gestation_days = 39, 0
        assert child.is_preterm is False

        child.gestation_weeks, child.gestation_days = 36, 6
        assert child.is_preterm is True, "36+6 is not 37 completed weeks"


def test_thirty_seven_exactly_is_term(clinic):
    """The boundary, pinned. 37+0 is term by definition and an off-by-one here
    would put a badge on a healthy newborn's file for life."""
    from app.utils.growth import correction_days

    assert correction_days(37 * 7) == 0
    assert correction_days(36 * 7 + 6) == 40 * 7 - (36 * 7 + 6)


# ------------------------------------------------------ the corrected age

def test_the_age_a_premature_child_is_scored_at_is_corrected(clinic):
    """Born at 32+0 — eight weeks early. At six months old they are scored as
    four months, which is what they are."""
    from app.utils.growth import age_for

    child = _Child(date(2026, 1, 1), weeks=32, days=0)

    with clinic["app"].app_context():
        age = age_for(child, date(2026, 7, 1))

    assert age["corrected"] is True
    assert age["days_early"] == 56
    assert 5.9 < age["raw_months"] < 6.1
    assert 4.0 < age["months"] < 4.2, \
        f"scored at {age['months']:.2f} months instead of about four"


def test_a_term_child_is_scored_at_their_own_age(clinic):
    from app.utils.growth import age_for

    child = _Child(date(2026, 1, 1), weeks=39, days=2)

    with clinic["app"].app_context():
        age = age_for(child, date(2026, 7, 1))

    assert age["corrected"] is False
    assert age["months"] == age["raw_months"]


def test_a_child_with_no_gestation_recorded_is_scored_as_before(clinic):
    """The change must not move a single existing patient's percentile. Every
    file in every clinic has a blank gestation the day this ships."""
    from app.utils.growth import age_for, age_in_months

    child = _Child(date(2026, 1, 1))

    with clinic["app"].app_context():
        age = age_for(child, date(2026, 7, 1))

    assert age["corrected"] is False
    assert age["months"] == age_in_months(date(2026, 1, 1), date(2026, 7, 1))


def test_the_correction_stops_at_two_years(clinic):
    """It has to end somewhere, and the same child either side of the line is
    the test worth having."""
    from app.utils.growth import age_for

    child = _Child(date(2024, 1, 1), weeks=32, days=0)

    with clinic["app"].app_context():
        inside = age_for(child, date(2025, 12, 1))    # ~23 months
        outside = age_for(child, date(2026, 3, 1))    # ~26 months

    assert inside["corrected"] is True
    assert outside["corrected"] is False
    assert outside["months"] == outside["raw_months"]


def test_a_very_premature_child_is_corrected_for_longer(clinic):
    """Three years rather than two below 28 weeks — the usual practice, and
    the reason the window is a function of the gestation rather than a
    constant."""
    from app.utils.growth import age_for

    very = _Child(date(2024, 1, 1), weeks=26, days=0)
    less = _Child(date(2024, 1, 1), weeks=32, days=0)

    with clinic["app"].app_context():
        on = date(2026, 6, 1)                          # ~29 months
        assert age_for(very, on)["corrected"] is True
        assert age_for(less, on)["corrected"] is False


def test_the_clinic_can_set_its_own_window(clinic):
    """No single universal rule, so it is a number the clinic owns rather than
    an expression in the code."""
    from app.extensions import db
    from app.models import Setting
    from app.utils.growth import age_for

    child = _Child(date(2024, 1, 1), weeks=32, days=0)
    on = date(2026, 3, 1)                              # ~26 months

    with clinic["app"].app_context():
        assert age_for(child, on)["corrected"] is False

        Setting.set("growth.correct_until_months", 36)
        db.session.commit()
        assert age_for(child, on)["corrected"] is True


def test_rubbish_in_the_setting_falls_back_rather_than_crashing(clinic):
    """A growth chart that raised because somebody typed a word into a settings
    box would take the whole screen down for every child in the clinic."""
    from app.extensions import db
    from app.models import Setting
    from app.utils.growth import age_for, correct_until_months

    with clinic["app"].app_context():
        Setting.set("growth.correct_until_months", "لا أعرف")
        db.session.commit()

        assert correct_until_months(32 * 7) == 24
        assert age_for(_Child(date(2026, 1, 1), 32, 0), date(2026, 7, 1))["months"]


def test_the_correction_never_makes_an_age_negative(clinic):
    """A 28-weeker measured in their first fortnight. The reference has nothing
    below zero, and a negative age would be a lookup nobody wrote a rule for."""
    from app.utils.growth import age_for

    with clinic["app"].app_context():
        age = age_for(_Child(date(2026, 1, 1), 28, 0), date(2026, 1, 10))

    assert age["months"] == 0.0


# ------------------------------------------- and the screen has to say so

def test_the_percentile_says_it_used_a_corrected_age(clinic):
    """A percentile computed against an age nobody can see is a number the
    parent and the next doctor cannot reproduce."""
    from app.extensions import db
    from app.models import GrowthRecord, Patient
    from app.utils.growth import summarise

    with clinic["app"].app_context():
        child = db.session.get(Patient, clinic["ids"]["child"])
        child.date_of_birth = date(2025, 1, 1)
        child.gestation_weeks, child.gestation_days = 32, 0
        rec = GrowthRecord(patient_id=child.id, record_date=date(2025, 7, 1),
                           weight_kg=6.0)
        db.session.add(rec)
        db.session.commit()

        rows = summarise(child, rec)

    assert rows and all(r["corrected"] is True for r in rows)


def test_the_corrected_percentile_is_the_kinder_one(clinic):
    """The measurement that makes the whole feature worth building: the same
    weight, the same day, read as a different child."""
    from app.extensions import db
    from app.models import GrowthRecord, Patient
    from app.utils.growth import summarise

    with clinic["app"].app_context():
        child = db.session.get(Patient, clinic["ids"]["child"])
        child.date_of_birth = date(2025, 1, 1)
        rec = GrowthRecord(patient_id=child.id, record_date=date(2025, 7, 1),
                           weight_kg=6.0)
        db.session.add(rec)
        db.session.commit()

        uncorrected = summarise(child, rec)[0]["percentile"]

        child.gestation_weeks, child.gestation_days = 32, 0
        db.session.commit()
        corrected = summarise(child, rec)[0]["percentile"]

    assert corrected > uncorrected, (
        f"a 32-weeker read at {corrected} corrected vs {uncorrected} raw — "
        "correcting made no difference")


def test_the_chart_marks_the_points_it_corrected(clinic):
    from app.extensions import db
    from app.models import GrowthRecord, Patient

    with clinic["app"].app_context():
        child = db.session.get(Patient, clinic["ids"]["child"])
        child.date_of_birth = date(2025, 1, 1)
        child.gestation_weeks, child.gestation_days = 32, 0
        db.session.add(GrowthRecord(patient_id=child.id,
                                    record_date=date(2025, 7, 1), weight_kg=6.0))
        db.session.commit()

    data = clinic["sign_in"]("boss").get(
        f"/growth/{clinic['ids']['child']}/data?ref=WHO&indicator=wfa").get_json()

    assert data["corrected"] is True
    assert any(p.get("corrected") for p in data["points"])


# ------------------------------------------------ the birth weight on the line

def test_the_birth_weight_is_the_first_point_on_the_weight_curve(clinic):
    """It is a weight-for-age reading at age zero, and it is the point that
    says where the line started."""
    from app.extensions import db
    from app.models import GrowthRecord, Patient

    with clinic["app"].app_context():
        child = db.session.get(Patient, clinic["ids"]["child"])
        child.date_of_birth = date(2025, 1, 1)
        child.birth_weight_kg = 3.2
        db.session.add(GrowthRecord(patient_id=child.id,
                                    record_date=date(2025, 7, 1), weight_kg=7.5))
        db.session.commit()

    data = clinic["sign_in"]("boss").get(
        f"/growth/{clinic['ids']['child']}/data?ref=WHO&indicator=wfa").get_json()

    first = data["points"][0]
    assert first["value"] == 3.2 and first["age_months"] == 0
    assert first["source"] == "birth", \
        "the birth weight is drawn as if this clinic had measured it"


def test_a_birth_weight_is_not_a_height_or_a_head(clinic):
    """Putting it on the other charts would be the program plotting a
    measurement nobody took."""
    from app.extensions import db
    from app.models import Patient

    with clinic["app"].app_context():
        child = db.session.get(Patient, clinic["ids"]["child"])
        child.date_of_birth = date(2025, 1, 1)
        child.birth_weight_kg = 3.2
        db.session.commit()

    for indicator in ("hfa", "hcfa", "bmifa"):
        data = clinic["sign_in"]("boss").get(
            f"/growth/{clinic['ids']['child']}/data?ref=WHO&indicator={indicator}"
        ).get_json()
        assert not any(p.get("source") == "birth" for p in data["points"]), \
            f"the birth weight was plotted on {indicator}"


def test_a_premature_birth_weight_is_drawn_where_it_happened(clinic):
    """Not corrected. The reference's zero *is* birth at term, so a 32-weeker's
    birth weight genuinely belongs off the bottom of it — moving the point
    would hide a real measurement rather than explain it."""
    from app.extensions import db
    from app.models import Patient

    with clinic["app"].app_context():
        child = db.session.get(Patient, clinic["ids"]["child"])
        child.date_of_birth = date(2025, 1, 1)
        child.birth_weight_kg = 1.7
        child.gestation_weeks, child.gestation_days = 32, 0
        db.session.commit()

    data = clinic["sign_in"]("boss").get(
        f"/growth/{clinic['ids']['child']}/data?ref=WHO&indicator=wfa").get_json()
    birth = [p for p in data["points"] if p.get("source") == "birth"][0]

    assert birth["age_months"] == 0
    assert birth["corrected"] is False


# ------------------------------------------------------------- the form

def _post(clinic, **extra):
    data = {"full_name": "طفل", "gender": "male", "date_of_birth": "2025-01-01",
            "auto_number": "1", "is_active": "1"}
    data.update(extra)
    return clinic["sign_in"]("boss").post("/patients/new", data=data,
                                          follow_redirects=True)


def _newest(clinic):
    from app.models import Patient

    with clinic["app"].app_context():
        return Patient.query.order_by(Patient.id.desc()).first()


def test_both_can_be_entered_and_both_can_be_left_blank(clinic):
    _post(clinic, birth_weight_kg="3.2", gestation_weeks="36", gestation_days="4")
    child = _newest(clinic)
    assert child.birth_weight_kg == 3.2 and child.gestation == "36+4"

    _post(clinic, full_name="طفل تاني")
    blank = _newest(clinic)
    assert blank.birth_weight_kg is None and blank.gestation_weeks is None


def test_a_gestation_typed_into_the_weight_box_is_refused(clinic):
    """The two boxes sit next to each other. "36" as a birth weight would be
    plotted without a murmur, and the chart would say a newborn weighed as
    much as a ten-year-old."""
    from app.models import Patient

    before = None
    with clinic["app"].app_context():
        before = Patient.query.count()

    _post(clinic, birth_weight_kg="36")

    with clinic["app"].app_context():
        assert Patient.query.count() == before, "a birth weight of 36 kg was saved"


def test_a_four_hundred_gram_survivor_is_not_refused(clinic):
    """The bounds are wide on purpose: a program that refused this child would
    be wrong about a child who exists."""
    _post(clinic, birth_weight_kg="0.45", gestation_weeks="24")

    child = _newest(clinic)
    assert child.birth_weight_kg == 0.45


def test_days_without_weeks_is_not_half_a_gestation(clinic):
    """"+4" on its own means nothing, and storing it would make `gestation`
    read as "None+4" somewhere later."""
    _post(clinic, gestation_days="4")

    child = _newest(clinic)
    assert child.gestation_weeks is None and child.gestation_days is None


def test_weeks_without_days_means_exactly_that_many_weeks(clinic):
    _post(clinic, gestation_weeks="34")

    child = _newest(clinic)
    assert child.gestation == "34+0"


def test_the_file_shows_both_even_when_nobody_has_said_yet(clinic):
    """A blank birth weight is somebody still to ask. Hiding the row makes it a
    question nobody remembers to ask."""
    page = (clinic["sign_in"]("boss")
            .get(f"/patients/{clinic['ids']['child']}").get_data(as_text=True))

    assert "الوزن عند الولادة" in page
    assert "سن الحمل عند الولادة" in page
