"""The patient lookup, narrowed while you type instead of after you press.

Reported from the clinic, on a real screen: a phone number shared by three
siblings. Type it, press the button, wait for a page, read the list, click the
right Khafaga, wait for another page. The answer was right every time — the
asking was the slow part.

**The live search calls the same function the page does.** That is the whole
design and it is not an implementation detail: two searches that disagreed —
one while typing, one after Enter — would be a child appearing and then
vanishing, and a doctor cannot tell which of the two answers is the register's.
:func:`ai_lookup.find_patients` answers both, so there is one answer.

**The form is still a form.** With no JavaScript this page behaves exactly as
it did: type, press, read. The live list is an addition on top of a working
page, not a replacement for it — which is also why the server's own results
stay on screen until the box has moved on from what the server was asked. A
page whose results blink out because a script woke up is worse than no live
search.

**And it sends back only what the list shows.** A name, a file number, and
where clicking goes. Not the phone it may have matched on, not an age, not an
address. A search box is not a reason to put a row of the register on the wire.
"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

SEARCH = "/ai/lookup/search"


@pytest.fixture()
def register(clinic):
    """Two siblings on one phone — the case that was reported."""
    from app.extensions import db
    from app.models import Family, Parent, Patient

    with clinic["app"].app_context():
        family = Family(family_name="خفاجة")
        db.session.add(family)
        db.session.flush()
        db.session.add(Parent(family_id=family.id, full_name="محمد خفاجة",
                              relation="father", phone="01091626165"))
        for number, name_ar, name_en in (
                ("PM-2026-0014", "عمر محمد السيد خفاجة", "Omar Khafaga"),
                ("PM-2026-0937", "ميرال محمد السيد خفاجة", "Miral Khafaga")):
            db.session.add(Patient(
                patient_number=number, full_name=name_ar, full_name_en=name_en,
                gender="male", date_of_birth=date(2020, 3, 1),
                family_id=family.id, is_active=True))
        db.session.commit()
    return clinic


# ---------------------------------------------------------- it answers at all

def test_typing_a_shared_phone_narrows_to_both_siblings(register):
    rows = (register["sign_in"]("boss").get(f"{SEARCH}?q=01091626165")
            .get_json()["patients"])

    assert {r["number"] for r in rows} == {"PM-2026-0014", "PM-2026-0937"}, \
        f"the phone did not reach the family it belongs to: {rows}"


def test_a_row_carries_where_clicking_goes(register):
    """Built on the server, so the page never assembles a URL of its own — the
    one place a live list could quietly start pointing somewhere else."""
    rows = (register["sign_in"]("boss").get(f"{SEARCH}?q=عمر")
            .get_json()["patients"])

    assert rows, "nothing matched a name that is in the register"
    for row in rows:
        assert row["url"].startswith("/ai/lookup"), row
        assert f"patient_id={row['id']}" in row["url"], row


def test_one_letter_is_not_a_search(register):
    """The same floor the page has. "ع" is half a register, and answering it
    is a list nobody can use and a query nobody wanted."""
    rows = (register["sign_in"]("boss").get(f"{SEARCH}?q=ع")
            .get_json()["patients"])

    assert rows == []


def test_nothing_matching_is_an_empty_list_and_not_an_error(register):
    reply = register["sign_in"]("boss").get(f"{SEARCH}?q=zzzzz")

    assert reply.status_code == 200
    assert reply.get_json()["patients"] == []


# ------------------------------------------------- one question, one function

def test_it_answers_with_the_same_search_the_page_uses(register):
    """The property this whole change rests on.

    Measured rather than asserted about the source: the endpoint and the page
    are asked the same thing and have to name the same children. If they ever
    diverge, a doctor sees a child while typing and loses them on Enter, with
    no way to tell which list was the register's.
    """
    client = register["sign_in"]("boss")

    live = {r["number"] for r in
            client.get(f"{SEARCH}?q=خفاجة").get_json()["patients"]}
    page = client.get("/ai/lookup?q=خفاجة").get_data(as_text=True)

    assert live, "the case is not being exercised"
    for number in live:
        assert number in page, \
            f"{number} is offered while typing and missing after pressing"


# ------------------------------------------------------- and it says no more

def test_it_does_not_put_the_register_on_the_wire(register):
    """It matched on a phone number; it does not send one back.

    The list shows a name and a file number, so that is what crosses. Every
    extra field here is a field on somebody's browser tab, in a page that can
    be left open on a shared desk.

    The `url` is exempt from the phone check and only that field is, because
    what it echoes is the term the person typed — already in their address bar
    before this endpoint was called — carried so that clicking a result keeps
    the box filled and the back button works. The first draft of this test
    caught it and was wrong to: a search term is the searcher's, a phone on
    file is the family's, and they are not the same fact.
    """
    rows = (register["sign_in"]("boss").get(f"{SEARCH}?q=01091626165")
            .get_json()["patients"])

    assert rows, "the case is not being exercised"
    for row in rows:
        assert set(row) == {"id", "name", "number", "url"}, \
            f"the search reply grew a field: {sorted(row)}"
        for field in ("name", "number"):
            assert "01091626165" not in str(row[field]), \
                f"the phone it matched on came back inside {field}"

    # And a name search brings back no phone anywhere at all, which is the
    # same claim without the echo to argue about.
    others = (register["sign_in"]("boss").get(f"{SEARCH}?q=عمر")
              .get_json()["patients"])
    assert others, "the case is not being exercised"
    assert "01091626165" not in str(others), \
        "a name search returned the family's phone number"


def test_a_stranger_cannot_search_the_register(register):
    """A JSON endpoint is a door like any other. It was added for a search box
    and it reads patient names."""
    reply = register["app"].test_client().get(f"{SEARCH}?q=خفاجة")

    assert reply.status_code in (301, 302, 401, 403), \
        f"anyone can list patients: {reply.status_code}"
    if reply.status_code in (301, 302):
        assert "login" in reply.headers.get("Location", "").lower()


# --------------------------------------------------- the page still works alone

def test_the_form_still_submits_without_javascript(register):
    """The live list is an addition. Somebody on a locked-down browser, or a
    machine where the script fails to load, must still be able to look a child
    up — which is the whole page."""
    page = (register["sign_in"]("boss").get("/ai/lookup")
            .get_data(as_text=True))

    assert 'method="get"' in page, "the search form stopped being a form"
    assert 'name="q"' in page, "the search box lost the name the route reads"
    assert 'action="/ai/lookup"' in page


def test_the_servers_own_answer_is_not_thrown_away_on_arrival(register):
    """Landing on a page with results and having them vanish because a script
    initialised would be a regression dressed as a feature. The live list only
    takes over once the box has moved on from what the server was asked."""
    page = (register["sign_in"]("boss").get("/ai/lookup?q=خفاجة")
            .get_data(as_text=True))

    assert "PM-2026-0014" in page and "PM-2026-0937" in page, \
        "the server stopped rendering its own matches"
    assert 'x-show="!typing()"' in page, \
        ("the server's results are no longer guarded — either they hide on "
         "load or they stack under the live ones")
