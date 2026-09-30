"""The tests a doctor orders from are the clinic's list, like its drugs.

Asked as *«هو طبيعي ان التحاليل فى العياد تبقى فى الكود؟ ما تخليها زي الادوية
فى العيادة يضيف اسماء التحاليل لو ملقهاش»* and then *«متخليهاش فى الكود
بالنسبة للعيادة»*. What is held here:

* the starter list is a data file, not names written in the program;
* it is given once: a test the clinic deleted is not brought back by the
  next update, and one it hid stays hidden;
* an entry new to the starter file still reaches a clinic that updates;
* the clinic's admin adds, renames and hides from its own screen; a test
  ever ordered is hidden, never deleted; nobody else reaches the screen.
"""
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def test_the_starter_list_is_data_not_code():
    from app.utils import investigations

    with open(investigations.STARTER_FILE, encoding="utf-8") as fh:
        rows = json.load(fh)["investigations"]
    assert len(rows) == len(investigations.COMMON_INVESTIGATIONS) > 0
    with open(os.path.join(ROOT, "app", "utils", "investigations.py"),
              encoding="utf-8") as fh:
        source = fh.read()
    for row in rows:
        assert f'"{row["name_ar"]}"' not in source, (
            f"{row['name_ar']} is still written in the program")


def test_the_codes_the_panels_use_are_all_in_the_file():
    """A specialty panel finds its tests by code; the move must not lose one."""
    from app.utils import investigations, panels

    seeded = {row[0] for row in investigations.COMMON_INVESTIGATIONS if row[0]}
    named = {code for key in panels.all_panels() for code in panels.charts_for(key)}
    assert named, "no panel names a test — the check checks nothing"
    assert named <= seeded, f"panels name codes the file lacks: {named - seeded}"


def test_a_test_the_clinic_deleted_is_not_brought_back(clinic):
    from app.models import Investigation
    from app.utils.investigations import seed_investigations

    with clinic["app"].app_context():
        db = clinic["db"]
        seed_investigations()
        first = Investigation.query.count()
        db.session.delete(Investigation.query.filter_by(code="hba1c").one())
        db.session.delete(Investigation.query.filter_by(name_ar="سرعة الترسيب").one())
        hidden = Investigation.query.filter_by(code="ferritin").one()
        hidden.is_active = False
        db.session.commit()

        assert seed_investigations() == 0
        assert Investigation.query.count() == first - 2
        assert Investigation.query.filter_by(code="hba1c").first() is None
        assert Investigation.query.filter_by(code="ferritin").one().is_active is False


def test_a_new_entry_in_the_file_still_reaches_a_clinic_that_updates(clinic, monkeypatch):
    from app.models import Investigation
    from app.utils import investigations

    with clinic["app"].app_context():
        investigations.seed_investigations()
        monkeypatch.setattr(investigations, "COMMON_INVESTIGATIONS",
                            investigations.COMMON_INVESTIGATIONS + [
                                ("new_one", "تحليل جديد", "New test", "lab", "أخرى", None)])
        assert investigations.seed_investigations() == 1
        assert Investigation.query.filter_by(code="new_one").count() == 1


# ============================================================== the screen ==
@pytest.fixture()
def listed(clinic):
    from app.models import Investigation, Visit, VisitInvestigation

    with clinic["app"].app_context():
        db = clinic["db"]
        used = Investigation(name_ar="صورة دم", kind="lab", is_active=True)
        spare = Investigation(name_ar="تحليل مش مستعمل", kind="lab", is_active=True)
        db.session.add_all([used, spare])
        db.session.flush()
        visit = db.session.get(Visit, clinic["ids"]["visit"])
        db.session.add(VisitInvestigation(visit_id=visit.id,
                                          patient_id=visit.patient_id,
                                          investigation_id=used.id, kind="lab",
                                          name="صورة دم"))
        db.session.commit()
        clinic.update(used=used.id, spare=spare.id)
    return clinic


def test_only_the_admin_reaches_the_list(listed):
    boss = listed["sign_in"]("boss")
    page = boss.get("/prescriptions/investigations").get_data(as_text=True)
    assert f'data-inv="{listed["used"]}"' in page
    assert "data-to-investigations" in boss.get("/prescriptions/drugs").get_data(as_text=True)
    assert listed["sign_in"]("doc").get("/prescriptions/investigations").status_code in (302, 403)


def test_add_rename_and_hide(listed):
    from app.models import Investigation

    boss = listed["sign_in"]("boss")
    boss.post("/prescriptions/investigations/new", data={
        "name_ar": "إيكو قلب", "name_en": "Echo", "kind": "diagnostic"})
    boss.post("/prescriptions/investigations/new", data={"name_ar": " "})
    with listed["app"].app_context():
        echo = Investigation.query.filter_by(name_ar="إيكو قلب").one()
        assert (echo.kind, echo.name_en, echo.is_active) == ("diagnostic", "Echo", True)
        assert Investigation.query.filter_by(name_ar="").count() == 0
    boss.post(f"/prescriptions/investigations/{listed['spare']}/edit", data={
        "name_ar": "تحليل بإسم جديد", "kind": "lab"})
    with listed["app"].app_context():
        row = listed["db"].session.get(Investigation, listed["spare"])
        assert row.name_ar == "تحليل بإسم جديد" and row.is_active is False


def test_a_test_ever_ordered_is_hidden_not_deleted(listed):
    from app.models import Investigation

    boss = listed["sign_in"]("boss")
    boss.post(f"/prescriptions/investigations/{listed['used']}/delete")
    boss.post(f"/prescriptions/investigations/{listed['spare']}/delete")
    with listed["app"].app_context():
        used = listed["db"].session.get(Investigation, listed["used"])
        assert used is not None and used.is_active is False
        assert listed["db"].session.get(Investigation, listed["spare"]) is None


def test_an_older_clinic_is_remembered_too(clinic):
    """A clinic seeded before this change has the rows and no record of
    having been given them. Found on the first update, they are remembered —
    so a test it deletes afterwards stays deleted."""
    from app.models import Investigation, Setting
    from app.utils.investigations import SEEN_KEY, seed_investigations

    with clinic["app"].app_context():
        db = clinic["db"]
        seed_investigations()
        Setting.set(SEEN_KEY, "[]")          # as an older install looks
        db.session.commit()
        seed_investigations()                # the update
        db.session.delete(Investigation.query.filter_by(code="igf1").one())
        db.session.commit()
        seed_investigations()                # the next one
        assert Investigation.query.filter_by(code="igf1").first() is None
