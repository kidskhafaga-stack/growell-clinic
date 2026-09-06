"""Two reception screens that showed one thing and held another.

Both reported off a real desk, and both are the same fault wearing different
clothes: **the screen said something the program was not holding**, so the
person in front of it did the right thing and the program refused.

**The walk-in doctor.** The box showed a doctor's name. Pressing the button
answered "choose a doctor". The control was a ``<select>`` with no empty
option, so a browser with nothing chosen paints the first row of the list —
and the state behind it stayed empty, because nothing had fired a change. The
only way out was to pick a *different* doctor and come back, which is the
change the state had been waiting for. Reported in those words: *"لازم تختار
طبيب تاني وبعد كده ترجع للطبيب اللي قدامه علشان البرنامج يحجز"*.

The fix is not an empty option. It is **one owner**: a search box that holds
the answer and writes it, seeded with the doctor the board is already showing.
And a search box rather than a list for the reason every other screen in this
program has one — *"موضوع الدروب ليست مش واقعي لو كذا طبيب متاح في نفس
الوقت"*. A list is fine at four doctors and *is* the screen at forty.

**The patient search on the booking form.** The results came out underneath
the card below them — *"البحث بيظهر مختفى تحت"*. Every section on that screen
is a stacking context of its own, because ``.gc-scale-in`` ends on a
transform; a later sibling then paints over an earlier sibling's absolutely
positioned child however high that child's own z-index is. The same fault the
theme already documents for ``.card:has(details[open])``, and it takes the
same one layer to fix — one, and never more, because the chrome above the
content is what a bigger number would go through.
"""
import os
import re
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def desk(clinic):
    """A clinic with two doctors, so the board carries no single default."""
    from app.models import User

    db = clinic["db"]
    with clinic["app"].app_context():
        other = User(username="doc2", full_name="د. تاني", role="doctor",
                     is_active=True)
        other.set_password("secret")
        db.session.add(other)
        db.session.commit()
        clinic["other"] = other.id
    return clinic


def _board(desk, **args):
    query = "&".join(f"{k}={v}" for k, v in args.items())
    return desk["sign_in"]("boss").get(
        f"/appointments/?{query}").get_data(as_text=True)


# --------------------------------------------------- the doctor that was not

def test_the_walk_in_doctor_is_not_a_dropdown(desk):
    """A list of every doctor is fine at four and is the screen at forty. The
    program has one search box for "which doctor?" and this was the screen
    still rendering its own list."""
    page = _board(desk)
    walkin = page.split("modal==='walkin'")[1].split("modal==='waitlist'")[0]
    assert "gcDoctorPicker" in walkin, "the walk-in has no doctor search"
    # The visit type is still a list, and rightly — six fixed kinds is what a
    # dropdown is for. What must be gone is a list of *people*.
    assert 'x-model="f.doctorId"' not in walkin
    assert 'x-model="wf.doctorId"' not in walkin


def test_the_waiting_list_keeps_its_list_and_that_is_deliberate(desk):
    """It is a *preference*, not a field: "any doctor" is the usual answer and
    a search box with no way back to "anybody" is a worse control than the
    list it replaced. Its first option is that answer, so the box never shows
    a doctor the program is not holding — which is the whole complaint."""
    page = _board(desk)
    waitlist = page.split("modal==='waitlist'")[1]
    assert '<option value="">' in waitlist


def test_the_box_never_shows_a_doctor_the_program_is_not_holding(desk):
    """The whole bug in one line.

    A ``<select>`` whose first option is a real doctor paints that doctor
    while the state holds nothing — so the desk reads a name, presses the
    button, and is told to choose a doctor. A search box shows what it holds
    and nothing else: empty state, empty box.
    """
    page = _board(desk)
    # The picker is seeded from the server with the board's doctor. Two
    # doctors and no filter means no default, so it is seeded with nothing —
    # and an empty box is the truth.
    seeded = re.search(r"gcDoctorPicker\([^)]*?,\s*(null|\d+)\s*,", page,
                       re.S)
    assert seeded, "the walk-in picker is not seeded from the server"
    assert seeded.group(1) == "null"


def test_the_board_filtered_to_a_doctor_starts_on_that_doctor(desk):
    """The reception desk is looking at one doctor's day. Making them type the
    name that is already at the top of the screen is the click this fixes."""
    page = _board(desk, doctor_id=desk["ids"]["doctor"])
    assert re.search(
        r"gcDoctorPicker\([^)]*?,\s*%d\s*," % desk["ids"]["doctor"], page,
        re.S), "the board's own doctor is not carried into the walk-in"


def test_a_clinic_with_one_doctor_starts_on_them(clinic):
    """There is nothing to choose, so nothing should have to be chosen."""
    page = clinic["sign_in"]("boss").get(
        "/appointments/").get_data(as_text=True)
    assert re.search(
        r"gcDoctorPicker\([^)]*?,\s*%d\s*," % clinic["ids"]["doctor"], page,
        re.S)


def test_the_walk_in_and_the_waiting_list_do_not_share_a_field(desk):
    """They are two controls. Sharing one field meant opening one modal after
    the other left a box showing one doctor and the state holding another —
    the same parting of screen and state, one screen along."""
    page = _board(desk)
    assert "wf: { doctorId" in page, "the walk-in doctor has no field of its own"
    assert 'doctor_id: this.wf.doctorId' in page


def test_opening_the_modal_does_not_clear_what_the_box_shows(desk):
    """Resetting the field while the box is still on the screen would put the
    two out of step again, in the other direction."""
    page = _board(desk)
    walk = page.split("openWalkIn()")[1][:400]
    assert "doctorId" not in walk, \
        "openWalkIn writes the doctor the search box owns"


# --------------------------------------------- the list that came out beneath

def test_the_patient_search_is_not_painted_over_by_the_card_below(desk):
    """Every section on the booking form is its own stacking context, so the
    results list needs its section lifted or it is drawn underneath the next
    one — which is what a desk saw."""
    page = desk["sign_in"]("boss").get(
        "/appointments/new").get_data(as_text=True)
    head = page.split('class="md-section')[1][:200]
    assert "z-index:1" in head.replace(" ", ""), \
        "the section holding the search is not lifted above the ones below it"


def test_and_it_is_lifted_by_one_layer_and_no_more(desk):
    """The budget the theme sets and explains: the chrome — topbar 20, sidebar
    30 — sits above the content, and nothing inside it may reach that far. A
    fix of 50 here would put the search list over the notification panel."""
    page = desk["sign_in"]("boss").get(
        "/appointments/new").get_data(as_text=True)
    flat = page.replace(" ", "")
    for high in ("z-index:20", "z-index:30", "z-index:50", "z-index:99"):
        assert high not in flat.split("md-section")[1][:300], \
            f"the booking form reaches the chrome with {high}"
