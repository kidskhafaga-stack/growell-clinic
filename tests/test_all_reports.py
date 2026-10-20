"""كل التقارير في مكان واحد (REPORTS_PLAN.md ت-١).

* تقارير شاشة التقارير وتقارير الأقسام في صفحة واحدة، بخانة بحث ومجموعات؛
* كل واحد بيشوف بس اللي يقدر يفتحه — والاختبار بيفتح كل كارت لكل دور: الكارت
  اللي بيوصّل لرفض باب ميت؛
* النجمة بتحفظ التقرير في «المفضلة» للشخص ده بس، وبتظهر فوق.
"""
import os
import re
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

ROLES = ("boss", "doc", "desk", "acct")


def _cards(client):
    page = client.get("/reports/").get_data(as_text=True)
    return page, re.findall(r'data-rep="([\w.]+)"[^>]*>\s*<a class="rep-link" href="([^"]+)"', page)


def test_every_card_opens_for_whoever_sees_it(clinic):
    seen_any = False
    for role in ROLES:
        client = clinic["sign_in"](role)
        resp = client.get("/reports/")
        if resp.status_code != 200:
            continue                      # this role has no reports screen at all
        _page, cards = _cards(client)
        for endpoint, href in cards:
            seen_any = True
            got = client.get(href)
            assert got.status_code == 200, f"{role} is shown {endpoint} ({href}) and gets {got.status_code}"
    assert seen_any


def test_the_departments_reports_are_listed_and_searchable(clinic):
    page, cards = _cards(clinic["sign_in"]("boss"))
    names = {ep for ep, _ in cards}
    assert {"reports.financial", "reports.medical_board", "visits.referrals"} <= names
    assert "data-rep-search" in page and 'data-rep-section="finance"' in page
    assert "تقرير" in page or "Report" in page


def test_a_star_is_one_person_s_and_comes_first(clinic):
    boss = clinic["sign_in"]("boss")
    boss.post("/reports/star", data={"endpoint": "reports.ar_aging"})
    page = boss.get("/reports/").get_data(as_text=True)
    assert 'data-rep-section="starred"' in page
    starred = page.split('data-rep-section="starred"', 1)[1].split("</section>", 1)[0]
    assert 'data-rep="reports.ar_aging"' in starred
    # Somebody else's page has no starred section.
    acct = clinic["sign_in"]("acct")
    other = acct.get("/reports/")
    if other.status_code == 200:
        assert 'data-rep-section="starred"' not in other.get_data(as_text=True)
    # Unknown names are ignored; a second press unstars.
    boss.post("/reports/star", data={"endpoint": "nope.nothing"})
    boss.post("/reports/star", data={"endpoint": "reports.ar_aging"})
    assert 'data-rep-section="starred"' not in boss.get("/reports/").get_data(as_text=True)


def test_every_catalogue_name_is_a_real_route(clinic):
    from app.utils.report_catalog import CATALOG

    rules = {r.endpoint for r in clinic["app"].url_map.iter_rules()}
    missing = [row[0] for row in CATALOG if row[0] not in rules]
    assert not missing, missing


def test_with_every_department_on_every_card_still_opens(clinic):
    """The hospital departments are off in a plain clinic; switched on, their
    reports appear — and each one must open for whoever is shown it."""
    from app.models import Setting
    from app.utils.facility import OPT_IN_MODULES

    with clinic["app"].app_context():
        for module in set(OPT_IN_MODULES) | {"labs", "imaging", "beds", "observations",
                                             "theatres", "pharmacy", "ambulance"}:
            Setting.set(f"mod_enabled:{module}", "1")
        clinic["db"].session.commit()
    names = set()
    for role in ROLES:
        client = clinic["sign_in"](role)
        if client.get("/reports/").status_code != 200:
            continue
        _page, cards = _cards(client)
        for endpoint, href in cards:
            names.add(endpoint)
            got = client.get(href)
            assert got.status_code == 200, f"{role} is shown {endpoint} ({href}) and gets {got.status_code}"
    assert {"labs.turnaround", "imaging.turnaround", "theatres.pathology"} <= names
