"""What actually comes out of the printer, and the one line that emptied it.

The report was a list of separate holes — *"the drugs aren't showing, I didn't
see the doctor's name … where is the signature, there's no stamp"* — and it
read like a dozen small omissions in the layout. It was one:

    @classmethod
    def default_instance(cls):
        \"\"\"A transient, fully-on white template used when none is configured.\"\"\"
        return cls(name="default", mode="white", logo_source="clinic")

``default=True`` on a Column is applied by the database at INSERT, and this
object is never inserted. So every ``show_*`` on it was ``None``, and any
clinic that had not built a print template printed with no doctor's name, no
specialty, no licence, no patient block, no diagnosis, no signature and no
stamp. The docstring said "fully-on" the entire time — it described the
intention, and nothing checked it. That is what these tests are for.

The rest is the paper as it was asked for: the patient above the clinical
part, the diagnosis carrying how settled it is, the complaint in the family's
own words, and a line the doctor can keep in the record without handing it to
the family.
"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def _write(client, patient_id, **extra):
    data = {
        "patient_id": patient_id,
        "item_name": ["Augmentin"], "item_dose": ["5 ml"],
        "item_frequency": ["×2"], "item_duration": ["7d"],
        "item_instructions": [""],
    }
    data.update(extra)
    return client.post("/prescriptions/new", data=data, follow_redirects=True)


# ================================================ the template that was empty
def test_a_clinic_with_no_print_template_still_prints_everything(clinic):
    """The bug, at its source.

    A brand-new clinic has no ``rx_print_templates`` row, so every printout
    goes through the transient default — and every flag on it was None.
    """
    from app.models import RxPrintTemplate

    with clinic["app"].app_context():
        tpl = RxPrintTemplate.default_instance()
        off = [flag for flag in RxPrintTemplate.BOOLS if not getattr(tpl, flag)]
        assert not off, (
            "these sections would silently vanish from every prescription in a "
            "clinic that never built a template: " + ", ".join(off))


def test_the_doctor_and_the_patient_reach_the_paper(clinic):
    """End to end, through the screen, on a clinic with no template — which is
    the state the reporting clinic was in."""
    from app.models import Patient, User

    db = clinic["db"]
    with clinic["app"].app_context():
        doctor = db.session.get(User, clinic["ids"]["doctor"])
        doctor.is_practitioner = True
        db.session.commit()
        patient = db.session.get(Patient, clinic["ids"]["child"])
        pid, number = patient.id, patient.patient_number

    client = clinic["sign_in"]("doc")
    page = _write(client, pid, diagnosis="التهاب رئوي").data.decode()

    assert "Augmentin" in page
    assert number in page, "the patient block was missing from the printout"
    assert "التهاب رئوي" in page
    with clinic["app"].app_context():
        doctor = db.session.get(User, clinic["ids"]["doctor"])
        assert doctor.doctor_print_name("ar") in page, "no doctor on the paper"


# ================================================ how a doctor is addressed ==
def test_every_doctor_is_addressed_and_a_professor_differently(clinic):
    """Asked for in these words: Arabic names take د/ and English Dr., unless
    the classification is professor, which takes أ.د/ and Prof. Dr."""
    from app.models import User

    db = clinic["db"]
    with clinic["app"].app_context():
        plain = db.session.get(User, clinic["ids"]["doctor"])
        plain.full_name = "منى حسن"
        plain.professional_title = None
        prof = User(username="prof", full_name="أحمد سمير", role="doctor",
                    is_active=True, professional_title="Professor")
        prof.set_password("x")
        db.session.add(prof)
        db.session.commit()

        assert plain.doctor_print_name("ar") == "د/ منى حسن"
        assert plain.doctor_print_name("en") == "Dr. منى حسن"
        assert prof.doctor_print_name("ar") == "أ.د/ أحمد سمير"
        assert prof.doctor_print_name("en") == "Prof. Dr. أحمد سمير"


def test_the_english_title_no_longer_lands_on_an_arabic_name(clinic):
    """It used to print ``professional_title`` verbatim, so an Arabic
    prescription read "Consultant منى حسن"."""
    from app.models import User

    db = clinic["db"]
    with clinic["app"].app_context():
        doctor = db.session.get(User, clinic["ids"]["doctor"])
        doctor.full_name = "منى حسن"
        doctor.professional_title = "Consultant"
        db.session.commit()
        assert "Consultant" not in doctor.doctor_print_name("ar")
        assert doctor.doctor_print_name("ar") == "د/ منى حسن"


def test_a_name_already_carrying_a_title_is_left_alone(clinic):
    """Clinics type "د/ أحمد" into the name field. Prefixing that again gives
    "د/ د/ أحمد" — the usual way a rule like this shows up in production."""
    from app.models import User

    db = clinic["db"]
    with clinic["app"].app_context():
        doctor = db.session.get(User, clinic["ids"]["doctor"])
        for typed in ("د/ أحمد", "Dr. Ahmed", "أ.د/ سمير"):
            doctor.full_name = typed
            assert doctor.doctor_print_name("ar") == typed


def test_a_deliberate_prescription_name_still_wins(clinic):
    """``rx_display_name`` is somebody's exact wording for their own paper."""
    from app.models import User

    db = clinic["db"]
    with clinic["app"].app_context():
        doctor = db.session.get(User, clinic["ids"]["doctor"])
        doctor.rx_display_name = "العيادة التخصصية للأطفال"
        assert doctor.doctor_print_name("ar") == "العيادة التخصصية للأطفال"


# ================================================ the paper's structure =====
def test_the_diagnosis_says_how_settled_it_is(clinic):
    """"التهاب رئوي" alone does not tell a guardian — or the next doctor —
    whether this is decided or still being worked out."""
    from app.i18n import t
    from app.models import Patient

    db = clinic["db"]
    with clinic["app"].app_context():
        pid = db.session.get(Patient, clinic["ids"]["child"]).id

    page = _write(clinic["sign_in"]("doc"), pid, diagnosis="التهاب رئوي",
                  diagnosis_stage="provisional").data.decode()
    with clinic["app"].test_request_context():
        assert t("rx.stage_provisional") in page


def test_an_ungraded_diagnosis_is_not_invented_as_final(clinic):
    """Plenty of prescriptions carry a diagnosis nobody wants to grade.
    Defaulting would print a certainty the doctor never claimed."""
    from app.models import Patient, Prescription

    db = clinic["db"]
    with clinic["app"].app_context():
        pid = db.session.get(Patient, clinic["ids"]["child"]).id

    _write(clinic["sign_in"]("doc"), pid, diagnosis="التهاب رئوي")
    with clinic["app"].app_context():
        assert Prescription.query.one().diagnosis_stage is None


def test_a_bad_stage_is_dropped_rather_than_stored(clinic):
    from app.models import Patient, Prescription

    db = clinic["db"]
    with clinic["app"].app_context():
        pid = db.session.get(Patient, clinic["ids"]["child"]).id

    _write(clinic["sign_in"]("doc"), pid, diagnosis="x",
           diagnosis_stage="definitely-probably")
    with clinic["app"].app_context():
        assert Prescription.query.one().diagnosis_stage is None


def test_the_complaint_is_kept_apart_from_the_diagnosis(clinic):
    """One is what the family said, the other is what the doctor concluded.
    Printed as separate sections because they are separate claims."""
    from app.models import Patient

    db = clinic["db"]
    with clinic["app"].app_context():
        pid = db.session.get(Patient, clinic["ids"]["child"]).id

    page = _write(clinic["sign_in"]("doc"), pid, complaint="كحة من ٣ أيام",
                  diagnosis="التهاب رئوي").data.decode()
    assert "كحة من ٣ أيام" in page and "التهاب رئوي" in page


# ================================================ leaving a line off the paper
def test_a_line_can_be_kept_in_the_record_and_off_the_printout(clinic):
    """A medicine being stopped, or a note to the next doctor. It belongs in
    the file; it does not belong in the family's hands."""
    from app.models import Patient, Prescription

    db = clinic["db"]
    with clinic["app"].app_context():
        pid = db.session.get(Patient, clinic["ids"]["child"]).id

    page = _write(
        clinic["sign_in"]("doc"), pid,
        item_name=["Augmentin", "Ventolin"], item_dose=["5 ml", "2 puffs"],
        item_frequency=["×2", "×3"], item_duration=["7d", "5d"],
        item_instructions=["", ""], item_hidden=["1"]).data.decode()

    with clinic["app"].app_context():
        kept = {i.drug_name: i.printed for i in Prescription.query.one().items}
        assert kept == {"Augmentin": True, "Ventolin": False}

    printed = page.split("℞", 1)[1].split("</table>", 1)[0]
    assert "Augmentin" in printed
    assert "Ventolin" not in printed, "an excluded medicine reached the paper"


def test_nothing_is_left_off_unless_it_was_asked_for(clinic):
    """The default has to be *printed*. A doctor's line disappearing from the
    paper because a box defaulted the wrong way is a prescribing error."""
    from app.models import Patient, Prescription

    db = clinic["db"]
    with clinic["app"].app_context():
        pid = db.session.get(Patient, clinic["ids"]["child"]).id

    _write(clinic["sign_in"]("doc"), pid,
           item_name=["A", "B", "C"], item_dose=["", "", ""],
           item_frequency=["", "", ""], item_duration=["", "", ""],
           item_instructions=["", "", ""])
    with clinic["app"].app_context():
        assert all(i.printed for i in Prescription.query.one().items)


# ================================================ finding the patient =======
def test_the_patient_is_searched_for_rather_than_scrolled_to(clinic):
    """The dropdown it replaces was capped at 500 names in alphabetical order,
    so a clinic with thousands of files simply stopped mid-alphabet and the
    child appeared not to be in the program at all."""
    from app.models import Patient

    db = clinic["db"]
    with clinic["app"].app_context():
        patient = db.session.get(Patient, clinic["ids"]["child"])
        patient.full_name = "زياد محمود"
        db.session.commit()

    client = clinic["sign_in"]("doc")
    found = client.get("/prescriptions/patient-search?q=زياد").get_json()
    assert [row["name"] for row in found] == ["زياد محمود"]
    # A bare array, because that is what the shared picker widget consumes.
    assert isinstance(found, list)


def test_one_letter_is_not_a_search(clinic):
    """Otherwise the first keystroke asks for the whole register."""
    client = clinic["sign_in"]("doc")
    assert client.get("/prescriptions/patient-search?q=ز").get_json() == []


def test_a_prescription_opened_from_a_file_cannot_change_patient(clinic):
    """Asked for directly: when it arrives from a child's file the patient is
    settled, and a picker there can only be used to get it wrong."""
    from app.models import Patient

    db = clinic["db"]
    with clinic["app"].app_context():
        pid = db.session.get(Patient, clinic["ids"]["child"]).id

    page = clinic["sign_in"]("doc").get(
        f"/prescriptions/new?patient_id={pid}").data.decode()
    assert f'name="patient_id" value="{pid}"' in page
    assert 'name="patient_id" required' not in page


def test_a_doctor_writing_a_prescription_signs_it_themselves(clinic):
    """A list that lets one doctor put another's name on a signed document is
    a list that will eventually be used that way by accident."""
    from app.models import User

    db = clinic["db"]
    with clinic["app"].app_context():
        doctor = db.session.get(User, clinic["ids"]["doctor"])
        doctor.is_practitioner = True
        db.session.commit()
        doctor_id = doctor.id

    page = clinic["sign_in"]("doc").get("/prescriptions/new").data.decode()
    assert f'name="doctor_id" value="{doctor_id}"' in page
    assert 'name="doctor_id"' in page and "<select class=\"select\" name=\"doctor_id\"" not in page


def test_an_admin_who_does_not_examine_still_gets_the_picker(clinic):
    """Somebody has to be able to write one on a doctor's behalf."""
    page = clinic["sign_in"]("boss").get("/prescriptions/new").data.decode()
    assert '<select class="select" name="doctor_id"' in page
