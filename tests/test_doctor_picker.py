"""One way to say which doctor, on every screen that asks.

**Measured before building.** A searchable doctor picker already existed and
exactly one screen used it — the prescription — because it was written inside
that template's own ``<script>`` and could not be reached from anywhere else.
Seven screens still rendered every doctor into a ``<select>``: the schedules,
the day board, the WhatsApp roster, the doctor statement, the invoice list, the
named discounts and the invoice itself.

A dropdown is fine at four doctors. At forty it *is* the screen: you open it,
scroll, and read forty names to find one.

**Two of the tests here are about a fault that only rendering finds.** Driving
the picker in a browser showed the id landing in the hidden field while the URL
never changed — the screen went on showing the previous doctor while the box
showed the new one, which is the worst way for a picker to fail because it
looks like it worked. It came from leaning on Alpine's magics (``$el``,
``$nextTick``) inside methods on a plain object, where they are not reliable.
"""
import html
import os
import re
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

# Every screen that used to hold the dropdown.
SCREENS = [
    "/appointments/schedules",
    "/appointments/",
    "/messages/roster",
    "/finance/statements",
    "/finance/invoices",
    "/finance/discounts",
]

SELECT = re.compile(r'<select[^>]*name="doctor_id"')


@pytest.fixture()
def crowded(clinic):
    """A centre rather than a single clinic: forty doctors."""
    with clinic["app"].app_context():
        from app.models import User
        db = clinic["db"]
        for i in range(40):
            user = User(username=f"pdoc{i}", full_name=f"طبيب رقم {i}",
                        role="doctor", is_active=True,
                        specialty="قلب الأطفال" if i % 2 else "طب الأطفال")
            user.set_password("x")
            db.session.add(user)
        db.session.commit()
    return clinic


# --- the list itself -------------------------------------------------------

def test_the_search_answers_by_name_and_by_specialty(crowded):
    """A receptionist told "book with the chest doctor" does not have a name.

    Searching only names would send them to ask somebody, which is what the
    dropdown already made them do.
    """
    boss = crowded["sign_in"]("boss")

    by_name = boss.get("/doctor-search?q=رقم 17").get_json()
    assert [d["name"] for d in by_name] == ["طبيب رقم 17"]

    by_specialty = boss.get("/doctor-search?q=قلب").get_json()
    assert len(by_specialty) >= 10
    assert all("قلب" in d["number"] for d in by_specialty)


def test_an_empty_query_offers_everybody(crowded):
    """A clinic has a handful of doctors, and making somebody guess the first
    two letters of a list that short is not searching — it is a hurdle."""
    rows = crowded["sign_in"]("boss").get("/doctor-search").get_json()
    assert len(rows) == 20, "the picker opened onto a near-empty list"


def test_it_answers_reception_who_has_no_prescriptions_module(crowded):
    """Why the endpoint moved out of ``prescriptions``.

    The searchable list lived behind ``prescriptions.doctor_search``. Reception
    needs it on the appointments board and has no prescriptions module — and a
    clinic can switch that module off entirely, which would have taken the
    doctor picker on unrelated screens with it.
    """
    desk = crowded["sign_in"]("desk")
    assert desk.get("/prescriptions/doctor-search").status_code == 403
    assert desk.get("/doctor-search").status_code == 200


def test_it_is_not_open_to_the_street(crowded):
    """The names are not secret — they are already on these screens for these
    users — but nothing here answers without a login."""
    anonymous = crowded["app"].test_client()
    response = anonymous.get("/doctor-search")
    assert response.status_code in (301, 302, 401), (
        "the staff list answered an unauthenticated request")


# --- the screens -----------------------------------------------------------

@pytest.mark.parametrize("url", SCREENS)
def test_every_screen_that_asked_now_searches(crowded, url):
    """The sweep, asserted per screen rather than "somewhere in the codebase".

    A macro imported without ``with context`` raises only on the screens that
    use its translations — so each one is opened rather than reasoned about.
    """
    body = crowded["sign_in"]("boss").get(url).data.decode()
    assert "gcDoctorPicker" in body, f"{url} has no doctor picker"
    assert not SELECT.search(body), f"{url} still renders the dropdown"


def test_no_doctor_dropdown_is_left_anywhere():
    """The one that catches the screen nobody remembered.

    Written as a sweep over the templates because the list above is one I
    wrote by hand, and the whole point of this change is that the next screen
    to need a doctor uses the macro instead of a fresh ``<select>``.
    """
    import pathlib

    root = pathlib.Path(__file__).resolve().parent.parent / "app" / "templates"
    offenders = [str(p.relative_to(root)) for p in root.rglob("*.html")
                 if SELECT.search(p.read_text(encoding="utf-8"))]
    assert offenders == [], f"doctor dropdowns left in: {offenders}"


# --- the fault that only the browser showed --------------------------------

def test_the_picker_carries_the_field_name_it_must_write(crowded):
    """The component writes the hidden input directly rather than through
    Alpine's binding, so it has to be told which field that is.

    With the binding, the value arrived a tick after the submit and the form
    posted the *previous* doctor — measured in a browser, where the id was in
    the field and the URL had not changed.
    """
    # Unescaped first: the field name goes through ``|forceescape`` into an
    # attribute, so the source holds &#34;doctor_id&#34; — which is what the
    # browser reads back as a plain string.
    body = html.unescape(
        crowded["sign_in"]("boss").get("/appointments/schedules").data.decode())
    assert re.search(r'gcDoctorPicker\([^)]*"doctor_id"', body, re.S), (
        "the picker was not told which field to write")


def test_a_filter_offers_a_way_back_to_everybody(crowded):
    """The difference between a field and a filter.

    The day board is a filter: a search box with no way back to "all doctors"
    would be a worse filter than the dropdown it replaced, which had the
    option built in.
    """
    boss = crowded["sign_in"]("boss")
    board = boss.get("/appointments/").data.decode()
    schedules = boss.get("/appointments/schedules").data.decode()

    assert re.search(r"gcDoctorPicker\([^)]*true,", board, re.S), (
        "the day board lost its 'all doctors' option")
    assert re.search(r"gcDoctorPicker\([^)]*false,", schedules, re.S), (
        "a schedule belongs to one doctor; 'all' is not a thing to offer")


def test_a_form_with_its_own_button_does_not_submit_on_choice(crowded):
    """The roster asks for a doctor *and* a date.

    Reloading the moment the doctor is chosen would send the form before
    anybody has touched the date next to it.
    """
    body = html.unescape(
        crowded["sign_in"]("boss").get("/messages/roster").data.decode())
    assert re.search(r'gcDoctorPicker\([^)]*"doctor_id",\s*false\)', body, re.S), (
        "the roster reloads as soon as a doctor is picked")
