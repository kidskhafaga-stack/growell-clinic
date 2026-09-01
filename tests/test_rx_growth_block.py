"""The growth picture on the prescription — for the doctors who read it.

Asked for by the clinic in these words: the endocrine and diabetes doctors
need the weight *and the height*, because they are looking at growth, and the
neurology and psychiatry doctors probably need something of their own. Which
is a question about whether every prescription in a clinic should look the
same, and the answer already in the program is no — ``User.rx_template_id``
means each doctor prints through their own template. What was missing was not
the mechanism, it was the fields.

So this is a block of flags, not a new concept: a clinic switches growth on in
a template, names it, and gives it to the doctors who want it.

**It is the first element on this page that defaults to off.** The weight and
the allergy are on for everybody because leaving them off can hurt a child; a
percentile cannot, and every block added competes for room with the drugs. A
general paediatrician writing an antibiotic does not need a growth curve, and
a page they stop reading is worse than a page with less on it.

**One measurement event, not the newest of each measurement.** Taking the
weight from today and the height from whichever visit last recorded one builds
a child who never existed and prints it as a single moment. So the block reads
one record, prints its date, and shows only what that record holds — which is
also why nothing needs configuring per age: a ten-year-old has no head
circumference on file, so none is printed.
"""
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# The clinic's today, not the server's — the same clock the
# screens filter by. See conftest.py.
from app.utils.clock import local_today  # noqa: E402

import pytest  # noqa: E402


def _template(clinic, **flags):
    with clinic["app"].app_context():
        from app.models import RxPrintTemplate
        db = clinic["db"]
        db.session.add(RxPrintTemplate(name="t", mode="white", is_default=True,
                                       page_size="A4", font_size=14,
                                       margin_mm=12, **flags))
        db.session.commit()


def _rx(clinic, **measurements):
    """A prescription, with one growth record holding whatever is passed."""
    with clinic["app"].app_context():
        from app.models import GrowthRecord, Patient, Prescription
        db = clinic["db"]

        patient = db.session.get(Patient, clinic["ids"]["child"])
        on = measurements.pop("record_date", date.today())
        if measurements:
            db.session.add(GrowthRecord(patient_id=patient.id, record_date=on,
                                        **measurements))
        rx = Prescription(patient_id=patient.id,
                          doctor_id=clinic["ids"]["doctor"],
                          rx_date=local_today())
        db.session.add(rx)
        db.session.commit()
        return rx.id


def _paper(clinic, rx_id):
    return (clinic["sign_in"]("doc").get(f"/prescriptions/{rx_id}")
            .get_data(as_text=True))


# --- off unless asked for -------------------------------------------------

def test_growth_stays_off_for_a_clinic_that_has_not_asked(clinic):
    """The decision this block turns on. Every other element defaults on."""
    from app.models import RxPrintTemplate

    tpl = RxPrintTemplate.default_instance()
    assert tpl.show_growth is False
    assert tpl.show_weight is True, "the safety elements must stay on"


def test_the_off_by_default_list_is_what_makes_that_true(clinic):
    """``default_instance`` switches on everything in BOOLS, which is exactly
    the behaviour that must not apply here."""
    from app.models import RxPrintTemplate

    assert "show_growth" in RxPrintTemplate.BOOLS, "the form would not save it"
    assert "show_growth" in RxPrintTemplate.OFF_BY_DEFAULT


def test_an_ordinary_prescription_has_no_growth_block(clinic):
    rx_id = _rx(clinic, weight_kg=12.0, height_cm=85.0)
    body = _paper(clinic, rx_id)
    assert "85.0" not in body, "height printed on a template that never asked"


# --- on, for the doctors who want it --------------------------------------

def test_the_height_reaches_the_paper(clinic):
    """The measurement the clinic named: growth needs the height too."""
    rx_id = _rx(clinic, weight_kg=12.0, height_cm=85.0)
    _template(clinic, show_growth=True, show_weight=True, show_allergies=True)
    body = _paper(clinic, rx_id)
    assert "85.0" in body


def test_the_percentile_is_printed_beside_the_measurement(clinic):
    """A number without its percentile is what the chart screen is for."""
    rx_id = _rx(clinic, weight_kg=12.0, height_cm=85.0)
    _template(clinic, show_growth=True, show_weight=True, show_allergies=True)
    body = _paper(clinic, rx_id)
    assert "المئين" in body, "measurements printed with no percentile"


def test_only_what_was_actually_measured_is_printed(clinic):
    """A visit where only the weight was taken prints only the weight.

    This is what saves the block from needing any per-age configuration: the
    record decides, so a ten-year-old with no head circumference on file
    simply has no head-circumference row.
    """
    rx_id = _rx(clinic, weight_kg=12.0)
    _template(clinic, show_growth=True, show_weight=True, show_allergies=True)
    body = _paper(clinic, rx_id)
    assert "محيط الرأس" not in body
    assert "الطول" not in body.split("rxPaper")[1][:5000]


def test_a_child_with_no_measurements_prints_no_empty_block(clinic):
    rx_id = _rx(clinic)
    _template(clinic, show_growth=True, show_weight=True, show_allergies=True)
    body = _paper(clinic, rx_id)
    assert "المئين" not in body


# --- one event, not a composite -------------------------------------------

def test_the_block_reads_one_measurement_event(clinic):
    """The child who never existed.

    An older visit has the height, today's has the weight. Reading "the newest
    height" and "the newest weight" separately would print both side by side
    under one date, describing a moment that never happened.
    """
    old = local_today() - timedelta(days=400)
    rx_id = _rx(clinic, height_cm=70.0, record_date=old)
    with clinic["app"].app_context():
        from app.models import GrowthRecord
        db = clinic["db"]
        db.session.add(GrowthRecord(patient_id=clinic["ids"]["child"],
                                    weight_kg=14.0, record_date=local_today()))
        db.session.commit()
    _template(clinic, show_growth=True, show_weight=True, show_allergies=True)

    body = _paper(clinic, rx_id)
    assert "70.0" not in body, (
        "a height from 400 days ago is printed beside today's weight")


def test_an_older_measurement_carries_its_date(clinic):
    taken = local_today() - timedelta(days=90)
    rx_id = _rx(clinic, weight_kg=11.0, height_cm=80.0, record_date=taken)
    _template(clinic, show_growth=True, show_weight=True, show_allergies=True)
    body = _paper(clinic, rx_id)
    assert str(taken) in body


# --- the shared reference -------------------------------------------------

def test_the_prescription_and_the_profile_measure_against_one_standard(clinic):
    """WHO under five, CDC after. Extracted so the two cannot disagree.

    A child read against the wrong reference gets a percentile that is wrong
    by a clinically interesting amount near the boundary, and nothing on
    either screen would say why.
    """
    with clinic["app"].app_context():
        from app.models import Patient
        from app.utils.growth import reference_for

        patient = clinic["db"].session.get(Patient, clinic["ids"]["child"])
        assert reference_for(patient) in ("WHO", "CDC")

    import inspect

    from app.blueprints.patients import routes

    source = inspect.getsource(routes._growth_concern)
    assert "reference_for" in source, (
        "the profile picks its own reference again")
    assert '"WHO" if' not in source, "the rule is duplicated"


@pytest.mark.parametrize("years,expected", [(2, "WHO"), (9, "CDC")])
def test_the_reference_follows_the_childs_age(clinic, years, expected):
    with clinic["app"].app_context():
        from app.models import Patient
        from app.utils.growth import reference_for

        db = clinic["db"]
        patient = db.session.get(Patient, clinic["ids"]["child"])
        patient.date_of_birth = local_today() - timedelta(days=int(years * 365.25))
        db.session.commit()
        assert reference_for(patient) == expected


def test_a_measurement_with_no_percentile_still_prints_its_value(clinic):
    """A birth year mistyped into the future — 2027 for 2017.

    There is no age, so there is no percentile to compute. The weight on that
    file is still a real measurement somebody took, and dropping the row would
    lose it to a failed lookup — on exactly the file that already has a
    data-entry error somebody needs to notice.

    (Falling off the *end* of a standard is a different matter and does not
    arise: ``_lms`` clamps to the last row of its table, so a value always
    scores against something.)
    """
    with clinic["app"].app_context():
        from app.models import GrowthRecord, Patient
        from app.utils.growth import summarise

        db = clinic["db"]
        patient = db.session.get(Patient, clinic["ids"]["child"])
        patient.date_of_birth = local_today() + timedelta(days=365)
        record = GrowthRecord(patient_id=patient.id, weight_kg=12.0,
                              record_date=local_today())
        db.session.add(record)
        db.session.commit()

        rows = summarise(patient, record)
        assert rows and rows[0]["value"] == 12.0
        assert rows[0]["percentile"] is None


# --- the upgrade ----------------------------------------------------------

def test_an_existing_clinic_gets_the_column_on_upgrade():
    from app.utils.schema import ADDITIONS

    assert any(table == "rx_print_templates" and name == "show_growth"
               for table, name, _ in ADDITIONS)


def test_the_column_arrives_switched_off():
    """A clinic upgrading must not find growth suddenly on every prescription."""
    from app.utils.schema import ADDITIONS

    ddl = next(d for t, n, d in ADDITIONS
               if t == "rx_print_templates" and n == "show_growth")
    assert "0" in ddl, f"show_growth arrives as {ddl!r}"
