"""Each section of the laboratory reads its own list — LAB_GLAB360_PLAN.md م-٥.

*«فلتر بالقسم الثابت (دم، كيمياء، هرمونات…) على شاشة المعمل، وكل فني يفتح على
قسمه، والقايمة مترتبة بالأقدم والمستعجل.»*

The sections were built (`utils/lab_sections`): every test sits in one of a
fixed list. The rack did not use them — the haematology technician read the
chemistry orders, the hormones and the urine, to find their own. Now a tab per
section with work waiting, with its count and an urgent mark; the choice is
remembered per person; and inside a section the order is the rack's own,
urgent first and then the oldest.
"""
import os
import re
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

from tests.test_the_sample_nobody_drew import _order, lab  # noqa: E402,F401


@pytest.fixture()
def benches(lab):
    """CBC in haematology, urine in urine & stool, a glucose in chemistry,
    and a test nobody has sorted yet."""
    from app.models import Investigation, User, VisitInvestigation

    db = lab["db"]
    with lab["app"].app_context():
        db.session.get(Investigation, lab["cbc"]).section = "hematology"
        db.session.get(Investigation, lab["urine"]).section = "urine_stool"
        glucose = Investigation(name_ar="سكر صايم", name_en="FBS", kind="lab",
                                sample_type="دم", section="chemistry")
        loose = Investigation(name_ar="تحليل جديد", kind="lab", sample_type="دم")
        tech = User(username="tech", full_name="فني المعمل", role="admin", is_active=True)
        tech.set_password("secret")
        db.session.add_all([glucose, loose, tech])
        db.session.commit()
        lab["glucose"], lab["loose"] = glucose.id, loose.id
    ids = {
        "cbc_old": _order(lab, "cbc", "صورة دم", minutes_ago=90),
        "cbc_new": _order(lab, "cbc", "صورة دم", minutes_ago=10),
        "cbc_urgent": _order(lab, "cbc", "صورة دم", minutes_ago=5),
        "urine": _order(lab, "urine", "تحليل بول", minutes_ago=30),
        "glucose": _order(lab, "glucose", "سكر صايم", minutes_ago=20),
        "loose": _order(lab, "loose", "تحليل جديد", minutes_ago=15),
    }
    with lab["app"].app_context():
        db.session.get(VisitInvestigation, ids["cbc_urgent"]).urgent = True
        db.session.commit()
    lab["orders"] = ids
    return lab


def _rack(page):
    """The orders on the rack, in the order they are drawn."""
    return [int(i) for i in re.findall(r'href="/labs/order/(\d+)"', page)][::2]


def _ids_on(page):
    return set(int(i) for i in re.findall(r'href="/labs/order/(\d+)"', page))


def test_a_tab_for_each_section_with_work_waiting(benches):
    page = benches["sign_in"]("boss").get("/labs/").get_data(as_text=True)
    tabs = page[page.index("data-lab-sections"):page.index("</nav>", page.index("data-lab-sections"))]
    for key in ("all", "hematology", "urine_stool", "chemistry", "none"):
        assert f'data-lab-section="{key}"' in tabs, key
    # No work waiting, no tab.
    assert 'data-lab-section="hormones"' not in tabs
    hema = tabs[tabs.index('data-lab-section="hematology"'):]
    hema = hema[:hema.index("</a>")]
    assert '<span class="num">3</span>' in hema and "bi-lightning-charge" in hema


def test_one_section_shows_only_its_own_urgent_first_then_oldest(benches):
    o = benches["orders"]
    page = benches["sign_in"]("boss").get("/labs/?section=hematology").get_data(as_text=True)
    assert _ids_on(page) == {o["cbc_old"], o["cbc_new"], o["cbc_urgent"]}
    assert _rack(page) == [o["cbc_urgent"], o["cbc_old"], o["cbc_new"]]
    assert "data-lab-section-note" in page
    # The two counts on top are the section's own.
    assert 'data-tally="to_collect"' in page
    collect = page[page.index('data-tally="to_collect"'):]
    assert "3" in collect[:collect.index("</a>")]


def test_a_test_in_no_section_is_never_lost(benches):
    o = benches["orders"]
    page = benches["sign_in"]("boss").get("/labs/?section=none").get_data(as_text=True)
    assert _ids_on(page) == {o["loose"]}
    assert "/labs/tests/sections" in page        # where to sort it


def test_each_person_opens_on_their_own_section(benches):
    o = benches["orders"]
    tech = benches["sign_in"]("tech")
    tech.get("/labs/?section=chemistry")
    assert _ids_on(tech.get("/labs/").get_data(as_text=True)) == {o["glucose"]}
    # Someone else is not moved by it.
    everyone = benches["sign_in"]("boss").get("/labs/").get_data(as_text=True)
    assert _ids_on(everyone) == set(o.values())
    # «All sections» forgets it.
    tech.get("/labs/?section=all")
    assert _ids_on(tech.get("/labs/").get_data(as_text=True)) == set(o.values())


def test_a_section_with_nothing_waiting_says_so(benches):
    page = benches["sign_in"]("boss").get("/labs/?section=hormones").get_data(as_text=True)
    assert _ids_on(page) == set()
    assert 'data-lab-section="hormones"' in page      # the chosen tab stays
    assert "data-lab-section-note" in page


def test_a_word_that_is_not_a_section_is_the_whole_lab(benches):
    o = benches["orders"]
    page = benches["sign_in"]("boss").get("/labs/?section=x' onmouseover=1").get_data(as_text=True)
    assert _ids_on(page) == set(o.values())
    assert "onmouseover" not in page


def test_without_a_section_the_rack_is_what_it_was(benches):
    """Nothing chosen: the same list, the same order, as before the tabs."""
    from app.utils import labs

    with benches["app"].app_context():
        whole = [r.id for r in labs.worklist()]
        assert set(whole) == set(benches["orders"].values())
        assert whole[0] == benches["orders"]["cbc_urgent"]
        assert labs.counts()["to_collect"] == 6
        assert labs.counts(section="chemistry")["to_collect"] == 1
        assert labs.section_counts()["hematology"] == (3, 1)
