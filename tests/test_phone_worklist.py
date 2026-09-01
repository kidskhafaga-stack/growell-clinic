"""A count you can act on.

Reported: *"the 13 cases are a number in a notification right now — I want a
screen reception can ring from and add the number on."*

A count says something is wrong. It is not a way to put it right: acting on it
meant opening a patient's file, finding the field, saving, going back, and
doing that thirteen times. So it stayed thirteen.

Looking at it turned up a second, worse gap the notification did not cover.
The existing one counts **teenagers without a personal number** — the family is
reachable, the young person is not. Nothing counted the children where **nobody
on the file has a number at all**: no appointment reminder, no call about a
result, no way to say the clinic is shut today. That one costs somebody a
visit, and it was invisible until the day somebody needed to ring.

The two are kept apart on purpose, in the code and on the screen. Adding them
together would produce one number that is urgent for some of its members and
routine for the rest, which is how a list stops being worked.
"""
import os
import sys
from datetime import timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# The clinic's today, not the server's — the same clock the
# screens filter by. See conftest.py.
from app.utils.clock import local_today  # noqa: E402

import pytest  # noqa: E402

TEEN_DOB = local_today() - timedelta(days=365 * 15)
TODDLER_DOB = local_today() - timedelta(days=365 * 3)


@pytest.fixture()
def book(clinic):
    """Four children covering the cases that matter."""
    from app.models import Family, Parent, Patient

    with clinic["app"].app_context():
        db = clinic["db"]
        reachable = Family(family_name="عائلة موصولة")
        silent = Family(family_name="عائلة مقطوعة")
        db.session.add_all([reachable, silent])
        db.session.flush()
        db.session.add_all([
            Parent(family_id=reachable.id, full_name="أم موصولة",
                   phone="01001234567", is_primary_contact=True),
            Parent(family_id=silent.id, full_name="أم مقطوعة",
                   is_primary_contact=True),
        ])

        rows = {
            # Teen, family reachable, no own number → the existing count.
            "teen": Patient(patient_number="P-TEEN", full_name="مراهق",
                            gender="male", date_of_birth=TEEN_DOB,
                            family_id=reachable.id, is_active=True),
            # Nobody has a number anywhere → the harder list.
            "silent": Patient(patient_number="P-SILENT", full_name="طفل مقطوع",
                              gender="female", date_of_birth=TODDLER_DOB,
                              family_id=silent.id, is_active=True),
            # Teen with a family that cannot be rung either.
            "both": Patient(patient_number="P-BOTH", full_name="مراهق مقطوع",
                            gender="male", date_of_birth=TEEN_DOB,
                            family_id=silent.id, is_active=True),
            # Fine: has their own number.
            "ok": Patient(patient_number="P-OK", full_name="طفل تمام",
                          gender="male", date_of_birth=TODDLER_DOB,
                          own_phone="01112223334", family_id=reachable.id,
                          is_active=True),
        }
        db.session.add_all(rows.values())
        db.session.commit()
        ids = {k: v.id for k, v in rows.items()}
    return {**clinic, "who": ids}


@pytest.fixture()
def desk(clinic):
    return clinic["sign_in"]("desk")


def _names(rows):
    return {r["patient"].full_name for r in rows}


# ------------------------------------------------- what lands on which list -
def test_a_child_nobody_can_be_rung_about_is_listed(book):
    from app.utils.phonebook import unreachable

    with book["app"].app_context():
        assert "طفل مقطوع" in _names(unreachable())


def test_a_child_with_a_reachable_guardian_is_not(book):
    """The guardian's number is a way to reach the child. Listing them as
    unreachable would bury the ones who genuinely are."""
    from app.utils.phonebook import unreachable

    with book["app"].app_context():
        names = _names(unreachable())
        assert "مراهق" not in names
        assert "طفل تمام" not in names


def test_a_teen_with_no_number_of_their_own_is_on_the_other_list(book):
    from app.utils.phonebook import teens_without_own_phone

    with book["app"].app_context():
        assert "مراهق" in _names(teens_without_own_phone())


def test_a_young_child_is_not_expected_to_have_their_own_phone(book):
    from app.utils.phonebook import teens_without_own_phone

    with book["app"].app_context():
        assert "طفل مقطوع" not in _names(teens_without_own_phone())


def test_nobody_appears_on_both_lists(book):
    """A teen whose family also has no number is already the harder problem.
    Counting them twice makes the two totals add up to more than the work."""
    from app.utils.phonebook import teens_without_own_phone, unreachable

    with book["app"].app_context():
        hard, teens = _names(unreachable()), _names(teens_without_own_phone())
        assert hard & teens == set()
        assert "مراهق مقطوع" in hard


def test_an_inactive_patient_is_not_chased(book):
    """A closed file is not a phone call somebody has to make."""
    from app.models import Patient
    from app.utils.phonebook import unreachable

    with book["app"].app_context():
        book["db"].session.get(Patient, book["who"]["silent"]).is_active = False
        book["db"].session.commit()
        assert "طفل مقطوع" not in _names(unreachable())


def test_the_two_counts_are_kept_apart(book):
    """Counted by name rather than by a bare number: the shared clinic fixture
    also contains a child with no phone and no family, and an expected total
    that quietly included them would pass while measuring the wrong thing."""
    from app.utils.phonebook import worklist

    with book["app"].app_context():
        data = worklist()
        hard, teens = _names(data["unreachable"]), _names(data["teens"])
        assert {"طفل مقطوع", "مراهق مقطوع"} <= hard
        assert teens == {"مراهق"}
        assert data["counts"]["unreachable"] == len(data["unreachable"])
        assert data["counts"]["teens"] == len(data["teens"])
        assert data["counts"]["total"] == (data["counts"]["unreachable"]
                                           + data["counts"]["teens"])


# ------------------------------------------------------ what the row gives --
def test_a_row_carries_the_number_to_ring(book):
    """A list telling reception to phone somebody without giving the number is
    a list worked with the patient file open in a second tab."""
    from app.utils.phonebook import teens_without_own_phone

    with book["app"].app_context():
        row = next(r for r in teens_without_own_phone()
                   if r["patient"].full_name == "مراهق")
        assert row["phone"] == "01001234567"
        assert row["guardian_name"]


def test_a_row_says_which_field_it_writes(book):
    """A teen's own number and their mother's are different facts. One box
    that quietly picks is a box that quietly picks wrong."""
    from app.utils.phonebook import teens_without_own_phone, unreachable

    with book["app"].app_context():
        teen = next(r for r in teens_without_own_phone())
        assert teen["target"] == "own"
        toddler = next(r for r in unreachable()
                       if r["patient"].full_name == "طفل مقطوع")
        assert toddler["target"] == "guardian"


def test_a_child_with_no_guardian_row_writes_to_their_own_field(book):
    """There is nowhere else to put it, and refusing to save would leave the
    row on the list forever."""
    from app.models import Patient
    from app.utils.phonebook import unreachable

    with book["app"].app_context():
        book["db"].session.add(Patient(
            patient_number="P-ALONE", full_name="طفل بلا ملف أسرة",
            gender="male", date_of_birth=TODDLER_DOB, is_active=True))
        book["db"].session.commit()
        row = next(r for r in unreachable()
                   if r["patient"].full_name == "طفل بلا ملف أسرة")
        assert row["target"] == "own"
        assert row["guardian_id"] is None


# ------------------------------------------------------------- saving ------
def test_saving_puts_the_number_on_the_guardian(book, desk):
    from app.models import Parent, Patient

    reply = desk.post("/patients/phones/save", data={
        "patient_id": book["who"]["silent"], "target": "guardian",
        "guardian_id": _guardian_id(book, "silent"),
        "phone": "01234567890"}, follow_redirects=True)
    assert reply.status_code == 200
    with book["app"].app_context():
        patient = book["db"].session.get(Patient, book["who"]["silent"])
        parent = Parent.query.filter_by(family_id=patient.family_id).first()
        assert parent.phone and parent.phone.endswith("1234567890")
        assert not (patient.own_phone or "")


def test_saving_puts_a_teens_number_on_the_teen(book, desk):
    from app.models import Patient

    desk.post("/patients/phones/save", data={
        "patient_id": book["who"]["teen"], "target": "own",
        "phone": "01098765432"}, follow_redirects=True)
    with book["app"].app_context():
        assert book["db"].session.get(
            Patient, book["who"]["teen"]).own_phone.endswith("1098765432")


def test_saving_comes_back_to_the_list(book, desk):
    """Not into the patient's file. Working through thirteen of these without
    leaving the screen is the entire request."""
    reply = desk.post("/patients/phones/save", data={
        "patient_id": book["who"]["teen"], "target": "own",
        "phone": "01098765432"})
    assert reply.status_code == 302
    assert "/patients/phones" in reply.headers["Location"]


def test_a_saved_row_leaves_the_list(book, desk):
    from app.utils.phonebook import worklist

    desk.post("/patients/phones/save", data={
        "patient_id": book["who"]["teen"], "target": "own",
        "phone": "01098765432"}, follow_redirects=True)
    with book["app"].app_context():
        assert "مراهق" not in _names(worklist()["teens"])


def test_a_number_with_no_digits_is_refused(book, desk):
    """Storing punctuation somebody typed by accident is worse than the blank
    it replaced: the blank is on this list and the non-number is not."""
    from app.models import Patient

    desk.post("/patients/phones/save", data={
        "patient_id": book["who"]["teen"], "target": "own",
        "phone": "-- --"}, follow_redirects=True)
    with book["app"].app_context():
        assert not (book["db"].session.get(
            Patient, book["who"]["teen"]).own_phone or "")


def test_a_number_cannot_be_written_onto_another_familys_guardian(book, desk):
    """The guardian id comes off a form, so it has to be checked against the
    patient it claims to belong to."""
    from app.models import Parent

    other = _guardian_id(book, "teen")   # the reachable family's mother
    desk.post("/patients/phones/save", data={
        "patient_id": book["who"]["silent"], "target": "guardian",
        "guardian_id": other, "phone": "01555555555"}, follow_redirects=True)
    with book["app"].app_context():
        parent = book["db"].session.get(Parent, other)
        assert parent.phone == "01001234567", "another family's number was overwritten"


def _guardian_id(book, key):
    from app.models import Parent, Patient

    with book["app"].app_context():
        patient = book["db"].session.get(Patient, book["who"][key])
        return Parent.query.filter_by(family_id=patient.family_id).first().id


# ------------------------------------------------------------- the screen --
def test_the_screen_opens_and_shows_both_groups(book, desk):
    reply = desk.get("/patients/phones")
    assert reply.status_code == 200
    body = reply.get_data(as_text=True)
    assert "طفل مقطوع" in body and "مراهق" in body
    assert "tel:01001234567" in body, "no number to ring from"


def test_the_screen_offers_a_box_per_row(book, desk):
    body = desk.get("/patients/phones").get_data(as_text=True)
    assert body.count('name="phone"') >= 3


def test_a_clinic_with_nothing_missing_says_so(clinic, desk):
    """An empty work list should read as finished, not as broken."""
    with clinic["app"].test_request_context("/"):
        from app.i18n import t
        marker = t("phones.all_clear")
    from app.models import Patient

    with clinic["app"].app_context():
        for p in Patient.query.all():
            p.own_phone = "01000000000"
        clinic["db"].session.commit()
    assert marker.rstrip(" ✅") in desk.get("/patients/phones").get_data(as_text=True)


def test_the_notification_now_leads_somewhere_you_can_act(book, desk):
    """It pointed at a filtered patient list, where the only thing to do was
    read the count again."""
    from app.utils.notifications import _compute

    with book["app"].test_request_context("/"):
        keys = {i["key"]: i for i in _compute()}
    for key in ("teens_no_phone", "no_contact"):
        if key in keys:
            assert keys[key]["endpoint"] == "patients.phones", key


def test_the_harder_case_has_a_notification_of_its_own(book, desk):
    """Nothing counted the families with no number anywhere, so they were
    invisible until the day somebody needed to ring one."""
    from app.utils.notifications import _compute

    with book["app"].test_request_context("/"):
        keys = {i["key"] for i in _compute()}
    assert "no_contact" in keys
