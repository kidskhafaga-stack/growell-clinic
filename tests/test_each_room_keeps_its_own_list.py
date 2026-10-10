"""Each room keeps its own list — «هل تم تصحيح مديول المعمل وفصله عن الاشعة ؟».

The worklists were split; the list a scan or a study is *defined* in was
not: it lived on the lab's page, behind the lab's module. Held here:

* a hospital with radiology and no laboratory adds and prices its scans;
* the scans' page carries nothing of the lab's — no store, no sheet;
* the scans' page edits scans, and only an administrator opens it;
* an old link to the lab's scans tab lands on radiology's list.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def rooms(clinic):
    from app.models import Investigation, Setting

    with clinic["app"].app_context():
        Setting.set("mod_enabled:labs", "1")
        Setting.set("mod_enabled:imaging", "1")
        rows = {"cbc": Investigation(name_ar="صورة دم كاملة", kind="lab", is_active=True),
                "xray": Investigation(name_ar="أشعة صدر", kind="imaging", is_active=True)}
        clinic["db"].session.add_all(rows.values())
        clinic["db"].session.commit()
        clinic["ids"].update({k: v.id for k, v in rows.items()})
    return clinic


def test_radiology_without_a_laboratory_defines_its_scans(rooms):
    from app.models import Investigation, Setting

    with rooms["app"].app_context():
        Setting.set("mod_enabled:labs", "0")
        rooms["db"].session.commit()
    boss = rooms["sign_in"]("boss")
    assert boss.get("/labs/tests").status_code == 404
    page = boss.get("/imaging/catalogue").get_data(as_text=True)
    assert "أشعة صدر" in page and "صورة دم كاملة" not in page
    boss.post("/imaging/catalogue/add", data={"name_ar": "أشعة بطن", "in_house": "1"})
    with rooms["app"].app_context():
        assert Investigation.query.filter_by(name_ar="أشعة بطن").one().kind == "imaging"


def test_the_scans_page_carries_nothing_of_the_lab(rooms):
    boss = rooms["sign_in"]("boss")
    scans = boss.get("/imaging/catalogue").get_data(as_text=True)
    for lab_only in ("data-lab-store", "data-lab-import", "data-lab-export",
                     "data-reject-reasons", "data-verify-setting", 'name="unit"'):
        assert lab_only not in scans, lab_only
    lab = boss.get("/labs/tests").get_data(as_text=True)
    assert "data-lab-import" in lab and "data-to-lab-settings" in lab
    # The lab's policy has a page of its own, off the list.
    settings = boss.get("/labs/settings").get_data(as_text=True)
    assert "data-lab-store" in settings and "data-reject-reasons" in settings
    assert rooms["sign_in"]("doc").get("/labs/settings").status_code == 403
    # Each room's door to its own list.
    assert "/imaging/catalogue" in boss.get("/imaging/").get_data(as_text=True)
    assert "/visits/studies/catalogue" in boss.get("/visits/studies/board").get_data(as_text=True)


def test_the_scans_page_edits_scans_and_only_for_an_administrator(rooms):
    from app.models import Investigation

    boss = rooms["sign_in"]("boss")
    assert boss.post(f"/imaging/catalogue/{rooms['ids']['cbc']}",
                     data={"name_ar": "x", "is_active": "1"}).status_code == 404
    with rooms["app"].app_context():
        assert rooms["db"].session.get(Investigation, rooms["ids"]["cbc"]).name_ar == "صورة دم كاملة"
    assert rooms["sign_in"]("doc").get("/imaging/catalogue").status_code == 403
    assert rooms["sign_in"]("doc").get("/visits/studies/catalogue").status_code == 403


def test_an_old_link_to_the_lab_s_scans_tab_lands_in_radiology(rooms):
    answer = rooms["sign_in"]("boss").get("/labs/tests?kind=imaging&q=صدر")
    assert answer.status_code == 302 and "/imaging/catalogue" in answer.headers["Location"]
    assert "q=" in answer.headers["Location"]
