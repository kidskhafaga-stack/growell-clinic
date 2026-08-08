"""Undoing a bad family link, and giving each doctor their own words.

**The family that should not have existed.** The history import links children
by their father's name, and on messy data that groups the wrong children under
one man. Until now the only way out was to unlink each child one at a time and
leave the empty family behind — so the wrong grouping stayed on the screen,
and nobody could tell a real family from an import artefact.

The dangerous version of this fix is the obvious one: delete the family and
let the cascade take whatever is attached. A family is a **grouping**, not a
container. Removing the grouping must never remove a patient's file, and that
is the thing worth a test with the reason written next to it.

**Quick phrases.** They were one list for the whole clinic. The sentences a
paediatrician reaches for are not a dermatologist's, and a shared list grows
until typing is faster than finding — so each doctor keeps their own, falling
back to the clinic's rather than to nothing.
"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def _family_with_two(clinic):
    """A family holding this clinic's child and a sibling."""
    from app.models import Family, Parent, Patient

    db = clinic["db"]
    family = Family(family_name="عائلة محمود")
    db.session.add(family)
    db.session.flush()
    first = db.session.get(Patient, clinic["ids"]["child"])
    first.family_id = family.id
    second = Patient(patient_number="P2", full_name="أخ", gender="male",
                     date_of_birth=date(2023, 5, 1), is_active=True,
                     family_id=family.id)
    db.session.add(second)
    db.session.add(Parent(family_id=family.id, full_name="محمود",
                          relation="father", phone="01001234567"))
    db.session.commit()
    return family.id, first.id, second.id


# ================================================== deleting a family =======
def test_deleting_a_family_keeps_every_child(clinic):
    """The whole risk of this feature in one assertion.

    A cascade here would delete two children's complete records — vaccination
    history, visits, invoices — because somebody wanted to undo a bad import
    link. The files stay; only the grouping goes.
    """
    from app.models import Family, Patient

    db = clinic["db"]
    with clinic["app"].app_context():
        family_id, first_id, second_id = _family_with_two(clinic)

    clinic["sign_in"]("boss").post(f"/patients/families/{family_id}/delete",
                                   follow_redirects=True)

    with clinic["app"].app_context():
        assert db.session.get(Family, family_id) is None
        for pid in (first_id, second_id):
            patient = db.session.get(Patient, pid)
            assert patient is not None, "a patient file was deleted with the family"
            assert patient.family_id is None


def test_the_parents_go_with_the_family_they_described(clinic):
    """A parent row belongs to the family, not to any one child. Left behind
    it would point at nothing and show up in searches for ever."""
    from app.models import Parent

    db = clinic["db"]
    with clinic["app"].app_context():
        family_id, _, _ = _family_with_two(clinic)
        assert Parent.query.count() == 1

    clinic["sign_in"]("boss").post(f"/patients/families/{family_id}/delete",
                                   follow_redirects=True)

    with clinic["app"].app_context():
        assert Parent.query.count() == 0


def test_the_children_can_be_regrouped_afterwards(clinic):
    """Undoing a bad link is only useful if the right one can be made next."""
    from app.models import Patient

    db = clinic["db"]
    with clinic["app"].app_context():
        family_id, first_id, second_id = _family_with_two(clinic)

    client = clinic["sign_in"]("boss")
    client.post(f"/patients/families/{family_id}/delete", follow_redirects=True)
    client.post(f"/patients/{first_id}/siblings/link",
                data={"sibling_id": second_id}, follow_redirects=True)

    with clinic["app"].app_context():
        first = db.session.get(Patient, first_id)
        second = db.session.get(Patient, second_id)
        assert first.family_id and first.family_id == second.family_id


def test_the_delete_button_is_beside_the_edit_button(clinic):
    """Asked for in those words, and a route with no way to reach it is the
    same as no route."""
    from app.models import Patient

    db = clinic["db"]
    with clinic["app"].app_context():
        family_id, pid, _ = _family_with_two(clinic)

    page = clinic["sign_in"]("boss").get(f"/patients/{pid}").data.decode()
    assert f"/patients/families/{family_id}/delete" in page
    # Next to the edit form for the same family, not stranded elsewhere.
    assert f"/patients/families/{family_id}/edit" in page


# ================================================== a doctor's own phrases ==
def test_a_doctor_sees_their_own_quick_phrases(clinic):
    """One clinic-wide list is the wrong shape: it grows until finding a
    phrase costs more than typing the sentence."""
    from app.models import User, Visit

    db = clinic["db"]
    with clinic["app"].app_context():
        doctor = db.session.get(User, clinic["ids"]["doctor"])
        doctor.visit_complaint_chips = "كحة ليلية|Night cough"
        db.session.commit()
        visit_id = db.session.get(Visit, clinic["ids"]["visit"]).id

    page = clinic["sign_in"]("doc").get(
        f"/visits/{visit_id}/record").data.decode()
    assert "كحة ليلية" in page
    # And the clinic-wide defaults stepped aside rather than piling up.
    assert "تسنين" not in page


def test_a_doctor_who_set_nothing_still_gets_a_full_palette(clinic):
    """Falling back to the clinic's list, not to an empty row of chips — a
    doctor's first consultation should not be the one where the feature looks
    broken."""
    from app.models import Visit

    db = clinic["db"]
    with clinic["app"].app_context():
        visit_id = db.session.get(Visit, clinic["ids"]["visit"]).id

    page = clinic["sign_in"]("doc").get(
        f"/visits/{visit_id}/record").data.decode()
    assert "تسنين" in page, "the clinic's defaults did not come through"


def test_the_clinic_list_is_the_fallback_not_the_ceiling(clinic):
    """A clinic list set by the admin is a starting point. A doctor who has
    written their own is not asking to see both."""
    from app.models import Setting, User, Visit

    db = clinic["db"]
    with clinic["app"].app_context():
        Setting.set("visit_complaint_chips", "شكوى العيادة|Clinic complaint")
        doctor = db.session.get(User, clinic["ids"]["doctor"])
        doctor.visit_complaint_chips = "شكواي أنا|Mine"
        db.session.commit()
        visit_id = db.session.get(Visit, clinic["ids"]["visit"]).id

    page = clinic["sign_in"]("doc").get(
        f"/visits/{visit_id}/record").data.decode()
    assert "شكواي أنا" in page
    assert "شكوى العيادة" not in page


def test_clearing_the_box_means_use_the_clinics(clinic):
    """Not "I have none". An empty palette would be a worse consultation than
    the shared list this replaced."""
    from app.models import Setting, User, Visit

    db = clinic["db"]
    with clinic["app"].app_context():
        Setting.set("visit_complaint_chips", "شكوى العيادة|Clinic complaint")
        doctor = db.session.get(User, clinic["ids"]["doctor"])
        doctor.visit_complaint_chips = "مؤقت|Temp"
        db.session.commit()
        visit_id = db.session.get(Visit, clinic["ids"]["visit"]).id

    clinic["sign_in"]("doc").post(
        "/profile", data={"full_name": "د. أحمد", "visit_complaint_chips": ""},
        follow_redirects=True)

    with clinic["app"].app_context():
        doctor = db.session.get(User, clinic["ids"]["doctor"])
        assert doctor.visit_complaint_chips is None

    page = clinic["sign_in"]("doc").get(
        f"/visits/{visit_id}/record").data.decode()
    assert "شكوى العيادة" in page


def test_a_doctor_can_reach_the_editor_from_their_profile(clinic):
    """The phrases are theirs, so they are edited where the rest of their own
    settings live — not in the clinic-wide settings screen."""
    page = clinic["sign_in"]("doc").get("/profile").data.decode()
    assert 'name="visit_complaint_chips"' in page
    assert 'name="visit_exam_chips"' in page
