"""The two things a paediatric prescription was going out without.

**The weight.** Every dose in paediatrics is mg/kg. The printed prescription
carried the child's *age* and not their weight, which means nobody downstream
could check a dose against anything: a two-year-old can be 9 kg or 16 kg, and
those are different prescriptions. The number the dose was computed from was
the one number missing from the page.

**The allergy.** ``patient.allergies`` has been in the model all along, shown
in a red banner on every clinical screen, and matched against written drugs by
``app/utils/allergy.py``. None of that reached the paper. A prescription for an
antibiotic that does not say the child reacts to penicillin is how the child is
handed penicillin.

Three decisions in here are worth more than the code:

*The allergy line prints when the file is empty*, and says **not recorded**
rather than **none**. A blank cannot be read — nobody looking at one can tell a
child with no allergies from a child nobody asked. And "no allergies" would be
a claim the program is not entitled to make: it knows the field is empty, it
does not know the child is safe.

*The weight prints with its date*, but only when that is not the prescription's
own date. 12 kg measured this morning and 12 kg measured last winter are the
same number and a different dose, so the date has to be there — and on the
common day, when it was taken at this visit, it is noise.

*One definition of the weight.* The paper reads the same
``latest_weight_record`` the dosing calculator does. A prescription whose
printed weight disagreed with the weight its doses were computed from would be
worse than printing nothing.
"""
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


def _rx(clinic, weight=None, weight_date=None, allergies=None):
    """A prescription on the child, optionally with a weight and an allergy."""
    with clinic["app"].app_context():
        from app.models import GrowthRecord, Patient, Prescription
        db = clinic["db"]

        patient = db.session.get(Patient, clinic["ids"]["child"])
        patient.allergies = allergies
        if weight is not None:
            db.session.add(GrowthRecord(
                patient_id=patient.id, weight_kg=weight,
                record_date=weight_date or date.today()))
        rx = Prescription(patient_id=patient.id,
                          doctor_id=clinic["ids"]["doctor"],
                          rx_date=date.today())
        db.session.add(rx)
        db.session.commit()
        return rx.id


def _paper(clinic, rx_id):
    return (clinic["sign_in"]("doc").get(f"/prescriptions/{rx_id}")
            .get_data(as_text=True))


# --- the weight -----------------------------------------------------------

def test_the_weight_the_dose_was_computed_from_is_on_the_paper(clinic):
    rx_id = _rx(clinic, weight=12.5)
    body = _paper(clinic, rx_id)
    assert "12.5" in body, "the child's weight never reaches the printed page"


def test_a_child_with_no_weight_on_file_prints_cleanly(clinic):
    """Most first visits. The band must not render an empty measurement."""
    rx_id = _rx(clinic, allergies=None)
    body = _paper(clinic, rx_id)
    assert "None" not in body.split("rxPaper")[1][:4000], (
        "an absent weight is being printed as a value")


def test_an_older_weight_carries_the_day_it_was_taken(clinic):
    """The whole reason the record is read rather than the bare number."""
    taken = date.today() - timedelta(days=200)
    rx_id = _rx(clinic, weight=9.0, weight_date=taken)
    body = _paper(clinic, rx_id)
    assert "9.0" in body
    assert str(taken) in body, (
        "a weight from 200 days ago is printed as if it were today's")


def test_todays_weight_does_not_repeat_todays_date(clinic):
    """On the common day the date is noise, so it is left off.

    Written as its own test because "always print the date" would pass the
    test above and put a redundant date on every prescription the clinic
    issues.
    """
    rx_id = _rx(clinic, weight=11.0)
    body = _paper(clinic, rx_id)
    band = body.split("rxPaper")[1][:4000]
    assert "11.0" in band
    assert band.count(str(date.today())) <= 1, (
        "today's date is repeated beside a weight measured today")


def test_the_paper_and_the_dosing_read_the_same_weight(clinic):
    """One definition. They must not be able to disagree."""
    rx_id = _rx(clinic, weight=13.4)
    with clinic["app"].app_context():
        from app.models import Patient
        from app.utils.dosing import latest_weight

        patient = clinic["db"].session.get(Patient, clinic["ids"]["child"])
        assert latest_weight(patient) == patient.latest_growth.weight_kg

    assert "13.4" in _paper(clinic, rx_id)


def test_the_most_recent_weight_wins_not_the_first_one(clinic):
    """A child who has been coming for years has a column of these."""
    rx_id = _rx(clinic, weight=8.0, weight_date=date.today() - timedelta(days=400))
    with clinic["app"].app_context():
        from app.models import GrowthRecord, Patient
        db = clinic["db"]
        db.session.add(GrowthRecord(patient_id=clinic["ids"]["child"],
                                    weight_kg=14.2, record_date=date.today()))
        db.session.commit()
        patient = db.session.get(Patient, clinic["ids"]["child"])
        assert patient.latest_growth.weight_kg == 14.2

    body = _paper(clinic, rx_id)
    assert "14.2" in body
    assert "8.0" not in body.split("rxPaper")[1][:4000], (
        "a weight from over a year ago is being printed")


# --- the allergy ----------------------------------------------------------

def test_what_the_child_reacts_to_is_printed(clinic):
    rx_id = _rx(clinic, allergies="حساسية من البنسلين")
    body = _paper(clinic, rx_id)
    assert "حساسية من البنسلين" in body


def test_an_empty_allergy_field_says_not_recorded_rather_than_nothing(clinic):
    """The decision this file exists to hold still.

    Printing nothing leaves a pharmacist unable to tell "no allergies" from
    "nobody asked", and those carry very different risk. Printing "none" would
    claim something the program cannot know from an empty column.
    """
    rx_id = _rx(clinic, allergies=None)
    with clinic["app"].app_context():
        from app.i18n import translate as t_
    body = _paper(clinic, rx_id)
    assert "لا توجد حساسية مسجّلة" in body, (
        "an empty allergy field prints as a silence nobody can read")
    assert t_ is not None


def test_whitespace_is_not_an_allergy(clinic):
    """A field somebody typed a space into is an empty field."""
    rx_id = _rx(clinic, allergies="   \n ")
    body = _paper(clinic, rx_id)
    assert "لا توجد حساسية مسجّلة" in body


def test_the_allergy_is_marked_not_just_coloured(clinic):
    """These come out of a black-and-white printer.

    Red on screen is grey on paper, so the warning has to survive without the
    colour.
    """
    rx_id = _rx(clinic, allergies="بنسلين")
    body = _paper(clinic, rx_id)
    band = body.split("بنسلين")[0][-600:]
    assert "exclamation-triangle" in band, (
        "the allergy is distinguished by colour alone")


# --- the toggles ----------------------------------------------------------

@pytest.mark.parametrize("flag", ["show_weight", "show_allergies"])
def test_the_clinic_can_turn_each_one_off(clinic, flag):
    from app.models import RxPrintTemplate

    assert flag in RxPrintTemplate.BOOLS, (
        f"{flag} is not saved by the template form, which reads BOOLS")


def test_both_are_on_for_a_clinic_that_never_built_a_template(clinic):
    """``default_instance`` is a transient object, so Column defaults never
    fire on it — the bug that once printed prescriptions with no doctor's
    name. Being in BOOLS is what saves these two from the same fate.
    """
    from app.models import RxPrintTemplate

    tpl = RxPrintTemplate.default_instance()
    assert tpl.show_weight is True
    assert tpl.show_allergies is True


def test_the_default_template_carries_its_numbers_too(clinic):
    """Found by the "prints cleanly" test above, and the same root cause.

    ``font_size`` was ``None`` on the fallback template, so every clinic that
    had not built one printed ``font-size:Nonepx`` — invalid, ignored, and the
    prescription came out at whatever size the page around it happened to be.
    ``margin_mm`` was ``None`` too, and ``_side`` turns that into a zero
    margin: printed hard against the edge of the paper.
    """
    from app.models import RxPrintTemplate

    tpl = RxPrintTemplate.default_instance()
    assert tpl.font_size, "font-size:Nonepx is back on the printed page"
    assert tpl.page_size
    assert tpl.m_top and tpl.m_left, "the fallback template prints edge to edge"


def test_turning_the_weight_off_removes_it(clinic):
    rx_id = _rx(clinic, weight=15.5)
    with clinic["app"].app_context():
        from app.models import RxPrintTemplate
        db = clinic["db"]
        db.session.add(RxPrintTemplate(name="bare", mode="white",
                                       is_default=True, show_weight=False,
                                       show_allergies=True))
        db.session.commit()
    body = _paper(clinic, rx_id)
    assert "15.5" not in body, "show_weight=False still prints the weight"


def test_turning_the_allergy_off_removes_it(clinic):
    rx_id = _rx(clinic, allergies="بنسلين")
    with clinic["app"].app_context():
        from app.models import RxPrintTemplate
        db = clinic["db"]
        db.session.add(RxPrintTemplate(name="bare", mode="white",
                                       is_default=True, show_weight=True,
                                       show_allergies=False))
        db.session.commit()
    body = _paper(clinic, rx_id)
    assert "بنسلين" not in body


# --- the parent's copy ----------------------------------------------------

def test_the_family_copy_says_the_same_as_the_doctors(clinic):
    """The one bug this feature cannot afford, in the paper's own words.

    The parent's page and the clinic's page are the same markup on purpose. A
    weight or an allergy that appeared on one and not the other would be two
    different prescriptions with one signature.
    """
    rx_id = _rx(clinic, weight=12.5, allergies="بنسلين")
    with clinic["app"].app_context():
        from app.models import Prescription
        db = clinic["db"]
        rx = db.session.get(Prescription, rx_id)
        rx.share_token = "tok123"
        db.session.commit()

    public = clinic["app"].test_client().get("/prescriptions/copy/tok123")
    assert public.status_code == 200
    body = public.get_data(as_text=True)
    assert "12.5" in body
    assert "بنسلين" in body


# --- the upgrade ----------------------------------------------------------

@pytest.mark.parametrize("column", ["show_weight", "show_allergies"])
def test_an_existing_clinic_gets_the_columns_on_upgrade(column):
    """New columns on an existing table have to be listed, or every clinic
    already running this program meets an OperationalError on the first
    prescription they print after updating.
    """
    from app.utils.schema import ADDITIONS

    assert any(table == "rx_print_templates" and name == column
               for table, name, _ in ADDITIONS), (
        f"{column} is missing from ADDITIONS")


# --- the chronic conditions -----------------------------------------------

def _rx_with_conditions(clinic, conditions):
    with clinic["app"].app_context():
        from app.models import Patient, Prescription
        db = clinic["db"]
        patient = db.session.get(Patient, clinic["ids"]["child"])
        patient.chronic_diseases = conditions
        rx = Prescription(patient_id=patient.id,
                          doctor_id=clinic["ids"]["doctor"],
                          rx_date=date.today())
        db.session.add(rx)
        db.session.commit()
        return rx.id


def test_what_the_child_is_being_treated_for_is_printed(clinic):
    """The other half of what the profile already calls an alert.

    ``chronic_diseases`` sat beside ``allergies`` in ``has_alerts``, showed in
    the red banner on every clinical screen, and never reached the paper. For
    a child with asthma or epilepsy that is context whoever reads this page
    next actually needs.
    """
    rx_id = _rx_with_conditions(clinic, "ربو")
    assert "ربو" in _paper(clinic, rx_id)


def test_a_healthy_child_gets_no_line_about_it(clinic):
    """Deliberately unlike the allergy line, and the asymmetry is the point.

    Silence about an allergy is dangerous ambiguity, so that line speaks even
    when the field is empty. Silence here is the ordinary case — most children
    have no chronic condition — and stamping "none recorded" on every
    prescription the clinic issues would be noise with no safety bought by it.
    """
    rx_id = _rx_with_conditions(clinic, None)
    body = _paper(clinic, rx_id)
    assert "أمراض مزمنة" not in body


def test_whitespace_is_not_a_condition(clinic):
    rx_id = _rx_with_conditions(clinic, "  \n ")
    assert "أمراض مزمنة" not in _paper(clinic, rx_id)


def test_the_clinic_can_turn_the_conditions_off(clinic):
    rx_id = _rx_with_conditions(clinic, "صرع")
    with clinic["app"].app_context():
        from app.models import RxPrintTemplate
        db = clinic["db"]
        db.session.add(RxPrintTemplate(name="bare", mode="white",
                                       is_default=True, show_weight=True,
                                       show_allergies=True,
                                       show_conditions=False))
        db.session.commit()
    assert "صرع" not in _paper(clinic, rx_id)


def test_conditions_can_be_the_only_thing_in_the_band(clinic):
    """The band's own guard has to know about it, or it renders nothing."""
    rx_id = _rx_with_conditions(clinic, "سكر")
    with clinic["app"].app_context():
        from app.models import RxPrintTemplate
        db = clinic["db"]
        db.session.add(RxPrintTemplate(name="only", mode="white",
                                       is_default=True, show_weight=False,
                                       show_allergies=False,
                                       show_conditions=True))
        db.session.commit()
    assert "سكر" in _paper(clinic, rx_id), (
        "the band is gated on weight and allergy, so conditions alone vanish")


def test_conditions_are_on_for_a_clinic_with_no_template(clinic):
    from app.models import RxPrintTemplate

    assert RxPrintTemplate.default_instance().show_conditions is True


def test_an_existing_clinic_gets_the_conditions_column():
    from app.utils.schema import ADDITIONS

    ddl = next(d for t, n, d in ADDITIONS
               if t == "rx_print_templates" and n == "show_conditions")
    assert "1" in ddl, f"show_conditions arrives as {ddl!r}"
