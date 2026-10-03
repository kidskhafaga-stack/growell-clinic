"""What a test measures, and its ranges, typed by hand — and a test stopped
with its reason.

Asked as *«فى تحاليل … مش مفتوح ان المعمل يدخلها او يغيراها بايده؟ ليه»*
and *«لازم يكون فى اضافة تحليل وتوقيف تحليل»*. What is held here:

* a component is added to a test, and one another test already measures
  under the same name is linked, not copied;
* a band typed by hand is a draft — it never judges a result until approved;
* the age is read the way the sheet writes it, and a band it cannot read is
  refused, never guessed;
* correcting an **approved** band leaves it judging, and approving the
  correction replaces that band **only** — not every other age, which is
  what a new sheet does;
* an approved band is never deleted from here;
* stopping a test needs a reason, and keeps it.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def lab(clinic):
    from datetime import datetime

    from app.models import Investigation, LabAnalyte, LabRange, LabTestAnalyte, Setting

    with clinic["app"].app_context():
        db = clinic["db"]
        Setting.set("mod_enabled:labs", "1")
        cbc = Investigation(name_ar="صورة دم كاملة", kind="lab", is_active=True)
        hb_test = Investigation(name_ar="هيموجلوبين", kind="lab", is_active=True)
        hb = LabAnalyte(name="Hemoglobin", unit="g/dL")
        db.session.add_all([cbc, hb_test, hb])
        db.session.flush()
        db.session.add(LabTestAnalyte(investigation_id=hb_test.id, analyte_id=hb.id))
        now = datetime.utcnow()
        infant = LabRange(analyte_id=hb.id, age_from_days=30, age_to_days=365,
                          age_label="1-11 months", low=9.5, high=13.5,
                          source="sheet", approved_at=now)
        child = LabRange(analyte_id=hb.id, age_from_days=365, age_to_days=None,
                         age_label="1 year+", low=11.0, high=14.5,
                         source="sheet", approved_at=now)
        db.session.add_all([infant, child])
        db.session.commit()
        clinic["ids"].update(cbc=cbc.id, hb_test=hb_test.id, hb=hb.id,
                             infant=infant.id, child_range=child.id)
    return clinic


def _ranges(lab):
    from app.models import LabRange

    with lab["app"].app_context():
        return {r.id: {"label": r.age_label, "low": r.low, "high": r.high,
                       "approved": r.approved, "manual": bool(r.manual),
                       "replaces": r.replaces_id}
                for r in LabRange.query.filter_by(analyte_id=lab["ids"]["hb"]).all()}


def test_a_component_is_added_and_an_existing_one_is_linked_not_copied(lab):
    from app.models import LabAnalyte

    boss = lab["sign_in"]("boss")
    boss.post(f"/labs/tests/{lab['ids']['cbc']}/analytes",
              data={"name": "hemoglobin", "unit": "g/dL"})
    boss.post(f"/labs/tests/{lab['ids']['cbc']}/analytes",
              data={"name": "Platelets", "name_ar": "الصفائح", "unit": "10^3/uL"})
    with lab["app"].app_context():
        assert LabAnalyte.query.filter(
            lab["db"].func.lower(LabAnalyte.name) == "hemoglobin").count() == 1
        from app.models import Investigation
        cbc = lab["db"].session.get(Investigation, lab["ids"]["cbc"])
        assert [link.analyte.name for link in cbc.analyte_links] == ["Hemoglobin", "Platelets"]
    page = boss.get(f"/labs/tests/{lab['ids']['cbc']}/ranges").get_data(as_text=True)
    assert "1-11 months" in page, "the linked component came without its ranges"


def test_a_band_typed_by_hand_is_a_draft_until_approved(lab):
    lab["sign_in"]("boss").post(
        f"/labs/tests/{lab['ids']['hb_test']}/analytes/{lab['ids']['hb']}/range",
        data={"age": "0-29 days", "sex": "all", "kind": "interval",
              "low": "14", "high": "22"})
    new = [r for r in _ranges(lab).values() if r["label"] == "0-29 days"]
    assert new == [{"label": "0-29 days", "low": 14.0, "high": 22.0,
                    "approved": False, "manual": True, "replaces": None}]

    from app.models import LabAnalyte
    from app.utils import lab_results

    with lab["app"].app_context():
        approved, draft = lab_results.references(
            lab["db"].session.get(LabAnalyte, lab["ids"]["hb"]), 10, "male")
        assert approved is None and draft is not None
        assert lab_results.judge(10.0, approved) is None, "a draft judged a result"


def test_approving_a_new_band_keeps_the_other_ages(lab):
    boss = lab["sign_in"]("boss")
    boss.post(f"/labs/tests/{lab['ids']['hb_test']}/analytes/{lab['ids']['hb']}/range",
              data={"age": "0-29 days", "low": "14", "high": "22"})
    boss.post(f"/labs/tests/{lab['ids']['hb_test']}/approve")
    rows = _ranges(lab)
    assert len(rows) == 3 and all(r["approved"] for r in rows.values())


def test_correcting_an_approved_band_replaces_only_that_one(lab):
    boss = lab["sign_in"]("boss")
    boss.post(f"/labs/tests/{lab['ids']['hb_test']}/ranges/{lab['ids']['infant']}",
              data={"age": "1-11 months", "low": "10", "high": "13.5"})
    rows = _ranges(lab)
    assert rows[lab["ids"]["infant"]]["approved"] and rows[lab["ids"]["infant"]]["low"] == 9.5
    drafts = [r for r in rows.values() if not r["approved"]]
    assert drafts and drafts[0]["replaces"] == lab["ids"]["infant"]

    # A second correction of the same band replaces the first draft.
    boss.post(f"/labs/tests/{lab['ids']['hb_test']}/ranges/{lab['ids']['infant']}",
              data={"age": "1-11 months", "low": "10.5", "high": "13.5"})
    drafts = [r for r in _ranges(lab).values() if not r["approved"]]
    assert len(drafts) == 1 and drafts[0]["low"] == 10.5

    boss.post(f"/labs/tests/{lab['ids']['hb_test']}/approve")
    rows = _ranges(lab)
    assert lab["ids"]["infant"] not in rows
    assert lab["ids"]["child_range"] in rows, "the other ages went with it"
    assert sorted((r["label"], r["low"]) for r in rows.values()) == [
        ("1 year+", 11.0), ("1-11 months", 10.5)]
    assert all(r["approved"] and r["replaces"] is None for r in rows.values())


def test_a_sheet_draft_still_replaces_every_approved_band(lab):
    from app.models import LabRange

    with lab["app"].app_context():
        lab["db"].session.add(LabRange(analyte_id=lab["ids"]["hb"], age_from_days=0,
                                       age_label="all", low=10, high=15, source="new sheet"))
        lab["db"].session.commit()
    lab["sign_in"]("boss").post(f"/labs/tests/{lab['ids']['hb_test']}/approve")
    assert [r["label"] for r in _ranges(lab).values()] == ["all"]


def test_an_age_it_cannot_read_and_a_backwards_range_are_refused(lab):
    boss = lab["sign_in"]("boss")
    before = _ranges(lab)
    page = boss.post(f"/labs/tests/{lab['ids']['hb_test']}/analytes/{lab['ids']['hb']}/range",
                     data={"age": "babies", "low": "1", "high": "2"},
                     follow_redirects=True).get_data(as_text=True)
    assert "مش قادر أقرا السن" in page
    boss.post(f"/labs/tests/{lab['ids']['hb_test']}/analytes/{lab['ids']['hb']}/range",
              data={"age": "all", "low": "20", "high": "10"})
    assert _ranges(lab) == before


def test_an_approved_band_is_never_deleted_from_here(lab):
    boss = lab["sign_in"]("boss")
    boss.post(f"/labs/tests/{lab['ids']['hb_test']}/ranges/{lab['ids']['infant']}/drop")
    assert lab["ids"]["infant"] in _ranges(lab)


def test_a_range_of_another_test_is_not_reached_through_this_one(lab):
    answer = lab["sign_in"]("boss").post(
        f"/labs/tests/{lab['ids']['cbc']}/ranges/{lab['ids']['infant']}",
        data={"age": "all", "low": "1", "high": "2"})
    assert answer.status_code == 404


def test_only_the_admin_types_ranges(lab):
    before = _ranges(lab)
    lab["sign_in"]("desk").post(
        f"/labs/tests/{lab['ids']['hb_test']}/analytes/{lab['ids']['hb']}/range",
        data={"age": "all", "low": "1", "high": "2"})
    assert _ranges(lab) == before


def test_stopping_a_test_needs_a_reason_and_keeps_it(lab):
    from app.models import Investigation

    boss = lab["sign_in"]("boss")
    boss.post(f"/labs/tests/{lab['ids']['cbc']}/stop", data={"reason": ""})
    with lab["app"].app_context():
        assert lab["db"].session.get(Investigation, lab["ids"]["cbc"]).is_active
    boss.post(f"/labs/tests/{lab['ids']['cbc']}/stop", data={"reason": "الكواشف خلصت"})
    with lab["app"].app_context():
        row = lab["db"].session.get(Investigation, lab["ids"]["cbc"])
        assert not row.is_active and row.stopped_reason == "الكواشف خلصت"
    page = boss.get(f"/labs/tests/{lab['ids']['cbc']}/ranges").get_data(as_text=True)
    assert "data-stopped" in page and "الكواشف خلصت" in page
    boss.post(f"/labs/tests/{lab['ids']['cbc']}/resume")
    with lab["app"].app_context():
        row = lab["db"].session.get(Investigation, lab["ids"]["cbc"])
        assert row.is_active and row.stopped_reason is None
