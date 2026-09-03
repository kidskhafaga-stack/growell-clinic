"""Every specialty said which tests it wants as a curve. Eight of them existed.

The survey asks each specialty *"تحاليل تريد رؤيتها كمنحنى"* and between them
they name sixty-three things. The investigations catalogue held **eight** of
them. Everything else — HbA1c, ferritin, albumin, creatinine and eGFR, IgE,
drug levels, NT-proBNP, INR, calprotectin, coeliac antibodies, microalbumin,
T2*, platelets — had to be typed by hand.

**That is not an inconvenience, it is a broken curve.** `lab_series._key`
groups results by catalogue id where there is one and **by name where there is
not**, so "HbA1c" typed on Sunday and "hba1c" typed on Thursday are two curves
for one test, on the same child, in the same clinic. The chart question could
not be answered while the tests were not in the catalogue, whatever the drawing
code did.

**What was already there, and is not rebuilt here.** `series.curves_for` merges
three sources into one curve — device studies, specialty-panel measurements and
lab results — refuses to draw a line through a single point, and refuses to
convert units. None of that is touched. This adds the tests, a stable key to
name them by, and the list each panel follows.

**And what is honestly not a curve.** A chest X-ray, a panoramic film,
before-and-after photographs, retinopathy screening dates: the questionnaire
lists them under charts because that is where a doctor thinks of them, and
nothing plots a photograph. They are attachments and appointments, and the
chart lists leave them out rather than promising a line that will never appear.
"""
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))


def _catalogue():
    with open(os.path.join(HERE, "..", "app", "data", "specialty_panels.json"),
              encoding="utf-8") as fh:
        return json.load(fh)["panels"]


def _seed():
    from app.utils.investigations import COMMON_INVESTIGATIONS

    return COMMON_INVESTIGATIONS


# ------------------------------------------------------------ the catalogue ---

def test_the_tests_the_specialties_asked_for_are_in_the_catalogue():
    """The bug, named test by test. Each of these was in a survey answer and
    not in the program."""
    codes = {code for code, *_ in _seed() if code}
    for wanted in ("hba1c", "ferritin", "albumin", "creatinine", "egfr", "ige",
                   "drug_level", "ntprobnp", "inr", "calprotectin",
                   "celiac_abs", "microalbumin", "t2_star", "platelets",
                   "bilirubin", "igf1", "sweat_test", "eosinophils"):
        assert wanted in codes, f"{wanted} still has to be typed by hand"


def test_every_code_is_unique():
    """A code is a key. Two rows answering to one key is worse than none,
    because the lookup would silently pick whichever came first."""
    codes = [code for code, *_ in _seed() if code]
    assert len(codes) == len(set(codes))


def test_a_test_with_a_unit_carries_it():
    """The unit is a fact about the measurement and belongs in the catalogue —
    which is exactly why the reference range does not, and this checks that
    distinction has not quietly eroded."""
    by_code = {code: row for code, *row in _seed() if code}
    assert by_code["hba1c"][4] == "%"
    assert by_code["hb"][4] == "g/dL"
    for code, row in by_code.items():
        assert "low" not in str(row).lower() and "high" not in str(row).lower(), \
            f"{code} looks like it carries a reference range"


# ---------------------------------------------------------- the panels' lists ---

def test_every_panel_names_its_tests_by_code_and_they_all_exist():
    """A list that names a test the catalogue does not have is a list that
    renders one item short and says nothing about why."""
    known = {code for code, *_ in _seed() if code}
    for key, panel in _catalogue().items():
        for code in panel.get("charts") or []:
            assert code in known, f"{key} follows '{code}', which is not a test"


def test_the_lists_are_codes_and_never_names():
    """The whole reason `Investigation.code` exists. A clinic renames a test
    and a list written in Arabic quietly stops matching it."""
    for key, panel in _catalogue().items():
        for code in panel.get("charts") or []:
            assert code.isascii() and code.islower(), \
                f"{key} follows '{code}', which looks like a name and not a key"


def test_the_specialties_that_follow_labs_do():
    """Nine of the eleven answered the chart question with lab tests."""
    charts = {k: (p.get("charts") or []) for k, p in _catalogue().items()}
    for key in ("endocrinology", "cardiology", "pulmonology", "neurology",
                "nephrology", "gastroenterology", "haematology", "neonatology",
                "developmental"):
        assert charts[key], f"{key} follows no tests at all"


def test_and_the_two_that_do_not_say_so_with_an_empty_list(clinic):
    """Ophthalmology and dentistry answered entirely with their own
    measurements and with images. Empty is a real answer, not a gap: their
    readings already draw, because panel measurements have been plotted since
    the panels existed."""
    from app.utils import panels

    with clinic["app"].app_context():
        assert panels.charts_for("ophthalmology") == []
        assert panels.charts_for("dentistry") == []
        # ...and they do have numeric measurements to draw.
        for key in ("ophthalmology", "dentistry"):
            numbers = [f for f in panels.panel(key)["fields"]
                       if f["type"] == "number"]
            assert numbers, f"{key} has neither a chart list nor a number"


def test_every_charted_test_is_a_lab_test_and_not_an_image():
    """Imaging and photographs are in the survey's chart answers and must not
    be in these lists. A list that names a panoramic film is a screen waiting
    for a line that will never be drawn.

    Checked by looking up each code's **kind**, not by comparing against a set
    of imaging codes: the first version did the latter and was vacuous, because
    no imaging entry carries a code at all, so the set it compared against was
    empty and the test passed on anything. It was caught by a mutation landing
    on a different test than the one aimed at.
    """
    by_code = {code: kind for code, _ar, _en, kind, *_ in _seed() if code}
    checked = 0
    for key, panel in _catalogue().items():
        for code in panel.get("charts") or []:
            assert by_code.get(code) == "lab", \
                f"{key} lists {code}, which is {by_code.get(code)} and not a curve"
            checked += 1
    assert checked > 20, \
        f"only {checked} charted tests were checked; this is not testing much"


# ----------------------------------------------------------- and it resolves ---

def test_a_panel_resolves_its_tests_in_the_order_it_named_them(clinic):
    from app.utils import investigations, panels

    with clinic["app"].app_context():
        investigations.seed_investigations()
        rows = panels.chart_tests("endocrinology")
        assert [r.code for r in rows] == panels.charts_for("endocrinology")


def test_a_code_that_answers_to_nothing_costs_that_test_and_not_the_screen(clinic):
    """The catalogue is a clinic's to edit. A panel losing one of its tests
    must not take the consultation screen with it."""
    from app.models import Investigation
    from app.utils import investigations, panels

    with clinic["app"].app_context():
        investigations.seed_investigations()
        row = Investigation.query.filter_by(code="hba1c").first()
        clinic["db"].session.delete(row)
        clinic["db"].session.commit()

        rows = panels.chart_tests("endocrinology")
        assert "hba1c" not in [r.code for r in rows]
        assert rows, "losing one test emptied the whole list"


# ------------------------------------------------------------- the upgrade ---

def test_seeding_twice_does_not_double_anything(clinic):
    from app.models import Investigation
    from app.utils import investigations

    with clinic["app"].app_context():
        investigations.seed_investigations()
        first = Investigation.query.count()
        investigations.seed_investigations()
        assert Investigation.query.count() == first


def test_a_clinic_that_already_had_the_test_keeps_its_row(clinic):
    """The upgrade case, and the one that would have hurt. A clinic has been
    ordering ferritin for months under the codeless row this catalogue seeded
    last year. Matching on code alone would insert a second ferritin beside it,
    and every result taken under the old row would fall out of the new row's
    curve."""
    from app.models import Investigation
    from app.utils import investigations

    with clinic["app"].app_context():
        old = Investigation(name_ar="مخزون الحديد (فيريتين)", name_en="Ferritin",
                            kind="lab", category="أمراض الدم", is_active=True)
        clinic["db"].session.add(old)
        clinic["db"].session.commit()
        old_id = old.id

        investigations.seed_investigations()

        rows = Investigation.query.filter_by(name_ar="مخزون الحديد (فيريتين)").all()
        assert len(rows) == 1, "the upgrade created a second ferritin"
        assert rows[0].id == old_id, "the clinic's own row was replaced"
        assert rows[0].code == "ferritin", \
            "the existing row was not adopted, so panels cannot find it"


def test_a_clinic_that_renamed_or_re_united_a_test_keeps_its_choice(clinic):
    """The seed is a starting point, not an owner."""
    from app.models import Investigation
    from app.utils import investigations

    with clinic["app"].app_context():
        investigations.seed_investigations()
        row = Investigation.query.filter_by(code="hba1c").first()
        row.name_ar = "تراكمي"
        row.unit = "mmol/mol"
        clinic["db"].session.commit()

        investigations.seed_investigations()

        row = Investigation.query.filter_by(code="hba1c").first()
        assert row.name_ar == "تراكمي"
        assert row.unit == "mmol/mol"


# --------------------------------------------------- and on the visit screen ---

@pytest.fixture()
def desk(clinic):
    """A clinic that works specialties, a doctor on the endocrine panel, and
    the catalogue seeded."""
    from app.extensions import db
    from app.models import Setting, User, Visit
    from app.utils import investigations

    with clinic["app"].app_context():
        Setting.set("mod_enabled:panels", "1")
        investigations.seed_investigations()
        visit = db.session.get(Visit, clinic["ids"]["visit"])
        db.session.get(User, visit.doctor_id).specialty_panels = "endocrinology"
        db.session.commit()
    clinic["url"] = f"/visits/{clinic['ids']['visit']}/record"
    return clinic


def _page(kit):
    return kit["sign_in"]("boss").get(kit["url"]).get_data(as_text=True)


# Matched on the attribute, never on the class name. `.chart-tests` is also a
# CSS rule at the bottom of the same template, and a test looking for the class
# passes whether the markup rendered or not — a trap this suite has fallen into
# four times in one day, on `dx-ai__head`, `panelBox`, `sigPad` and this.
STRIP = 'data-chart-tests="'


def _old_result(kit, code, value, unit, when, high=None):
    """A result on an *earlier* visit, which is where old results live."""
    from app.models import Investigation, Visit, VisitInvestigation
    from app.utils.clock import local_today

    with kit["app"].app_context():
        test = Investigation.query.filter_by(code=code).first()
        earlier = Visit(patient_id=kit["ids"]["child"],
                        doctor_id=kit["ids"]["doctor"],
                        visit_date=local_today())
        kit["db"].session.add(earlier)
        kit["db"].session.flush()
        kit["db"].session.add(VisitInvestigation(
            visit_id=earlier.id, patient_id=kit["ids"]["child"],
            investigation_id=test.id, kind="lab", name=test.name_ar,
            status="resulted", result_value=value, result_unit=unit,
            result_high=high, resulted_at=when))
        kit["db"].session.commit()


def test_the_panel_offers_its_tests_on_the_visit_screen(desk):
    page = _page(desk)

    assert STRIP in page, "the panel does not show the tests it follows"
    assert "HbA1c" in page or "التراكمي" in page


def test_ordering_one_is_a_single_press(desk):
    """Typing the name is what splits a curve, so the order has to carry the
    catalogue id and the result land on the same test as every previous one.

    The form is read **off the rendered page** and posted back field for field,
    rather than the fields being typed here. The first version typed them, and
    so it passed with the id deleted from the template — it was testing the
    route, which was never in doubt, and calling it a test of the screen.
    """
    import re

    from app.models import Investigation, VisitInvestigation

    with desk["app"].app_context():
        test_id = Investigation.query.filter_by(code="hba1c").first().id

    page = _page(desk)
    forms = re.findall(
        r'<form[^>]*action="[^"]*/investigations"[^>]*>(.*?)</form>', page, re.S)
    mine = [f for f in forms if f'value="{test_id}"' in f]
    assert mine, "no one-press order for this test is on the screen"

    fields = dict(re.findall(r'<input[^>]*name="([^"]+)"[^>]*value="([^"]*)"',
                             mine[0]))
    desk["sign_in"]("boss").post(
        f"/visits/{desk['ids']['visit']}/investigations",
        data=fields, follow_redirects=True)

    with desk["app"].app_context():
        row = VisitInvestigation.query.filter_by(
            visit_id=desk["ids"]["visit"]).first()
        assert row is not None, "the one-press order wrote nothing"
        assert row.investigation_id == test_id, \
            "it was ordered as free text, so its result will not join the curve"


def test_the_last_result_is_shown_beside_the_test(desk):
    """"What was his last HbA1c" is asked more often than "show me the curve",
    and the answer exists from the very first result."""
    from datetime import datetime

    _old_result(desk, "hba1c", 8.4, "%", datetime(2026, 6, 1, 10, 0), high=7.0)

    page = _page(desk)

    assert "8.4" in page, "the last result is not beside the test"
    assert "2026-06-01" in page, "the reading is offered without its date"


def test_a_test_never_done_says_so_rather_than_showing_a_zero(desk):
    """Matched on the attribute again, for the reason written beside `STRIP`:
    `chart-test__none` is a CSS rule as well as a class, so looking for the
    class name passed with the label deleted from the markup."""
    page = _page(desk)

    assert 'data-never-done="hba1c"' in page, \
        "a test with no result shows nothing at all, or worse, a number"


def test_the_last_result_is_not_filled_into_todays_boxes(desk):
    """The same rule the echo hint follows: a result from June is not a reading
    taken today, and a screen that pre-fills one records a measurement nobody
    made.

    The old result is put on an *earlier* visit, which is where an old result
    actually is. The first version of this test put it on today's visit and
    then complained that today's result box contained it — which it should,
    because that is this visit's own result being edited."""
    from datetime import datetime

    _old_result(desk, "hba1c", 8.4, "%", datetime(2026, 6, 1, 10, 0))

    page = _page(desk)
    # Shown as a reading with its date, never as an input's value.
    assert "8.4" in page, "the last result is not shown at all"
    assert 'value="8.4"' not in page, \
        "an old result was pre-filled into a box on today's visit"


def test_a_clinic_without_the_module_is_offered_nothing(desk):
    """The rule the whole specialty layer follows: off means absent."""
    from app.models import Setting

    with desk["app"].app_context():
        Setting.set("mod_enabled:panels", "0")
        desk["db"].session.commit()

    page = _page(desk)

    assert STRIP not in page
