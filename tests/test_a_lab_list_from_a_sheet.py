"""The laboratory's list, and its ranges, brought in from a sheet.

Asked as *«قايمة التحاليل كل تحليل ليه حجات هو بيقيسها … وهل الاستيراد هيبقى
ذكي انه يفهم؟»*, with the rule *«مش عايز اعمل اي حاجه فى مديول العيادة»*.
What is held here:

* the sheet is read by what its columns are called, in either language, from
  every sheet of the workbook, and put together by test;
* ages are read as a laboratory writes them; a one-sided figure is a cutoff,
  a row with no figure a note; what looks wrong is said, never mended;
* a sheet test meets ours by its English name first, a clinic's second copy
  of a test is the same test, and nothing is preselected on a hunch;
* importing links without renaming, and a clinic's catalogue is exactly as
  it was; imported ranges are drafts until approved;
* the export reads back in without making a single new test;
* only the lab module's admin reaches any of it.
"""
import io
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

CATALOGUE = [
    ("Arabic Test Name", "English Test Name", "Search Aliases", "Category"),
    ("صورة دم كاملة", "Complete Blood Count (CBC)", "CBC; FBC", "Hematology"),
    ("الهيموجلوبين", "Hemoglobin", "Hb; HGB", "Hematology"),
    ("الصفائح الدموية", "Platelet Count", "PLT", "Hematology"),
    ("سكر صائم", "Fasting Blood Glucose", "FBS", "Chemistry"),
    ("Chloride", "Chloride", "Cl", "Chemistry"),
    ("زمن البروثرومبين", "Prothrombin Time", "PT", "Coagulation"),
    ("PT/INR", "Prothrombin Time / INR", "PT; INR", "Coagulation"),
    ("وظائف كلى", "Renal Function Panel", "RFT", "Chemistry"),
    ("17-OHP", "17-Hydroxyprogesterone", "17-OHP", "Endocrine"),
    ("17-OHP", "17-Hydroxyprogesterone Newborn Screen", "", "Neonatal"),
    ("بروتين سي", "C-Reactive Protein", "CRP", "Inflammation"),
    ("بروتين سي لحديثي الولادة", "Neonatal C-Reactive Protein", "CRP", "Neonatal"),
]
# Deliberately in another order and half in Arabic, as a laboratory sends it.
RANGES = [
    ("المكوّن", "Test Name", "الوحدة", "من سن", "Sex", "الحد الأدنى",
     "Reference High", "Reference Type", "Source", "Source URL",
     "الحد الحرج الأدنى", "Expected TAT (Routine)", "Tube Color"),
    ("Hemoglobin", "CBC", "g/dL", "0-14 days", "All", 13.4, 19.9,
     "Reference interval", "Mayo", "https://example.org/cbc", "", "30-60", "Lavender"),
    ("Hemoglobin", "CBC", "g/dL", "15 days-4 weeks", "All", 10.7, 17.1,
     "Reference interval", "Mayo", "https://example.org/cbc", "", "", ""),
    ("Platelets", "CBC", "x10^9/L", "1 year+", "All", 150, 450,
     "Reference interval", "", "", 20, "", ""),
    ("Glucose", "Fasting Blood Glucose", "mg/dL", "18 years+", "All", None, 100,
     "Desirable cutoff", "Guide", "javascript:alert(1)", "", "2 hours", ""),
    ("aPTT", "Coagulation", "s", "Full-term newborn", "All", None, None,
     "Age caveat", "", "", "", "", ""),
    ("Bicarbonate", "Renal Function Panel", "mmol/L", "12-24 months", "Male", 17, 25,
     "Reference interval", "", "", "", "", ""),
    ("Bicarbonate", "Renal Function Panel", "mmol/L", "3 years", "Male", 18, 26,
     "Reference interval", "", "", "", "", ""),
    ("Bicarbonate", "Renal Function Panel", "mmol/L", "4-5 years", "Female", 30, 19,
     "Reference interval", "", "", "", "", ""),
]
NOTES = [("Priority Test", "English Test Name", "Source URL"),
         ("Preterm bilirubin", "Hyperbilirubinemia in Preterm Infants", "https://x")]
README = [("Purpose", "A template"), ("Rule", "Do not invent")]


def _book(*sheets):
    import openpyxl

    book = openpyxl.Workbook()
    book.remove(book.active)
    for title, rows in sheets:
        sheet = book.create_sheet(title)
        for row in rows:
            sheet.append(list(row))
    out = io.BytesIO()
    book.save(out)
    out.seek(0)
    return out


def _sheet():
    # The ranges sheet first, the way the first real sheet arrived: «CBC»
    # there is only known as the list's «Complete Blood Count (CBC)» later.
    return _book(("README", README), ("Ranges", RANGES),
                 ("Catalog", CATALOGUE), ("Priority", NOTES))


@pytest.fixture()
def lab(clinic):
    from app.models import Setting
    from app.utils.investigations import seed_investigations

    with clinic["app"].app_context():
        Setting.set("mod_enabled:labs", "1")
        seed_investigations()
        clinic["db"].session.commit()
    return clinic


# ------------------------------------------------------------- reading ---
@pytest.mark.parametrize("text,days", [
    ("0-14 days", (0, 15)), ("15 days-4 weeks", (15, 35)),
    ("6-23 months", (183, 730)), ("18 years+", (6574, None)),
    ("<1 year", (0, 365)), ("1-<10 years", (365, 3652)),
    ("17 years", (6209, 6574)), (">90 years", (33238, None)),
    ("Adult", (6574, None)), ("All ages", (0, None)),
    ("من 2 إلى 5 سنوات", None), ("Full-term newborn", None), ("", None),
])
def test_ages_are_read_as_a_laboratory_writes_them(text, days):
    from app.utils.lab_import import age_band

    assert age_band(text) == days


@pytest.mark.parametrize("text,span", [
    ("30-60", (30, 60)), ("45", (45, 45)), ("2 hours", (120, 120)),
    ("1-2 days", (1440, 2880)), ("٢٤ ساعة", (1440, 1440)), ("24 ساعة", (1440, 1440)),
    ("", None), ("soon", None),
])
def test_times_are_minutes_or_nothing(text, span):
    from app.utils.lab_import import minutes

    assert minutes(text) == span


def test_the_sheet_is_read_by_what_its_columns_are_called(lab):
    from app.utils import lab_import

    with lab["app"].app_context():
        plan = lab_import.read(_sheet())
    names = {t["name_en"] or t["label"] for t in plan["tests"]}
    # The list's tests, plus the ranges' own panel; not the notes page.
    assert "Coagulation" in names and "Hyperbilirubinemia in Preterm Infants" not in names
    assert {"17-Hydroxyprogesterone", "17-Hydroxyprogesterone Newborn Screen"} <= names
    assert plan["sheets"] == ["Ranges", "Catalog"]
    cbc = next(t for t in plan["tests"] if t["name_en"] == "Complete Blood Count (CBC)")
    parts = [plan["analytes"][a]["name"] for a in cbc["analytes"]]
    # «Platelets» of the CBC is the list's «Platelet Count»: one analyte.
    assert parts == ["Hemoglobin", "Platelet Count"]
    assert cbc["tat"] == (30, 60) and cbc["tube"] == "Lavender"
    hb = plan["analytes"][cbc["analytes"][0]]
    assert [(r["from"], r["to"], r["low"], r["high"], r["source"]) for r in hb["ranges"]] == [
        (0, 15, 13.4, 19.9, "Mayo"), (15, 35, 10.7, 17.1, "Mayo")]
    plt = plan["analytes"][cbc["analytes"][1]]
    assert plt["ranges"][0]["critical_low"] == 20 and plt["unit"] == "x10^9/L"
    glucose = [a for a in plan["analytes"].values() if a["name"] == "Glucose"][0]
    assert glucose["ranges"][0]["kind"] == "cutoff"
    aptt = [a for a in plan["analytes"].values() if a["name"] == "aPTT"][0]
    assert aptt["ranges"][0]["kind"] == "note"
    # PT and INR share an alias, so neither is claimed by it.
    pt = [t for t in plan["tests"] if t["name_en"] == "Prothrombin Time"][0]
    ptinr = [t for t in plan["tests"] if t["name_en"] == "Prothrombin Time / INR"][0]
    assert pt["analytes"] != ptinr["analytes"]
    what = sorted((p["what"], p["detail"]) for p in plan["problems"])
    assert [w for w, _ in what] == ["age", "age_gap", "low_above_high"]
    assert "Full-term newborn" in what[0][1] and "12-24 months → 3 years" in what[1][1]


def test_a_placeholder_part_is_said_not_made(lab):
    from app.utils import lab_import

    rows = [("Test Name", "Component", "Unit"),
            ("Renal Function Panel", "Panel / Profile", ""),
            ("Renal Function Panel", "Renal Function Panel", "")]
    with lab["app"].app_context():
        plan = lab_import.read(_book(("Catalog", CATALOGUE), ("Parts", rows)))
    renal = [t for t in plan["tests"] if t["name_en"] == "Renal Function Panel"][0]
    assert renal["parts_missing"] is True and len(renal["analytes"]) == 1
    assert "panel profile" not in plan["analytes"]


# ------------------------------------------------------------ matching ---
def test_our_tests_meet_the_sheet_by_name_and_nothing_on_a_hunch(lab):
    from app.models import Investigation
    from app.utils import lab_import

    with lab["app"].app_context():
        plan = lab_import.read(_sheet())
        found = lab_import.match(plan)
        by = {t["key"]: t["name_en"] for t in plan["tests"]}
        ours = {i.id: i for i in Investigation.query.all()}
        auto = {by[k]: ours[cid].name_ar for k, cid in found["auto"].items()}
        asked = {ours[q["id"]].name_ar: q for q in found["questions"]}
    assert auto["Fasting Blood Glucose"] == "سكر صائم"
    assert auto["Hemoglobin"] == "نسبة الهيموجلوبين"
    # A clinic with CBC twice has one CBC: both copies get it.
    for copy in ("صورة دم كاملة", "صورة دم كاملة (CBC)"):
        assert by[asked[copy]["pick"]] == "Complete Blood Count (CBC)"
    # «CRP» is the adult test the other copy took, not the neonatal one.
    assert by[asked["بروتين سي التفاعلي"]["pick"]] == "C-Reactive Protein"
    # Offered, never preselected: sweat chloride is not serum chloride.
    sweat = asked["اختبار العرق"]
    assert sweat["pick"] is None and "Chloride" in [c[1] for c in sweat["candidates"]]


# ---------------------------------------------------- the whole journey ---
def _upload(client, data):
    return client.post("/labs/tests/import", data={"sheet": (data, "lab.xlsx")},
                       content_type="multipart/form-data")


def _answers(page):
    import re

    form = {"show_new": "1"}
    for m in re.finditer(r'<select class="select" name="(q_\d+)"[^>]*>(.*?)</select>',
                         page, re.S):
        chosen = re.search(r'<option value="([^"]*)" selected', m.group(2))
        form[m.group(1)] = chosen.group(1) if chosen else ""
    return form


def test_importing_links_without_renaming_and_ranges_wait_for_approval(lab):
    from app.models import Investigation, LabRange

    with lab["app"].app_context():
        before = {i.id: (i.name_ar, i.name_en, i.code, i.unit, i.kind, i.in_house)
                  for i in Investigation.query.all()}
    boss = lab["sign_in"]("boss")
    reply = _upload(boss, _sheet())
    assert reply.status_code == 302
    preview = boss.get(reply.headers["Location"]).get_data(as_text=True)
    assert "data-lab-preview" in preview and "data-lab-problems" in preview
    assert "data-owed-critical" in preview and "data-owed-parts" not in preview
    with lab["app"].app_context():
        # Nothing is written by reading.
        assert Investigation.query.count() == len(before)
    done = boss.post(reply.headers["Location"], data=_answers(preview))
    assert done.status_code == 302
    with lab["app"].app_context():
        after = {i.id: (i.name_ar, i.name_en, i.code, i.unit, i.kind, i.in_house)
                 for i in Investigation.query.filter(Investigation.id.in_(before)).all()}
        assert after == before
        cbc = Investigation.query.filter_by(code="cbc").one()
        assert [link.analyte.name for link in cbc.analyte_links] == [
            "Hemoglobin", "Platelet Count"]
        assert "FBC" in (cbc.aliases or "") and cbc.tat_min == 30
        assert Investigation.query.filter_by(name_en="Coagulation").count() == 1
        assert LabRange.query.count() and not LabRange.query.filter(
            LabRange.approved_at.isnot(None)).count()
        cbc_id = cbc.id
    page = boss.get(f"/labs/tests/{cbc_id}/ranges").get_data(as_text=True)
    assert page.count('data-state="draft"') == 3 and "data-approve" in page
    # A source link is only ever a web address.
    fbs = boss.get("/labs/tests?q=Fasting").get_data(as_text=True)
    assert "data-ref-line" in fbs
    with lab["app"].app_context():
        fbs_id = Investigation.query.filter_by(code="fbs").one().id
    glucose = boss.get(f"/labs/tests/{fbs_id}/ranges").get_data(as_text=True)
    assert "javascript:" not in glucose.split("<tbody>")[1]
    boss.post(f"/labs/tests/{cbc_id}/approve")
    page = boss.get(f"/labs/tests/{cbc_id}/ranges").get_data(as_text=True)
    assert page.count('data-state="approved"') == 3 and "data-approve" not in page


def test_a_new_sheet_waits_beside_the_approved_one(lab):
    from app.models import Investigation, LabRange
    from app.utils import lab_import

    with lab["app"].app_context():
        plan = lab_import.read(_sheet())
        lab_import.apply(plan, lab_import.links_from(plan, {}))
        cbc = Investigation.query.filter_by(name_en="Complete Blood Count (CBC)").one()
        lab_import.approve_test(cbc, None)
        lab["db"].session.commit()
        approved = {r.id for r in LabRange.query.filter(LabRange.approved_at.isnot(None))}
        again = lab_import.read(_sheet())
        lab_import.apply(again, lab_import.links_from(again, {}))
        lab["db"].session.commit()
        # The approved rows stand; the new ones wait as drafts beside them.
        assert approved <= {r.id for r in LabRange.query.all()}
        drafts = LabRange.query.filter(LabRange.approved_at.is_(None),
                                       LabRange.analyte_id.in_(
                                           [l.analyte_id for l in cbc.analyte_links])).count()
        assert drafts == 3
        # Approving the new sheet replaces the old one, not doubles it.
        lab_import.approve_test(cbc, None)
        lab["db"].session.commit()
        ids = [l.analyte_id for l in cbc.analyte_links]
        assert LabRange.query.filter(LabRange.analyte_id.in_(ids)).count() == 3


def test_the_export_reads_back_in_without_a_new_test(lab):
    boss = lab["sign_in"]("boss")
    reply = _upload(boss, _sheet())
    preview = boss.get(reply.headers["Location"]).get_data(as_text=True)
    boss.post(reply.headers["Location"], data=_answers(preview))
    sheet = boss.get("/labs/tests/export")
    assert sheet.status_code == 200 and sheet.mimetype.endswith("sheet")
    again = _upload(boss, io.BytesIO(sheet.data))
    page = boss.get(again.headers["Location"]).get_data(as_text=True)
    import re
    assert re.search(r"data-n-new>(\d+)<", page).group(1) == "0"


def test_the_clinics_catalogue_is_untouched_by_updates_and_imports(lab):
    """The starter list every clinic is given runs on install and update. It
    must neither grow from a laboratory's sheet nor fight one."""
    from app.models import Investigation
    from app.utils import lab_import
    from app.utils.investigations import COMMON_INVESTIGATIONS, seed_investigations

    with lab["app"].app_context():
        plan = lab_import.read(_sheet())
        lab_import.apply(plan, lab_import.links_from(plan, {}))
        lab["db"].session.commit()
        count = Investigation.query.count()
        seed_investigations()
        assert Investigation.query.count() == count
    # And nothing of the sheet is in the list a clinic is given.
    seeded = {row[2] for row in COMMON_INVESTIGATIONS}
    assert "Coagulation" not in seeded and "Neonatal C-Reactive Protein" not in seeded


def test_only_the_lab_modules_admin_reaches_it(lab, clinic):
    from app.models import Setting

    doc = lab["sign_in"]("doc")
    assert doc.get("/labs/tests/import").status_code in (302, 403)
    assert doc.get("/labs/tests/export").status_code in (302, 403)
    with lab["app"].app_context():
        Setting.set("mod_enabled:labs", "0")
        lab["db"].session.commit()
    boss = lab["sign_in"]("boss")
    assert boss.get("/labs/tests/import").status_code in (302, 404)
    assert boss.post("/labs/tests/import", data={}).status_code in (302, 404)


def test_a_sheet_that_is_not_one_is_refused_in_words(lab):
    boss = lab["sign_in"]("boss")
    bad = boss.post("/labs/tests/import",
                    data={"sheet": (io.BytesIO(b"not a workbook"), "x.xlsx")},
                    content_type="multipart/form-data", follow_redirects=True)
    assert bad.status_code == 200 and "data-lab-upload" in bad.get_data(as_text=True)
    empty = _upload(boss, _book(("README", README)))
    assert empty.headers["Location"].endswith("/labs/tests/import")
    assert boss.get("/labs/tests/import/" + "0" * 32).status_code == 302


def test_two_rows_stay_two_and_a_repeated_range_keeps_its_source(lab):
    """A list that names «Fecal Elastase» on its own row and as an alias of
    «Pancreatic Elastase» has listed two tests; and a range written on two
    sheets, once with its source and once without, keeps the source."""
    from app.utils import lab_import

    catalogue = [("Arabic Test Name", "English Test Name", "Search Aliases", "Category"),
                 ("إيلاستاز", "Pancreatic Elastase", "Fecal Elastase", "GI"),
                 ("إيلاستاز البراز", "Fecal Elastase", "", "GI")]
    bare = [("Test Name", "Component", "Unit", "Age From", "Sex", "Reference Low",
             "Reference High"),
            ("Pancreatic Elastase", "Pancreatic Elastase", "mcg/g", "1 year+", "All", 200, 500)]
    sourced = [("Test Name", "Component", "Unit", "Age From", "Sex", "Reference Low",
                "Reference High", "Source", "Source URL"),
               ("Pancreatic Elastase", "Pancreatic Elastase", "mcg/g", "1 year+", "All",
                200, 500, "Lab book", "https://example.org/e")]
    with lab["app"].app_context():
        plan = lab_import.read(_book(("Bare", bare), ("Sourced", sourced),
                                     ("Catalog", catalogue)))
    names = sorted(t["name_en"] for t in plan["tests"])
    assert names == ["Fecal Elastase", "Pancreatic Elastase"]
    rows = [r for a in plan["analytes"].values() for r in a["ranges"]]
    assert len(rows) == 1 and rows[0]["source"] == "Lab book"
    assert rows[0]["source_url"] == "https://example.org/e"
