"""Crediting somebody who already exists, without typing them twice.

A doctor who logs in already has a name in both languages, a title, a
specialty and a photograph on their user record. The About page asked for all
of it again. That is not merely tedious — it is a **second copy, and second
copies drift**: the doctor is promoted from Specialist to Consultant, somebody
updates the user, and this page goes on printing last year's title until a
person happens to notice. The question was never whether it would disagree,
only when.

**And the other half, which is the harder constraint.** Stated plainly when
this was proposed: *"some of the people we enter don't use the program at all
— supervision — and we may enter other people who aren't in the program."* A
supervising professor, the clinic's owner, somebody who helped once and was
thanked. None of them have logins and none of them ever will. A design where
being credited requires being a user cannot say what this page exists to say.

So the link is optional, blank is the ordinary answer, and a row with nobody
linked behaves exactly as it always did. Both halves are tested here, and the
unlinked half is tested first, because it is the one a refactor breaks.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def clinic_with_doctor(clinic):
    from app.extensions import db
    from app.models import User

    with clinic["app"].app_context():
        doc = User.query.filter_by(role="doctor").first()
        doc.full_name = "د. سارة عبد الله"
        doc.full_name_en = "Dr Sarah Abdullah"
        doc.specialty = "طب الأطفال"
        doc.photo = "sarah.jpg"
        db.session.commit()
        return clinic, doc.id


def _add(clinic, **fields):
    from app.extensions import db
    from app.utils import project

    with clinic["app"].app_context():
        person = project.add_person(fields, {})
        db.session.commit()
        return person.id


def _person(clinic, person_id):
    from app.extensions import db
    from app.models.about_person import AboutPerson

    return db.session.get(AboutPerson, person_id)


# ------------------------------------- somebody who is not in the program

def test_a_supervisor_with_no_login_is_credited_normally(clinic):
    """The constraint that shaped this, asserted before the feature it
    constrains. A professor who supervises the clinic has no account here and
    is not going to be given one."""
    person_id = _add(clinic, name="أ.د. محمود الجندي",
                     name_en="Prof. Mahmoud El-Gindy",
                     title="الإشراف الطبي")

    with clinic["app"].app_context():
        person = _person(clinic, person_id)

        assert person.user_id is None
        assert person.display_name("ar") == "أ.د. محمود الجندي"
        assert person.display_name("en") == "Prof. Mahmoud El-Gindy"
        assert person.display_title("ar") == "الإشراف الطبي"


def test_leaving_the_picker_empty_is_a_real_answer(clinic):
    """Blank is the commonest case, so it must be a decision the form can
    express rather than a value it ignores."""
    person_id = _add(clinic, name="صاحب العيادة", user_id="")

    with clinic["app"].app_context():
        assert _person(clinic, person_id).user_id is None


def test_an_id_naming_nobody_does_not_become_a_dangling_row(clinic):
    """A stale form, or somebody editing the page's HTML. Either way the row
    must not end up pointing at a user that is not there."""
    person_id = _add(clinic, name="لا أحد", user_id="999999")

    with clinic["app"].app_context():
        assert _person(clinic, person_id).user_id is None


def test_a_page_full_of_outsiders_still_renders(clinic):
    """The whole feature could be added and this stay broken."""
    _add(clinic, name="أ.د. محمود", title="الإشراف الطبي")

    page = clinic["sign_in"]("boss").get(
        "/about", follow_redirects=True).data.decode()

    assert "أ.د. محمود" in page


# ---------------------------------------------- somebody who is a colleague

def test_a_linked_colleague_is_read_from_their_own_record(clinic_with_doctor):
    clinic, doc_id = clinic_with_doctor
    person_id = _add(clinic, name="سارة", user_id=str(doc_id))

    with clinic["app"].app_context():
        person = _person(clinic, person_id)

        assert person.display_name("ar") == "د. سارة عبد الله"
        assert person.display_name("en") == "Dr Sarah Abdullah"


def test_the_copy_cannot_go_stale_because_there_is_no_copy(clinic_with_doctor):
    """The defect this exists to remove, measured as a change over time.

    Promote the doctor on their user record and read the About page again.
    With the name copied into the credit row this assertion is what fails —
    and in a real clinic it fails silently, for months.
    """
    clinic, doc_id = clinic_with_doctor
    _add(clinic, name="سارة", user_id=str(doc_id))

    from app.extensions import db
    from app.models import User

    with clinic["app"].app_context():
        doc = db.session.get(User, doc_id)
        doc.full_name = "د. سارة عبد الله — استشاري"
        db.session.commit()

    page = clinic["sign_in"]("boss").get(
        "/about", follow_redirects=True).data.decode()

    assert "د. سارة عبد الله — استشاري" in page, \
        "the credits page is still showing the name it was given last year"


def test_the_clinic_still_says_what_they_are_to_it(clinic_with_doctor):
    """A user record says what somebody is to the *program* — their specialty.
    This page says what they are to *this clinic*, and "الإشراف الطبي" is not
    a specialty. So a typed title wins, and nothing is duplicated by that
    because the clinic only ever typed one of them."""
    clinic, doc_id = clinic_with_doctor
    person_id = _add(clinic, name="سارة", title="الإشراف الطبي",
                     user_id=str(doc_id))

    with clinic["app"].app_context():
        assert _person(clinic, person_id).display_title("ar") == "الإشراف الطبي"


def test_with_no_title_typed_it_falls_back_to_their_specialty(clinic_with_doctor):
    clinic, doc_id = clinic_with_doctor
    person_id = _add(clinic, name="سارة", user_id=str(doc_id))

    with clinic["app"].app_context():
        assert _person(clinic, person_id).display_title("ar") == "طب الأطفال"


def test_the_photograph_comes_from_the_right_folder(clinic_with_doctor):
    """Two folders: a staff photo is already in `uploads/users`, an outsider's
    is uploaded here into `uploads/about`. The macro drew every face from
    `uploads/about` and would have shown a broken image for every colleague."""
    clinic, doc_id = clinic_with_doctor
    linked = _add(clinic, name="سارة", user_id=str(doc_id))
    outsider = _add(clinic, name="أ.د. محمود")

    with clinic["app"].app_context():
        assert _person(clinic, linked).photo_path() == "uploads/users/sarah.jpg"

        person = _person(clinic, outsider)
        person.photo = "guest.png"
        assert person.photo_path() == "uploads/about/guest.png"

        person.photo = None
        assert person.photo_path() is None, \
            "a person with no picture must fall through to their initial"


# ---------------------------------------------------- the credit outlives it

def test_deleting_a_login_does_not_delete_the_credit(clinic_with_doctor):
    """Tidying up an account is not a decision to remove somebody from the
    clinic's credits. The row survives and falls back to what was typed."""
    clinic, doc_id = clinic_with_doctor
    person_id = _add(clinic, name="د. سارة عبد الله", user_id=str(doc_id))

    from app.extensions import db
    from app.models import User

    with clinic["app"].app_context():
        person = _person(clinic, person_id)
        person.user_id = None       # what SET NULL leaves behind
        db.session.commit()

        assert _person(clinic, person_id).display_name("ar") == "د. سارة عبد الله"


# --------------------------------------------------------------- the screen

def test_the_form_offers_both_ways_in(clinic_with_doctor):
    clinic, _doc_id = clinic_with_doctor

    page = clinic["sign_in"]("boss").get(
        "/about", follow_redirects=True).data.decode()

    from app.i18n import t

    assert 'name="user_id"' in page, "there is no way to pick a colleague"
    with clinic["app"].test_request_context("/"):
        assert t("about.not_a_user") in page, \
            "the form does not offer 'nobody' as a choice"
    assert 'name="name"' in page, "the free-text name is gone"


def test_the_picker_is_not_narrowed_to_doctors(clinic):
    """A clinic credits its matron and its manager as readily as its
    paediatricians. A filter that decided for them sends them back to
    typing."""
    from app.utils import project

    with clinic["app"].app_context():
        roles = {u.role for u in project.creditable_staff()}

    assert len(roles) > 1, f"only {roles} can be credited from the program"


def test_the_new_column_is_registered_for_an_existing_database(clinic):
    from app.utils.schema import ADDITIONS

    assert ("about_people", "user_id") in {
        (table, column) for table, column, *_ in ADDITIONS}


def test_the_wording_exists_in_both_languages(clinic):
    import json

    here = os.path.dirname(os.path.abspath(__file__))
    for lang in ("ar", "en"):
        with open(os.path.join(here, "..", "app/i18n/locales", f"{lang}.json"),
                  encoding="utf-8") as fh:
            block = json.load(fh)["about"]
        for key in ("link_user", "not_a_user", "link_user_hint"):
            assert key in block, f"{lang} is missing about.{key}"
