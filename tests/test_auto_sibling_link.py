"""Linking the brother the program is *sure* about — and only that one.

The history import groups children by their father's name, which on real
Egyptian data puts strangers in one household: "محمد أحمد" is not a fact about
a family. So the clinic asked for the 100% matches to be linked without being
asked each time, labelled as the program's doing, with a way back.

Every test here is really about the same question: **what makes a match
certain enough to act on without a person looking?** The answer this settles
on is that one signal is never enough. Two children sharing a guardian's phone
are often cousins in a shop's records; two children sharing the last two words
of a name are often unrelated. A household matching on *both* is one household.

And the link says it was automatic. That is not decoration: somebody deciding
whether to undo it needs to know whether they are correcting a guess or
overruling a colleague who opened both files.
"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def _household(clinic, phone="01001234567", name="زياد محمود سعيد"):
    """This clinic's child, in a family with a guardian's phone on it."""
    from app.models import Family, Parent, Patient

    db = clinic["db"]
    family = Family(family_name="محمود سعيد")
    db.session.add(family)
    db.session.flush()
    patient = db.session.get(Patient, clinic["ids"]["child"])
    patient.full_name = name
    patient.family_id = family.id
    db.session.add(Parent(family_id=family.id, full_name="محمود سعيد",
                          relation="father", phone=phone))
    db.session.commit()
    return patient


def _loose(clinic, name, phone=None, number="P9"):
    """A patient with no family, optionally carrying their own phone."""
    from app.models import Patient

    db = clinic["db"]
    patient = Patient(patient_number=number, full_name=name, gender="male",
                      date_of_birth=date(2022, 3, 1), is_active=True,
                      own_phone=phone)
    db.session.add(patient)
    db.session.commit()
    return patient


# ============================================== what counts as certain ======
def test_both_signals_agreeing_is_a_link(clinic):
    """Same guardian phone, same family part of the name. This is the case
    the clinic wants handled without being asked."""
    from app.utils.siblings import certain_sibling

    with clinic["app"].app_context():
        patient = _household(clinic)
        brother = _loose(clinic, "عمر محمود سعيد", phone="01001234567")
        assert certain_sibling(patient) is not None
        assert certain_sibling(patient).id == brother.id


def test_a_matching_name_alone_is_not_enough(clinic):
    """Two unrelated "محمد أحمد" walk in every week. Linking their files
    merges two children's vaccination histories."""
    from app.utils.siblings import certain_sibling

    with clinic["app"].app_context():
        patient = _household(clinic)
        _loose(clinic, "عمر محمود سعيد")          # no phone at all
        assert certain_sibling(patient) is None


def test_a_matching_phone_alone_is_not_enough(clinic):
    """One shop's number sits on half a street's records, and cousins share a
    grandmother's phone."""
    from app.utils.siblings import certain_sibling

    with clinic["app"].app_context():
        patient = _household(clinic)
        _loose(clinic, "حسن إبراهيم علي", phone="01001234567")
        assert certain_sibling(patient) is None


def test_two_equally_good_matches_is_not_certainty(clinic):
    """It is a coincidence with a witness. Twins registered twice, or a
    duplicated file — either way a person should look."""
    from app.utils.siblings import certain_sibling

    with clinic["app"].app_context():
        patient = _household(clinic)
        _loose(clinic, "عمر محمود سعيد", phone="01001234567", number="P8")
        _loose(clinic, "أدهم محمود سعيد", phone="01001234567", number="P7")
        assert certain_sibling(patient) is None


def test_a_child_who_already_has_a_family_is_never_taken(clinic):
    """Joining two existing families is a merge of two sets of parents, and no
    rule should ever do that on its own."""
    from app.models import Family, Patient
    from app.utils.siblings import certain_sibling

    db = clinic["db"]
    with clinic["app"].app_context():
        patient = _household(clinic)
        brother = _loose(clinic, "عمر محمود سعيد", phone="01001234567")
        theirs = Family(family_name="عائلة تانية")
        db.session.add(theirs)
        db.session.flush()
        db.session.get(Patient, brother.id).family_id = theirs.id
        db.session.commit()

        assert certain_sibling(patient) is None


def test_a_patient_with_no_household_phone_matches_nobody(clinic):
    """Without one of the two signals there is no certainty to be had, and
    falling back to the name alone is the mistake this exists to avoid."""
    from app.models import Family, Patient
    from app.utils.siblings import certain_sibling

    db = clinic["db"]
    with clinic["app"].app_context():
        family = Family(family_name="محمود سعيد")
        db.session.add(family)
        db.session.flush()
        patient = db.session.get(Patient, clinic["ids"]["child"])
        patient.full_name = "زياد محمود سعيد"
        patient.family_id = family.id          # a family, but no parent phone
        db.session.commit()
        _loose(clinic, "عمر محمود سعيد", phone="01001234567")

        assert certain_sibling(patient) is None


# ============================================== and it says it was automatic
def test_the_link_is_marked_as_the_programs_doing(clinic):
    """Somebody deciding whether to undo it needs to know whether they are
    correcting a guess or overruling a colleague."""
    from app.models import Patient

    db = clinic["db"]
    with clinic["app"].app_context():
        patient = _household(clinic)
        brother_id = _loose(clinic, "عمر محمود سعيد",
                            phone="01001234567").id
        pid = patient.id

    clinic["sign_in"]("boss").post(f"/patients/{pid}/siblings/auto",
                                   follow_redirects=True)

    with clinic["app"].app_context():
        brother = db.session.get(Patient, brother_id)
        assert brother.family_id is not None
        assert brother.family_auto is True


def test_the_screen_says_so(clinic):
    from app.i18n import t
    from app.models import Patient

    db = clinic["db"]
    with clinic["app"].app_context():
        patient = _household(clinic)
        _loose(clinic, "عمر محمود سعيد", phone="01001234567")
        pid = patient.id

    client = clinic["sign_in"]("boss")
    client.post(f"/patients/{pid}/siblings/auto", follow_redirects=True)
    page = client.get(f"/patients/{pid}").data.decode()

    with clinic["app"].test_request_context():
        assert t("siblings.auto_flag") in page


def test_a_link_made_by_a_person_is_not_labelled_automatic(clinic):
    """The label has to mean something, so it must not appear on a link a
    receptionist made after looking at both files."""
    from app.models import Patient

    db = clinic["db"]
    with clinic["app"].app_context():
        patient = _household(clinic)
        brother_id = _loose(clinic, "حسن إبراهيم علي").id
        pid = patient.id

    clinic["sign_in"]("boss").post(f"/patients/{pid}/siblings/link",
                                   data={"sibling_id": brother_id},
                                   follow_redirects=True)

    with clinic["app"].app_context():
        assert db.session.get(Patient, brother_id).family_auto is False


def test_unlinking_clears_the_label_too(clinic):
    """A child linked again by hand tomorrow must not still be claiming the
    program did it."""
    from app.models import Patient

    db = clinic["db"]
    with clinic["app"].app_context():
        patient = _household(clinic)
        brother_id = _loose(clinic, "عمر محمود سعيد", phone="01001234567").id
        pid = patient.id

    client = clinic["sign_in"]("boss")
    client.post(f"/patients/{pid}/siblings/auto", follow_redirects=True)
    client.post(f"/patients/{pid}/siblings/unlink",
                data={"sibling_id": brother_id}, follow_redirects=True)

    with clinic["app"].app_context():
        brother = db.session.get(Patient, brother_id)
        assert brother.family_id is None
        assert brother.family_auto is False


def test_it_is_a_press_rather_than_something_that_happens_on_save(clinic):
    """The import already groups by the father's name and gets it wrong on
    real data. More of that happening invisibly is how a clinic stops trusting
    every family on the screen — so nothing links until somebody asks."""
    from app.models import Patient

    db = clinic["db"]
    with clinic["app"].app_context():
        patient = _household(clinic)
        brother_id = _loose(clinic, "عمر محمود سعيد", phone="01001234567").id
        pid = patient.id

    # Merely looking at the file must change nothing.
    clinic["sign_in"]("boss").get(f"/patients/{pid}")

    with clinic["app"].app_context():
        assert db.session.get(Patient, brother_id).family_id is None


def test_nothing_certain_says_so_instead_of_linking_anything(clinic):
    from app.i18n import t
    from app.models import Patient

    db = clinic["db"]
    with clinic["app"].app_context():
        patient = _household(clinic)
        stranger_id = _loose(clinic, "حسن إبراهيم علي").id
        pid = patient.id

    page = clinic["sign_in"]("boss").post(
        f"/patients/{pid}/siblings/auto", follow_redirects=True).data.decode()

    with clinic["app"].test_request_context():
        assert t("siblings.no_certain_match") in page
    with clinic["app"].app_context():
        assert db.session.get(Patient, stranger_id).family_id is None
