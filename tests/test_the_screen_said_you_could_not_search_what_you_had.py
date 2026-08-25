"""The clinic downloaded ICD-11 and the screen still said to type it by hand.

Reported with two screenshots: *"انا حملت ICD 11 ليه مش بقدر ابحث فيه؟ وفي ملف
المريض مفيش بحث؟ ليه"*.

**Two different faults, and only one of them was in the search.**

The first was a sentence. `search_icd` has always searched every version that
has codes on the machine — but the box said *"Search by name or code
(ICD-10)…"* and the line under it said *"For ICD-11 or any diagnosis not
listed, type the code and name manually and choose version 11"*. Both were
written when nothing of ICD-11 was loaded, and both stayed after it was. A
clinic that had imported the classification was told by its own program that
it could not search it, and believed the program. Nothing was broken except
what the screen claimed.

The second was real: the patient file's problem list had **no search at all**
— three text boxes, one of them called "ICD code". So the same diagnosis
picked in a visit and typed on the problem list ended up spelled two ways with
the code on only one of them, and the problem list is the thing a locum reads
first.

And there were two endpoints answering one question, with a comment in one of
them saying so. There is one now.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def with_icd11(clinic):
    """A clinic that has imported ICD-11, as the reporter had."""
    from app.utils import icd

    icd.install_full("11", [("CA23", "Asthma, unspecified"),
                            ("5A11", "Type 2 diabetes mellitus"),
                            ("BA00", "Essential hypertension")])
    yield clinic
    if os.path.exists(icd._FULL["11"]):
        os.remove(icd._FULL["11"])
    icd._full_cache.pop("11", None)


# ------------------------------------- it could search it all along

def test_a_downloaded_icd11_is_searchable(with_icd11):
    """The claim the screen denied. Asserted through the endpoint a screen
    actually calls, not through the function underneath it."""
    found = (with_icd11["sign_in"]("doc")
             .get("/icd-search?q=CA23").get_json())

    assert found, "an imported ICD-11 code cannot be found"
    assert found[0]["code"] == "CA23"
    assert found[0]["version"] == "11"


def test_it_searches_by_name_too(with_icd11):
    found = (with_icd11["sign_in"]("doc")
             .get("/icd-search?q=asthma").get_json())

    assert any(r["version"] == "11" for r in found), \
        "searching by name never reaches ICD-11"


def test_the_search_never_asks_which_classification(with_icd11):
    """A doctor typing "asthma" wants the code, not a quiz about which book it
    is in. The endpoint takes no version and never has."""
    import inspect

    from app.blueprints.main.routes import icd_search

    source = inspect.getsource(icd_search)

    assert "version" not in source.split('"""')[-1], \
        "the shared search filters by version"


# ---------------------------------------- and the screen now says so

def test_the_box_no_longer_claims_to_be_icd_ten_only(clinic):
    """The sentence that caused the report."""
    page = (clinic["sign_in"]("doc")
            .get(f"/visits/{clinic['ids']['visit']}/record").get_data(as_text=True))

    assert "(ICD-10)" not in page, \
        "the search box still advertises itself as ICD-10 only"


def test_the_hint_names_what_this_machine_holds(with_icd11):
    page = (with_icd11["sign_in"]("doc")
            .get(f"/visits/{with_icd11['ids']['visit']}/record")
            .get_data(as_text=True))

    assert "ICD-10 + ICD-11" in page, \
        "the screen does not say which classifications it can search"


def test_a_clinic_without_it_is_not_promised_it(clinic):
    """The other direction, and the reason the sentence is generated rather
    than written: a machine with only ICD-10 must not claim ICD-11."""
    page = (clinic["sign_in"]("doc")
            .get(f"/visits/{clinic['ids']['visit']}/record").get_data(as_text=True))

    assert "ICD-10 + ICD-11" not in page
    assert "ICD-10" in page


# --------------------------------- the problem list has a search now

def test_the_problem_list_can_search(clinic):
    """It had three text boxes and no way to look anything up, so the same
    diagnosis was spelled one way in a visit and another on the list a locum
    reads first."""
    page = (clinic["sign_in"]("doc")
            .get(f"/patients/{clinic['ids']['child']}").get_data(as_text=True))

    assert "/icd-search" in page, "the problem list still has no ICD search"
    assert "gcPicker" in page, "it is not the picker the rest of the program uses"


def test_it_fills_the_code_and_both_names(clinic):
    """Filling one box and leaving the others is how a list ends up with an
    Arabic name and an English one that are not the same diagnosis."""
    page = (clinic["sign_in"]("doc")
            .get(f"/patients/{clinic['ids']['child']}").get_data(as_text=True))

    for ref in ("x-ref=\"title\"", "x-ref=\"titleEn\"", "x-ref=\"code\""):
        assert ref in page, f"the picker cannot reach {ref}"


def test_it_does_not_read_a_global_that_is_not_there(clinic):
    """`window.current_lang` is set inside the visit screen's own script block
    and is undefined everywhere else. Reading it here would have silently
    always taken the other branch — the kind of fault that shows as "the
    Arabic name never fills in" and nothing in a log."""
    import pathlib

    root = pathlib.Path(__file__).resolve().parent.parent
    markup = (root / "app/templates/patients/profile.html").read_text(encoding="utf-8")

    code = "\n".join(line for line in markup.splitlines()
                     if "window.current_lang" in line and "#}" not in line
                     and not line.strip().startswith("`"))
    assert not code.strip(), f"the profile reads a global it does not set: {code}"


# ------------------------------------- one question, one answer

def test_there_is_one_icd_search_in_the_program(clinic):
    """Two endpoints answered this, and one of them carried a comment saying
    so. A third screen needing it was the moment to stop having two."""
    urls = [str(r) for r in clinic["app"].url_map.iter_rules()
            if "icd" in str(r).lower() and "search" in str(r).lower()]

    assert urls == ["/icd-search"], f"more than one ICD search: {urls}"


def test_it_is_not_behind_a_module_a_clinic_can_switch_off(clinic):
    """The reason it sits in `main`: a clinic can turn the prescriptions
    module off, and the diagnosis picker on the patient file must not go with
    it. A classification is not patient data — the query carries nothing about
    anybody, and it is the same published list on every machine."""
    answer = clinic["sign_in"]("desk").get("/icd-search?q=asthma")

    assert answer.status_code == 200


def test_but_it_still_needs_a_login(clinic):
    answer = clinic["app"].test_client().get("/icd-search?q=asthma")

    assert answer.status_code in (301, 302, 401)


# ------------------- found while looking at the picker, and older than it

def test_the_live_notice_script_is_not_html_escaped(clinic):
    """A JavaScript syntax error that had been on two screens for a while.

    Found by opening the patient file in a real browser to check the new
    picker: the console said `Unexpected token '&'`, and it was there without
    the picker too. The live "this page changed — somebody recorded something"
    block wrote its strings as `{{ … |tojson|forceescape }}`, which produced
    `&#34;` inside a `<script>`. A browser does not decode HTML entities
    inside a script, so the parser stopped at the `&` and **the block never
    ran on either screen**.

    The repo-wide rule pairs those two filters *inside an attribute*, where the
    quotes `tojson` emits would end it. There is no attribute in a script
    block, and Flask's `tojson` is already script-safe on its own.
    """
    import pathlib

    root = pathlib.Path(__file__).resolve().parent.parent
    for name in ("app/templates/patients/profile.html",
                 "app/templates/visits/record.html"):
        markup = (root / name).read_text(encoding="utf-8")
        block = markup[markup.index("gcLiveNotify"):]
        block = block[:block.index("</script>")]
        # The filter, not the word: the block carries a comment explaining
        # why the filter is absent, and matching the word matched the note.
        assert "|forceescape" not in block.replace(" ", ""), \
            f"{name} html-escapes inside a script block again"
        assert "tojson" in block, f"{name} stopped escaping altogether"


def test_the_notice_renders_as_javascript_and_not_entities(clinic):
    """Asserted on the rendered page, not only on the template — the fault was
    only ever visible in the output."""
    page = (clinic["sign_in"]("doc")
            .get(f"/patients/{clinic['ids']['child']}").get_data(as_text=True))

    script = page[page.index("gcLiveNotify"):]
    script = script[:script.index("</script>")]

    assert "&#34;" not in script and "&amp;" not in script, \
        "the live-notice script is still full of HTML entities"


# ------------------ which book the code came from, and the bug under it

def test_picking_a_code_files_it_under_its_own_classification(with_icd11):
    """The fault behind the request, and worse than the request.

    Asked for: *"لازم يبقى في تمييز الكود ده ICD 10 ولا ICD 11"*. The list did
    not say — but `applyIcd` also carried `this.version = '10'` as a constant,
    so choosing an ICD-11 code **recorded it as ICD-10**. The search reaches
    both books and every row knows which one it came from; the one line that
    had to use that threw it away.
    """
    import pathlib

    root = pathlib.Path(__file__).resolve().parent.parent
    markup = (root / "app/templates/visits/record.html").read_text(encoding="utf-8")
    body = markup[markup.index("applyIcd(r) {"):]
    body = body[:body.index("},")]

    assert "r.version" in body, \
        "picking a code still files it under a hard-coded classification"
    assert "this.version = '10';" not in body


def test_each_row_says_which_classification_it_is(with_icd11):
    """Two books searched at once make a bare code ambiguous — which is a
    consequence of the search being fixed, and had to be answered with it."""
    page = (with_icd11["sign_in"]("doc")
            .get(f"/visits/{with_icd11['ids']['visit']}/record")
            .get_data(as_text=True))

    assert "'ICD-' + r.version" in page, \
        "the visit's diagnosis list does not say which classification a code is"

    profile = (with_icd11["sign_in"]("doc")
               .get(f"/patients/{with_icd11['ids']['child']}").get_data(as_text=True))
    assert "'ICD-' + r.version" in profile, \
        "the problem list does not say which classification a code is"


def test_a_problem_records_the_classification_too(with_icd11):
    """`PatientProblem` held the code alone. "CA23" and "J45" are each just a
    string until something says which book they belong to — and the problem
    list is what a locum reads first."""
    from app.models import PatientProblem

    boss = with_icd11["sign_in"]("doc")
    boss.post(f"/patients/{with_icd11['ids']['child']}/problems",
              data={"title": "ربو", "title_en": "Asthma",
                    "icd_code": "CA23", "icd_version": "11"},
              follow_redirects=True)

    with with_icd11["app"].app_context():
        row = PatientProblem.query.filter_by(icd_code="CA23").first()

    assert row is not None and row.icd_version == "11"


def test_a_version_nobody_recognises_is_not_stored(with_icd11):
    """The code box beside it can be typed by hand, so the version arriving
    with it is checked rather than trusted. A classification the program does
    not know is worse than none: it would print on the screen as fact."""
    from app.models import PatientProblem

    boss = with_icd11["sign_in"]("doc")
    boss.post(f"/patients/{with_icd11['ids']['child']}/problems",
              data={"title": "حاجة", "icd_code": "X1",
                    "icd_version": "99"}, follow_redirects=True)

    with with_icd11["app"].app_context():
        row = PatientProblem.query.filter_by(icd_code="X1").first()

    assert row is not None and row.icd_version is None


def test_an_older_problem_shows_its_code_without_a_guess(clinic):
    """Every problem recorded before the column existed has an answer nobody
    wrote down. Printing "ICD-10" against them would be inventing it."""
    from app.extensions import db
    from app.models import PatientProblem

    with clinic["app"].app_context():
        db.session.add(PatientProblem(patient_id=clinic["ids"]["child"],
                                      title="قديم", icd_code="J45"))
        db.session.commit()

    page = (clinic["sign_in"]("doc")
            .get(f"/patients/{clinic['ids']['child']}").get_data(as_text=True))

    assert "J45" in page
    assert "J45 · ICD-" not in page, "a classification was invented for an old row"
