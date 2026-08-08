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


# ============================================== the merge that was refused ==
def _split_household(clinic):
    """The state a real clinic's database was in.

    Two siblings from one import, in two family records — because the import
    split them — with the guardian's phone attached to one of the two.
    """
    from app.models import Family, Parent, Patient

    db = clinic["db"]
    first = Family(family_name="Mohammed Khafaga")
    second = Family(family_name="محمد السيد خفاجه")
    db.session.add_all([first, second])
    db.session.flush()
    db.session.add(Parent(family_id=second.id, full_name="محمد السيد",
                          relation="father", phone="01005551234"))
    omar = db.session.get(Patient, clinic["ids"]["child"])
    omar.full_name = "عمر محمد السيد خفاجة"
    omar.family_id = first.id
    meral = Patient(patient_number="P5", full_name="ميرال محمد السيد خفاجه",
                    gender="female", date_of_birth=date(2020, 6, 1),
                    is_active=True, family_id=second.id)
    db.session.add(meral)
    db.session.commit()
    return omar.id, meral.id, second.id


def test_a_sibling_already_in_a_family_can_finally_be_linked(clinic):
    """The bug a clinic reported with names.

    "عمر محمد السيد خفاجة" and "ميرال محمد السيد خفاجه" arrived from one import
    in two families. The screen suggested each to the other and refused every
    attempt to act on it — and renaming either family changed nothing, because
    the problem was never the name.

    I wrote that refusal deliberately: joining two households is a merge of two
    sets of parents. The clinic showed why it was the wrong call. The
    commonest case is not two households — it is one household the program
    itself divided, and refusing left the only way out as deleting a family by
    hand.
    """
    from app.models import Patient

    db = clinic["db"]
    with clinic["app"].app_context():
        omar_id, meral_id, _ = _split_household(clinic)

    clinic["sign_in"]("boss").post(f"/patients/{omar_id}/siblings/link",
                                   data={"sibling_id": meral_id},
                                   follow_redirects=True)

    with clinic["app"].app_context():
        omar = db.session.get(Patient, omar_id)
        meral = db.session.get(Patient, meral_id)
        assert omar.family_id == meral.family_id, "the link was refused again"


def test_the_emptied_family_does_not_linger(clinic):
    """Left behind, it keeps the guardian's phone attached to a household with
    no children — invisible on every screen and still turning up in searches."""
    from app.models import Family

    db = clinic["db"]
    with clinic["app"].app_context():
        omar_id, meral_id, old_family_id = _split_household(clinic)

    clinic["sign_in"]("boss").post(f"/patients/{omar_id}/siblings/link",
                                   data={"sibling_id": meral_id},
                                   follow_redirects=True)

    with clinic["app"].app_context():
        assert db.session.get(Family, old_family_id) is None


def test_the_guardian_survives_the_merge(clinic):
    """The phone number is the whole reason the family record existed.

    ``Family.parents`` cascades delete-orphan, so a parent still in the old
    family's collection when it is deleted goes with it — reassigning
    ``family_id`` alone silently loses the guardian, which the first version of
    this did.
    """
    from app.models import Parent, Patient

    db = clinic["db"]
    with clinic["app"].app_context():
        omar_id, meral_id, _ = _split_household(clinic)

    clinic["sign_in"]("boss").post(f"/patients/{omar_id}/siblings/link",
                                   data={"sibling_id": meral_id},
                                   follow_redirects=True)

    with clinic["app"].app_context():
        omar = db.session.get(Patient, omar_id)
        phones = {p.phone for p in omar.family.parents}
        assert "01005551234" in phones, "the guardian's phone was lost"
        assert Parent.query.filter(Parent.family_id.is_(None)).count() == 0


def test_the_same_guardian_is_not_recorded_twice(clinic):
    """Both families usually carry the same father, because both were built
    from the same import."""
    from app.models import Parent, Patient

    db = clinic["db"]
    with clinic["app"].app_context():
        omar_id, meral_id, _ = _split_household(clinic)
        omar = db.session.get(Patient, omar_id)
        db.session.add(Parent(family_id=omar.family_id, full_name="محمد السيد",
                              relation="father", phone="01005551234"))
        db.session.commit()

    clinic["sign_in"]("boss").post(f"/patients/{omar_id}/siblings/link",
                                   data={"sibling_id": meral_id},
                                   follow_redirects=True)

    with clinic["app"].app_context():
        omar = db.session.get(Patient, omar_id)
        assert len(omar.family.parents) == 1


def test_a_family_with_other_children_is_left_alone(clinic):
    """Moving one child out of a real household must not delete it, nor take
    the guardians away from the siblings still in it."""
    from app.models import Family, Patient

    db = clinic["db"]
    with clinic["app"].app_context():
        omar_id, meral_id, old_family_id = _split_household(clinic)
        db.session.add(Patient(patient_number="P6", full_name="ياسين محمد السيد",
                               gender="male", date_of_birth=date(2016, 2, 1),
                               is_active=True, family_id=old_family_id))
        db.session.commit()

    clinic["sign_in"]("boss").post(f"/patients/{omar_id}/siblings/link",
                                   data={"sibling_id": meral_id},
                                   follow_redirects=True)

    with clinic["app"].app_context():
        old = db.session.get(Family, old_family_id)
        assert old is not None, "a family with children in it was deleted"
        assert len(old.parents) == 1
        assert [p.full_name for p in old.patients] == ["ياسين محمد السيد"]


def test_the_screen_offers_the_button_it_used_to_withhold(clinic):
    """The row said "in another family" and gave a link to their file. That is
    a dead end when what you need is to join them."""
    db = clinic["db"]
    with clinic["app"].app_context():
        omar_id, _, _ = _split_household(clinic)

    page = clinic["sign_in"]("boss").get(f"/patients/{omar_id}").data.decode()
    assert f"/patients/{omar_id}/siblings/link" in page
    assert ':disabled="p.in_family"' not in page
