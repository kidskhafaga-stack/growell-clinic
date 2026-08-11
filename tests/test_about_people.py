"""The credits on the About page: two languages, and more than one person.

The section used to hold **one** medical supervisor in **one** string per
field. On a bilingual page that is two bugs at once: a name typed in Arabic
was printed unchanged to an English reader, and a clinic with three doctors
could credit one of them.

These tests are written against what the page actually renders, in both
languages, because that is where both faults were visible and neither was
visible in the stored value.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def app_ctx():
    from app import create_app
    from app.extensions import db

    app = create_app("testing")
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


def _staff(username="boss", role="admin"):
    from app.extensions import db
    from app.models import User

    existing = User.query.filter_by(username=username).first()
    if existing is not None:      # some tests read the page in both languages
        return existing
    user = User(username=username, full_name="موظف", role=role, is_active=True)
    user.set_password("secret")
    db.session.add(user)
    db.session.commit()
    return user


def _admin():
    return _staff()


def _client(app, lang, username="boss"):
    client = app.test_client()
    client.post("/login", data={"username": username, "password": "secret"},
                follow_redirects=True)
    with client.session_transaction() as session:
        session["lang"] = lang
    return client


def _about(app, lang):
    """The page as a **reader** sees it, not an admin.

    An admin also gets the edit form, and that form holds both languages of
    every field by design — so asserting "the Arabic name is absent from the
    English page" against an admin's HTML tests nothing at all. It has to be
    read by somebody who cannot edit it, which is who the page is for.
    """
    _staff("reader", "reception")
    page = _client(app, lang, "reader").get("/about")
    assert page.status_code == 200
    return page.get_data(as_text=True)


# --------------------------------------------------------------- two languages

def test_the_english_page_shows_the_english_name(app_ctx):
    from app.extensions import db
    from app.models import AboutPerson

    _admin()
    db.session.add(AboutPerson(name="د. أحمد جمال", name_en="Dr. Ahmed Gamal",
                               title="استشاري", title_en="Consultant"))
    db.session.commit()

    english = _about(app_ctx, "en")
    assert "Dr. Ahmed Gamal" in english
    assert "Consultant" in english
    assert "د. أحمد جمال" not in english, \
        "the English page printed the Arabic name at an English reader"


def test_the_arabic_page_shows_the_arabic_name(app_ctx):
    from app.extensions import db
    from app.models import AboutPerson

    _admin()
    db.session.add(AboutPerson(name="د. أحمد جمال", name_en="Dr. Ahmed Gamal",
                               title="استشاري", title_en="Consultant"))
    db.session.commit()

    arabic = _about(app_ctx, "ar")
    assert "د. أحمد جمال" in arabic
    assert "استشاري" in arabic


def test_a_blank_english_side_falls_back_to_the_arabic(app_ctx):
    """Nobody should have to type everything twice to get a working page."""
    from app.extensions import db
    from app.models import AboutPerson

    _admin()
    db.session.add(AboutPerson(name="د. منى سعيد"))
    db.session.commit()

    assert "د. منى سعيد" in _about(app_ctx, "en")


# ------------------------------------------------------------- more than one

def test_a_clinic_can_credit_several_doctors(app_ctx):
    from app.extensions import db
    from app.models import AboutPerson

    _admin()
    for order, name in enumerate(["د. أحمد", "د. منى", "د. إسراء"]):
        db.session.add(AboutPerson(name=name, sort_order=order))
    db.session.commit()

    page = _about(app_ctx, "ar")
    for name in ["د. أحمد", "د. منى", "د. إسراء"]:
        assert name in page


def test_the_clinics_order_is_the_order_on_the_page(app_ctx):
    from app.extensions import db
    from app.models import AboutPerson

    _admin()
    # Three rows, because two are not enough to catch anything: with two, the
    # answer the clinic asked for is also what reversing the insertion order
    # gives, and deleting the ORDER BY entirely leaves this test green. It did.
    #
    # Inserted 2, 0, 1. So the wanted order is neither the order they were
    # added in nor the reverse of it, and only reading sort_order produces it.
    db.session.add(AboutPerson(name="الثالث", sort_order=2))
    db.session.add(AboutPerson(name="الأول", sort_order=0))
    db.session.add(AboutPerson(name="الثاني", sort_order=1))
    db.session.commit()

    page = _about(app_ctx, "ar")
    assert page.index("الأول") < page.index("الثاني") < page.index("الثالث")


# ------------------------------------------------------------------- editing

def test_an_admin_adds_a_person_from_the_page(app_ctx):
    from app.models import AboutPerson

    _admin()
    client = _client(app_ctx, "ar")
    client.post("/about/people", data={
        "action": "add", "name": "د. سارة", "name_en": "Dr. Sara",
        "title": "طب أطفال", "sort_order": "0"}, follow_redirects=True)

    row = AboutPerson.query.filter_by(name="د. سارة").first()
    assert row is not None
    assert row.name_en == "Dr. Sara"


def test_a_person_without_an_arabic_name_is_refused(app_ctx):
    """The Arabic name is the required side — this is an Arabic-first page."""
    from app.models import AboutPerson

    _admin()
    client = _client(app_ctx, "ar")
    client.post("/about/people", data={
        "action": "add", "name": "", "name_en": "Dr. Nobody"},
        follow_redirects=True)

    assert AboutPerson.query.count() == 0


def test_an_admin_deletes_a_person(app_ctx):
    from app.extensions import db
    from app.models import AboutPerson

    _admin()
    person = AboutPerson(name="د. مؤقت")
    db.session.add(person)
    db.session.commit()
    person_id = person.id

    client = _client(app_ctx, "ar")
    client.post("/about/people", data={"action": "delete", "id": person_id},
                follow_redirects=True)

    assert AboutPerson.query.count() == 0


def test_a_non_admin_cannot_touch_the_credits(app_ctx):
    from app.extensions import db
    from app.models import AboutPerson, User

    _admin()
    nurse = User(username="desk", full_name="الاستقبال", role="reception",
                 is_active=True)
    nurse.set_password("secret")
    db.session.add(nurse)
    db.session.commit()

    client = app_ctx.test_client()
    client.post("/login", data={"username": "desk", "password": "secret"},
                follow_redirects=True)
    client.post("/about/people", data={"action": "add", "name": "د. دخيل"},
                follow_redirects=True)

    assert AboutPerson.query.count() == 0


# ------------------------------------------------------ the developer's note

def test_the_developer_note_is_a_pair_not_one_string(app_ctx):
    """The fault the doctors' names had, in the one block that is not a row."""
    from app.extensions import db
    from app.models import Setting

    _admin()
    Setting.set("about_developer_note", "نبذة بالعربي")
    Setting.set("about_developer_note_en", "An English note")
    db.session.commit()

    assert "An English note" in _about(app_ctx, "en")
    assert "نبذة بالعربي" not in _about(app_ctx, "en")
    assert "نبذة بالعربي" in _about(app_ctx, "ar")


# ------------------------------------------------------------- the carry-over

def test_the_supervisor_a_clinic_already_typed_is_not_lost(app_ctx):
    """An upgrade moves the old single supervisor into the new table."""
    from app.extensions import db
    from app.models import AboutPerson, Setting
    from app.utils.project import carry_over_supervisor

    Setting.set("about_supervisor_name", "د. محمد المشرف")
    Setting.set("about_supervisor_title", "الإشراف الطبي")
    Setting.set("about_supervisor_note", "نبذة قديمة")
    db.session.commit()

    assert carry_over_supervisor() is True
    db.session.commit()

    row = AboutPerson.query.one()
    assert row.name == "د. محمد المشرف"
    assert row.title == "الإشراف الطبي"
    assert row.note == "نبذة قديمة"
    # And the old keys are cleared, so a second upgrade cannot duplicate them.
    assert not (Setting.get("about_supervisor_name") or "")
    assert carry_over_supervisor() is False


def test_the_carry_over_does_not_resurrect_a_deleted_person(app_ctx):
    """Running it against a table that already has rows must add nothing."""
    from app.extensions import db
    from app.models import AboutPerson, Setting
    from app.utils.project import carry_over_supervisor

    db.session.add(AboutPerson(name="د. الموجود"))
    Setting.set("about_supervisor_name", "د. المحذوف")
    db.session.commit()

    assert carry_over_supervisor() is False
    db.session.commit()

    assert [p.name for p in AboutPerson.query.all()] == ["د. الموجود"]
