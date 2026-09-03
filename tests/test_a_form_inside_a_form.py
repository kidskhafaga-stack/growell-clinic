"""A Save that only reloaded, and one card showing on every tab. One cause.

Reported from a live consultation, two symptoms at once:

    "عندي مشكله فى الحفظ فى الزيارة لما بدوس حفظ بعمل ريفريش ومش بيحفظ حاجه"
    "البيانات السريرية متكرر فى التشخيص وفى التابه الاولى ليه مش عارف؟"
    "هو محتفظ بالجزء الاول ده مع كل الشاشات — ده بج خطير"

Both came from four characters of HTML. The specialty panel's chips — follow
this condition, order this test — were written as little `<form>` elements,
and they sit **inside** the consultation form. HTML forbids that, and a browser
does not deal with it by ignoring the mistake: it ignores the inner `<form>`
start tag and then lets the inner `</form>` close the **outer** form.

So the consultation form ended halfway down the specialty panel:

* everything below the cut — the whole clinical card, the plan, the Save
  button — was no longer in any form, so pressing Save posted nothing and the
  page simply reloaded. Nothing was ever saved, and nothing said so;
* `x-show="tab==='case'"` is an attribute of that same form element, so the
  re-parented content was outside it and no tab could hide it. The clinical
  card appeared under the diagnoses, under the vaccinations, under everything.

It only appeared for a clinic that had switched the panels on **and** whose
panel carried conditions or chart tests — which is why it was invisible in
development and immediate in the clinic.

The fix is a button that names a form it does not sit inside, with the two
forms moved to the foot of the page. The test below is deliberately not about
those two chips: it walks the tags of a rendered screen and fails on **any**
form inside a form, because this is a mistake whose symptom appears three
sections away from its cause and points at neither.
"""
import os
import sys
from html.parser import HTMLParser

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


class Nesting(HTMLParser):
    """Where a ``<form>`` opens while another one is still open."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.nested = []          # (line, column) of every form inside a form

    def handle_starttag(self, tag, attrs):
        if tag != "form":
            return
        if self.depth:
            self.nested.append(self.getpos())
        self.depth += 1

    def handle_endtag(self, tag):
        if tag == "form":
            self.depth = max(0, self.depth - 1)


def forms_inside_forms(html):
    parser = Nesting()
    parser.feed(html)
    return parser.nested


@pytest.fixture()
def panelled(clinic):
    """A clinic that works a specialty — the state the bug needed.

    Cardiology, because it is the panel that carries both a condition list and
    chart tests, which is what put two forms inside the consultation form.
    """
    from app.models import Setting, User
    from app.utils.investigations import seed_investigations

    with clinic["app"].app_context():
        Setting.set("mod_enabled:panels", "1")
        doctor = User.query.get(clinic["ids"]["doctor"])
        doctor.specialty_panels = "cardiology"
        # The chart-test strip only draws for tests the catalogue actually
        # holds, and an empty catalogue would make the guard above pass by
        # drawing nothing — which is the vacuous pass this file exists to
        # avoid. See `test_the_panel_really_does_offer_its_chips`.
        seed_investigations()
        clinic["db"].session.commit()
    return clinic


def _record(clinic):
    page = clinic["sign_in"]("boss").get(
        f"/visits/{clinic['ids']['visit']}/record")
    assert page.status_code == 200
    return page.get_data(as_text=True)


# ------------------------------------------------------------- the guard ---
def test_no_form_is_drawn_inside_another_form_on_the_visit_screen(panelled):
    html = _record(panelled)
    nested = forms_inside_forms(html)
    assert not nested, (
        "a <form> is drawn inside another <form> at line/col "
        + ", ".join(f"{line}:{col}" for line, col in nested)
        + " — the browser will end the outer form there, and everything after "
          "it loses both its Save and the tab that hides it")


def test_the_panel_really_does_offer_its_chips(panelled):
    """The guard above passes trivially if the chips are not on the page at
    all, so this holds the state the bug needed: cardiology draws both."""
    html = _record(panelled)
    assert 'data-conditions="cardiology"' in html
    assert 'data-chart-tests="cardiology"' in html


def test_the_clinical_fields_are_inside_the_consultation_form(panelled):
    """The symptom itself, measured rather than inferred.

    The chief complaint and the Save button have to be between the opening tag
    of ``#visitForm`` and its matching close. When the form was cut short they
    were outside it — no Save, and no tab could hide them.
    """
    html = _record(panelled)
    start = html.index('id="visitForm"')
    # Walk from the form's opening tag counting depth, to find *its* close
    # rather than the first `</form>` that happens to follow.
    depth, index, close = 0, start, None
    while index < len(html):
        nxt_open = html.find("<form", index)
        nxt_close = html.find("</form>", index)
        if nxt_close == -1:
            break
        if nxt_open != -1 and nxt_open < nxt_close:
            depth += 1
            index = nxt_open + 5
            continue
        if depth == 0:
            close = nxt_close
            break
        depth -= 1
        index = nxt_close + 7
    assert close is not None, "#visitForm is never closed"

    inside = html[start:close]
    assert 'name="chief_complaint"' in inside
    assert 'name="clinical_exam"' in inside
    assert 'name="plan"' in inside


def test_the_chips_name_the_forms_they_are_not_inside(panelled):
    """The shape of the fix: a button may name a form it does not sit in."""
    html = _record(panelled)
    assert 'form="panelProblemForm"' in html
    assert 'form="panelTestForm"' in html
    assert 'id="panelProblemForm"' in html
    assert 'id="panelTestForm"' in html


# --------------------------------------------------- and they still work ---
def _chip_value(html, form_id):
    """What the first chip for this form actually carries, read off the page.

    Read rather than composed, after a mutation slipped: a chip that stopped
    naming *which* condition still passed a test that posted the value by
    hand. The page and the route are one chain and are checked as one.
    """
    import re

    match = re.search(
        r'<button[^>]*form="' + form_id + r'"[^>]*value="([^"]+)"', html)
    assert match, f"no chip on the page submits {form_id}"
    return match.group(1)


def test_a_condition_chip_still_puts_the_condition_on_the_file(panelled):
    """The chip carries `panel:code` and the program looks the wording up —
    a browser that posted the title could post any title, and this is a line
    on a child's problem list."""
    from app.models import PatientProblem
    from app.utils import panels

    value = _chip_value(_record(panelled), "panelProblemForm")
    with panelled["app"].app_context():
        wanted = next(c for c in panels.conditions_for("cardiology", "ar")
                      if c["code"] == value.split(":", 1)[1])

    client = panelled["sign_in"]("boss")
    client.post(f"/patients/{panelled['ids']['child']}/problems",
                data={"visit_id": panelled["ids"]["visit"],
                      "condition": value},
                follow_redirects=True)

    with panelled["app"].app_context():
        rows = PatientProblem.query.filter_by(
            patient_id=panelled["ids"]["child"]).all()
        assert [r.title for r in rows] == [wanted["label_ar"]]


def test_a_condition_chip_carrying_a_code_nobody_offers_writes_nothing(
        panelled):
    """The other half: an id that is not on the panel is not a condition, and
    inventing a title from it would put a made-up line on a child's file."""
    from app.models import PatientProblem

    client = panelled["sign_in"]("boss")
    client.post(f"/patients/{panelled['ids']['child']}/problems",
                data={"visit_id": panelled["ids"]["visit"],
                      "condition": "cardiology:not-a-real-condition"},
                follow_redirects=True)

    with panelled["app"].app_context():
        assert PatientProblem.query.filter_by(
            patient_id=panelled["ids"]["child"]).count() == 0


def test_a_test_chip_orders_the_test_by_id_alone(panelled):
    """The name and the kind come from the catalogue row, not from the page."""
    from app.models import Investigation, VisitInvestigation

    with panelled["app"].app_context():
        row = Investigation(name_ar="إيكو القلب", name_en="Echocardiogram",
                            kind="imaging", is_active=True)
        panelled["db"].session.add(row)
        panelled["db"].session.commit()
        test_id = row.id

    client = panelled["sign_in"]("boss")
    client.post(f"/visits/{panelled['ids']['visit']}/investigations",
                data={"investigation_id": test_id}, follow_redirects=True)

    with panelled["app"].app_context():
        ordered = VisitInvestigation.query.filter_by(
            visit_id=panelled["ids"]["visit"]).all()
        assert len(ordered) == 1
        assert ordered[0].name == "إيكو القلب"
        assert ordered[0].kind == "imaging"
        assert ordered[0].investigation_id == test_id

    # And the chip on the screen carries an id, read off the page, that the
    # same route accepts — the two halves checked as one chain.
    from_page = _chip_value(_record(panelled), "panelTestForm")
    client.post(f"/visits/{panelled['ids']['visit']}/investigations",
                data={"investigation_id": from_page}, follow_redirects=True)
    with panelled["app"].app_context():
        assert VisitInvestigation.query.filter_by(
            visit_id=panelled["ids"]["visit"]).count() == 2


def test_a_test_chip_with_an_id_that_is_not_in_the_catalogue_orders_nothing(
        panelled):
    from app.models import VisitInvestigation

    client = panelled["sign_in"]("boss")
    client.post(f"/visits/{panelled['ids']['visit']}/investigations",
                data={"investigation_id": 999999}, follow_redirects=True)

    with panelled["app"].app_context():
        assert VisitInvestigation.query.filter_by(
            visit_id=panelled["ids"]["visit"]).count() == 0


def test_typing_a_test_by_hand_still_works(panelled):
    """The investigations tab posts a typed name with no id, and that path
    must not have been narrowed by making the id sufficient."""
    from app.models import VisitInvestigation

    client = panelled["sign_in"]("boss")
    client.post(f"/visits/{panelled['ids']['visit']}/investigations",
                data={"name": "تحليل نادر", "kind": "lab"},
                follow_redirects=True)

    with panelled["app"].app_context():
        rows = VisitInvestigation.query.filter_by(
            visit_id=panelled["ids"]["visit"]).all()
        assert [r.name for r in rows] == ["تحليل نادر"]


# ------------------------------------------------------- and it does save --
def test_saving_the_consultation_saves_it(panelled):
    """The reported symptom, end to end: press Save, and it is on file."""
    from app.models import Visit

    client = panelled["sign_in"]("boss")
    client.post(f"/visits/{panelled['ids']['visit']}/record",
                data={"chief_complaint": "حرارة، كحة",
                      "clinical_exam": "الطفل في حالة عامة جيدة",
                      "plan": "خافض حرارة عند اللزوم",
                      "temperature_c": "37.0", "pulse_bpm": "100"},
                follow_redirects=True)

    with panelled["app"].app_context():
        visit = Visit.query.get(panelled["ids"]["visit"])
        assert visit.chief_complaint == "حرارة، كحة"
        assert visit.plan == "خافض حرارة عند اللزوم"
        assert visit.vitals is not None and visit.vitals.temperature_c == 37.0


def test_the_other_screens_do_not_nest_forms_either(clinic):
    """The same walk over the screens that carry the most forms. This class of
    bug is invisible until somebody's data makes the inner form render, so it
    is worth asking of every busy screen rather than only the one that broke.
    """
    from app.models import Setting

    with clinic["app"].app_context():
        for module in ("dentistry", "panels", "observations"):
            Setting.set(f"mod_enabled:{module}", "1")
        clinic["db"].session.commit()

    client = clinic["sign_in"]("boss")
    child, visit = clinic["ids"]["child"], clinic["ids"]["visit"]
    for path in (f"/patients/{child}", f"/visits/{visit}/record",
                 "/appointments/", "/settings/", "/finance/invoices",
                 f"/observations/patient/{child}", "/beds/setup"):
        page = client.get(path)
        if page.status_code != 200:
            continue
        nested = forms_inside_forms(page.get_data(as_text=True))
        assert not nested, f"{path} draws a form inside a form at {nested}"
