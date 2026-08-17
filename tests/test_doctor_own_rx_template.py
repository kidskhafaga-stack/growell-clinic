"""A doctor setting up their own prescription, without the settings screen.

Reported in these words: *"I gave the doctor the settings screen so he could
set up his own prescription — why does it give me 404?"*

Two separate things were wrong.

**The settings module permission does not do anything.** All 26 routes under
`/settings` are `@admin_required`, which asks `is_admin`; the sidebar asks
`can_access('settings')`, which reads the role's module list. So ticking the
box put a Settings link in the doctor's sidebar and the route behind it
refused them — 403 on `/settings/`, and a genuine 404 on any remembered
address underneath it that does not exist. That is not fixed here: handing a
doctor `/settings/` would hand them the data reset and the backup restore,
which is not what anybody was asking for.

**What was actually being asked for had no screen.** A doctor could already
*choose* which layout their prescriptions print with, from their own profile,
and could not change one thing about it. So the layout screen now opens for
whoever prescribes, and a template carries an owner: a doctor edits theirs,
an admin edits the clinic's, and neither reaches into the other's.

The tests that matter most here are the refusals. A shared template edited by
one doctor reshapes every other doctor's paper silently, and "silently" is the
word that makes it worth a test rather than a code review.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def layouts(clinic):
    """A clinic template, a template owned by the doctor, and a second doctor."""
    from app.extensions import db
    from app.models import RxPrintTemplate, User

    with clinic["app"].app_context():
        doctor = User.query.filter_by(username="doc").first()
        other = User(username="doc2", full_name="د. تاني", role="doctor",
                     is_active=True)
        other.set_password("secret")
        db.session.add(other)

        shared = RxPrintTemplate(name="قالب العيادة", is_default=True)
        mine = RxPrintTemplate(name="روشتة الدكتور", doctor_id=doctor.id)
        db.session.add_all([shared, mine])
        db.session.commit()
        clinic["shared"] = shared.id
        clinic["mine"] = mine.id
        clinic["other_doctor"] = other.id
    return clinic


# ------------------------------------------------------------ who may edit

def test_a_doctor_can_open_the_layout_screen(layouts):
    """It used to be admin-only, which is why the settings screen was handed
    over instead."""
    assert layouts["sign_in"]("doc").get("/prescriptions/templates").status_code == 200


def test_a_doctor_still_cannot_open_the_settings_screen(layouts):
    """The screen carries the data reset and the backup restore.

    Fixing the reported symptom by opening `/settings/` to a doctor would
    have handed those over to get at one form.
    """
    assert layouts["sign_in"]("doc").get("/settings/").status_code == 403


def test_a_doctor_edits_their_own_layout(layouts):
    client = layouts["sign_in"]("doc")

    answer = client.post(f"/prescriptions/templates/{layouts['mine']}/edit",
                         data={"name": "روشتة معدّلة"}, follow_redirects=True)

    assert answer.status_code == 200
    with layouts["app"].app_context():
        from app.models import RxPrintTemplate
        assert layouts["db"].session.get(
            RxPrintTemplate, layouts["mine"]).name == "روشتة معدّلة"


def test_a_doctor_cannot_edit_the_clinics_layout(layouts):
    """The one that would go unnoticed: it prints for everybody."""
    client = layouts["sign_in"]("doc")

    answer = client.post(f"/prescriptions/templates/{layouts['shared']}/edit",
                         data={"name": "مخطوف"})

    assert answer.status_code == 403
    with layouts["app"].app_context():
        from app.models import RxPrintTemplate
        assert layouts["db"].session.get(
            RxPrintTemplate, layouts["shared"]).name == "قالب العيادة"


def test_one_doctor_cannot_edit_anothers(layouts):
    from app.extensions import db
    from app.models import User

    with layouts["app"].app_context():
        other = db.session.get(User, layouts["other_doctor"])
        other.set_password("secret")
        db.session.commit()

    client = layouts["app"].test_client()
    client.post("/login", data={"username": "doc2", "password": "secret"},
                follow_redirects=True)

    answer = client.post(f"/prescriptions/templates/{layouts['mine']}/edit",
                         data={"name": "مخطوف"})

    assert answer.status_code == 403, \
        "one doctor just rewrote another doctor's prescription layout"


def test_a_doctor_cannot_delete_the_clinics_layout(layouts):
    client = layouts["sign_in"]("doc")

    assert client.post(
        f"/prescriptions/templates/{layouts['shared']}/delete").status_code == 403


def test_the_clinic_default_stays_the_clinics_decision(layouts):
    """A doctor picks what *they* print with, from their profile. Changing
    the clinic's default changes it for everybody who has not chosen."""
    client = layouts["sign_in"]("doc")

    assert client.post(
        f"/prescriptions/templates/{layouts['mine']}/default").status_code == 403


def test_an_admin_may_still_do_all_of_it(layouts):
    client = layouts["sign_in"]("boss")

    for url in (f"/prescriptions/templates/{layouts['shared']}/edit",
                f"/prescriptions/templates/{layouts['mine']}/edit"):
        assert client.post(url, data={"name": "من الأدمن"}).status_code in (200, 302), \
            f"the admin lost access to {url}"


# ------------------------------------------------------------- who owns it

def test_a_layout_a_doctor_creates_belongs_to_them(layouts):
    """Otherwise the next doctor to open the screen could edit it."""
    from app.models import RxPrintTemplate, User

    client = layouts["sign_in"]("doc")
    client.post("/prescriptions/templates/new",
                data={"name": "قالب جديد", "mode": "white"},
                follow_redirects=True)

    with layouts["app"].app_context():
        made = RxPrintTemplate.query.filter_by(name="قالب جديد").first()
        doctor = User.query.filter_by(username="doc").first()
        assert made is not None, "the doctor could not create a layout at all"
        assert made.doctor_id == doctor.id, \
            "a doctor's new layout was created as the clinic's"


def test_a_layout_an_admin_creates_is_the_clinics(layouts):
    from app.models import RxPrintTemplate

    client = layouts["sign_in"]("boss")
    client.post("/prescriptions/templates/new",
                data={"name": "قالب إداري", "mode": "white"},
                follow_redirects=True)

    with layouts["app"].app_context():
        made = RxPrintTemplate.query.filter_by(name="قالب إداري").first()
        assert made.doctor_id is None, \
            "the admin's template was filed as one doctor's private layout"


def test_a_doctor_is_not_shown_another_doctors_layout(layouts):
    from app.extensions import db
    from app.models import RxPrintTemplate

    with layouts["app"].app_context():
        db.session.add(RxPrintTemplate(name="قالب دكتور تاني",
                                       doctor_id=layouts["other_doctor"]))
        db.session.commit()

    page = layouts["sign_in"]("doc").get("/prescriptions/templates").data.decode()

    assert "قالب دكتور تاني" not in page, \
        "one doctor's private layout is listed on another's screen"
    assert "قالب العيادة" in page, \
        "the clinic's layout is hidden, so a doctor cannot see what they print with"


def test_the_existing_clinic_templates_stay_the_clinics(layouts):
    """Every row that predates the column has no owner, and must not acquire
    one — an upgrade that reassigned templates would be a surprise."""
    from app.models import RxPrintTemplate

    with layouts["app"].app_context():
        assert layouts["db"].session.get(
            RxPrintTemplate, layouts["shared"]).doctor_id is None


def test_ownership_is_one_rule_not_a_check_per_route(layouts):
    """Four routes ask the same question; it is answered in one place."""
    from app.models import RxPrintTemplate, User

    with layouts["app"].app_context():
        mine = layouts["db"].session.get(RxPrintTemplate, layouts["mine"])
        shared = layouts["db"].session.get(RxPrintTemplate, layouts["shared"])
        doctor = User.query.filter_by(username="doc").first()
        boss = User.query.filter_by(username="boss").first()

        assert mine.editable_by(doctor) is True
        assert shared.editable_by(doctor) is False
        assert shared.editable_by(boss) is True
        assert mine.editable_by(None) is False


# --------------------------------------------------- the program's own line

def test_the_program_line_can_be_switched_off(layouts):
    """The credit line at the foot of every printed page.

    It lives in the shell, so it is switched off from the paper — the only
    place that knows which template is being printed with.
    """
    from app.extensions import db
    from app.models import RxPrintTemplate

    with layouts["app"].app_context():
        tpl = db.session.get(RxPrintTemplate, layouts["mine"])
        tpl.show_program_line = False
        db.session.commit()

    page = layouts["sign_in"]("doc").get(
        f"/prescriptions/templates/{layouts['mine']}/test-print").data.decode()

    assert ".print-footer" in page and "display: none" in page, \
        "the program line still prints on a template that switched it off"


def test_it_is_on_unless_somebody_turns_it_off(layouts):
    """An upgrade must not strip the line off a clinic's paper unasked."""
    from app.models import RxPrintTemplate

    with layouts["app"].app_context():
        fresh = RxPrintTemplate(name="جديد")
        layouts["db"].session.add(fresh)
        layouts["db"].session.commit()
        assert fresh.show_program_line is True

    page = layouts["sign_in"]("doc").get(
        f"/prescriptions/templates/{layouts['shared']}/test-print").data.decode()
    assert "display: none" not in page.split("print-footer")[0][-200:], \
        "the line was hidden on a template that never asked for that"


def test_the_switch_is_saved_from_the_form(layouts):
    """In BOOLS, or the checkbox would draw and never persist."""
    from app.models import RxPrintTemplate

    assert "show_program_line" in RxPrintTemplate.BOOLS

    client = layouts["sign_in"]("doc")
    client.post(f"/prescriptions/templates/{layouts['mine']}/edit",
                data={"name": "بدون سطر"}, follow_redirects=True)

    with layouts["app"].app_context():
        tpl = layouts["db"].session.get(RxPrintTemplate, layouts["mine"])
        assert tpl.show_program_line is False, \
            "unticking the switch did not save"


# --------------------------------------------------------------- the way in

def test_the_doctor_is_given_a_way_in_from_their_own_profile(layouts):
    """The reason this was reachable only through the settings screen."""
    page = layouts["sign_in"]("doc").get("/profile").data.decode()

    assert "/prescriptions/templates" in page, \
        "a doctor still has no route to their own prescription layout"


# ------------------------------------------------------------- the schema

def test_both_columns_are_in_the_additive_migration(layouts):
    """New columns on an existing table upgrade nobody's database by
    themselves — they have to be listed."""
    from app.utils.schema import ADDITIONS

    listed = {(table, column) for table, column, _type in ADDITIONS}
    for column in ("show_program_line", "doctor_id"):
        assert ("rx_print_templates", column) in listed, \
            f"{column} would be missing on every existing clinic after an upgrade"
