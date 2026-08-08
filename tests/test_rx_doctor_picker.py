"""Saying which doctor a prescription is for, without a dropdown.

The patient list on this screen was a dropdown capped at 500 names in
alphabetical order, so a clinic with thousands of files simply stopped
mid-alphabet and the child appeared not to exist. That was fixed with a
search. The doctor list beside it was still a dropdown, and the request was to
make it a search too — *"واسم الطبيب برده بحث، يا يخذه لو الطبيب فاتح من الـ
account بتاعه"*.

Two cases, and they are not the same:

**A doctor signed in.** Their name comes from the account and there is no list
at all. A picker that lets one doctor put another's name on a signed
prescription is a picker that will eventually be used that way by accident.

**Anybody else** — an administrator, the front desk — is writing on a
doctor's behalf and has to be able to say which doctor. That is the search,
and it starts on the signed-in user when they see patients too, which is the
case that used to behave oddly: an admin marked as a practitioner got their
own name locked in with no way to write for anyone else.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def _extra_doctor(clinic, name="سامي عبد الله", username="doc2", active=True):
    from app.models import User

    db = clinic["db"]
    user = User(username=username, full_name=name, role="doctor",
                is_active=active)
    user.set_password("secret")
    db.session.add(user)
    db.session.commit()
    return user.id


def _search(clinic, q=None, who="boss"):
    url = "/prescriptions/doctor-search" + (f"?q={q}" if q else "")
    return clinic["sign_in"](who).get(url).get_json()


# ============================================== the search ==================
def test_an_empty_query_lists_the_doctors(clinic):
    """A clinic has a handful of doctors. Making somebody guess the first two
    letters of a list that short is a hurdle, not a search — the box shows
    them all the moment it is focused."""
    with clinic["app"].app_context():
        _extra_doctor(clinic)

    rows = _search(clinic)
    assert len(rows) == 2, rows
    assert all(row["name"] for row in rows)


def test_it_finds_a_doctor_by_name(clinic):
    with clinic["app"].app_context():
        other = _extra_doctor(clinic)

    rows = _search(clinic, "سامي")
    assert [row["id"] for row in rows] == [other]


def test_a_doctor_who_left_is_not_offered(clinic):
    """Prescriptions carry the doctor's name onto paper. Somebody no longer at
    the clinic should not be reachable from a picker."""
    with clinic["app"].app_context():
        _extra_doctor(clinic, name="مغادر", username="gone", active=False)

    assert all("مغادر" not in row["name"] for row in _search(clinic))


# ============================================== on the screen ===============
def _page(clinic, who):
    return clinic["sign_in"](who).get("/prescriptions/new").data.decode()


def test_a_doctor_gets_their_own_name_and_no_list(clinic):
    """From their account, settled, with nothing to pick."""
    page = _page(clinic, "doc")

    assert 'name="doctor_id"' in page
    assert "doctor-search" not in page, "a doctor was offered other doctors"


def test_everybody_else_gets_the_search(clinic):
    """The administrator writing one on a doctor's behalf."""
    page = _page(clinic, "boss")

    assert "doctor-search" in page
    assert '<select class="select" name="doctor_id">' not in page, \
        "the dropdown is still there"


def test_an_admin_who_sees_patients_starts_on_their_own_name(clinic):
    """The odd case. Being marked as a practitioner used to lock the field to
    themselves, so an admin who also examines patients could not write a
    prescription for a colleague at all. It is a starting point now, not a
    cage."""
    from app.models import User

    db = clinic["db"]
    with clinic["app"].app_context():
        boss = db.session.get(User, clinic["ids"]["admin"])
        boss.is_practitioner = True
        db.session.commit()
        expected = boss.doctor_print_name("ar")

    page = _page(clinic, "boss")
    # The name reaches the browser JSON-escaped, so the id is what can be read
    # back out of the page.
    import re

    match = re.search(r"rxDoctor\('[^']*',\s*(\d+)", page)
    assert match, "the doctor field is not the search"
    assert int(match.group(1)) == clinic["ids"]["admin"]
    assert expected, "the account carries no printable name to start from"


def test_the_patient_dropdown_is_gone_too(clinic):
    """The change that came first, pinned here because both fields on this
    screen had the same fault and only one of them had a test."""
    page = _page(clinic, "boss")

    assert "patient-search" in page
    assert 'name="patient_id"' in page
    assert '<select class="select" name="patient_id">' not in page


# ============================================== the shared picker ===========
def test_the_picker_honours_a_minimum_of_zero(clinic):
    """``cfg.minChars || 1`` reads an explicit 0 as 1, so the doctor box would
    have shown nothing on focus and the whole point of the change would have
    been lost — quietly, in a browser, where no test would be looking."""
    with open(os.path.join(os.path.dirname(__file__), "..", "app", "static",
                           "js", "app.js"), encoding="utf-8") as fh:
        source = fh.read()

    assert "cfg.minChars === undefined ? 1 : cfg.minChars" in source
    assert "minChars: 0" in open(
        os.path.join(os.path.dirname(__file__), "..", "app", "templates",
                     "prescriptions", "new.html"), encoding="utf-8").read()
