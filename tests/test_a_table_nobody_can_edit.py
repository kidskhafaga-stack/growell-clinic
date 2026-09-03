"""A clinical table with no box to type in, and the question that raised.

Reported while reading the settings screen: *"هو فى الجدول تحت العيادة مش
المفروض تعدل او تعمل اجراء ؟ انا شايف مفيش تعديل"*.

It is a fair question, and the screen was the thing at fault. The fever and
oxygen limits directly above have an input on every row — a clinic sets its
own triage policy — so a table underneath them with nothing to type in reads
as a screen somebody forgot to finish.

It is not unfinished, and it must not become editable. A fever threshold is
one number with an obvious meaning. The bilirubin table is ninety-six numbers
from one published guideline, and a cell edited in the middle of it produces a
table that is no longer that guideline and is not any other one either — while
still looking authoritative to whoever reads it at three in the morning.

So the screen says so, and the one action a person can honestly take on a
hand-transcribed clinical table — read it, and put their name to it — now
records **whose** name. A tick in a box names nobody, and the first question
anybody asks about a decision taken on these numbers is who accepted them.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def newborn_clinic(clinic):
    """A clinic that says it sees newborns — the table is theirs to review."""
    from app.utils.facility import apply_facility, derive_modules

    caps = ["general_consultation", "newborn_care"]
    with clinic["app"].app_context():
        apply_facility("pediatric_center", "عيادة", caps, derive_modules(caps))
        clinic["db"].session.commit()
    return clinic


def _save(client, **extra):
    """Post the settings form the way the screen does."""
    data = {"clinic_name": "عيادة", "clinic_timezone": "Africa/Cairo"}
    data.update(extra)
    return client.post("/settings/", data=data, follow_redirects=True)


def test_the_screen_says_the_table_is_not_edited_here(newborn_clinic):
    from app.i18n import t

    with newborn_clinic["app"].test_request_context("/"):
        sentence = t("settings.j_not_editable")

    page = newborn_clinic["sign_in"]("boss").get(
        "/settings/").get_data(as_text=True)
    assert sentence in page


def test_the_thresholds_the_clinic_does_set_still_have_a_box(newborn_clinic):
    """The other half of the sentence: the distinction only makes sense if the
    editable ones are visibly editable on the same screen."""
    page = newborn_clinic["sign_in"]("boss").get(
        "/settings/").get_data(as_text=True)
    assert 'name="triage_fever_0"' in page


def test_nothing_on_the_page_offers_to_edit_a_bilirubin_number(newborn_clinic):
    """The guard on the decision itself. If somebody later adds an input for
    these cells, this fails and they have to come and read the reasoning."""
    page = newborn_clinic["sign_in"]("boss").get(
        "/settings/").get_data(as_text=True)
    for field in ("jaundice_photo", "jaundice_exchange", "j_photo_", "j_ex_"):
        assert f'name="{field}' not in page


def test_accepting_the_table_records_who_and_when(newborn_clinic):
    from app.utils.jaundice import approval, confirmed

    client = newborn_clinic["sign_in"]("boss")
    _save(client, jaundice_table_confirmed="1")

    with newborn_clinic["app"].app_context():
        assert confirmed()
        signed = approval()
        assert signed["name"] == "المدير"
        assert signed["at"]


def test_the_name_is_shown_back_on_the_screen(newborn_clinic):
    client = newborn_clinic["sign_in"]("boss")
    _save(client, jaundice_table_confirmed="1")
    page = client.get("/settings/").get_data(as_text=True)
    assert "data-jaundice-approval" in page and "المدير" in page


def test_saving_again_does_not_move_the_date(newborn_clinic):
    """The stamp is the moment somebody accepted it, not the last time
    anybody pressed save on an unrelated setting.

    The stored moment is set back to last year before the second save rather
    than the two being compared as they fall: the stamp has minute resolution,
    so two saves in the same minute look identical whether or not the second
    one overwrote the first — and a test that cannot tell those apart is not
    testing anything. Found by mutation: re-stamping on every save passed the
    first version of this.
    """
    from app.models import Setting
    from app.utils.jaundice import approval

    client = newborn_clinic["sign_in"]("boss")
    _save(client, jaundice_table_confirmed="1")
    with newborn_clinic["app"].app_context():
        Setting.set("jaundice_table_confirmed_at", "2025-01-01T09:00")
        newborn_clinic["db"].session.commit()

    _save(client, jaundice_table_confirmed="1", clinic_motto="أطفالنا أمانة")
    with newborn_clinic["app"].app_context():
        assert approval()["at"] == "2025-01-01T09:00"


def test_withdrawing_the_acceptance_takes_the_name_with_it(newborn_clinic):
    """A clinic that unticks the box has taken the acceptance back. Leaving
    the previous name beside a table the program is no longer allowed to use
    would read as a sign-off that still stands."""
    from app.models import Setting
    from app.utils.jaundice import approval, confirmed

    client = newborn_clinic["sign_in"]("boss")
    _save(client, jaundice_table_confirmed="1")
    _save(client)                     # the box unticked

    with newborn_clinic["app"].app_context():
        assert not confirmed()
        assert approval() is None
        assert not Setting.get("jaundice_table_confirmed_by")


def test_an_acceptance_from_an_older_copy_still_stands(newborn_clinic):
    """Upgrading must not withdraw a sign-off somebody already gave. A clinic
    that accepted the table before the program recorded names keeps its
    acceptance, and the screen says the name is not known rather than
    pretending nobody accepted."""
    from app.models import Setting
    from app.utils.jaundice import approval, confirmed

    with newborn_clinic["app"].app_context():
        Setting.set("jaundice_table_confirmed", "1")
        newborn_clinic["db"].session.commit()
        assert confirmed()
        assert approval() == {"name": "", "at": ""}


def test_the_calculator_still_refuses_until_it_is_accepted(newborn_clinic):
    """None of the above weakens the gate itself, which is the whole reason
    the table is on a settings screen at all."""
    from app.models import Patient
    from app.utils.jaundice import assess

    with newborn_clinic["app"].app_context():
        baby = Patient(full_name="مولود")
        assert assess(baby, 12.0)["reason"] == "table_not_confirmed"
