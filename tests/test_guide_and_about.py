"""A guide that knows who is reading it, and an About page that counts.

**The measurement that started this.** The guide rendered the same page for
everybody. Signing in as three roles and measuring the *text* of ``/guide``
gave 4,193 characters for an admin, 4,114 for a doctor and 4,075 for a
receptionist — a 3% spread, and all of it the name in the top bar. So a
receptionist was taught the doctor's statement of account and how to write a
prescription, neither of which opens for them, and the parts that *are* their
job sat in between.

After, measured the same way: 8,725 / 4,747 / 3,144 / 3,373 / 2,575 for admin,
doctor, reception, accountant and pharmacy. Pharmacy now reads *less* than it
did — 2,575 against 4,075 — and that is the improvement, not a regression: all
of it is about screens they can open. The tests below are written against the
*shape* of that difference rather than the numbers, because the numbers move
every time a bullet is edited and a test that pins them would be a test of
nothing.

**The bug this found.** The till is the one screen reached by module *or*
capability — ``cashier_access`` lets reception collect money without handing
them the P&L. Gating the guide's cashier section on module *and* capability
told a receptionist "you may take payments" in the permissions card and then
showed them no section explaining how. ``test_the_till_section_follows_the_same
_rule_the_till_screen_does`` holds the guide and the decorator together.

**About.** Every figure on it is counted at render time. A number typed into a
template is true on the day it is written and quietly wrong afterwards, and
this is a page whose whole job is to be believed.
"""
import os
import re
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

ARABIC = re.compile(r"[؀-ۿ]")


def text_of(html):
    """The words a person actually reads — markup and scripts removed."""
    html = re.sub(r"(?s)<script.*?</script>|<style.*?</style>", " ", html)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


def guide_sections(html):
    return re.findall(r'id="g-([a-z_]+)"', html)


def add_role(clinic, username, role):
    """A user for a role the shared fixture does not carry."""
    with clinic["app"].app_context():
        from app.models import User
        user = User(username=username, full_name=username, role=role,
                    is_active=True)
        user.set_password("secret")
        clinic["db"].session.add(user)
        clinic["db"].session.commit()


# --- the guide reads differently for different people ----------------------

def test_the_guide_is_cut_to_the_role_reading_it(clinic):
    """The failure this whole change exists for.

    Before, three roles read 4,193 / 4,114 / 4,075 characters — the same page.
    The assertion is on the *sections*, not the length: a receptionist and a
    doctor must not be handed the same set, and each must be handed strictly
    less than the admin, who can reach everything.
    """
    add_role(clinic, "pharm", "pharmacy")
    seen = {}
    for username in ("boss", "doc", "desk", "acct", "pharm"):
        body = clinic["sign_in"](username).get("/guide").data.decode()
        seen[username] = set(guide_sections(body))

    assert seen["desk"] != seen["doc"], (
        "reception and the doctor are still reading the same guide")
    for username in ("doc", "desk", "acct", "pharm"):
        assert seen[username] < seen["boss"], (
            f"{username} sees sections the admin does not, or all of them")


def test_reception_is_not_taught_the_screens_it_cannot_open(clinic):
    """Instructions for a locked door are worse than no instructions.

    Reception has no finance module beyond the till and no clinical file, so
    the statement of account, the ledgers and the medical file must not appear
    — a receptionist following those steps meets a 403 and concludes the
    program is broken.
    """
    body = clinic["sign_in"]("desk").get("/guide").data.decode()
    sections = guide_sections(body)

    for absent in ("books", "payers", "services", "treasury", "patient_file",
                   "visits", "prescriptions", "users", "settings", "reports"):
        assert absent not in sections, f"reception was shown '{absent}'"
    assert "كشف حساب الطبيب" not in body


def test_the_doctor_is_taught_the_clinic_and_not_the_cash(clinic):
    """The other half of the same rule, from the other side."""
    body = clinic["sign_in"]("doc").get("/guide").data.decode()
    sections = guide_sections(body)

    for present in ("visits", "growth", "vaccinations", "prescriptions",
                    "patient_file"):
        assert present in sections, f"the doctor is missing '{present}'"
    for absent in ("cashier", "invoices", "books", "treasury", "users"):
        assert absent not in sections, f"the doctor was shown '{absent}'"


def test_the_till_section_follows_the_same_rule_the_till_screen_does(clinic):
    """The bug: the guide's gate and the decorator's gate must agree.

    ``cashier_access`` admits anyone with the finance module **or** the
    ``cashier`` capability. Reception has only the capability — so the screen
    opens for them and the section must too. Pharmacy has neither, and gets
    neither. This asserts the two together, because a guide that disagrees
    with the decorator is wrong in one of two directions and both are worse
    than silence.
    """
    add_role(clinic, "pharm", "pharmacy")

    desk = clinic["sign_in"]("desk")
    assert desk.get("/finance/cashier").status_code == 200
    assert "cashier" in guide_sections(desk.get("/guide").data.decode()), (
        "reception can open the till and is not told how")

    pharm = clinic["sign_in"]("pharm")
    assert pharm.get("/finance/cashier").status_code == 403
    assert "cashier" not in guide_sections(pharm.get("/guide").data.decode())


def test_the_rest_of_the_program_is_one_click_away_and_labelled(clinic):
    """Hiding the answer to "what could I do as a doctor?" only sends people
    to ask somebody. ``?all=1`` shows everything — and marks what is not
    theirs, so nobody follows steps they cannot complete."""
    client = clinic["sign_in"]("desk")
    mine = guide_sections(client.get("/guide").data.decode())
    everything = client.get("/guide?all=1").data.decode()

    assert len(guide_sections(everything)) > len(mine)
    marked = everything.count("خارج صلاحياتك")
    assert marked == len(guide_sections(everything)) - len(mine), (
        "sections outside the user's permissions are not all marked")


def test_a_module_the_clinic_switched_off_is_not_explained_to_anybody(clinic):
    """Describing a screen that is not in the sidebar is how a guide lies.

    A small clinic turns finance off; the admin can still "access" the module
    by role, so a role-only filter would keep teaching a screen that 404s.
    """
    with clinic["app"].app_context():
        from app.models import Setting
        # Module switches only bind once the facility has been configured —
        # before the wizard runs, everything is on.
        Setting.set("facility_configured", "1")
        Setting.set("mod_enabled:finance", "0")
        clinic["db"].session.commit()

    sections = guide_sections(
        clinic["sign_in"]("boss").get("/guide").data.decode())
    for absent in ("cashier", "invoices", "books", "payers", "treasury"):
        assert absent not in sections, (
            f"'{absent}' is still taught with finance switched off")
    assert "patients" in sections, "the rest of the guide went with it"


# --- the content itself ----------------------------------------------------

def test_every_section_points_at_a_module_that_exists():
    """A typo here hides a section from everybody, silently.

    ``can_access`` answers "no" for a module nobody has, so a misspelled key
    does not raise — it just quietly removes the section from every role
    including the admin, and nothing complains.
    """
    from app.utils.handbook import unknown_modules

    assert unknown_modules() == []


def test_every_bullet_is_written_in_both_languages():
    """Half of this program's users read English and half read Arabic.

    Checked by *script*, not by length: a copy-pasted pair with the Arabic in
    both slots passes any "both are non-empty" test, and that is exactly the
    mistake this file's shape invites.
    """
    from app.utils.handbook import CAPABILITY_LABELS, SECTIONS

    pairs = []
    for section in SECTIONS:
        pairs.append((section["key"], "title", section["title"]))
        for index, line in enumerate(section["lines"]):
            pairs.append((section["key"], f"line {index}", line))
    for key, label in CAPABILITY_LABELS.items():
        pairs.append((key, "capability", label))

    for key, where, (arabic, english) in pairs:
        assert arabic.strip() and english.strip(), f"{key} {where} is empty"
        assert ARABIC.search(arabic), f"{key} {where}: Arabic slot is not Arabic"
        assert not ARABIC.search(english), (
            f"{key} {where}: Arabic text left in the English slot")


def test_the_roadmap_is_written_in_both_languages_too():
    """Same rule for the About page's plan, which is the longest prose here."""
    from app.utils.project import (BUILDING, DEFERRED, DONE, NEXT, PRINCIPLES,
                                   SUMMARY)

    items = list(DONE) + list(BUILDING) + list(NEXT) + list(DEFERRED)
    items.append(SUMMARY)
    for arabic, english in items:
        assert ARABIC.search(arabic) and not ARABIC.search(english)
    for title_ar, title_en, body_ar, body_en in PRINCIPLES:
        assert ARABIC.search(title_ar) and not ARABIC.search(title_en)
        assert ARABIC.search(body_ar) and not ARABIC.search(body_en)


def test_what_is_deferred_is_published_next_to_what_is_done(clinic):
    """The section every roadmap leaves out, and the reason for this page.

    A clinic deciding how far to rely on this needs to know that device
    integration and multi-branch are **decisions**, not oversights. A roadmap
    with no deferred list reads as a promise of everything.
    """
    from app.utils.project import DEFERRED

    assert DEFERRED, "the deferred list is empty — that is the tell"
    body = clinic["sign_in"]("boss").get("/about").data.decode()
    assert "مؤجّل عن قصد" in body
    for arabic, _ in DEFERRED:
        assert arabic in body


# --- the About page's figures ---------------------------------------------

def test_the_figures_are_counted_at_render_time_not_typed(clinic):
    """The whole point of the numbers card.

    A figure written into the template is true the day it is written. This
    adds a patient between two renders and expects the page to notice — which
    a hard-coded number cannot do.
    """
    client = clinic["sign_in"]("boss")
    before = text_of(client.get("/about").data.decode())

    with clinic["app"].app_context():
        from datetime import date

        from app.models import Patient
        clinic["db"].session.add(Patient(
            patient_number="P-NEW", full_name="طفل تاني", gender="female",
            date_of_birth=date(2024, 5, 1), is_active=True))
        clinic["db"].session.commit()

    after = text_of(client.get("/about").data.decode())
    assert before != after, "the page did not notice a new patient file"
    # Asserted on the figure and its own label, not on the digit anywhere on
    # the page. This looked for " 2 " in the whole text, and the page is full
    # of other numbers — the notification badge, the date, the module count.
    # It failed on a day the badge happened to read 2, having never once
    # checked the figure it is named after.
    assert "1 ملف مريض" in before
    assert "2 ملف مريض" in after


def test_the_page_states_what_this_installation_actually_ships(clinic):
    """ICD-10 is bundled and ICD-11 is not, and the page must say so honestly.

    The figure comes from ``icd.coverage()`` — the same function the doctor's
    version picker asks — so the page cannot advertise codes the search cannot
    find.
    """
    from app.utils.icd import coverage

    body = clinic["sign_in"]("boss").get("/about").data.decode()
    total = coverage()["10"]["total"]
    assert f"{total:,}" in body
    if coverage()["11"]["total"] == 0:
        # The plan may *mention* ICD-11 as work in progress — that is honest.
        # What must not appear is a count of codes this machine does not hold.
        assert "كود ICD-11" not in text_of(body), (
            "ICD-11 codes are advertised on a machine holding none of them")


# --- the people section ----------------------------------------------------

def test_a_doctor_appears_only_when_the_clinic_names_one(clinic):
    """No real person's biography belongs compiled into a program.

    The doctors a clinic credits differ per installation, so the section is
    absent until somebody fills it in — rather than shipping a placeholder
    name that every clinic then has to notice and remove.
    """
    client = clinic["sign_in"]("boss")
    assert "الإشراف الطبي" not in client.get("/about").data.decode()

    client.post("/about/people", data={
        "action": "add",
        "name": "د. منى حسن",
        "title": "استشاري طب الأطفال",
    }, follow_redirects=True)

    body = client.get("/about").data.decode()
    assert "د. منى حسن" in body and "استشاري طب الأطفال" in body


def test_the_developer_credit_is_the_copyright_holder(clinic):
    """The credit already existed — as 0.64rem type down the side of every
    screen. It is the same person, said where somebody will read it."""
    body = clinic["sign_in"]("boss").get("/about").data.decode()
    assert "محمد خفاجة" in body


@pytest.mark.parametrize("username", ["desk", "doc", "acct"])
def test_only_an_admin_can_edit_the_credits(clinic, username):
    """An editable page on a shared screen is an editable page for whoever is
    standing at it. The form is admin-only, and so is the endpoint behind it —
    hiding the button is not a permission."""
    client = clinic["sign_in"](username)
    assert "people-edit" not in client.get("/about").data.decode()

    client.post("/about/people", data={"action": "add", "name": "دخيل"},
                follow_redirects=True)
    with clinic["app"].app_context():
        from app.models import AboutPerson
        assert AboutPerson.query.count() == 0
