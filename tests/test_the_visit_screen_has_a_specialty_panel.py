"""One visit screen with a panel on it, not a screen per specialty.

Asked directly: *"هل هنعمل شاشة مختلفة للزيارة لو الدكتور دكتور اسنان ولو غدد
ولو رمد ولو مخ واعصاب؟"* — and the answer is no.

**The file is one, and that is the survey's own strongest argument.** Its
starred items all say the same thing: *"طبيب الأسنان لا يعرف أن الطفل عنده فتحة
في القلب"*. A screen per specialty would break the exact thing the survey says
is valuable. A child with asthma and caries is one visit; if the dental screen
is its own, the weight is recorded twice or not at all. And the constant part
is the larger part — complaint, examination, diagnosis, plan, investigations,
prescription do not change by specialty.

**Whose choice the panel is: both, in an order.** It follows the doctor by
default, because nobody opens a dropdown forty times a day, and the visit can
change it, because the panel is a property of what this visit is about rather
than of who is typing — a cardiologist seeing a child with a cold does not want
LVEDD on the screen.

**And blood pressure is not a cardiology field.** Three specialties asked for
it, which is the argument against giving it to any of them: it is a vital sign,
the nurse measures it before the child goes in, and a panel that owned it would
mean a nephrologist typing into a screen headed "cardiology".

Cardiology is the first panel because it is the one the clinic asked for. The
mechanism is what is being tested; the second panel should be an edit to a JSON
file and no code at all.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def desk(clinic):
    """A clinic that works specialties, and a doctor who works cardiology."""
    from app.extensions import db
    from app.models import Setting, User, Visit

    with clinic["app"].app_context():
        Setting.set("mod_enabled:panels", "1")
        visit = db.session.get(Visit, clinic["ids"]["visit"])
        doctor = db.session.get(User, visit.doctor_id)
        doctor.specialty_panels = "cardiology"
        db.session.commit()
    clinic["url"] = f"/visits/{clinic['ids']['visit']}/record"
    return clinic


def _save(desk, **form):
    data = {"chief_complaint": "متابعة"}
    data.update(form)
    return desk["sign_in"]("boss").post(desk["url"], data=data,
                                        follow_redirects=True)


def _readings(desk):
    from app.models import Measurement

    with desk["app"].app_context():
        return {m.code: m for m in
                Measurement.query.filter_by(
                    visit_id=desk["ids"]["visit"]).all()}


# ------------------------------------------------------- the panel is data

def test_a_panel_is_a_json_entry_and_not_a_screen(desk):
    """The whole mechanism in one assertion: adding a specialty must be an
    edit to a data file. A panel that needed a template would make ten
    specialties ten screens to keep in step."""
    import glob

    from app.utils import panels

    assert "cardiology" in panels.all_panels()
    assert not glob.glob("app/templates/visits/record_cardiology*.html"), \
        "a specialty grew a screen of its own"


def test_the_catalogue_names_where_its_fields_came_from(desk):
    """A clinical field list with no source is a list somebody invented. The
    vaccine tables carry their reference for the same reason."""
    from app.utils import panels

    cat = panels.catalogue()

    assert cat.get("version"), "the catalogue is not versioned"
    assert cat.get("_sources"), "nothing says where these fields came from"


def test_an_unknown_panel_key_answers_with_nothing(desk):
    """`None` rather than a default. A visit recorded under a panel that has
    since been renamed should show no panel and keep its readings, not
    silently acquire another specialty's fields."""
    from app.utils import panels

    assert panels.panel("orthopaedics") is None
    assert panels.panel("") is None


# ------------------------------------------------- whose choice the panel is

def test_it_follows_the_doctor_when_the_visit_has_not_said(desk):
    from app.extensions import db
    from app.models import User, Visit
    from app.utils import panels

    with desk["app"].app_context():
        visit = db.session.get(Visit, desk["ids"]["visit"])
        doctor = db.session.get(User, visit.doctor_id)
        key, meta = panels.for_visit(visit, doctor)

    assert key == "cardiology" and meta is not None


def test_and_the_visit_can_say_otherwise(desk):
    """The panel is about what this visit is for. A cardiologist seeing a
    child with a cold should be able to put the panel away."""
    from app.extensions import db
    from app.models import Visit

    _save(desk, specialty_panel="")

    with desk["app"].app_context():
        assert db.session.get(Visit, desk["ids"]["visit"]).specialty_panel is None


def test_the_panel_used_is_recorded_on_the_visit(desk):
    """Recorded rather than derived from the doctor when the file is read
    later: a visit whose doctor changes specialty next year must not have its
    measurements re-labelled underneath it."""
    from app.extensions import db
    from app.models import Visit

    _save(desk, specialty_panel="cardiology", m_ef_pct="58")

    with desk["app"].app_context():
        visit = db.session.get(Visit, desk["ids"]["visit"])
        assert visit.specialty_panel == "cardiology"


def test_the_doctors_free_text_specialty_is_left_alone(desk):
    """It prints on the prescription and a doctor has typed prose into it.
    Driving a panel from it would be a lookup that works in testing and fails
    on a real clinic — so the coded field is a separate one."""
    from app.models import User

    columns = User.__table__.columns

    assert "specialty" in columns and "specialty_panel" in columns
    assert columns["specialty"].type.length > columns["specialty_panel"].type.length


# ---------------------------------------------------- it does not ask twice

def test_the_panel_reads_the_vitals_rather_than_asking_again(desk):
    """A second weight box would mean two weights for one visit and no way to
    know which is the real one. The panel lists what it wants to *see*."""
    from app.utils import panels

    meta = panels.panel("cardiology")

    for vital in ("weight_kg", "height_cm", "pulse_bpm", "resp_rate", "spo2"):
        assert vital in meta["reads"], f"{vital} is not read from the vitals"
        assert vital not in {f["code"] for f in meta["fields"]}, \
            f"{vital} is asked for again by the panel"


def test_blood_pressure_is_a_vital_sign_and_not_a_cardiology_field(desk):
    """Cardiology, endocrine and nephrology all asked for it, which is the
    argument against giving it to any of them."""
    from app.extensions import db
    from app.models import Visit
    from app.utils import panels

    assert "blood_pressure" not in {f["code"]
                                    for f in panels.panel("cardiology")["fields"]}

    _save(desk, bp_systolic="95", bp_diastolic="60", bp_arm="right")

    with desk["app"].app_context():
        vitals = db.session.get(Visit, desk["ids"]["visit"]).vitals
        assert vitals.blood_pressure == "95/60"
        assert vitals.bp_arm == "right", \
            "which arm was not kept — a difference between them is the finding"


def test_half_a_blood_pressure_is_not_a_reading(desk):
    """A systolic with no diastolic is a typing accident, and showing it as a
    reading invites somebody to act on it."""
    from app.extensions import db
    from app.models import Visit

    _save(desk, bp_systolic="95")

    with desk["app"].app_context():
        assert db.session.get(Visit, desk["ids"]["visit"]).vitals.blood_pressure is None


# ------------------------------------------------------------ what it stores

def test_a_number_is_stored_as_a_number_and_a_class_as_a_word(desk):
    """EF is 55. Ross is II. Forcing everything numeric would have somebody
    storing 2 for Ross II and drawing a chart of it; forcing everything
    textual would lose every curve."""
    _save(desk, specialty_panel="cardiology",
          m_ef_pct="58", m_nyha_ross="II", m_lvedd_mm="34.5")

    rows = _readings(desk)

    assert rows["ef_pct"].value_num == 58.0 and rows["ef_pct"].unit == "%"
    assert rows["lvedd_mm"].value_num == 34.5
    assert rows["nyha_ross"].value_text == "II"
    assert rows["nyha_ross"].value_num is None, \
        "a heart-failure class was stored as a number"


def test_a_field_no_catalogue_describes_is_not_written(desk):
    """A form posts names. Without checking them the child's file would carry
    a reading nothing can label and no screen can show."""
    _save(desk, specialty_panel="cardiology", m_ef_pct="58",
          m_secret_field="whatever", m_weight_kg="99")

    rows = _readings(desk)

    assert "secret_field" not in rows, "an invented field was written to the file"
    assert "weight_kg" not in rows, \
        "the panel wrote a vital sign, so there are now two weights"


def test_clearing_a_box_clears_the_reading(desk):
    """Correcting a visit by emptying a field is exactly where a stale value
    would survive — and a stale measurement is worse than a gap, because a gap
    is visible."""
    _save(desk, specialty_panel="cardiology", m_ef_pct="58")
    assert "ef_pct" in _readings(desk)

    _save(desk, specialty_panel="cardiology", m_ef_pct="")
    assert "ef_pct" not in _readings(desk), "the previous reading outlived it"


def test_saving_twice_corrects_rather_than_adds(desk):
    """One reading per field per visit. Two would make "the EF at this visit"
    a question with two answers."""
    _save(desk, specialty_panel="cardiology", m_ef_pct="58")
    _save(desk, specialty_panel="cardiology", m_ef_pct="61")

    rows = _readings(desk)
    assert rows["ef_pct"].value_num == 61.0

    from app.models import Measurement

    with desk["app"].app_context():
        count = Measurement.query.filter_by(
            visit_id=desk["ids"]["visit"], code="ef_pct").count()
    assert count == 1, f"the same field was recorded {count} times for one visit"


def test_which_panel_is_showing_does_not_decide_what_is_kept(desk):
    """A doctor who works a panel records under it whether or not the chips
    happened to be showing it when they pressed save.

    This test used to assert the opposite — that an empty `specialty_panel`
    threw the readings away — and that was right while a visit belonged to one
    panel. It stopped being right when a doctor could work several: a
    cardiology reading typed on a screen whose chips had moved on to another
    panel is still a cardiology reading, and deleting it would be the screen
    editing the file behind the doctor.
    """
    _save(desk, specialty_panel="", m_ef_pct="58")

    rows = _readings(desk)
    assert rows["ef_pct"].value_num == 58.0
    assert rows["ef_pct"].panel == "cardiology", \
        "the reading lost the panel it was taken under"


# ------------------------------------------------------------- on the screen

def test_the_panel_is_on_the_visit_screen(desk):
    page = desk["sign_in"]("boss").get(desk["url"]).get_data(as_text=True)

    assert 'name="specialty_panel"' in page, "there is no way to choose a panel"
    assert 'name="m_ef_pct"' in page, "the cardiology fields are not rendered"
    assert 'name="bp_systolic"' in page, "blood pressure is not on the vitals"


def test_the_survey_asked_for_a_control_number_and_the_catalogue_declines(desk):
    """The contradiction found while reviewing the survey, kept honest here.

    `control_number` is `required: true` and numeric in the questionnaire, and
    the answer key's own words for cardiology are *"لا يوجد رقم موحّد لـSpO2 أو
    EF لكل مرض قلبي"*. So the catalogue holds none. A number invented to fill a
    mandatory box is what later fires a false alert.
    """
    from app.utils import panels

    meta = panels.panel("cardiology")

    assert meta.get("control_number") is None, \
        "a control number was invented for a specialty whose reference declines one"
