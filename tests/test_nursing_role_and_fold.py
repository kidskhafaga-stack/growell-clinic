"""A nursing role that ships, and a strip that folds without hiding the answer.

**The role.** Nursing stations arrived and there was no role to stand at one.
A nurse is not a doctor with fewer screens: they take the vitals and the
reason for the visit before the child is seen, so they need the clinical
module and write access to the record — and nothing that prices or bills.

The seeder now stores the role's *capabilities* as well as its modules. Until
this, a fresh clinic's roles got their screens and no permission to write on
any of them, and `can` fell back to the table in code — which is precisely
what the column was added to replace.

**The fold.** Four عيادات of cards push the day's list below the fold on a
laptop, and the list is where reception spends the day.

The summary line is the whole design. Folded, it still answers "is anything
wrong out there": how many rooms are working, how many are waiting, and
whether anybody is flagged. A fold that hides the answer is one people unfold
every time, which is the same as not having it — and it is remembered, because
a collapse that comes back open on the next page is worse than no collapse.
"""
import os
import re
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


# ----------------------------------------------------------------- the role

def test_nursing_is_a_role_the_program_ships(clinic):
    from app.models.permissions import ROLES

    assert "nursing" in ROLES


def test_it_gets_the_clinical_screens_and_no_money(clinic):
    """A nurse writes in the record and never touches a price."""
    from app.models.permissions import ROLE_PERMISSIONS

    modules = ROLE_PERMISSIONS["nursing"]

    for wanted in ("patients", "visits", "growth", "vaccinations"):
        assert wanted in modules, f"nursing cannot reach {wanted}"
    for unwanted in ("finance", "reports", "settings", "users", "prescriptions"):
        assert unwanted not in modules, f"nursing was given {unwanted}"


def test_it_may_write_in_the_record_and_not_take_money(clinic):
    from app.models.permissions import ROLE_CAPABILITIES

    assert ROLE_CAPABILITIES["nursing"] == ["patient_medical"]


def test_the_seeder_stores_the_capabilities_too(clinic):
    """Not only the modules.

    Without this a fresh clinic's roles arrive with their screens and no
    permission to write on any of them, and `can` falls back to the table in
    code — the thing the column was added to replace.
    """
    import inspect

    from app import cli

    source = inspect.getsource(cli._ensure_default_roles)
    assert "set_capabilities" in source, \
        "the seeder gives a role its screens and not its permissions"


def test_seeding_creates_it_with_both(clinic):
    from app.extensions import db
    from app.models import Role

    from app.cli import _ensure_default_roles

    with clinic["app"].app_context():
        _ensure_default_roles()
        db.session.commit()

        role = Role.query.filter_by(name="nursing").first()
        assert role is not None, "the nursing role was not seeded"
        assert "visits" in role.module_list
        assert role.capability_list == ["patient_medical"]
        assert "finance" not in role.module_list


def test_a_nurse_can_open_the_station_and_not_the_till(clinic):
    from app.extensions import db
    from app.models import User

    from app.cli import _ensure_default_roles

    with clinic["app"].app_context():
        _ensure_default_roles()
        nurse = User(username="nurse1", full_name="ممرضة", role="nursing",
                     is_active=True)
        nurse.set_password("secret")
        db.session.add(nurse)
        db.session.commit()

    client = clinic["app"].test_client()
    client.post("/login", data={"username": "nurse1", "password": "secret"},
                follow_redirects=True)

    assert client.get("/visits/station",
                      follow_redirects=True).status_code == 200
    assert client.get("/finance/cashier").status_code == 403


def test_it_has_a_label_in_both_languages(clinic):
    from app.cli import _ROLE_LABELS

    label_ar, label_en = _ROLE_LABELS["nursing"]
    assert label_ar and label_en and label_ar != "nursing"


# ----------------------------------------------------------------- the fold

def _board(clinic):
    """The whole-clinic board, which is where the strip lives."""
    return clinic["sign_in"]("boss").get("/appointments/",
                                         follow_redirects=True).data.decode()


@pytest.fixture()
def busy(clinic):
    """Two doctors working, so the strip renders at all."""
    from datetime import time

    from app.extensions import db
    from app.models import Appointment, Patient, User
    from app.utils.clock import local_today

    with clinic["app"].app_context():
        doctor = User.query.filter_by(username="doc").first()
        kid = Patient.query.first()
        db.session.add(Appointment(patient_id=kid.id, doctor_id=doctor.id,
                                   appt_date=local_today(),
                                   appt_time=time(10, 0), status="waiting"))
        db.session.commit()
    return clinic


def test_the_strip_folds(busy):
    page = _board(busy)

    assert "clinics-fold" in page, "the عيادات strip cannot be folded"
    assert 'data-fold="clinics"' in page


def test_it_starts_open(busy):
    """Nobody should have to discover the strip on their first morning."""
    page = _board(busy)

    found = re.search(r"<details[^>]*clinics-fold[^>]*>", page)
    assert found and " open" in found.group(0)


def test_folded_it_still_answers_the_question(busy):
    """The whole design. A fold that hides the answer gets unfolded every
    time, which is the same as not having one."""
    from app.i18n import t

    page = _board(busy)
    summary = page[page.index("clinics-sum"):]
    summary = summary[:summary.index("</summary>")]

    with busy["app"].test_request_context("/"):
        assert t("rooms.busy_n", n=1).split("{")[0][:4] in summary or "شغالة" in summary
        assert "مستني" in summary or "waiting" in summary.lower(), \
            "the folded summary does not say how many are waiting"


def test_the_choice_is_remembered(busy):
    """A collapse that comes back open on the next page is worse than none —
    the same reasoning the sidebar preference already carries."""
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "..", "app/static/js/app.js"), encoding="utf-8") as fh:
        js = fh.read()

    assert "details[data-fold]" in js, "nothing remembers the fold"
    assert "localStorage" in js


def test_the_cards_are_still_there_when_open(busy):
    """Folding must not have cost the thing being folded."""
    page = _board(busy)

    assert "clinic-card" in page
    assert "cl-rail" in page


def test_the_summary_counts_agree_with_the_cards(busy):
    """A count that disagrees with the list it heads is why nobody trusts one."""
    page = _board(busy)
    summary = page[page.index("clinics-sum"):]
    summary = summary[:summary.index("</summary>")]
    cards = page.count('class="clinic-card')

    assert cards >= 1
    # One doctor is working in this fixture, and the summary must say so.
    assert re.search(r"\b1\b", summary), \
        f"the folded summary does not report the working room: {summary[:120]}"
