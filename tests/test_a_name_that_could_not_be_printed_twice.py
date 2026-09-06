"""An Arabic prescription with an English name at the top of it.

Reported from a printout, with an arrow drawn at the name: the letterhead is
Arabic — the specialty, the hospital, the address, the licence — and the line
above all of it says **"Dr. Ahmed Gamal Kandil"**.

The cause is one column. ``rx_display_name`` is the doctor's own answer to
"what should the prescription say", and it was a **single field**, so whatever
was typed into it printed in both languages. A doctor who typed their English
name got it on the Arabic sheet, and the reverse for anybody who typed Arabic.

The argument for the fix is already written down in this codebase, in the
credits model: *"A name typed once cannot be shown in two languages. Every
other name in this program carries both — ``full_name`` / ``full_name_en`` on
a user, ``name`` / ``name_en`` on a service."* This was the one name that did
not, and it is the one printed largest.

**The fallback is what keeps an existing clinic unchanged.** Whichever side is
filled in answers for both, so every doctor who has typed one name goes on
seeing exactly that name on both sheets until somebody types the other.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def doctor(clinic):
    from app.models import User

    with clinic["app"].app_context():
        row = clinic["db"].session.get(User, clinic["ids"]["doctor"])
        row.full_name = "أحمد جمال قنديل"
        row.full_name_en = "Ahmed Gamal Kandil"
        row.professional_title = "consultant"
        clinic["db"].session.commit()
    return clinic


def _set(fx, **fields):
    from app.models import User

    with fx["app"].app_context():
        row = fx["db"].session.get(User, fx["ids"]["doctor"])
        for key, value in fields.items():
            setattr(row, key, value)
        fx["db"].session.commit()


def _printed(fx, lang):
    from app.models import User

    with fx["app"].app_context():
        return fx["db"].session.get(
            User, fx["ids"]["doctor"]).doctor_print_name(lang)


# ------------------------------------------------------------- the report

def test_the_arabic_sheet_no_longer_prints_the_english_name(doctor):
    """The bug, as one assertion. Both boxes filled, each page its own."""
    _set(doctor, rx_display_name="أحمد جمال قنديل",
         rx_display_name_en="Ahmed Gamal Kandil")
    assert "أحمد جمال قنديل" in _printed(doctor, "ar")
    assert "Ahmed Gamal Kandil" in _printed(doctor, "en")
    assert "Ahmed" not in _printed(doctor, "ar")


def test_one_side_filled_in_still_answers_for_both(doctor):
    """What keeps an existing clinic exactly where it was: every doctor there
    has typed one name, and it goes on printing on both sheets."""
    _set(doctor, rx_display_name="أحمد جمال قنديل", rx_display_name_en=None)
    assert "أحمد جمال قنديل" in _printed(doctor, "ar")
    assert "أحمد جمال قنديل" in _printed(doctor, "en")

    _set(doctor, rx_display_name=None, rx_display_name_en="Ahmed Gamal Kandil")
    assert "Ahmed Gamal Kandil" in _printed(doctor, "en")
    assert "Ahmed Gamal Kandil" in _printed(doctor, "ar")


def test_with_neither_typed_the_user_s_own_name_is_used(doctor):
    """Unchanged behaviour, and the reason the box is optional at all."""
    _set(doctor, rx_display_name=None, rx_display_name_en=None)
    assert "أحمد جمال قنديل" in _printed(doctor, "ar")
    assert "Ahmed Gamal Kandil" in _printed(doctor, "en")


# --------------------------------------------------- the rules around it

def test_the_title_still_follows_the_name_it_is_stuck_to(doctor):
    """The earlier fix, which this must not undo: an Arabic page showing a
    doctor whose only name is English still says "Dr.", not "د/"."""
    _set(doctor, rx_display_name=None, rx_display_name_en=None,
         full_name="Ahmed Gamal Kandil", full_name_en="Ahmed Gamal Kandil")
    assert _printed(doctor, "ar").startswith("Dr.")


def test_a_practice_name_is_still_printed_as_written(doctor):
    """The other rule this shares a function with: a clinic that puts its
    *practice* name on the paper must never be addressed as a doctor."""
    _set(doctor, rx_display_name="العيادة التخصصية للأطفال",
         rx_display_name_en="The Paediatric Specialty Clinic")
    assert _printed(doctor, "ar") == "العيادة التخصصية للأطفال"
    assert _printed(doctor, "en") == "The Paediatric Specialty Clinic"


def test_a_practice_name_on_one_side_only_is_still_a_practice_name(doctor):
    """The fallback must not turn a practice name into a person by crossing
    languages: if either box holds wording that is not this person's name, no
    title is added to either."""
    _set(doctor, rx_display_name="العيادة التخصصية للأطفال",
         rx_display_name_en=None)
    assert _printed(doctor, "en") == "العيادة التخصصية للأطفال"
    assert not _printed(doctor, "en").startswith("Dr.")


# ------------------------------------------------------------ the screens

@pytest.mark.parametrize("who,path", [
    ("doc", "/profile"),        # the doctor's own — the block is theirs
    ("boss", "/users/new"),     # and where an admin sets somebody else's
])
def test_the_english_box_is_on_the_screen(doctor, who, path):
    page = doctor["sign_in"](who).get(path)
    assert page.status_code == 200, path
    assert 'name="rx_display_name_en"' in page.get_data(as_text=True), path


def test_typing_it_saves_it(doctor):
    from app.models import User

    client = doctor["sign_in"]("doc")
    client.post("/profile", data={"rx_display_name": "أحمد جمال قنديل",
                                  "rx_display_name_en": "Ahmed Gamal Kandil"},
                follow_redirects=True)
    with doctor["app"].app_context():
        row = doctor["db"].session.get(User, doctor["ids"]["doctor"])
        assert row.rx_display_name_en == "Ahmed Gamal Kandil"


def test_the_paper_prints_the_name_for_the_page_it_is(doctor):
    """End to end, on the sheet the report came from."""
    _set(doctor, rx_display_name="أحمد جمال قنديل",
         rx_display_name_en="Ahmed Gamal Kandil")
    from app.models import Prescription

    db = doctor["db"]
    with doctor["app"].app_context():
        rx = Prescription(patient_id=doctor["ids"]["child"],
                          doctor_id=doctor["ids"]["doctor"])
        db.session.add(rx)
        db.session.commit()
        rx_id = rx.id

    client = doctor["sign_in"]("boss")
    arabic = client.get(f"/prescriptions/{rx_id}").get_data(as_text=True)
    assert "أحمد جمال قنديل" in arabic
    client.get("/lang/en")
    english = client.get(f"/prescriptions/{rx_id}").get_data(as_text=True)
    assert "Ahmed Gamal Kandil" in english
